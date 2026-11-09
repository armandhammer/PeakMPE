"""MPE v1.1 channel reuse: idle voices rotate as stock (patches/mpe/mpe_voice.c).

v1 took a channel's voices over whether they sounded, released or were idle,
so a sender reusing a channel always got the same voice (hardware
observation L5 of the v1 run, docs/hardware-log.md). v1.1 takes over only a
voice that still sounds or releases; an idle one is unbound and the note goes
to the stock allocator.

Emulated. "Releasing" vs "idle" is what the FPGA reports (envelope state 3
for both, level above 0x200 while it still sounds; observed in
voice_candidates), so these tests turn on the simulator's release model
(``SimulatedSummit.release_ms``, inferred: a voice's level falls to 0 over
that many ms after its release command).
"""

import pytest

from mpe_expr_sim import MODWHEEL, member_offset, osc, shifted
from mpe_sim import MODE, UNISON, mpe_summit

RELEASE = 40  # ms the modelled release takes
QUICK = {
    "test_reused_channel_after_the_release_rotates_like_mpe_off",
    "test_reused_channel_during_the_release_takes_over_that_voice",
}


@pytest.fixture
def m(tmp_path_factory):
    m = mpe_summit(tmp_path_factory).reset()
    m.s.release_ms = RELEASE
    return m


def started_voices(s, since_ms):
    """Voices that got an amp envelope start since *since_ms*, in order."""
    return [e.voice for e in s.fpga_events(param=0x3F, since_ms=since_ms) if e.value & 3 == 0]


def play_reused(s, channel, notes, gap_ms, hold_ms=10):
    """Note, release, wait *gap_ms*, next note, all on one channel; the voice
    each note took."""
    voices = []
    for n in notes:
        t = s.time_ms
        s.note_on(n, channel=channel)
        s.tick(hold_ms)
        (v,) = started_voices(s, t)
        voices.append(v)
        s.note_off(n, channel=channel)
        s.tick(gap_ms)
    return voices


# -- rotation ------------------------------------------------------------------------


def test_reused_channel_after_the_release_rotates_like_mpe_off(m):
    """Repeated note / release / note on one member channel, each release
    finished: the voices rotate exactly as with MPE off on the global
    channel (v1: voice 0 every time)."""
    notes = [60, 62, 64, 65, 67, 69]
    mpe_off = play_reused(m.s, 1, notes, gap_ms=RELEASE + 20)
    m.reset()
    m.s.release_ms = RELEASE
    m.flag()
    mpe_on = play_reused(m.s, 2, notes, gap_ms=RELEASE + 20)
    assert len(set(mpe_off)) > 1, mpe_off  # stock rotates
    assert mpe_on == mpe_off
    assert m.voice_channel()[mpe_on[-1]] == 2


