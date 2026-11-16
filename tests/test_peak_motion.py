"""Peak motion recording (patches/peak_mpe/motion.c; docs/peak-motion-morph.md).

Hold Mod and press Animate 1, move a control: its values over one loop of 32
steps are recorded and then played back in time with the tempo. The Init
Patch runs at 120 BPM, so a step (3 MIDI clocks) is 62.5 ms and the one-bar
loop 2 s.

A control move is simulated as tests/test_peak_sim.py does for undo: the
patch's hook function is called with the control's value, then the patch byte
is written as stock's knob handling would.
"""
import pytest

from test_peak_sim import GLOBALS, MOD_PRESS, PATCHES, _boot, _call, _show, mpe_built  # noqa: F401

ANIMATE1_PRESS, ANIMATE1_RELEASE = (14 << 8) | 0x01, (14 << 8) | 0xFF
RESONANCE, FILT_FREQ, NO_NUMBER = 0x82, 0x83, 0xC8     # 7-bit; 9-bit pair 0x83/0x84; LevelComp: no CC or NRPN number
G_MOTION_LEN = 0x3F
MOTION_PAGE = 10                                         # Settings: after MIDI MONITOR
LOOP_MS = 2000
MS_COUNTER = 0x20003AD0 + 0x1C0                       # tim6_isr: +1 per millisecond

pytestmark = pytest.mark.slow


def _board(built):
    b = _boot(built.patched)
    b.uc.mem_write(PATCHES + RESONANCE, bytes([5]))
    return b


def _arm(b, blob):
    assert _call(b, blob.address("motion_button"), ANIMATE1_PRESS, 1) == 1
    assert _call(b, blob.address("motion_button"), ANIMATE1_RELEASE, 1) == 1    # the release is taken too


def _move(b, blob, offset, value, hires=0):
    _call(b, blob.address("motion_knob"), offset, value, hires)
    if hires:
        b.uc.mem_write(PATCHES + offset, bytes([value >> 1, (value & 1) << 6]))
    else:
        b.uc.mem_write(PATCHES + offset, bytes([value]))


def _state(b):
    rows = _show(b, 8, MOTION_PAGE, 0)
    assert rows[0].startswith("MOTION"), rows
    return rows[2].split()[1]


