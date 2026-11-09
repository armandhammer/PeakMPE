"""MPE expression in Single mode: per-note bend, pressure and Slide (patches/mpe).

Emulated: the patch runs in the simulated Summit and the tests play MIDI
through DIN. docs/mpe-design.md ("Step 2: expression") is the spec. Each
test reads what the voices get from the FPGA writes: the oscillator pitch
0x000-0x002, aftertouch 0x61 and ModWheel 0x60 per voice target.

The Lower Zone has members 2-6 here (master 1); notes on channels 2, 3 and 4
take voices 0, 1 and 2.
"""

import pytest

from mpe_expr_sim import (AFTERTOUCH, FULL_SLIDE, MODWHEEL, MODWHEEL_PART, OSC, OSC_MAX, OSC_MIN,
                          PART_LEVEL, at_sent, broadcasts, master_offset, member_offset, moved, osc, shifted, slide,
                          wheel)
from mpe_sim import MODE, UNISON, mpe_summit

QUICK = {
    "test_member_bend_moves_only_its_voices",
    "test_member_pressure_reaches_only_its_voices",
    "test_slide_is_a_per_voice_modwheel_without_the_broadcast",
}

BEND_MS = 50     # member bend: 1/4 per tick, settled to the count well within this
MASTER_MS = 300  # master bend: stock's 1/16 per tick
SLIDE_MS = 120   # Slide and wheel: 1/8 per tick, plus the per-voice sends
AT_MS = 200      # aftertouch: stock's 1/4 per 8 ms refresh


@pytest.fixture
def m(tmp_path_factory):
    m = mpe_summit(tmp_path_factory).reset()
    m.zone_setting(1, 5)  # Lower, members 2-6
    m.flag()
    return m


def chord(m, notes=((2, 60), (3, 64), (4, 67))):
    for ch, n in notes:
        m.on(n, ch)
    m.s.tick(20)
    voices = {ch: m.bound(ch) for ch, _ in notes}
    assert all(len(v) == 1 for v in voices.values())
    return {ch: v[0] for ch, v in voices.items()}


# -- per-note bend ---------------------------------------------------------------------


def test_member_bend_moves_only_its_voices(m):
    s = m.s
    v = chord(m)
    base = {ch: osc(s, x) for ch, x in v.items()}
    t = s.time_ms
    s.bend(8191, channel=3)
    s.tick(BEND_MS)
    assert osc(s, v[3]) == shifted(base[3], member_offset(8191))  # +48 semitones = +16,382
    assert moved(s, t, OSC) == {v[3]}
    assert osc(s, v[2]) == base[2] and osc(s, v[4]) == base[4]
    s.bend(-8192, channel=3)
    s.bend(4096, channel=4)
    s.tick(BEND_MS)
    assert osc(s, v[3]) == shifted(base[3], -16384)  # -48 semitones
    assert osc(s, v[4]) == shifted(base[4], member_offset(4096))  # +24
    assert osc(s, v[2]) == base[2]
    assert moved(s, t, OSC) == {v[3], v[4]}
    s.bend(0, channel=3)
    s.bend(0, channel=4)
    s.tick(BEND_MS)
    assert {ch: osc(s, x) for ch, x in v.items()} == base
    m.all_off()


def test_member_bend_is_smoothed_by_a_quarter_per_tick(m):
    s = m.s
    v = chord(m, ((2, 60),))[2]
    base = osc(s, v)[0]
    t = s.time_ms
    s.bend(8191, channel=2)
    s.tick(BEND_MS)
    steps = [e.value - base for e in s.fpga_events(voice=v, param=0) if e.time_ms > t and e.value != base]
    assert steps == sorted(steps) and len(set(steps)) > 5  # rises in steps, never overshoots
    assert steps[0] < 16382 * 0.6  # the first refresh is part of the way
    assert steps[-1] == 16382
    m.all_off()


