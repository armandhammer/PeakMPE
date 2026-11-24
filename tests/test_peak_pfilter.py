"""Peak per-port receive filters: Settings USB IN and DIN IN (patches/peak_mpe/pfilter.c).

DIN bytes go in through the simulated USART. The simulator has no USB endpoint,
so USB bytes are written into port 0's receive ring (0x200040B4: +0 write
index, +1 read index, +2 256 bytes), where stock's USB receive (0x0801D2F0)
puts them; port 2, the synth's own output read back in, likewise. Received
messages are counted by the MIDI MONITOR page, which only sees what the filter
let through.
"""
import pytest

from test_peak_sim import FLAG, PATCHES, _boot, _call, _send, _show, mpe_built  # noqa: F401

pytestmark = pytest.mark.slow

GLOBALS, PF, G_CC_NRPN, G_BANK_PATCH = 0x20014494, 0x50, 0x14, 0x15
USB, DIN = 0, 1
NOTES, CC, PATCH = 0, 1, 2
RING = 0x200040B4
VOICE_STATE = 0x20004650                 # +0x1F4+v gate
PATCH_SELECT = 0x20002D14                # +5 number of the loaded patch
MON_PAGE, USB_PAGE, DIN_PAGE = 9, 18, 19


def ring_put(b, port, *data, ms=20):
    """Bytes into a port's receive ring, as stock's midi_rx_put (0x0800F5B0) does."""
    base = RING + port * 0x110
    head = b.u8(base)
    for x in data:
        b.uc.mem_write(base + 2 + head, bytes([x]))
        head = (head + 1) & 0xFF
    b.uc.mem_write(base, bytes([head]))
    b.run_ms(ms)


def usb(b, *data, ms=20):
    ring_put(b, 0, *data, ms=ms)


@pytest.fixture
def board(mpe_built):
    b = _boot(mpe_built.patched)
    b.run_ms(300)
    b.uc.mem_write(GLOBALS + G_CC_NRPN, bytes([3]))      # CC/NRPN and Bank/Patch Rec+Tran (the simulator boots with 0)
    b.uc.mem_write(GLOBALS + G_BANK_PATCH, bytes([3]))
    return b


def _off(b, port, group):
    b.uc.mem_write(GLOBALS + PF + 3 * port + group, bytes([1]))


def _on(b, port, group):
    b.uc.mem_write(GLOBALS + PF + 3 * port + group, bytes([0]))


def _gates(b):
    return sum(1 for g in b.uc.mem_read(VOICE_STATE + 0x1F4, 8) if g)


def _count(b):
    rows = _show(b, 8, MON_PAGE, 1)
    assert rows[2].startswith("Msg count"), rows
    return int(rows[2][10:19])


def _loaded(b):
    return b.u8(PATCH_SELECT + 5)


def _items(rows):
    return [r[:19].split() for r in rows[1:4]]


def test_the_settings_pages(board, mpe_built):
    b = board
    change = mpe_built.blob.address("mpe_ui_value_change")
    rows = _show(b, 8, USB_PAGE, 0)
    assert rows[0].startswith("USB IN"), rows
    assert _items(rows) == [["Notes", "On"], ["CC", "On"], ["Patch", "On"]], rows
    _call(b, change, -1)
    assert b.u8(GLOBALS + PF) == 1
    assert _items(_show(b, 8, USB_PAGE, 0))[0] == ["Notes", "Off"]
    _call(b, change, -5)                                     # Off is the end
    assert b.u8(GLOBALS + PF) == 1
    _call(b, change, 1)
    assert b.u8(GLOBALS + PF) == 0
    rows = _show(b, 8, DIN_PAGE, 2)
    assert rows[0].startswith("DIN IN"), rows
    _call(b, change, -1)
    assert b.u8(GLOBALS + PF + 5) == 1
    assert _items(_show(b, 8, DIN_PAGE, 2)) == [["Notes", "On"], ["CC", "On"], ["Patch", "Off"]]


def test_din_notes_off_drops_note_ons_but_lets_a_held_note_end(board):
    b = board
    _send(b, 0x90, 60, 100, ms=40)
    assert _gates(b) == 1
    _off(b, DIN, NOTES)
    _send(b, 0x90, 64, 100, ms=40)
    assert _gates(b) == 1                                    # dropped
    _send(b, 0x80, 60, 0, ms=40)
    assert _gates(b) == 0                                    # the note-off still ends the held note


def test_usb_notes_off_leaves_din_alone(board):
    b = board
    usb(b, 0x90, 60, 100, ms=40)
    assert _gates(b) == 1                                    # USB through the ring plays, as from the endpoint
    usb(b, 0x80, 60, 0, ms=40)
    assert _gates(b) == 0
    _off(b, USB, NOTES)
    usb(b, 0x90, 62, 100, ms=40)
    assert _gates(b) == 0
    _send(b, 0x90, 64, 100, ms=40)
    assert _gates(b) == 1


def test_patch_off_drops_program_change_and_bank_select_not_the_synths_own(board):
    b = board
    _off(b, DIN, PATCH)
    was = _loaded(b)
    _send(b, 0xB0, 32, 4, 0xC0, 5, ms=40)
    assert _loaded(b) == was
    ring_put(b, 2, 0xC0, 6, ms=40)                           # port 2 is never filtered
    assert _loaded(b) == 6
    usb(b, 0xC0, 7, ms=40)                                   # USB Patch is still on
    assert _loaded(b) == 7


def test_cc_off_drops_controllers_and_nrpns_not_rpns_or_panic(board):
    b = board
    _off(b, DIN, CC)
    n = _count(b)
    _send(b, 0xB0, 7, 100)                                   # volume: CC
    assert _count(b) == n
    _send(b, 0xB0, 99, 0, 0xB0, 98, 5, 0xB0, 6, 10)          # NRPN select and its data entry: CC
    assert _count(b) == n
    _send(b, 0xB0, 101, 0, 0xB0, 100, 0, 0xB0, 6, 12)        # RPN 0 (bend range): Notes
    assert _count(b) == n + 3
    _send(b, 0xB0, 123, 0)                                   # all notes off: always
    assert _count(b) == n + 4
    usb(b, 0xB0, 7, 90)                                      # USB CC is still on
    assert _count(b) == n + 5


def test_member_channel_controllers_go_with_notes(board):
    b = board
    b.uc.mem_write(PATCHES + FLAG, b"\x01")                  # MPE on: Lower Zone, members 2-16
    _off(b, DIN, CC)
    n = _count(b)
    _send(b, 0xB1, 74, 90)                                   # slide on member channel 2: note expression
    assert _count(b) == n + 1
    _on(b, DIN, CC)
    _off(b, DIN, NOTES)
    _send(b, 0xB1, 74, 40, 0xE1, 0, 0x50, 0xD1, 70)
    assert _count(b) == n + 1
    _send(b, 0xB0, 1, 64)                                    # mod wheel on the master channel: CC
    assert _count(b) == n + 2