def _record_four(b, blob, offset=RESONANCE):
    """Arm and record 10, 60, 110, 30, each for a quarter of the bar."""
    _arm(b, blob)
    for v in (10, 60, 110, 30):
        _move(b, blob, offset, v)
        b.run_ms(LOOP_MS // 4)


def test_arming_asks_for_a_control_and_cancels(mpe_built):
    b, blob = _board(mpe_built), mpe_built.blob
    assert _state(b) == "Off"
    _arm(b, blob)
    rows = b.display.lcd.text()
    assert rows[0].startswith("MOTION") and rows[1].startswith("Move a control"), rows
    assert _state(b) == "Armed"
    _arm(b, blob)                                        # again: cancel
    assert _state(b) == "Off"
    assert b.u8(PATCHES + RESONANCE) == 5


def test_animate_1_without_mod_is_stock(mpe_built):
    b, blob = _board(mpe_built), mpe_built.blob
    assert _call(b, blob.address("motion_button"), ANIMATE1_PRESS, 0) == 0
    assert _call(b, blob.address("motion_button"), ANIMATE1_RELEASE, 0) == 0
    assert _state(b) == "Off"


def test_one_bar_is_recorded_and_loops(mpe_built):
    b, blob = _board(mpe_built), mpe_built.blob
    _arm(b, blob)
    _move(b, blob, RESONANCE, 10)
    assert _state(b) == "Rec"
    b.run_ms(500)
    for v in (60, 110, 30):
        _move(b, blob, RESONANCE, v)
        b.run_ms(500)
    b.run_ms(250)                                        # 2.25 s: playing, in the first quarter again
    assert _state(b) == "Play"
    heard = []
    for _ in range(6):                                   # a bar and a half, a quarter apart
        heard.append(b.u8(PATCHES + RESONANCE))
        b.run_ms(500)
    assert heard == [10, 60, 110, 30, 10, 60], heard


def test_stop_puts_the_value_back(mpe_built):
    b, blob = _board(mpe_built), mpe_built.blob
    _record_four(b, blob)
    b.run_ms(700)
    assert b.u8(PATCHES + RESONANCE) != 5
    _arm(b, blob)                                        # Mod + Animate 1 again: stop
    assert b.u8(PATCHES + RESONANCE) == 5                # the value from before the recording
    rows = b.display.lcd.text()
    assert rows[0].startswith("MOTION") and rows[1].startswith("Stopped"), rows
    b.run_ms(2500)
    assert b.u8(PATCHES + RESONANCE) == 5 and _state(b) == "Off"


def test_a_nine_bit_control_keeps_its_fine_bit(mpe_built):
    b, blob = _board(mpe_built), mpe_built.blob
    _arm(b, blob)
    _move(b, blob, FILT_FREQ, 40, hires=1)
    b.run_ms(1000)
    _move(b, blob, FILT_FREQ, 201, hires=1)
    b.run_ms(1250)                                       # 2.25 s: first half again
    assert b.u8(PATCHES + FILT_FREQ) * 2 + (b.u8(PATCHES + FILT_FREQ + 1) >> 6) == 40
    b.run_ms(1000)
    assert b.u8(PATCHES + FILT_FREQ) * 2 + (b.u8(PATCHES + FILT_FREQ + 1) >> 6) == 201


def test_moving_the_control_while_it_plays_replaces_those_steps(mpe_built):
    b, blob = _board(mpe_built), mpe_built.blob
    _record_four(b, blob)                                # ends at 2.0 s: the loop starts again
    b.run_ms(600)                                        # in the second quarter (60)
    _move(b, blob, RESONANCE, 99)
    b.run_ms(1650)                                       # 4.25 s: first quarter of the next loop
    assert b.u8(PATCHES + RESONANCE) == 10
    b.run_ms(450)                                        # 4.7 s: where the hand was
    assert b.u8(PATCHES + RESONANCE) == 99
    b.run_ms(550)                                        # 5.25 s: third quarter, untouched
    assert b.u8(PATCHES + RESONANCE) == 110


def test_a_control_without_a_midi_number_is_not_taken(mpe_built):
    b, blob = _board(mpe_built), mpe_built.blob
    _arm(b, blob)
    _move(b, blob, NO_NUMBER, 20)
    assert _state(b) == "Armed"
    _move(b, blob, RESONANCE, 20)                        # the next playable control is
    assert _state(b) == "Rec"


def test_another_control_is_left_alone(mpe_built):
    b, blob = _board(mpe_built), mpe_built.blob
    _record_four(b, blob)
    b.uc.mem_write(PATCHES + 0x93, bytes([33]))
    _move(b, blob, 0x93, 77)                             # Amp Decay, not the recorded control
    b.run_ms(2300)
    assert b.u8(PATCHES + 0x93) == 77
    assert b.u8(PATCHES + RESONANCE) == 10


def test_two_bars_take_twice_as_long(mpe_built):
    b, blob = _board(mpe_built), mpe_built.blob
    b.uc.mem_write(GLOBALS + G_MOTION_LEN, bytes([1]))
    _arm(b, blob)
    _move(b, blob, RESONANCE, 10)
    b.run_ms(2000)
    _move(b, blob, RESONANCE, 90)
    b.run_ms(500)
    assert _state(b) == "Rec"                            # 2.5 s: one bar would be playing by now
    b.run_ms(2000)                                       # 4.5 s
    assert _state(b) == "Play" and b.u8(PATCHES + RESONANCE) == 10
    b.run_ms(2000)                                       # 6.5 s
    assert b.u8(PATCHES + RESONANCE) == 90


def test_motion_page_and_late_ticks(mpe_built):
    b, blob = _board(mpe_built), mpe_built.blob
    b.run_ms(500)
    rows = _show(b, 8, MOTION_PAGE, 0)
    assert rows[0].startswith("MOTION"), rows
    assert rows[1].startswith("Length") and "1 bar" in rows[1], rows
    assert rows[2].startswith("Motion") and "Off" in rows[2], rows
    assert rows[3].startswith("LateTicks"), rows
    assert int(rows[3].split()[1]) < 100, rows           # an idle synth loses few ticks
    _call(b, blob.address("mpe_ui_value_change"), 1)
    assert b.u8(GLOBALS + G_MOTION_LEN) == 1
    assert "2 bars" in _show(b, 8, MOTION_PAGE, 0)[1]
    _call(b, blob.address("mpe_ui_value_change"), 5)
    assert b.u8(GLOBALS + G_MOTION_LEN) == 2
    assert "4 bars" in _show(b, 8, MOTION_PAGE, 0)[1]
    rows = _show(b, 8, MOTION_PAGE + 1, 0)               # the stock page after ours is still there
    assert rows[0].startswith("MIDI ENABLE"), rows


def test_late_ticks_row_is_a_latched_reading(mpe_built):
    """On the synth (v0.16) the row showed the live count, each change redrew the
    page, and drawing loses ticks: it ran up by about 1,000 a second by itself.
    Now a reading is taken only when the page is drawn."""
    b, blob = _board(mpe_built), mpe_built.blob
    rows = _show(b, 8, MOTION_PAGE, 0)
    assert rows[3].split()[1:] == ["0", "0"] or int(rows[3].split()[1]) < 100, rows
    before = b.display.lcd.text()[3]
    ms = int.from_bytes(b.uc.mem_read(MS_COUNTER, 4), "little")
    b.uc.mem_write(MS_COUNTER, (ms + 500).to_bytes(4, "little"))     # the main loop "lost" half a second
    b.run_ms(300)
    assert b.display.lcd.text()[3] == before                         # the open page does not follow
    rows = _show(b, 8, MOTION_PAGE, 0)                               # drawn again: a new reading
    count, gap = rows[3].split()[1:3]
    assert 495 <= int(count) < 600 and gap == "99", rows
    rows = _show(b, 8, MOTION_PAGE, 0)
    assert int(rows[3].split()[2]) < 99, rows                        # the gap is since the last reading


def test_playback_does_not_ask_for_a_page_redraw(mpe_built):
    b, blob = _board(mpe_built), mpe_built.blob
    _record_four(b, blob)
    b.run_ms(100)
    b.uc.mem_write(0x20011208 + 1, b"\x00")              # stock's changed flag: clear
    b.run_ms(1200)                                       # several steps played with new values
    assert b.u8(PATCHES + RESONANCE) in (60, 110)
    assert b.u8(0x20011208 + 1) == 0
