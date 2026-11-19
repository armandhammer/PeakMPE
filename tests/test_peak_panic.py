"""Peak front-panel panic: Mod + Audition (patches/peak_mpe/panic.c).

The buttons go in through the firmware's own event queue (the panel scan's
ring at 0x20003AD0+0x88, as tests/test_peak_morph.py), so the press passes
through panel_button_event and our qa_panel_read as it does on the synth.
"""
import pytest
import unicorn

from test_peak_arp_echo import ARP_ON
from test_peak_sim import FLAG, PATCHES, _boot, _send, mpe_built  # noqa: F401

BUTTON_QUEUE = 0x20003AD0                 # +0x88 64 events (button, bit 7 = pressed), +0x84 write index
MOD, AUDITION = 7, 18
VOICE_STATE = 0x20004650                  # +0x1F4+v gate
NOTE_STATE = 0x200127D4                   # +0xD8 held-key bitmap, +0x1D3 last note
ARP_STATE_PTR = 0x20000640                # +0x168 keys held, +0x178 play map
ARP_STEP = 0x080151A0
VOICE_MODE = 0x22
NONE = 0xFF

pytestmark = pytest.mark.slow


def _button(b, index, pressed, ms=60):
    w = b.u8(BUTTON_QUEUE + 0x84)
    b.uc.mem_write(BUTTON_QUEUE + 0x88 + w, bytes([index | (0x80 if pressed else 0)]))
    b.uc.mem_write(BUTTON_QUEUE + 0x84, bytes([(w + 1) & 0x3F]))
    b.run_ms(ms)


def _gates(b):
    return list(b.uc.mem_read(VOICE_STATE + 0x1F4, 8))


def _panic(b):
    _button(b, MOD, True)
    _button(b, AUDITION, True)
    gates_while_pressed = _gates(b)
    _button(b, AUDITION, False)
    _button(b, MOD, False)
    return gates_while_pressed


def _arp(b):
    return bytes(b.uc.mem_read(int.from_bytes(b.uc.mem_read(ARP_STATE_PTR, 4), "little") + 0x168, 32))


@pytest.fixture
def board(mpe_built):
    b = _boot(mpe_built.patched)
    b.run_ms(100)
    return b


def test_mod_audition_ends_every_mpe_note_and_clears_the_bindings(board, mpe_built):
    b, blob = board, mpe_built.blob
    b.uc.mem_write(PATCHES + FLAG, b"\x01")
    _send(b, 0x91, 60, 100, 0x92, 64, 100, 0x93, 67, 100, 0x90, 72, 100, ms=40)   # members 2-4 and the master
    _send(b, 0xE2, 0x00, 0x50, 0xD3, 90, 0xB1, 74, 100, ms=20)                    # bend, pressure, slide
    assert sum(_gates(b)) == 4
    assert sum(c != NONE for c in b.uc.mem_read(blob.address("voice_channel"), 8)) == 4
    while_pressed = _panic(b)
    assert sum(while_pressed) == 0                       # Audition's own note did not sound
    assert sum(_gates(b)) == 0
    assert set(b.uc.mem_read(blob.address("voice_channel"), 8)) == {NONE}
    assert not any(b.uc.mem_read(blob.address("mpe_chan_bend"), 32))
    assert not any(b.uc.mem_read(blob.address("mpe_chan_pressure"), 16))
    assert not any(b.uc.mem_read(blob.address("mpe_chan_slide"), 16))
    assert not any(b.uc.mem_read(NOTE_STATE + 0xD8, 16)) and b.u8(NOTE_STATE + 0x1D3) == NONE
    rows = b.display.lcd.text()
    assert rows[0].startswith("PANIC") and rows[1].startswith("All notes off"), rows
    _send(b, 0x92, 64, 100, ms=40)                       # a new note plays as usual
    assert sum(_gates(b)) == 1


def test_audition_alone_is_stock(board):
    b = board
    _button(b, AUDITION, True)
    assert sum(_gates(b)) == 1                           # middle C
    _button(b, AUDITION, False)
    assert sum(_gates(b)) == 0


@pytest.mark.parametrize("panic", [False, True])
def test_a_key_left_held_does_not_come_back_in_mono(board, panic):
    """Mono: let go of the top key and stock goes back to a key still held.
    After a panic the key whose note-off never came is forgotten (without
    one, the control case, it comes back)."""
    b = board
    b.uc.mem_write(PATCHES + VOICE_MODE, b"\x00")
    _send(b, 0x90, 60, 100, 0x90, 67, 100, ms=40)
    if panic:
        _panic(b)
    _send(b, 0x90, 72, 100, ms=40)
    _send(b, 0x80, 72, 0, ms=40)
    assert sum(_gates(b)) == (0 if panic else 1)


@pytest.mark.parametrize("panic", [False, True])
def test_the_arp_stops_with_keys_whose_note_off_never_came(board, panic):
    b = board
    steps = []
    b.uc.hook_add(unicorn.UC_HOOK_CODE, lambda uc, a, size, user: steps.append(b.time_us),
                  begin=ARP_STEP, end=ARP_STEP)
    b.uc.mem_write(PATCHES + ARP_ON, b"\x01")
    _send(b, 0x90, 60, 100, 0x90, 64, 100, ms=600)       # no note-offs: the arp would play on for ever
    assert len(steps) >= 2 and any(_arp(b))
    if panic:
        _panic(b)
        assert not any(_arp(b))
    steps.clear()
    b.run_ms(800)
    assert (steps == []) == panic                        # without a panic it plays on
