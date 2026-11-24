"""Peak: the Compare button with the patch's undo step and motion lane.

Stock's Compare loads the stored patch while the button is held and copies
the patch back when it is let go (docs/findings/peak-2.2-build2108.md,
"Compare and Save"). The patch's hook on patch_load's copy (plock_copy) used
to take that load for a patch change and cleared the undo step and the
motion lane (v0.12 to v0.19). From v0.20 both stand still while Compare is
held and go on at the release, as the morph does since v0.19
(tests/test_peak_morph.py).
"""
import pytest

from test_peak_morph import _compare
from test_peak_motion import LOOP_MS, RESONANCE, _arm, _move, _record_four, _state
from test_peak_motion import _board as _motion_board
from test_peak_sim import MOD_PRESS, PATCHES, UNDO_LEFT, UNDO_RIGHT, _boot, _call, mpe_built  # noqa: F401

AMP_ATTACK = 0x93

pytestmark = pytest.mark.slow


def _gesture(b, blob, values, offset=AMP_ATTACK):
    for v in values:
        _call(b, blob.address("undo_knob"), offset)      # what disp_knob_overlay does first
        b.uc.mem_write(PATCHES + offset, bytes([v]))     # knob_poll applies the value afterwards


def test_the_undo_step_is_still_there_after_compare(mpe_built):
    b, blob = _boot(mpe_built.patched), mpe_built.blob
    b.uc.mem_write(PATCHES + AMP_ATTACK, bytes([50]))
    _gesture(b, blob, (60, 70, 80))
    _compare(b, True)
    _compare(b, False)
    assert b.u8(PATCHES + AMP_ATTACK) == 80              # stock gave the patch back
    _call(b, blob.address("qa_button"), MOD_PRESS)
    assert _call(b, blob.address("edit_button"), UNDO_LEFT) == 1
    assert b.u8(PATCHES + AMP_ATTACK) == 50
    assert _call(b, blob.address("edit_button"), UNDO_RIGHT) == 1
    assert b.u8(PATCHES + AMP_ATTACK) == 80


def test_undo_is_not_done_on_the_patch_compare_plays(mpe_built):
    """While Compare is held the patch in RAM is the stored one, which stock
    throws away at the release: no undo or redo on it, and a control moved
    meanwhile is not a new undo step."""
    b, blob = _boot(mpe_built.patched), mpe_built.blob
    b.uc.mem_write(PATCHES + AMP_ATTACK, bytes([50]))
    _gesture(b, blob, (80,))
    _compare(b, True)
    stored = b.u8(PATCHES + AMP_ATTACK)
    assert stored not in (50, 80)
    _call(b, blob.address("qa_button"), MOD_PRESS)
    assert _call(b, blob.address("edit_button"), UNDO_LEFT) == 1     # taken, nothing done
    assert b.u8(PATCHES + AMP_ATTACK) == stored
    assert "Not during Compare" in "\n".join(b.display.lcd.text())
    b.run_ms(2500)                                       # a new gesture by its time
    _gesture(b, blob, (stored + 5,))                     # a control moved while Compare is held
    _compare(b, False)
    assert b.u8(PATCHES + AMP_ATTACK) == 80
    assert _call(b, blob.address("edit_button"), UNDO_LEFT) == 1
    assert b.u8(PATCHES + AMP_ATTACK) == 50              # the step from before Compare


def test_a_motion_lane_waits_while_compare_is_held_and_plays_on(mpe_built):
    b, blob = _motion_board(mpe_built), mpe_built.blob
    _record_four(b, blob)                                # 10, 60, 110, 30 over one bar
    b.run_ms(250)
    assert _state(b) == "Play"
    _compare(b, True, ms=100)
    stored = b.u8(PATCHES + RESONANCE)
    seen = set()
    for _ in range(8):                                   # a whole bar held
        b.run_ms(LOOP_MS // 8)
        seen.add(b.u8(PATCHES + RESONANCE))
    assert seen == {stored}                              # the lane writes nothing into the stored patch
    assert _state(b) == "Play"
    _compare(b, False, ms=100)
    heard = set()
    for _ in range(16):                                  # the lane plays on, in time
        b.run_ms(LOOP_MS // 8)
        heard.add(b.u8(PATCHES + RESONANCE))
    assert {10, 60, 110, 30} <= heard, heard
    _arm(b, blob)                                        # Mod + Animate 1: stop
    assert b.u8(PATCHES + RESONANCE) == 5                # the value from before the recording


def test_a_control_moved_during_compare_is_not_recorded(mpe_built):
    b, blob = _motion_board(mpe_built), mpe_built.blob
    _arm(b, blob)
    _compare(b, True, ms=100)
    _move(b, blob, RESONANCE, 99)                        # armed, but this is the stored patch
    assert _state(b) == "Armed"
    _compare(b, False, ms=100)
    assert b.u8(PATCHES + RESONANCE) == 5
    _move(b, blob, RESONANCE, 40)
    assert _state(b) == "Rec"


def test_a_patch_change_still_clears_both(mpe_built):
    b, blob = _motion_board(mpe_built), mpe_built.blob
    _record_four(b, blob)
    b.run_ms(250)
    _gesture(b, blob, (80,))
    record = b.flash[11].read(0x200, 0x201)              # record 1, as a patch select reads it
    buf = 0x20003CA4
    b.uc.mem_write(buf, bytes(record))
    _call(b, 0x0801AEB8, buf)                            # patch_load
    assert _state(b) == "Off"
    _call(b, blob.address("qa_button"), MOD_PRESS)
    _call(b, blob.address("edit_button"), UNDO_LEFT)
    assert "Nothing to undo" in "\n".join(b.display.lcd.text())
