"""Peak patch morph (patches/peak_mpe/morph.c; docs/peak-motion-morph.md).

Settings > MORPH > Morph = ModWheel: CC 1 blends the patch as it stands
(wheel 0) towards the patch as stored (wheel 127). The simulator's patch
memory holds the Init Patch in every record, so "stored" is the Init Patch
unless a test writes another record; edits are made through stock's setter
behind a received CC, or straight into the patch before the wheel leaves 0.
"""
import pytest

from test_peak_disp import _overlay
from test_peak_sim import GLOBALS, PATCHES, _boot, _call, _send, _show, mpe_built  # noqa: F401

G_MORPH, G_LOCK_FX = 0x40, 0x36
MORPH_PAGE = 11                                          # Settings: after MOTION
PATCH_SELECT = 0x20002D14                                # +4 bank (1-based), +5 number
RESONANCE, FILT_FREQ, FILT_SLOPE, AMP_DECAY, O1_FINE, DEL_LEVEL = 0x82, 0x83, 0x7F, 0x93, 0x33, 0xCC
CC_RESONANCE, CC_FILT_FREQ, CC_WHEEL, CC_O1_FINE, CC_DEL_LEVEL = 79, 29, 1, 15, 108
MATRIX1 = 0xFC                                           # slot 1: source A, source B, depth, destination
MSG_STATE = 0x20011208
PARAM_SET_BY_ID = 0x0800F6AC                             # (value, id): id = the CC number
EXT_FLASH_READ_PAGE, PATCH_LOAD = 0x0800EA64, 0x0801AEB8
BUTTON_TABLE = 0x20000AB8                                # 4 bytes a button: 4, action, argument (panel_button_event 0x08016FF0)
BUTTON_QUEUE = 0x20003AD0                                # +0x88 64 events (button, bit 7 = pressed), +0x84 write index
ACTION_SAVE, ACTION_COMPARE = 3, 8

pytestmark = pytest.mark.slow


def _board(built, on=True):
    b = _boot(built.patched)
    b.uc.mem_write(GLOBALS + G_MORPH, bytes([1 if on else 0]))
    return b


def _record(b):
    bank, number = b.u8(PATCH_SELECT + 4), b.u8(PATCH_SELECT + 5)
    return ((bank - 1) * 128 + number) & 0x1FF


def _stored(b, offset):
    return b.flash[11].read((_record(b) << 9) + offset, 1)[0]


def _set(b, cc, value, ms=20):
    """A value as a received CC sets it: stock's setter (the simulator's default
    Settings do not take CCs from MIDI IN)."""
    _call(b, PARAM_SET_BY_ID, value, cc)
    b.run_ms(ms)


def _wheel(b, value, ms=400):
    _send(b, 0xB0, CC_WHEEL, value, ms=ms)


def _blend(a, bv, pos):
    return (bv * (127 - pos) + a * pos + 63) // 127


def test_off_the_wheel_changes_nothing(mpe_built):
    b = _board(mpe_built, on=False)
    _set(b, CC_RESONANCE, 100)
    _wheel(b, 127)
    assert b.u8(PATCHES + RESONANCE) == 100


def test_the_wheel_blends_an_edit_back_to_the_stored_value(mpe_built):
    b = _board(mpe_built)
    a = _stored(b, RESONANCE)
    assert b.u8(PATCHES + RESONANCE) == a                # the loaded patch is the stored one
    edit = 100 if a < 60 else 10
    _set(b, CC_RESONANCE, edit)
    assert b.u8(PATCHES + RESONANCE) == edit
    _wheel(b, 127)
    assert b.u8(PATCHES + RESONANCE) == a
    _wheel(b, 64)
    assert b.u8(PATCHES + RESONANCE) == _blend(a, edit, 64)
    _wheel(b, 1)
    assert b.u8(PATCHES + RESONANCE) == _blend(a, edit, 1)
    _wheel(b, 0)
    assert b.u8(PATCHES + RESONANCE) == edit


