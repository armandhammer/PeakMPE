"""Peak: features that act on their own while Compare is held (an outside
code audit of v0.42, MED-5b and MED-6a, 2026-11-23).

Held, stock keeps the edited patch aside (0x20012570) and plays the stored
one; let go, it copies the edited patch back over whatever is in the patch
then. The patch's motion lane, morph and undo stand still while it is held
(paramlock.c); these are the two that run from the clock.
"""
import pytest

from test_peak_morph import CC_RESONANCE, RESONANCE, _compare, _set
from test_peak_ptime import BAR, CLOCK, G_BANK_PATCH, START, STOP, _loaded, _timing
from test_peak_sim import (AMP_DECAY, AMP_RELEASE, G_ENVSYNC, GLOBALS, PATCHES, _boot, _send, _stock,  # noqa: F401
                           _times, mpe_built)

pytestmark = pytest.mark.slow

G_CLOCK_SOURCE = 0x08          # globals: 3 = MIDI


def _board(image):
    b = _boot(image)
    b.run_ms(300)
    b.uc.mem_write(GLOBALS + G_BANK_PATCH, bytes([3]))   # Bank/Patch Rec+Tran (the simulator boots with 0)
    _set(b, CC_RESONANCE, 123)                           # an edit, not saved
    return b


def _outcome(b):
    return _loaded(b), b.u8(PATCHES + RESONANCE)


def test_a_bar_timed_change_during_compare_ends_as_stocks_change_at_once(mpe_built):
    """Stock, a program change while Compare is held loads the patch (its
    number is the one selected), and the release copies the edited patch
    back over it. A change timed to the bar that falls due while Compare is
    held ends the same way: the patch follows stock rather than holding the
    change back (MED-5b; checked 2026-11-24, no change)."""
    s = _board(_stock())
    _compare(s, True)
    _send(s, 0xC0, 5, ms=300)
    _compare(s, False)
    stock = _outcome(s)
    assert stock == (5, 123)

    b = _board(mpe_built.patched)
    _timing(b, BAR)
    _send(b, START, ms=2)
    for _ in range(10):
        _send(b, CLOCK, ms=2)
    _send(b, 0xC0, 5, ms=2)
    assert _loaded(b) != 5                             # waiting for bar 2
    _compare(b, True, ms=2)
    for _ in range(90):                                # the clock goes on: bar 2 comes while held
        _send(b, CLOCK, ms=2)
    assert _loaded(b) == 5
    _send(b, STOP, ms=300)
    _compare(b, False)
    assert _outcome(b) == stock


TEMPO_WORD, WORD_PER_BPM = 0x20000264, 1717984


def _tempo(b, bpm):
    """The tempo as stock keeps it with an external clock. The simulator
    doesn't model stock's measurement of the clock bytes (the word stays as
    it was); with Clock Source = MIDI stock leaves the word alone, so it is
    written here as that measurement would."""
    b.uc.mem_write(TEMPO_WORD, (bpm * WORD_PER_BPM).to_bytes(4, "little"))


def test_envsync_after_compare_has_the_tempo_that_changed_while_it_was_held(mpe_built):
    """EnvSync 1/8 and an external clock at 120 BPM, then 240 BPM while
    Compare is held. Up to v0.43 EnvSync set the new times in the patch
    Compare plays, which stock throws away at the release, and took them as
    applied: the edited patch came back with the 120 BPM times and kept them
    (MED-6a). From v0.44 EnvSync waits while Compare is held and applies the
    tempo after it."""
    b = _board(mpe_built.patched)
    b.uc.mem_write(GLOBALS + G_CLOCK_SOURCE, bytes([3]))
    b.uc.mem_write(GLOBALS + G_ENVSYNC, bytes([3]))      # 1/8
    _tempo(b, 120)
    b.run_ms(2500)
    decay, release = _times(b)
    assert 200 <= decay <= 320 and 200 <= release <= 320, (decay, release)   # 1/8 = 250 ms
    edited = (b.u8(PATCHES + AMP_DECAY), b.u8(PATCHES + AMP_RELEASE))
    _compare(b, True, ms=200)
    _tempo(b, 240)
    b.run_ms(2000)
    _compare(b, False, ms=50)
    assert (b.u8(PATCHES + AMP_DECAY), b.u8(PATCHES + AMP_RELEASE)) == edited   # the edited patch back
    b.run_ms(2000)
    decay, release = _times(b)
    assert 90 <= decay <= 160 and 90 <= release <= 160, (decay, release)     # 1/8 = 125 ms
