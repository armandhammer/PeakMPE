"""Peak: with every voice still in its attack, a new note takes the oldest one
(patches/peak_mpe/steal.c, v0.39).

Stock's voice_candidates (0x08011B70) keeps, of the voices in envelope state 0
(attack), the one with the largest start stamp, so a new note cut the note
played just before it (observed on the synth, findings "Voice allocation and
stealing"; stock pinned in test_peak_voice_steal.py). The user guide says, of
Unison, that when voices run out "the first note played will be cancelled".
The patch keeps the smallest stamp instead. A voice in release and then a held
one still go first, as in stock. The FPGA's replies are modelled
(emu/fpga.py, VoiceStateModel), as in test_peak_voice_steal.py.
"""
import pytest

from test_peak_sim import _boot, _send, mpe_built  # noqa: F401

pytestmark = pytest.mark.slow

VOICE_STATE, VOICE_NOTE = 0x20004650, 0x20012794
GATE = VOICE_STATE + 0x1F4
RELEASE_MS = 1000.0
SLOW = 10000.0


@pytest.fixture(scope="module")
def board(mpe_built):
    b = _boot(mpe_built.patched)
    b.fpga.voices.release_ms = RELEASE_MS
    b.run_ms(300)
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


@pytest.fixture
def attack(board):
    """A slow attack for the test; afterwards everything let go and quiet."""
    board.fpga.voices.attack_ms = SLOW
    yield board
    board.fpga.voices.attack_ms = 5.0
    for n in _held(board):
        _off(board, n, 2)
    board.run_ms(RELEASE_MS + 200)
    assert not any(_gates(board))


def _eight(b):
    voice = {n: _on(b, n)[0] for n in range(60, 68)}
    assert len(set(voice.values())) == 8
    return voice


def test_all_in_attack_the_oldest_goes(attack):
    b = attack
    voice = _eight(b)
    assert _on(b, 72) == (voice[60], 60)     # stock: voice[67], cutting 67
    assert _on(b, 73) == (voice[61], 61)     # stock: the same voice again, cutting 72
    assert _on(b, 74) == (voice[62], 62)
    assert _held(b) == [63, 64, 65, 66, 67, 72, 73, 74]


def test_age_not_rotation(attack):
    b = attack
    voice = _eight(b)
    _off(b, 63, 50)                          # a releasing voice is taken first, as stock
    assert _on(b, 72) == (voice[63], None)
    assert _on(b, 73) == (voice[60], 60)     # then the oldest, not the voice after the pick
    assert _on(b, 74) == (voice[61], 61)
    assert 72 in _held(b)                    # the newer notes keep sounding


def test_a_held_voice_still_goes_before_one_in_attack(board):
    b = board
    try:
        # Attack 5 ms: 60-62 read held (state 2) at the next note's read. 63 is
        # read first at 64's, by then with the slow attack, so 63-67 are in theirs.
        for n in (60, 61, 62, 63):
            _on(b, n)
        b.fpga.voices.attack_ms = SLOW
        for n in (64, 65, 66, 67):
            _on(b, n)
        assert sorted(set(_notes(b))) == list(range(60, 68))
        _, cut = _on(b, 72)
        assert cut in (60, 61, 62)           # a held note, as stock, not the oldest in attack (63)
    finally:
        b.fpga.voices.attack_ms = 5.0
        for n in _held(b):
            _off(b, n, 2)
        b.run_ms(RELEASE_MS + 200)


# --- v0.40: held voices at one level -------------------------------------
# Stock keeps the quietest held voice, the first in its scan order (from the
# voice after the last pick) on a tie, and held voices at full sustain tie on
# the synth (A4). v0.40 breaks the tie: a voice a pedal holds with its key up
# first, then the oldest.

SUSTAIN, SOSTENUTO = 64, 66


@pytest.fixture
def held(board):
    """Attack 5 ms; afterwards the pedals up, everything let go and quiet."""
    yield board
    _send(board, 0xB0, SUSTAIN, 0, ms=2)
    _send(board, 0xB0, SOSTENUTO, 0, ms=2)
    for n in _held(board):
        _off(board, n, 2)
    board.run_ms(RELEASE_MS + 200)
    assert not any(_gates(board))


def test_held_at_one_level_the_oldest_goes(held):
    b = held
    voice = _eight(b)
    _off(b, 62, 200)
    assert _on(b, 72) == (voice[62], None)   # the releasing voice first, as stock
    assert _on(b, 73) == (voice[60], 60)     # stock: voice[63], the voice after the pick
    assert _on(b, 74) == (voice[61], 61)
    assert _held(b) == [63, 64, 65, 66, 67, 72, 73, 74]


def test_a_note_the_sustain_pedal_holds_goes_before_a_key_held_down(held):
    b = held
    voice = {n: _on(b, n)[0] for n in (60, 61)}          # keys stay down
    _send(b, 0xB0, SUSTAIN, 127, ms=5)
    for n in range(62, 68):
        voice[n] = _on(b, n)[0]
    for n in range(62, 68):
        _off(b, n, 5)                                    # the pedal holds them
    assert _held(b) == list(range(60, 68))
    assert _on(b, 72) == (voice[62], 62)                 # stock: voice[60], a key still down
    assert _on(b, 73) == (voice[63], 63)
    assert 60 in _held(b) and 61 in _held(b)