def test_the_stored_patch_is_the_loaded_patchs_own_record(mpe_built):
    b = _board(mpe_built)
    record = _record(b)
    a = _stored(b, RESONANCE)
    b.flash[11].write((record << 9) + RESONANCE, bytes([a ^ 0x55 if (a ^ 0x55) < 128 else 33]))
    for other in ((record + 1) & 0x1FF, (record - 1) & 0x1FF):
        b.flash[11].write((other << 9) + RESONANCE, bytes([77]))
    want = _stored(b, RESONANCE)
    assert want not in (a, 77)
    _wheel(b, 127)
    assert b.u8(PATCHES + RESONANCE) == want
    _wheel(b, 0)
    assert b.u8(PATCHES + RESONANCE) == a


def test_the_position_follows_a_jump_as_a_ramp(mpe_built):
    b = _board(mpe_built)
    a = _stored(b, RESONANCE)
    edit = 100 if a < 60 else 10
    _set(b, CC_RESONANCE, edit)
    _send(b, 0xB0, CC_WHEEL, 127, ms=1)
    seen = set()
    for _ in range(20):
        b.run_ms(10)
        seen.add(b.u8(PATCHES + RESONANCE))
    lo, hi = min(a, edit), max(a, edit)
    assert len({v for v in seen if lo < v < hi}) >= 4, seen   # about eight slots of 16 ms
    assert b.u8(PATCHES + RESONANCE) == a


def test_a_nine_bit_control_blends_as_one_value(mpe_built):
    b = _board(mpe_built)

    def freq():
        return b.u8(PATCHES + FILT_FREQ) * 2 + (b.u8(PATCHES + FILT_FREQ + 1) >> 6)

    a = freq()
    _set(b, CC_FILT_FREQ, 20 if a > 128 else 110)
    edit = freq()
    assert abs(edit - a) > 60
    _wheel(b, 127)
    assert freq() == a
    _wheel(b, 63)
    assert freq() == _blend(a, edit, 63)
    _wheel(b, 0)
    assert freq() == edit


def test_a_low_fine_tune_comes_back(mpe_built):
    """Stock's setter holds the coarse byte of O1Fine against the pair's range
    (28-228) and refuses 14-27, the lowest fine tunings. The morph has to get
    such an edit back when the wheel returns."""
    b = _board(mpe_built)

    def fine():
        return b.u8(PATCHES + O1_FINE) * 2 + (b.u8(PATCHES + O1_FINE + 1) >> 6)

    a = fine()
    before = b.u8(PATCHES + O1_FINE)
    _call(b, PARAM_SET_BY_ID, 16, CC_O1_FINE)            # as a CC from MIDI: refused
    assert b.u8(PATCHES + O1_FINE) == before
    b.uc.mem_write(PATCHES + O1_FINE, bytes([16, 0]))    # the edit: 32, 96 cents flat or so
    _wheel(b, 127)
    assert fine() == a
    _wheel(b, 100)
    assert fine() == _blend(a, 32, 100)
    _wheel(b, 0)
    assert fine() == 32


def test_locked_fx_are_not_morphed(mpe_built):
    """PARAM LOCK > Lock FX: the FX are not the stored patch's on purpose."""
    b = _board(mpe_built)
    b.uc.mem_write(GLOBALS + G_LOCK_FX, bytes([1]))
    a = _stored(b, DEL_LEVEL)
    b.uc.mem_write(PATCHES + DEL_LEVEL, bytes([a + 50]))
    _set(b, CC_RESONANCE, 90)
    _wheel(b, 127)
    assert b.u8(PATCHES + DEL_LEVEL) == a + 50
    assert b.u8(PATCHES + RESONANCE) == _stored(b, RESONANCE)
    _set(b, CC_DEL_LEVEL, a + 20, ms=200)                # an edit of it with the wheel up stays as made
    assert b.u8(PATCHES + DEL_LEVEL) == a + 20
    b.uc.mem_write(GLOBALS + G_LOCK_FX, bytes([0]))         # lock off: now it follows the wheel
    b.run_ms(200)
    assert b.u8(PATCHES + DEL_LEVEL) == a


def test_switches_stay_as_edited(mpe_built):
    b = _board(mpe_built)
    slope = b.u8(PATCHES + FILT_SLOPE) ^ 1
    b.uc.mem_write(PATCHES + FILT_SLOPE, bytes([slope]))
    _set(b, CC_RESONANCE, 90)
    _wheel(b, 127)
    assert b.u8(PATCHES + FILT_SLOPE) == slope
    assert b.u8(PATCHES + RESONANCE) == _stored(b, RESONANCE)


