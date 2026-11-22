"""MPE for Summit: notes on a zone's master channel (patches/mpe/mpe_voice.c, v1.3).

With MPE on, a member channel plays one note at a time (channel reuse: a new
note takes over the voice still sounding on its channel). A zone's master
channel plays as the part's normal channel, so a chord there sounds in full.
Before v1.3 channel reuse caught the master channel too and its notes took
each other's voice, one note at a time: the condition found on the Peak in
series AC and fixed there in Peak v0.36 (docs/findings/peak-2.2-build2108.md).
The Summit has no hardware run of this; emulated only. Mpe.check() asserts
the binding invariants after every note.
"""

import pytest

from mpe_sim import mpe_summit

C4, E4, G4, C5 = 60, 64, 67, 72

# The quick run (-m "not slow") keeps these; the rest are marked slow at the end.
QUICK = {
    "test_a_chord_on_the_master_channel_plays_in_full",
    "test_a_member_channel_still_plays_one_note_at_a_time",
}


@pytest.fixture
def m(tmp_path_factory):
    m = mpe_summit(tmp_path_factory).reset()
    m.flag()  # no zone configured: Lower Zone, master 1, members 2-16
    return m


def sounding(m, voices=None):
    s = m.s
    return sorted(s.voice_note(v) for v in s.active_voices() if voices is None or v in voices)


def chord(m, ch, notes):
    for n in notes:
        m.on(n, ch)


# -- Single mode ----------------------------------------------------------------------


def test_a_chord_on_the_master_channel_plays_in_full(m):
    assert m.zones() == {"lower": (0, 1, 2, 16)}
    chord(m, 1, (C4, E4, G4))
    assert sounding(m) == [C4, E4, G4]
    assert sorted(m.s.voice_note(v) for v in m.bound(1)) == [C4, E4, G4]
    m.all_off()


def test_a_master_note_off_ends_only_its_note(m):
    chord(m, 1, (C4, E4, G4))
    m.off(E4, 1)
    assert sounding(m) == [C4, G4]
    m.off(C4, 1)
    assert sounding(m) == [G4]
    m.all_off()


def test_the_upper_zone_master_plays_chords_too(m):
    m.mcm(1, 0)
    m.mcm(16, 15)
    assert m.zones() == {"upper": (0, 16, 1, 15)}
    chord(m, 16, (C4, E4, G4))
    assert sounding(m) == [C4, E4, G4]
    m.off(G4, 16)
    assert sounding(m) == [C4, E4]
    m.all_off()


def test_a_member_channel_still_plays_one_note_at_a_time(m):
    m.on(C4, 2)
    m.on(E4, 2)  # the same member channel: takes over C4's voice
    assert sounding(m) == [E4]
    assert len(m.bound(2)) == 1
    m.all_off()


def test_master_and_member_notes_together(m):
    chord(m, 1, (C4, E4))
    m.on(G4, 2)
    m.on(C5, 3)
    assert sounding(m) == [C4, E4, G4, C5]
    m.off(C4, 1)
    assert sounding(m) == [E4, G4, C5]
    m.all_off()


# -- Multi mode -----------------------------------------------------------------------


def test_in_multi_each_parts_master_plays_chords_on_its_own_voices(m):
    m.s.set_mode("multi")
    m.s.set_channels(global_=16, part_a=11, part_b=12)
    m.flag(True, part=0)
    m.flag(True, part=1)
    m.s.tick(2)
    # No zone configured, both parts on: Lower 7 (2-8) to Part A, Upper 7 (9-15) to Part B.
    assert m.zones() == {"lower": (0, 1, 2, 8), "upper": (1, 16, 9, 15)}
    chord(m, 1, (C4, E4, G4))
    chord(m, 16, (E4, G4, C5))
    assert sounding(m, range(8)) == [C4, E4, G4]
    assert sounding(m, range(8, 16)) == [E4, G4, C5]
    m.off(E4, 16)  # Part B's E4 only; Part A's E4 sounds on
    assert sounding(m, range(8)) == [C4, E4, G4]
    assert sounding(m, range(8, 16)) == [G4, C5]
    m.all_off()


for _name, _test in list(globals().items()):
    if _name.startswith("test_") and _name not in QUICK:
        globals()[_name] = pytest.mark.slow(_test)
