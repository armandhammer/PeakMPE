"""Peak: where a poly glide starts (Settings > MPE EXTRAS > Glide;
docs/findings/peak-2.2-build2108.md, "Glide").

Stock starts a note's glide from the pitch its voice last had. LastNote
starts it from the previous note; Legato does so only while another note is
held. Pitches are the firmware's own, 1/256 semitone (voice_pitch_out).
"""
import struct

import pytest

from test_peak_sim import GLOBALS, PATCHES, _boot, _call, _send, _show, mpe_built  # noqa: F401

VOICE_STATE, VOICE_PITCH_OUT = 0x20004650, 0x20012544
VOICE_PARAMS_CHANGED = 0x08012D80      # recomputes the glide rate from the patch
GLIDE_TIME, PRE_GLIDE, GLIDE_ON = 0x27, 0x28, 0x29
G_GLIDE = 0x3E
STOCK, LAST_NOTE, LEGATO = 0, 1, 2
SETTLE_MS = 800                        # GlideTime 60 is there in under 300 ms

pytestmark = pytest.mark.slow


def _board(image, mode):
    b = _boot(image)
    b.uc.mem_write(PATCHES + GLIDE_ON, b"\x01")
    b.uc.mem_write(PATCHES + GLIDE_TIME, bytes([60]))
    _call(b, VOICE_PARAMS_CHANGED)
    b.uc.mem_write(GLOBALS + G_GLIDE, bytes([mode]))
    return b


def _out(b, v):
    return struct.unpack_from("<8H", bytes(b.uc.mem_read(VOICE_PITCH_OUT, 16)))[v] / 256


def _on(b, note, ms=3):
    """Play a note; return (voice, its pitch a few ms later, in semitones)."""
    b.fpga.reset()
    _send(b, 0x90, note, 100, ms=ms)
    took = {e.target for e in b.fpga.events
            if not e.read and e.target < 8 and e.param == 0x3F and e.value & 3 == 0}
    assert len(took) == 1, took
    v = took.pop()
    return v, _out(b, v)


def _from(start, origin, target):
    """The pitch a few ms into a glide is still near where it started: within a
    fifth of the way from origin to target (the glide is fastest at its start)."""
    return abs(start - origin) <= 0.2 * abs(target - origin) and abs(start - target) > 0.5 * abs(target - origin)


def _off(b, note):
    _send(b, 0x80, note, 0, ms=5)


def test_stock_glides_from_the_voices_own_last_pitch(mpe_built):
    b = _board(mpe_built.patched, STOCK)
    va, start = _on(b, 48)
    assert _from(start, 60, 48)             # every voice is left at note 60 by power-on
    b.run_ms(SETTLE_MS)
    assert _out(b, va) == 48
    vb, start = _on(b, 72)                  # 48 still held: another voice
    assert vb != va and _from(start, 60, 72)    # from that voice's 60, not from 48
    b.run_ms(SETTLE_MS)
    assert _out(b, vb) == 72


def test_last_note_glides_from_the_previous_note(mpe_built):
    b = _board(mpe_built.patched, LAST_NOTE)
    va, start = _on(b, 48)
    assert _from(start, 60, 48)             # the first note has no previous one: as stock
    b.run_ms(SETTLE_MS)
    vb, start = _on(b, 72)
    assert vb != va and _from(start, 48, 72)    # from 48
    b.run_ms(SETTLE_MS)
    assert _out(b, vb) == 72 and _out(b, va) == 48      # the held note stays put
    _off(b, 48); _off(b, 72)
    vc, start = _on(b, 50)                  # detached: still from the last note
    assert _from(start, 72, 50)
    b.run_ms(SETTLE_MS)
    assert _out(b, vc) == 50


def test_last_note_follows_a_glide_in_progress(mpe_built):
    b = _board(mpe_built.patched, LAST_NOTE)
    va, _ = _on(b, 48)
    b.run_ms(SETTLE_MS)
    vb, _ = _on(b, 72, ms=40)               # on its way up from 48
    mid = _out(b, vb)
    assert 49 < mid < 71
    vc, start = _on(b, 60)
    assert abs(start - mid) < 3 or mid < start < 72     # from where the last note is now, not from 72 or 48


def test_legato_glides_only_from_a_held_note(mpe_built):
    b = _board(mpe_built.patched, LEGATO)
    va, start = _on(b, 55)
    assert start == 55                      # detached: on pitch at once (stock would glide from 60)
    vb, start = _on(b, 79)                  # 55 held
    assert vb != va and _from(start, 55, 79)
    b.run_ms(SETTLE_MS)
    assert _out(b, vb) == 79
    _off(b, 55); _off(b, 79)
    vc, start = _on(b, 40)                  # nothing held
    assert start == 40


def test_glide_off_in_the_patch_stays_off(mpe_built):
    b = _board(mpe_built.patched, LAST_NOTE)
    b.uc.mem_write(PATCHES + GLIDE_ON, b"\x00")
    _call(b, VOICE_PARAMS_CHANGED)
    _on(b, 48)
    _, start = _on(b, 72)
    assert start == 72


def test_glide_setting_on_the_extras_page(mpe_built):
    b = _boot(mpe_built.patched)
    rows = _show(b, 8, 6, 2)                # Settings MPE EXTRAS, third item
    assert any("Glide" in r and "Stock" in r for r in rows), rows
    _call(b, mpe_built.blob.address("mpe_ui_value_change"), 1)
    assert b.u8(GLOBALS + G_GLIDE) == LAST_NOTE
    rows = _show(b, 8, 6, 2)
    assert any("Glide" in r and "LastNote" in r for r in rows), rows
    _call(b, mpe_built.blob.address("mpe_ui_value_change"), 5)
    assert b.u8(GLOBALS + G_GLIDE) == LEGATO
    rows = _show(b, 8, 6, 2)
    assert any("Glide" in r and "Legato" in r for r in rows), rows