def test_note_range_from_rpn_0_and_independent_of_bendrange(m):
    s = m.s
    v = chord(m)
    base = {ch: osc(s, x) for ch, x in v.items()}
    m.rpn(2, 0, 0, 12)  # a member channel: the zone's note range
    assert m.live()["note_range"][0] == 12
    s.bend(8191, channel=3)
    s.tick(BEND_MS)
    assert osc(s, v[3]) == shifted(base[3], member_offset(8191, 12))  # +12 semitones = 4,095
    s.nrpn(0, 20, 64)  # Osc 1 BendRange 0: the per-note bend doesn't use it
    s.tick(BEND_MS)
    assert osc(s, v[3])[0] == base[3][0] + member_offset(8191, 12)
    m.all_off()


def test_extreme_offsets_are_clamped_not_wrapped(m):
    s = m.s
    m.rpn(2, 0, 0, 96)  # the largest range: +-96 semitones = +-32,768
    v = chord(m, ((2, 127), (3, 0)))
    s.bend(8191, channel=2)
    s.bend(-8192, channel=3)
    s.tick(BEND_MS)
    assert osc(s, v[2]) == (OSC_MAX,) * 3
    assert osc(s, v[3]) == (OSC_MIN,) * 3
    m.all_off()


def test_a_note_started_on_a_bent_channel_starts_bent(m):
    s = m.s
    ref = chord(m, ((2, 72),))[2]
    base = osc(s, ref)
    s.bend(4096, channel=5)
    s.tick(5)
    t = s.time_ms
    m.on(72, 5)
    v = m.bound(5)[0]
    first = [e.value for e in s.fpga_events(voice=v, param=0) if e.time_ms >= t][0]  # voice_alloc's write
    assert first == base[0] + member_offset(4096)
    m.all_off()


# -- the master bend ---------------------------------------------------------------------


def test_master_bend_moves_every_zone_voice_by_the_master_range(m):
    s = m.s
    s.set_channels(global_=10)  # outside the zone: plays the patch unbound, as stock
    v = chord(m)
    s.note_on(48, channel=10)
    s.tick(10)
    unbound = [x for x in s.active_voices() if m.voice_channel()[x] is None][0]
    base = {x: osc(s, x) for x in (*v.values(), unbound)}
    s.bend(8191, channel=1)
    s.bend(4096, channel=3)
    s.tick(MASTER_MS)
    master = master_offset(s, 2)
    assert 680 <= master <= 683  # 2 semitones
    for ch, x in v.items():
        assert osc(s, x) == shifted(base[x], master + (member_offset(4096) if ch == 3 else 0))
    # The master's bend is the part bend: an unbound voice takes it as
    # stock does, through the oscillators' BendRange (12 in the Init Patch).
    assert all(abs(a - b - 4096) <= 2 for a, b in zip(osc(s, unbound), base[unbound]))
    m.rpn(1, 0, 0, 12)  # master range 12
    s.tick(10)
    assert osc(s, v[2]) == shifted(base[v[2]], master_offset(s, 12))
    s.note_off(48, channel=10)
    m.all_off()


def test_master_channel_notes_take_only_the_master_bend(m):
    s = m.s
    m.on(60, 1)
    v = m.bound(1)[0]
    base = osc(s, v)
    s.bend(8191, channel=2)  # no voice on 2
    s.tick(BEND_MS)
    assert osc(s, v) == base
    s.bend(-8192, channel=1)
    s.tick(MASTER_MS)
    assert osc(s, v) == shifted(base, master_offset(s, 2))
    m.all_off()


# -- pressure ---------------------------------------------------------------------------


def test_member_pressure_reaches_only_its_voices(m):
    s = m.s
    v = chord(m)
    t = s.time_ms
    s.channel_pressure(100, channel=2)
    s.tick(AT_MS)
    assert [s.voice_aftertouch(x) for x in (v[2], v[3], v[4])] == [100 << 8, 0, 0]
    assert moved(s, t, AFTERTOUCH) == {v[2]}
    assert abs(s.last_value(voice=v[2], param=AFTERTOUCH) - at_sent(100 << 8)) < 200
    m.all_off()