def test_an_edit_with_the_wheel_up_is_the_new_edited_value(mpe_built):
    """A received CC (or a menu) while the wheel is up: the value becomes B."""
    b = _board(mpe_built)
    a = _stored(b, RESONANCE)
    _set(b, CC_RESONANCE, 100 if a < 60 else 10)
    _wheel(b, 127)
    _set(b, CC_RESONANCE, 70, ms=200)
    assert b.u8(PATCHES + RESONANCE) == a                # at 127 the stored value sounds
    _wheel(b, 0)
    assert b.u8(PATCHES + RESONANCE) == 70


def test_a_knob_with_the_wheel_up_sets_the_edit_and_applies_the_blend(mpe_built):
    b, blob = _board(mpe_built), mpe_built.blob
    a = _stored(b, RESONANCE)
    start = 100 if a < 60 else 10
    _set(b, CC_RESONANCE, start)
    _wheel(b, 64)
    turned = start + 12
    applied, _ = _overlay(b, blob.address("disp_knob_overlay"), RESONANCE, start, turned, a)
    assert not applied                                   # stock must not write the knob's own position
    assert b.u8(PATCHES + RESONANCE) == _blend(a, turned, 64)   # the blend of it is in the patch
    b.run_ms(100)
    assert b.u8(PATCHES + RESONANCE) == _blend(a, turned, 64)
    _wheel(b, 0)
    assert b.u8(PATCHES + RESONANCE) == turned


def test_a_matrix_slot_added_by_hand_fades_to_zero(mpe_built):
    b = _board(mpe_built)
    src, dest = b.u8(PATCHES + MATRIX1), b.u8(PATCHES + MATRIX1 + 3)
    b.uc.mem_write(PATCHES + MATRIX1, bytes([src + 2, 0, 110, dest + 3]))   # another routing, depth +46
    _wheel(b, 127)
    assert b.u8(PATCHES + MATRIX1 + 2) == 64
    assert b.u8(PATCHES + MATRIX1) == src + 2 and b.u8(PATCHES + MATRIX1 + 3) == dest + 3
    _wheel(b, 0)
    assert b.u8(PATCHES + MATRIX1 + 2) == 110


def test_many_controls_are_spread_over_slots(mpe_built):
    b = _board(mpe_built)
    offsets = [0x24, 0x25, 0x2B, 0x2C, 0x2D, 0x2E, 0x3B, 0x3E, 0x3F, 0x40, 0x50, 0x53, 0x54, 0x55,
               0x65, 0x68, 0x69, 0x6A, 0x79, 0x7A, 0x7B, 0x7C, 0x7D, 0x7E, 0x81, 0x82, 0x87, 0x8B,
               0x92, 0x93, 0x94, 0x95, 0x98, 0x9B, 0x9C, 0x9D, 0x9E, 0xA1, 0xA3, 0xA4, 0xA5, 0xA6,
               0xB1, 0xB2, 0xBF, 0xC0, 0xC7, 0xCC, 0xCD, 0xCF, 0xD2, 0xD9, 0xDB, 0xDE, 0xE5, 0xE7]
    a = {o: _stored(b, o) for o in offsets}
    for o in offsets:
        b.uc.mem_write(PATCHES + o, bytes([a[o] + 20 if a[o] < 100 else a[o] - 20]))
    _send(b, 0xB0, CC_WHEEL, 127, ms=40)                 # two or three slots
    moved = sum(b.u8(PATCHES + o) != (a[o] + 20 if a[o] < 100 else a[o] - 20) for o in offsets)
    assert 0 < moved <= 48, moved                        # at most 16 setter calls a slot
    b.run_ms(1500)
    assert all(b.u8(PATCHES + o) == a[o] for o in offsets)
    assert _call(b, mpe_built.blob.address("morph_differ")) == len(offsets)


def test_switching_off_with_the_wheel_up_gives_the_edit_back(mpe_built):
    b = _board(mpe_built)
    a = _stored(b, RESONANCE)
    edit = 100 if a < 60 else 10
    _set(b, CC_RESONANCE, edit)
    _wheel(b, 127)
    assert b.u8(PATCHES + RESONANCE) == a
    b.uc.mem_write(GLOBALS + G_MORPH, b"\x00")
    b.run_ms(400)
    assert b.u8(PATCHES + RESONANCE) == edit
    _set(b, CC_RESONANCE, 55)                     # and the morph has let go
    assert b.u8(PATCHES + RESONANCE) == 55