def test_reused_channel_during_the_release_takes_over_that_voice(m):
    """A note on the channel while its voice still releases takes that voice
    over: the channel never sounds twice."""
    m.flag()
    voices = play_reused(m.s, 2, [60, 62, 64, 65], gap_ms=RELEASE // 4)
    assert len(set(voices)) == 1, voices
    (v,) = set(voices)
    assert m.voice_channel()[v] == 2
    m.s.tick(RELEASE + 20)
    assert m.s.voice_idle(v)


def test_note_held_on_a_reused_channel_is_taken_over(m):
    """No note-off before the next note on the channel (a sender reusing it
    early): still the same voice, no doubled note."""
    m.flag()
    m.on(60, 2)
    (v,) = m.bound(2)
    m.on(62, 2)
    assert m.bound(2) == [v] and m.s.voice_note(v) == 62
    assert len(m.s.active_voices()) == 1
    m.all_off()


def test_mixed_gaps_take_over_only_while_releasing(m):
    m.flag()
    s = m.s
    first = play_reused(s, 2, [60], gap_ms=RELEASE // 4)[0]
    during = play_reused(s, 2, [62], gap_ms=RELEASE + 20)[0]
    after = play_reused(s, 2, [64], gap_ms=RELEASE + 20)[0]
    assert during == first
    assert after != during
    assert m.voice_channel()[during] is None  # unbound when it was found idle
    assert m.voice_channel()[after] == 2


def test_default_model_releases_end_at_once_so_every_reuse_rotates(m):
    """With the simulator's default model (every level 0) a released voice
    is idle at once, so even a short gap rotates."""
    m.s.release_ms = None
    m.flag()
    mpe_on = play_reused(m.s, 2, [60, 62, 64], gap_ms=2)
    assert len(set(mpe_on)) == 3, mpe_on


def test_unison_stack_rotates_after_the_release_and_is_taken_over_during_it(m):
    m.flag()
    m.s.set_patch_byte(UNISON, 1)  # 2 voices per note
    m.on(60, 2)
    stack = sorted(m.bound(2))
    m.off(60, 2)
    m.s.tick(RELEASE // 4)
    m.on(62, 2)
    assert sorted(m.bound(2)) == stack  # during the release: the whole stack
    m.off(62, 2)
    m.s.tick(RELEASE + 20)
    m.on(64, 2)
    new = sorted(m.bound(2))
    assert len(new) == 2 and new != stack  # after it: stock's choice, both bound to 2
    m.all_off()


@pytest.mark.parametrize("mode", [0, 1], ids=["mono", "monolg"])
def test_mono_modes_keep_the_allocators_voice(m, mode):
    m.flag()
    m.s.set_patch_byte(MODE, mode)
    voices = play_reused(m.s, 2, [60, 62, 64], gap_ms=RELEASE + 20)
    m.reset()
    m.s.release_ms = RELEASE
    m.s.set_patch_byte(MODE, mode)
    assert voices == play_reused(m.s, 1, [60, 62, 64], gap_ms=RELEASE + 20)


# -- expression on the newly allocated voice -----------------------------------------


def neutral(s, ch):
    s.bend(0, channel=ch)
    s.channel_pressure(0, channel=ch)
    s.cc(74, 0, channel=ch)


def expressive(s, ch, bend=4096, pressure=100, cc74=120):
    s.bend(bend, channel=ch)
    s.channel_pressure(pressure, channel=ch)
    s.cc(74, cc74, channel=ch)


def note(s, n, ch, hold_ms=60):
    """Note on, held long enough for every smoother; the voice it took."""
    t = s.time_ms
    s.note_on(n, channel=ch)
    s.tick(hold_ms)
    (v,) = started_voices(s, t)
    return v


def assert_voice_gets(m, v, ch, bend, pressure, cc74, ref_osc):
    s = m.s
    assert m.voice_channel()[v] == ch
    assert osc(s, v) == shifted(ref_osc, member_offset(bend))
    assert s.voice_aftertouch(v) == pressure << 8
    assert s.last_value(voice=v, param=MODWHEEL) == (0x7FFF if cc74 == 127 else cc74 << 8)


def rotate_onto(m, ch, target, first, count, notes=(64, 65)):
    """Reuse channel *ch* (neutral) after each release until stock's rotation
    lands on voice *target*; the voice it landed on."""
    s = m.s
    for i in range(count):
        neutral(s, ch)
        s.tick(2)
        v = note(s, notes[i % 2], ch, hold_ms=10)
        if v == target:
            return v
        s.note_off(notes[i % 2], channel=ch)
        s.tick(RELEASE + 20)
    raise AssertionError(f"rotation never reached voice {target}")


@pytest.mark.parametrize("multi", [False, True], ids=["single", "multi-one-mpe-part"])
def test_rotated_voice_takes_its_new_channels_expression_nothing_stale(m, multi):
    """Channel 3 leaves voice X bent, pressed and slid, released and idle.
    Channel 2, reused after each release, rotates through the voices onto X:
    X gets channel 2's neutral bend, pressure and Slide, not channel 3's.
    Then channel 3 plays again: its old voice now belongs to channel 2, so it
    gets a voice from the allocator, with channel 3's (new) values. In Multi,
    Part A is the MPE part (voices 0-7) and Part B, MPE off, plays its own
    channel as stock in between."""
    s = m.s
    if multi:
        s.set_mode("multi")
        s.set_channels(global_=16, part_a=11, part_b=12)
        m.zone_setting(1, 5)  # Lower, members 2-6: Part B's channel 12 stays outside
        m.flag(True, part=0)
        m.flag(False, part=1)
        first, count = 0, 8
    else:
        m.flag()
        first, count = 0, 16
    neutral(s, 2)
    s.tick(2)
    ref_v = note(s, 64, 2)
    ref = {64: osc(s, ref_v)}
    s.note_off(64, channel=2)
    s.tick(RELEASE + 20)
    ref_v = note(s, 65, 2)
    ref[65] = osc(s, ref_v)
    s.note_off(65, channel=2)
    s.tick(RELEASE + 20)
    expressive(s, 3)
    s.tick(2)
    x = note(s, 60, 3)
    assert_voice_gets(m, x, 3, 4096, 100, 120, shifted(osc(s, x), -member_offset(4096)))
    s.note_off(60, channel=3)
    if multi:
        b = note(s, 72, 12, hold_ms=10)  # Part B, stock: its own voices
        assert b >= 8 and m.voice_channel()[b] is None
        s.note_off(72, channel=12)
    s.tick(RELEASE + 20)
    assert s.active_voices() == []

    v = rotate_onto(m, 2, x, first, 2 * count)
    assert len(s.active_voices()) == 1  # no doubled note
    s.tick(60)
    n = s.voice_note(v)
    assert_voice_gets(m, v, 2, 0, 0, 0, ref[n])
    assert m.voice_channel().count(3) == 0  # channel 3 holds nothing now

    expressive(s, 3, bend=-2048, pressure=40, cc74=127)
    s.tick(2)
    y = note(s, n, 3)
    assert y != v and (y < 8 if multi else True)
    assert_voice_gets(m, y, 3, -2048, 40, 127, ref[n])
    assert_voice_gets(m, v, 2, 0, 0, 0, ref[n])  # channel 2's note untouched
    assert sorted(s.active_voices()) == sorted([v, y])
    s.note_off(n, channel=2)
    s.note_off(n, channel=3)
    s.tick(RELEASE + 20)
    assert s.active_voices() == []


def test_multi_mpe_part_rotates_within_its_8_voices_like_mpe_off(m):
    s = m.s
    s.set_mode("multi")
    s.set_channels(global_=16, part_a=11, part_b=12)
    notes = [60, 62, 64, 65, 67, 69, 71, 72, 74, 76]
    mpe_off = play_reused(s, 11, notes, gap_ms=RELEASE + 20)
    m.reset()
    s.release_ms = RELEASE
    s.set_mode("multi")
    s.set_channels(global_=16, part_a=11, part_b=12)
    m.zone_setting(1, 5)
    m.flag(True, part=0)
    m.flag(False, part=1)
    mpe_on = play_reused(s, 2, notes, gap_ms=RELEASE + 20)
    assert all(v < 8 for v in mpe_on)
    assert len(set(mpe_off)) > 1
    assert mpe_on == mpe_off
    during = play_reused(s, 3, [60, 62, 64], gap_ms=RELEASE // 4)
    assert len(set(during)) == 1


for _name, _test in list(globals().items()):
    if _name.startswith("test_") and _name not in QUICK:
        globals()[_name] = pytest.mark.slow(_test)