def test_master_pressure_reaches_every_voice_without_overwriting_members(m):
    s = m.s
    v = chord(m)
    s.channel_pressure(100, channel=2)
    s.tick(5)
    s.channel_pressure(50, channel=1)  # master: every voice, but member 2 is higher
    s.tick(5)
    assert [s.voice_aftertouch(x) for x in (v[2], v[3], v[4])] == [100 << 8, 50 << 8, 50 << 8]
    s.channel_pressure(20, channel=2)  # below the master now: the master's
    s.channel_pressure(90, channel=4)
    s.tick(5)
    assert [s.voice_aftertouch(x) for x in (v[2], v[3], v[4])] == [50 << 8, 50 << 8, 90 << 8]
    s.channel_pressure(0, channel=1)
    s.tick(AT_MS)
    assert [s.voice_aftertouch(x) for x in (v[2], v[3], v[4])] == [20 << 8, 0, 90 << 8]
    assert abs(s.last_value(voice=v[4], param=AFTERTOUCH) - at_sent(90 << 8)) < 200
    assert s.last_value(voice=v[3], param=AFTERTOUCH) < 100
    m.all_off()


def test_a_note_starts_at_its_channels_pressure(m):
    s = m.s
    s.channel_pressure(80, channel=5)
    s.tick(5)
    t = s.time_ms
    m.on(60, 5)
    v = m.bound(5)[0]
    first = [e.value for e in s.fpga_events(voice=v, param=AFTERTOUCH) if e.time_ms >= t][0]
    assert first == at_sent(80 << 8)
    m.all_off()


# -- Slide --------------------------------------------------------------------------------


def test_slide_is_a_per_voice_modwheel_without_the_broadcast(m):
    s = m.s
    v = chord(m)
    t = s.time_ms
    s.cc(74, 127, channel=3)
    s.cc(74, 64, channel=4)
    s.tick(SLIDE_MS)
    assert [wheel(s, v[ch]) for ch in (2, 3, 4)] == [0, FULL_SLIDE, slide(64)]
    assert moved(s, t, MODWHEEL) == {v[3], v[4]}
    assert broadcasts(s, t) == []  # the zone's part never sends the broadcast 0x60
    s.cc(74, 0, channel=3)
    s.tick(SLIDE_MS)
    assert wheel(s, v[3]) == 0
    m.all_off()


def test_master_mod_wheel_adds_to_every_voices_slide_and_drives_the_fx(m):
    s = m.s
    v = chord(m)
    s.cc(74, 32, channel=2)
    s.cc(74, 100, channel=3)
    t = s.time_ms
    s.cc(1, 64, channel=1)  # master mod wheel
    s.tick(SLIDE_MS)
    w = s.last_value(target=PART_LEVEL, param=MODWHEEL_PART)  # 0x860: the master's wheel, stock-smoothed
    assert abs(w - (64 << 8)) <= 0x10
    assert [wheel(s, v[ch]) for ch in (2, 3, 4)] == [w + slide(32), min(FULL_SLIDE, w + slide(100)), w]
    assert broadcasts(s, t) == []
    m.all_off()


def test_a_note_starts_at_its_channels_slide(m):
    s = m.s
    s.cc(74, 90, channel=6)
    s.tick(5)
    t = s.time_ms
    m.on(60, 6)
    v = m.bound(6)[0]
    first = [e.value for e in s.fpga_events(voice=v, param=MODWHEEL) if e.time_ms >= t][0]
    assert first == slide(90)
    m.all_off()


# -- unison and mono ------------------------------------------------------------------------


def test_every_voice_of_a_unison_stack_takes_its_channels_expression(m):
    s = m.s
    s.set_patch_byte(UNISON, 2)  # 3 voices per note
    s.tick(5)
    m.on(60, 2)
    m.on(67, 3)
    stack, other = m.bound(2), m.bound(3)
    assert len(stack) == 3 and len(other) == 3
    base = {x: osc(s, x) for x in stack + other}
    t = s.time_ms
    s.bend(8191, channel=2)
    s.channel_pressure(70, channel=2)
    s.cc(74, 127, channel=2)
    s.tick(AT_MS)
    for x in stack:
        assert osc(s, x) == shifted(base[x], member_offset(8191))
        assert s.voice_aftertouch(x) == 70 << 8
        assert wheel(s, x) == FULL_SLIDE
    for x in other:
        assert osc(s, x) == base[x] and s.voice_aftertouch(x) == 0 and wheel(s, x) == 0
    assert moved(s, t, (*OSC, AFTERTOUCH, MODWHEEL)) == set(stack)
    m.all_off()