def test_a_patch_load_starts_afresh(mpe_built):
    b = _board(mpe_built)
    a = _stored(b, RESONANCE)
    _set(b, CC_RESONANCE, 100 if a < 60 else 10)
    _wheel(b, 100)
    page = _call(b, EXT_FLASH_READ_PAGE, _record(b) << 9, 0x200)   # a patch load, the wheel still up:
    _call(b, PATCH_LOAD, page)                                     # the record, then stock's load of it
    b.run_ms(400)
    assert b.u8(PATCHES + RESONANCE) == _stored(b, RESONANCE)
    _set(b, CC_RESONANCE, 90, ms=300)             # an edit of the new patch
    _wheel(b, 0)
    assert b.u8(PATCHES + RESONANCE) == 90


def _button(b, action, pressed, ms=300):
    """A panel button as the scan reports it: an event in the firmware's
    queue, taken by the main loop (panel_button_event)."""
    ids = [i for i in range(64) if bytes(b.uc.mem_read(BUTTON_TABLE + 4 * i, 2)) == bytes([4, action])]
    assert len(ids) == 1, ids
    w = b.u8(BUTTON_QUEUE + 0x84)
    b.uc.mem_write(BUTTON_QUEUE + 0x88 + w, bytes([ids[0] | (0x80 if pressed else 0)]))
    b.uc.mem_write(BUTTON_QUEUE + 0x84, bytes([(w + 1) & 0x3F]))
    b.run_ms(ms)


def _compare(b, pressed, ms=300):
    """Compare held or let go. Held, stock keeps the patch aside (0x20012570)
    and loads the stored one; let go, it copies the patch back."""
    _button(b, ACTION_COMPARE, pressed, ms)


@pytest.mark.parametrize("pos", [64, 127])
def test_compare_with_the_wheel_up_gives_the_blend_back(mpe_built, pos):
    b = _board(mpe_built)
    a = _stored(b, RESONANCE)
    edit = 100 if a < 60 else 10
    _set(b, CC_RESONANCE, edit)
    _wheel(b, pos)
    assert b.u8(PATCHES + RESONANCE) == _blend(a, edit, pos)
    _compare(b, True)
    assert b.u8(PATCHES + RESONANCE) == a                # Compare plays the stored patch
    _compare(b, False)
    assert b.u8(PATCHES + RESONANCE) == _blend(a, edit, pos)
    _wheel(b, 0)
    assert b.u8(PATCHES + RESONANCE) == edit             # and the edit is still there


def test_the_wheel_moved_during_compare_counts_at_the_release(mpe_built):
    b = _board(mpe_built)
    a = _stored(b, RESONANCE)
    edit = 100 if a < 60 else 10
    _set(b, CC_RESONANCE, edit)
    _wheel(b, 100)
    _compare(b, True)
    _wheel(b, 30)
    assert b.u8(PATCHES + RESONANCE) == a                # still the stored patch
    _compare(b, False)
    assert b.u8(PATCHES + RESONANCE) == _blend(a, edit, 30)
    _compare(b, True)                                    # and with the wheel taken to 0 meanwhile
    _wheel(b, 0)
    _compare(b, False)
    assert b.u8(PATCHES + RESONANCE) == edit


def test_compare_does_not_start_a_morph(mpe_built):
    """The wheel goes up while Compare is held and nothing was morphing: the
    patch that sounds is the stored one, not an edit to blend."""
    b = _board(mpe_built)
    a = _stored(b, RESONANCE)
    edit = 100 if a < 60 else 10
    _set(b, CC_RESONANCE, edit)
    _compare(b, True)
    _wheel(b, 127)
    assert b.u8(PATCHES + RESONANCE) == a
    _wheel(b, 0)
    _compare(b, False)
    assert b.u8(PATCHES + RESONANCE) == edit
    _wheel(b, 127)
    assert b.u8(PATCHES + RESONANCE) == a
    _wheel(b, 0)
    assert b.u8(PATCHES + RESONANCE) == edit