def test_a_note_the_sostenuto_pedal_holds_goes_before_a_key_held_down(held):
    b = held
    voice = {n: _on(b, n)[0] for n in range(60, 66)}
    _send(b, 0xB0, SOSTENUTO, 127, ms=5)                 # marks 60-65
    for n in range(62, 66):
        _off(b, n, 5)                                    # the pedal holds 62-65; 60 and 61 stay down
    for n in (66, 67):
        voice[n] = _on(b, n)[0]
    assert _held(b) == list(range(60, 68))
    assert _on(b, 72) == (voice[62], 62)                 # stock: voice[60]
    assert 60 in _held(b) and 61 in _held(b)


# --- v0.41: Settings VOICE STEAL > Keep Low ---------------------------------
# With Keep Low on (Poly, Poly2) neither pick is a voice playing the lowest
# note that sounds: a key held down or a note a pedal holds. A note in its
# release is not kept, and the release candidate still goes first.

GLOBALS, G_KEEP_LOW = 0x20014494, 0x58
PATCH = 0x20012340                       # the edit buffer (test_peak_sim.PATCHES)
UNISON = 0x23                            # 0-3 = 1-4 voices per note, 4 = 8
STEAL_PAGE = 21                          # Settings page index: 4 + 17


@pytest.fixture
def keep(held):
    held.uc.mem_write(GLOBALS + G_KEEP_LOW, b"\x01")
    yield held
    held.uc.mem_write(GLOBALS + G_KEEP_LOW, b"\x00")


def test_keep_low_the_lowest_note_stays(keep):
    b = keep
    voice = _eight(b)
    assert _on(b, 72) == (voice[61], 61)     # Off: voice[60], the oldest
    assert _on(b, 73) == (voice[62], 62)
    assert 60 in _held(b)


def test_keep_low_off_cuts_the_oldest_even_if_lowest(held):
    b = held
    voice = _eight(b)
    assert _on(b, 72) == (voice[60], 60)


def test_keep_low_a_bass_the_pedal_holds_stays(keep):
    b = keep
    bass = _on(b, 48)[0]
    _send(b, 0xB0, SUSTAIN, 127, ms=5)
    _off(b, 48, 5)                           # the pedal holds the bass
    voice = {n: _on(b, n)[0] for n in range(60, 67)}
    for n in range(60, 67):
        _off(b, n, 5)
    assert _held(b) == [48] + list(range(60, 67))
    assert _on(b, 72) == (voice[60], 60)     # Off: the bass, the oldest note the pedal holds
    assert 48 in _held(b) and bass not in voice.values()


def test_keep_low_in_the_attack(keep):
    b = keep
    b.fpga.voices.attack_ms = SLOW
    try:
        voice = _eight(b)
        assert _on(b, 72) == (voice[61], 61)  # Off: voice[60]
    finally:
        b.fpga.voices.attack_ms = 5.0


def test_keep_low_a_released_bass_is_not_kept(keep):
    b = keep
    voice = _eight(b)
    _off(b, 60, 200)
    assert _on(b, 72) == (voice[60], None)   # the releasing voice first, as stock


def test_keep_low_a_lower_new_note_becomes_the_lowest(keep):
    b = keep
    voice = _eight(b)
    assert _on(b, 55) == (voice[61], 61)     # 60 is the lowest when 55 arrives
    assert _on(b, 72) == (voice[60], 60)     # now 55 is, and 60 the oldest
    assert 55 in _held(b)


def test_keep_low_unison_8_still_plays_a_second_note(keep):
    b = keep
    b.uc.mem_write(PATCH + UNISON, b"\x04")
    try:
        _send(b, 0x90, 60, 100, ms=40)
        assert _notes(b) == [60] * 8 and all(_gates(b))
        _send(b, 0x90, 64, 100, ms=40)       # the kept note is all there is: taken as with Off
        assert sorted(set(n for n, g in zip(_notes(b), _gates(b)) if g)) == [64]
    finally:
        _off(b, 64, 2)
        _off(b, 60, 2)
        b.uc.mem_write(PATCH + UNISON, b"\x00")


def test_keep_low_settings_page(board, mpe_built):
    from test_peak_sim import _call, _show
    b = board
    change = mpe_built.blob.address("mpe_ui_value_change")
    rows = _show(b, 8, STEAL_PAGE, 0)
    assert rows[0].startswith("VOICE STEAL"), rows
    assert rows[1][:19].split() == ["Keep", "Low", "Off"], rows
    _call(b, change, 1)
    assert b.u8(GLOBALS + G_KEEP_LOW) == 1
    assert _show(b, 8, STEAL_PAGE, 0)[1][:19].split() == ["Keep", "Low", "On"]
    _call(b, change, -1)
    assert b.u8(GLOBALS + G_KEEP_LOW) == 0
    assert _show(b, 8, STEAL_PAGE + 1, 0)[0].startswith("MIDI ENABLE")   # the stock page after ours
