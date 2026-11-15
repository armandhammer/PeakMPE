"""Peak 2.2 (build 2108): which voice the stock allocator takes when all eight
are in use (docs/findings/peak-2.2-build2108.md, "Voice allocation and
stealing").

The allocator ranks voices by what the sound chip reports (2 bits of envelope
state and a 16-bit level per voice). The simulator models those replies
(emu/fpga.py, VoiceStateModel): a voice reads 0 during the model's attack,
then 2 while held, 3 from its release command on, with a level that falls to
0 over ``release_ms``. So these tests pin the MCU's choice for a given reply,
not what the real chip replies.
"""
import pytest

from test_peak_sim import _boot, _send, _stock

VOICE_STATE, VOICE_NOTE = 0x20004650, 0x20012794
GATE = VOICE_STATE + 0x1F4
RELEASE_MS = 1000.0

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def board():
    b = _boot(_stock())
    b.fpga.voices.release_ms = RELEASE_MS
    return b


def _gates(b):
    return list(bytes(b.uc.mem_read(GATE, 8)))


def _notes(b):
    return list(bytes(b.uc.mem_read(VOICE_NOTE, 8)))


def _held(b):
    return sorted(n for n, g in zip(_notes(b), _gates(b)) if g)


def _on(b, note, ms=30):
    """Play a note; return (voice it took, held note it cut or None)."""
    notes, gates = _notes(b), _gates(b)
    b.fpga.reset()
    _send(b, 0x90, note, 100, ms=ms)
    took = {e.target for e in b.fpga.events
            if not e.read and e.target < 8 and e.param == 0x3F and e.value & 3 == 0}
    assert len(took) == 1, took
    v = took.pop()
    return v, (notes[v] if gates[v] else None)


def _off(b, note, ms=10):
    _send(b, 0x80, note, 0, ms=ms)


def _clear(b):
    for n in _held(b):
        _off(b, n, 2)
    b.run_ms(RELEASE_MS + 200)
    assert not any(_gates(b))


def _eight(b):
    return {n: _on(b, n)[0] for n in range(60, 68)}


def test_ninth_note_takes_the_releasing_voice(board):
    b = board
    voice = _eight(b)
    assert len(set(voice.values())) == 8
    _off(b, 62, 200)
    v, cut = _on(b, 72)
    assert v == voice[62] and cut is None
    assert _held(b) == [60, 61, 63, 64, 65, 66, 67, 72]
    _clear(b)


def test_the_quieter_of_two_releasing_voices_goes_first(board):
    b = board
    voice = _eight(b)
    _off(b, 64, 600)                   # further into its release, so quieter
    _off(b, 61, 100)
    assert _on(b, 72) == (voice[64], None)
    assert _on(b, 73) == (voice[61], None)
    _clear(b)


def test_all_held_at_one_level_steals_in_rotation_order(board):
    b = board
    voice = _eight(b)
    assert _on(b, 72) == (voice[60], 60)    # the voice after the last pick
    assert _on(b, 73) == (voice[61], 61)
    _clear(b)
    # Rotation, not age: after a pick in the middle, the next steal is the
    # voice after that pick, although older notes are held.
    voice = _eight(b)
    _off(b, 62, 200)
    assert _on(b, 72) == (voice[62], None)
    assert _on(b, 73) == (voice[63], 63)
    assert 60 in _held(b) and 61 in _held(b)
    _clear(b)


def test_voices_still_in_attack_lose_the_newest(board):
    b = board
    b.fpga.voices.attack_ms = 10000.0
    try:
        voice = _eight(b)
        assert _on(b, 72) == (voice[67], 67)
        assert _on(b, 73) == (voice[67], 72)
    finally:
        b.fpga.voices.attack_ms = 5.0
    _clear(b)
