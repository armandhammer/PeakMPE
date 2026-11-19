"""Peak: patch dump on patch change (Settings > PATCH DUMP; patches/peak_mpe/pdump.c).

The simulator doesn't model the Peak's USB endpoint, so the tests collect the
bytes stock hands to its USB byte-stream function (0x0801D484, port 0), which
is where sysex_rx_poll's answers to port 0 go.
"""
import pytest
import unicorn

from test_peak_sim import PATCHES, _boot, _call, _send, _show, mpe_built  # noqa: F401

pytestmark = pytest.mark.slow

GLOBALS, G_PDUMP = 0x20014494, 0x4E
G_BANK_PATCH = 0x15                       # Settings Bank/Patch: bit 0 receive (program_change 0x0800F0EC)
PATCH_SELECT = 0x20002D14                 # +4 bank, +5 number of the loaded patch
USB_TX = 0x0801D484
SYSEX_STATE = 0x20011214 + 0x67C
PDUMP_PAGE = 16                           # Settings: after RANDOMISE
HDR = bytes([0xF0, 0x00, 0x20, 0x29, 0x01, 0x10, 0x00, 0x7E])


@pytest.fixture
def board(mpe_built):
    b = _boot(mpe_built.patched)
    b.run_ms(300)
    b.uc.mem_write(GLOBALS + G_BANK_PATCH, bytes([3]))   # Rec+Tran; the simulator boots with it 0
    usb = []
    b.uc.hook_add(unicorn.UC_HOOK_CODE, lambda uc, a, s, u: usb.append(uc.reg_read(unicorn.arm_const.UC_ARM_REG_R0) & 0xFF),
                  begin=USB_TX, end=USB_TX)
    return b, usb


def _sysex(data):
    out, cur = [], None
    for x in data:
        if x == 0xF0:
            cur = [x]
        elif cur is not None:
            cur.append(x)
            if x == 0xF7:
                out.append(bytes(cur))
                cur = None
    return out


def _on(b):
    b.uc.mem_write(GLOBALS + G_PDUMP, b"\x01")


def test_the_settings_page(board, mpe_built):
    b, _ = board
    rows = _show(b, 8, PDUMP_PAGE, 0)
    assert rows[0].startswith("PATCH DUMP"), rows
    assert rows[1][:19].split() == ["Send", "Off"], rows
    _call(b, mpe_built.blob.address("mpe_ui_value_change"), 1)
    assert b.u8(GLOBALS + G_PDUMP) == 1
    assert _show(b, 8, PDUMP_PAGE, 0)[1][:19].split() == ["Send", "USB"]
    _call(b, mpe_built.blob.address("mpe_ui_value_change"), 5)        # 0-1 only
    assert b.u8(GLOBALS + G_PDUMP) == 1


def test_a_program_change_sends_the_new_patch_over_usb(board):
    b, usb = board
    _on(b)
    _send(b, 0xC0, 5, ms=300)
    assert b.u8(PATCH_SELECT + 5) == 5                     # the patch was loaded
    msgs = _sysex(usb)
    assert len(msgs) == 1, [len(m) for m in msgs]
    m = msgs[0]
    assert len(m) == 527 and m[:9] == HDR + b"\x00"                 # the editor's current patch (answer 00)
    assert m[14:14 + 512] == bytes(b.uc.mem_read(PATCHES, 512))     # what is now loaded


def test_off_sends_nothing(board):
    b, usb = board
    _send(b, 0xC0, 5, ms=300)
    assert b.u8(PATCH_SELECT + 5) == 5
    assert _sysex(usb) == []


def test_a_patch_sent_by_the_editor_is_not_echoed(board):
    b, usb = board
    _on(b)
    _send(b, 0xC0, 5, ms=300)
    usb.clear()
    patch = bytes(b.uc.mem_read(PATCHES, 512))
    write = list(HDR) + [0x00, 0, 0, 0, 0, 0] + list(patch) + [0xF7]   # write 00 into the edit buffer
    _send(b, *write, ms=600)
    assert _sysex(usb) == []


def test_the_dump_waits_for_an_answer_in_progress(board, mpe_built):
    """While stock is answering (a bank dump takes seconds) the request waits;
    the next tick's poll sends it. Called directly, the state set by hand."""
    b, _ = board
    blob = mpe_built.blob
    _on(b)
    b.uc.mem_write(SYSEX_STATE, bytes([3, 0, 0, 1]))            # answering a stored patch, to DIN
    _call(b, blob.address("pdump_patch_selected"), 5, 1)
    assert list(b.uc.mem_read(SYSEX_STATE, 4)) == [3, 0, 0, 1]  # left alone
    b.uc.mem_write(SYSEX_STATE, bytes([0, 0, 0, 1]))            # that answer is done
    _call(b, blob.address("pdump_poll"))
    state = list(b.uc.mem_read(SYSEX_STATE, 4))
    assert state[0] == 2 and state[3] == 0                      # current patch, to USB
    b.uc.mem_write(SYSEX_STATE, bytes([0]))
    _call(b, blob.address("pdump_poll"))
    assert b.u8(SYSEX_STATE) == 0                               # sent once only