def test_save_with_the_wheel_up_stores_the_blend_and_it_is_the_patch(mpe_built):
    b = _board(mpe_built)
    a = _stored(b, RESONANCE)
    edit = 100 if a < 60 else 10
    _set(b, CC_RESONANCE, edit)
    _wheel(b, 64)
    mid = _blend(a, edit, 64)
    assert b.u8(PATCHES + RESONANCE) == mid
    for _ in range(6):                                   # Save: name, category, destination, done
        _button(b, ACTION_SAVE, True, ms=100)
        _button(b, ACTION_SAVE, False, ms=100)
        if _stored(b, RESONANCE) == mid:
            break
    assert _stored(b, RESONANCE) == mid                  # what sounded is what is stored
    b.run_ms(300)
    assert b.u8(PATCHES + RESONANCE) == mid
    _wheel(b, 127)
    assert b.u8(PATCHES + RESONANCE) == mid              # stored and patch are the same now
    _wheel(b, 0)
    assert b.u8(PATCHES + RESONANCE) == mid
    assert _call(b, mpe_built.blob.address("morph_differ")) == 0


def test_compare_on_the_save_page_plays_the_destination_and_the_blend_comes_back(mpe_built):
    """Save, page 2 (the destination): Compare plays the patch stored there
    (stock, 0x0801AF44). With the wheel up the blend has to be back at the
    release, and it is the blend that the last Save press stores."""
    b = _board(mpe_built)
    a = _stored(b, RESONANCE)
    edit = 100 if a < 60 else 10
    _set(b, CC_RESONANCE, edit)
    _wheel(b, 64)
    mid = _blend(a, edit, 64)
    for _ in range(2):                                   # the name page, then the destination page
        _button(b, ACTION_SAVE, True, ms=100)
        _button(b, ACTION_SAVE, False, ms=100)
    _compare(b, True)
    assert b.u8(PATCHES + RESONANCE) == a
    _compare(b, False)
    assert b.u8(PATCHES + RESONANCE) == mid
    for _ in range(2):
        _button(b, ACTION_SAVE, True, ms=100)
        _button(b, ACTION_SAVE, False, ms=100)
    assert _stored(b, RESONANCE) == mid
    _wheel(b, 0)
    assert b.u8(PATCHES + RESONANCE) == mid


def test_morphing_asks_for_no_page_redraw(mpe_built):
    b = _board(mpe_built)
    _set(b, CC_RESONANCE, 100)
    _wheel(b, 20)
    b.uc.mem_write(MSG_STATE + 1, b"\x00")               # stock's changed flag: clear
    before = b.u8(PATCHES + RESONANCE)
    _wheel(b, 110)
    assert b.u8(PATCHES + RESONANCE) != before
    assert b.u8(MSG_STATE + 1) == 0


def test_morph_page(mpe_built):
    b, blob = _board(mpe_built, on=False), mpe_built.blob
    rows = _show(b, 8, MORPH_PAGE, 0)
    assert rows[0].startswith("MORPH"), rows
    assert rows[1].startswith("Morph") and "Off" in rows[1], rows
    assert rows[2].startswith("Position") and rows[2].split()[1] == "0", rows
    assert rows[3].startswith("Differ") and rows[3].split()[1] == "0", rows
    _call(b, blob.address("mpe_ui_value_change"), 1)
    assert b.u8(GLOBALS + G_MORPH) == 1
    assert "ModWheel" in _show(b, 8, MORPH_PAGE, 0)[1]
    _set(b, CC_RESONANCE, 100 if _stored(b, RESONANCE) < 60 else 10)
    _wheel(b, 90)
    rows = _show(b, 8, MORPH_PAGE, 0)
    assert rows[2].split()[1] == "90" and rows[3].split()[1] == "1", rows
    _show(b, 8, MORPH_PAGE, 1)                           # the read-only rows take no edit
    _call(b, blob.address("mpe_ui_value_change"), 1)
    assert _show(b, 8, MORPH_PAGE, 0)[2].split()[1] == "90"
    rows = _show(b, 8, MORPH_PAGE + 1, 0)                # the stock page after ours is still there
    assert rows[0].startswith("MIDI ENABLE"), rows
