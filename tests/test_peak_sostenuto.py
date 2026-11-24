"""Peak: the sostenuto pedal (CC 66) lets go only of keys that are up
(patches/peak_mpe/sostenuto.c, v0.38).

Stock's pedal-up (0x08011F90) released every voice the pedal held unless the
sustain pedal held it, without looking at the key: a key held down through
the pedal's release stopped sounding. A voice's release is its amp envelope's
release command (FPGA param 0x3F, command 3).
"""
import pytest

from test_peak_sim import _boot, _send, mpe_built  # noqa: F401

pytestmark = pytest.mark.slow

SUSTAIN, SOSTENUTO = 64, 66


@pytest.fixture
def board(mpe_built):
    b = _boot(mpe_built.patched)
    b.run_ms(300)
    return b


def _voice_of(b, note):
    b.fpga.reset()
    _send(b, 0x90, note, 100, ms=5)
    took = {e.target for e in b.fpga.events
            if not e.read and e.target < 8 and e.param == 0x3F and e.value & 3 == 0}
    assert len(took) == 1, took
    return took.pop()


def _released(b, msgs, ms=5):
    """Send msgs; return the voices that got an amp release command."""
    b.fpga.reset()
    for m in msgs:
        _send(b, *m, ms=ms)
    return {e.target for e in b.fpga.events
            if not e.read and e.target < 8 and e.param == 0x3F and e.value & 3 == 3}


def test_a_key_held_through_the_pedal_release_keeps_sounding(board):
    b = board
    v = _voice_of(b, 60)
    assert _released(b, [(0xB0, SOSTENUTO, 127), (0xB0, SOSTENUTO, 0)]) == set()   # stock released it here
    assert _released(b, [(0x80, 60, 0)]) == {v}                                     # and the key lets it go


def test_a_key_let_go_under_the_pedal_ends_at_pedal_up(board):
    b = board
    v = _voice_of(b, 60)
    assert _released(b, [(0xB0, SOSTENUTO, 127), (0x80, 60, 0)]) == set()           # the pedal holds it
    assert _released(b, [(0xB0, SOSTENUTO, 0)]) == {v}


def test_only_the_keys_that_are_up_end(board):
    b = board
    va, vb = _voice_of(b, 60), _voice_of(b, 64)
    assert _released(b, [(0xB0, SOSTENUTO, 127), (0x80, 60, 0)]) == set()
    assert _released(b, [(0xB0, SOSTENUTO, 0)]) == {va}                             # 64 still down
    assert _released(b, [(0x80, 64, 0)]) == {vb}


def test_with_the_sustain_pedal(board):
    b = board
    va = _voice_of(b, 60)
    # Sostenuto down, then sustain down; let go of the key: both pedals hold it.
    assert _released(b, [(0xB0, SOSTENUTO, 127), (0xB0, SUSTAIN, 127), (0x80, 60, 0)]) == set()
    assert _released(b, [(0xB0, SUSTAIN, 0)]) == set()                              # sostenuto still holds
    assert _released(b, [(0xB0, SOSTENUTO, 0)]) == {va}                             # its key is up
    # A key down at sostenuto up, sustain down: the key's release goes to the sustain pedal.
    vb = _voice_of(b, 62)
    assert _released(b, [(0xB0, SOSTENUTO, 127), (0xB0, SUSTAIN, 127), (0xB0, SOSTENUTO, 0)]) == set()
    assert _released(b, [(0x80, 62, 0)]) == set()
    assert _released(b, [(0xB0, SUSTAIN, 0)]) == {vb}


def test_a_key_held_by_sustain_at_sostenuto_down_ends_at_its_pedal_ups(board):
    b = board
    v = _voice_of(b, 60)
    # Key up under sustain, then sostenuto down: the key is already up.
    assert _released(b, [(0xB0, SUSTAIN, 127), (0x80, 60, 0), (0xB0, SOSTENUTO, 127), (0xB0, SUSTAIN, 0)]) == set()
    assert _released(b, [(0xB0, SOSTENUTO, 0)]) == {v}