def test_mono_voice_follows_the_sounding_notes_channel(m):
    s = m.s
    s.set_patch_byte(MODE, 0)  # Mono
    s.tick(5)
    s.bend(4096, channel=2)
    s.cc(74, 50, channel=2)
    s.tick(5)
    m.on(60, 2)
    v = m.bound(2)[0]
    s.tick(BEND_MS)
    bent = osc(s, v)
    s.note_on(64, channel=3)  # no bend on 3: the new note plays unbent at once
    s.tick(SLIDE_MS)
    assert m.voice_channel()[v] == 3
    assert wheel(s, v) == 0
    unbent_64 = osc(s, v)
    s.note_off(64, channel=3)  # back to 60 on channel 2: bent again
    s.tick(SLIDE_MS)
    assert m.voice_channel()[v] == 2
    assert osc(s, v) == bent
    assert wheel(s, v) == slide(50)
    assert abs(unbent_64[0] - bent[0] - ((64 - 60) * 4096 / 12 - member_offset(4096))) <= 1
    s.note_off(60, channel=2)
    s.tick(300)
    assert s.active_voices() == []


# -- nothing left behind ----------------------------------------------------------------------


def test_nothing_is_stuck_after_release(m):
    """Bend, pressure and Slide on every channel, release with them still
    applied, then reuse the voices: new notes on neutral channels and a
    note on an unbound channel start neutral, and with MPE off again every
    voice is stock (broadcast 0x60, slot = the part's pressure)."""
    s = m.s
    s.set_channels(global_=10)
    v = chord(m, ((2, 60), (3, 64), (4, 67), (5, 71), (6, 74)))
    base = {x: osc(s, x) for x in v.values()}
    for i, ch in enumerate(v):
        s.bend(8191 - 3000 * i, channel=ch)
        s.channel_pressure(120, channel=ch)
        s.cc(74, 127, channel=ch)
    s.tick(AT_MS)
    m.all_off()  # channels stay bent, pressed and slid
    for ch in (2, 3, 4, 5, 6):  # a sender resets a channel before its next note
        s.bend(0, channel=ch)
        s.channel_pressure(0, channel=ch)
        s.cc(74, 0, channel=ch)
    for ch, n in ((2, 60), (3, 64), (4, 67), (5, 71), (6, 74)):
        m.on(n, ch)
    s.tick(AT_MS)
    for ch, x in v.items():
        y = m.bound(ch)[0]
        assert osc(s, y) == base[x]
        assert s.voice_aftertouch(y) == 0 and wheel(s, y) == 0
        assert s.last_value(voice=y, param=AFTERTOUCH) == 0
    m.all_off()
    s.bend(8191, channel=2)
    s.channel_pressure(127, channel=2)
    s.cc(74, 127, channel=2)
    m.on(60, 2)
    s.tick(AT_MS)
    m.all_off()
    for i in range(16):  # unbound notes take every voice back to stock
        s.note_on(48 + i, channel=10)
        s.tick(4)
    s.tick(AT_MS)
    assert len(s.active_voices()) == 16 and m.voice_channel() == [None] * 16
    c4 = base[v[2]][0]
    for y in range(16):
        assert all(abs(p - (c4 + (s.voice_note(y) - 60) * 4096 / 12)) <= 1 for p in osc(s, y))
        assert s.voice_aftertouch(y) == 0 and wheel(s, y) == 0
    for i in range(16):
        s.note_off(48 + i, channel=10)
    s.tick(300)
    t = s.time_ms
    m.flag(False)  # MPE off: the broadcast 0x60 sets every voice again
    s.tick(SLIDE_MS)
    assert [e.value for e in broadcasts(s, t)][-2:] == [0, 0]
    assert all(s.voice_aftertouch(y) == 0 for y in range(16))
    assert s.active_voices() == []


for _name, _test in list(globals().items()):
    if _name.startswith("test_") and _name not in QUICK:
        globals()[_name] = pytest.mark.slow(_test)
