"""Peak MPE: notes on a zone's master channel (patches/peak_mpe/mpe_voice.c, v0.36).

With MPE on, a member channel plays one note at a time (a new note takes
over the voice still sounding on its channel). The master channel plays as
the Peak's normal channel, so a chord there sounds in full. Before v0.36
channel reuse caught the master channel too and its notes took each other's
voice (found on the synth in series AC; docs/findings, "Notes on the master
channel play one at a time with MPE on").
"""
import pytest

from test_peak_sim import FLAG, PATCHES, _boot, _send, mpe_built  # noqa: F401

pytestmark = pytest.mark.slow

VOICE_NOTE = 0x20012794
GATE = 0x20004650 + 0x1F4
C4, E4, G4 = 60, 64, 67


@pytest.fixture
def board(mpe_built):
    b = _boot(mpe_built.patched)
    b.run_ms(200)
    b.uc.mem_write(PATCHES + FLAG, b"\x01")       # MPE on; no zone configured: Lower Zone, 15 members
    return b


def _sounding(b):
    notes = b.uc.mem_read(VOICE_NOTE, 8)
    gates = b.uc.mem_read(GATE, 8)
    return sorted(notes[v] for v in range(8) if gates[v])


def test_a_chord_on_the_master_channel_plays_in_full(board):
    b = board
    _send(b, 0x90, C4, 100, 0x90, E4, 100, 0x90, G4, 100, ms=60)
    assert _sounding(b) == [C4, E4, G4]


def test_a_master_note_off_ends_only_its_note(board):
    b = board
    _send(b, 0x90, C4, 100, 0x90, E4, 100, 0x90, G4, 100, ms=60)
    _send(b, 0x80, E4, 0, ms=60)
    assert _sounding(b) == [C4, G4]


def test_the_upper_zone_master_plays_chords_too(board):
    b = board
    # MCM: Lower Zone off (RPN 6 = 0 on channel 1), Upper Zone with 15 members (on channel 16)
    for ch, n in ((0x0, 0), (0xF, 15)):
        _send(b, 0xB0 | ch, 101, 0, 0xB0 | ch, 100, 6, 0xB0 | ch, 6, n, ms=20)
    b.run_ms(100)
    _send(b, 0x9F, C4, 100, 0x9F, E4, 100, 0x9F, G4, 100, ms=60)
    assert _sounding(b) == [C4, E4, G4]


def test_a_member_channel_still_plays_one_note_at_a_time(board):
    b = board
    _send(b, 0x91, C4, 100, ms=40)                  # member channel 2
    _send(b, 0x91, E4, 100, ms=60)                  # the same channel: takes over C's voice
    assert _sounding(b) == [E4]


def test_master_and_member_notes_together(board):
    b = board
    _send(b, 0x90, C4, 100, 0x90, E4, 100, ms=40)   # master
    _send(b, 0x91, G4, 100, ms=60)                  # member channel 2
    assert _sounding(b) == [C4, E4, G4]
