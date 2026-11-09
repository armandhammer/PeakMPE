"""MPE expression in Multi mode: two zones, and an MPE part next to a normal one.

Emulated (patches/mpe, docs/mpe-design.md). With both parts on, Part A is the
Lower Zone (master 1, members 2-8, voices 0-7) and Part B the Upper Zone
(master 16, members 9-15, voices 8-15). Each zone's expression must reach
only its own part's voices, and neither engine gets the broadcast 0x60.

With one part on, the other part must play exactly as stock: the last test
plays one sequence on stock and on the patch and compares every engine B
register's value sequence.
"""

import pytest

from bend_play import changes
from mpe_expr_sim import (AFTERTOUCH, FULL_SLIDE, MODWHEEL, OSC, broadcasts, master_offset, member_offset, moved,
                          osc, shifted, wheel)
from mpe_sim import FLAG, G_MEMBERS, G_ZONE, built, mpe_summit, stock_summit

QUICK = {"test_two_zones_each_reach_only_their_parts_voices"}

SETTLE_MS = 300
AT_PART = 0x861  # part-level copy of the aftertouch round-robin's voice: its order follows the tick phase


@pytest.fixture
def m(tmp_path_factory):
    return mpe_summit(tmp_path_factory).reset()


def test_two_zones_each_reach_only_their_parts_voices(m):
    s = m.s
    s.set_mode("multi")
    m.flag(True, 0)
    m.flag(True, 1)
    assert m.zones() == {"lower": (0, 1, 2, 8), "upper": (1, 16, 9, 15)}
    m.on(60, 3)
    m.on(64, 4)
    m.on(67, 12)
    m.on(72, 16)  # Upper master
    a3, a4, b12, b16 = m.bound(3)[0], m.bound(4)[0], m.bound(12)[0], m.bound(16)[0]
    assert a3 < 8 and a4 < 8 and b12 >= 8 and b16 >= 8
    voices = (a3, a4, b12, b16)
    base = {x: osc(s, x) for x in voices}
    t = s.time_ms
    s.bend(8191, channel=12)
    s.bend(-4096, channel=3)
    s.channel_pressure(90, channel=4)
    s.cc(74, 127, channel=12)
    s.tick(SETTLE_MS)
    assert osc(s, b12) == shifted(base[b12], member_offset(8191))
    assert osc(s, a3) == shifted(base[a3], member_offset(-4096))
    assert osc(s, a4) == base[a4] and osc(s, b16) == base[b16]
    assert moved(s, t, OSC) == {a3, b12}
    assert [s.voice_aftertouch(x) for x in voices] == [0, 90 << 8, 0, 0]
    assert moved(s, t, AFTERTOUCH) == {a4}
    assert [wheel(s, x) for x in voices] == [0, 0, FULL_SLIDE, 0]
    assert moved(s, t, MODWHEEL) == {b12}

    t = s.time_ms
    s.bend(8191, channel=16)  # Upper master: Part B's voices only
    s.channel_pressure(40, channel=1)  # Lower master: Part A's voices only
    s.cc(1, 127, channel=1)  # Lower master's wheel: Part A's voices only
    s.tick(SETTLE_MS)
    mb = master_offset(s, 2, part=1)
    assert 680 <= mb <= 683
    assert osc(s, b12) == shifted(base[b12], member_offset(8191) + mb)
    assert osc(s, b16) == shifted(base[b16], mb)
    assert osc(s, a3) == shifted(base[a3], member_offset(-4096))
    assert [s.voice_aftertouch(x) for x in voices] == [40 << 8, 90 << 8, 0, 0]
    assert [wheel(s, x) for x in voices] == [FULL_SLIDE, FULL_SLIDE, FULL_SLIDE, 0]
    assert broadcasts(s, t) == []
    m.all_off()


def test_an_mpe_part_next_to_a_normal_part(m):
    s = m.s
    s.set_mode("multi")
    s.set_channels(global_=16, part_a=1, part_b=10)
    m.zone_setting(1, 5)  # Lower, members 2-6
    m.flag(True, 0)
    assert m.zones() == {"lower": (0, 1, 2, 6)} and m.clash() == 0
    m.on(60, 3)
    s.note_on(64, channel=10)
    s.note_on(67, channel=10)
    s.tick(10)
    a = m.bound(3)[0]
    b = [x for x in s.active_voices() if x >= 8]
    assert len(b) == 2 and m.voice_channel()[b[0]] is None
    base = {x: osc(s, x) for x in (a, *b)}
    t = s.time_ms
    s.bend(8191, channel=10)  # Part B: stock, BendRange 12 on every voice of the part
    s.cc(1, 127, channel=10)
    s.cc(74, 127, channel=3)
    s.tick(SETTLE_MS)
    assert osc(s, a) == base[a]
    assert all(abs(osc(s, x)[0] - base[x][0] - 4096) <= 2 for x in b)
    assert wheel(s, a) == FULL_SLIDE
    assert all(e.engines == "B" for e in broadcasts(s, t))  # only Part B's engine keeps the broadcast
    assert broadcasts(s, t)[-1].value == 0x7FFF
    assert all(wheel(s, x) is None or x < 8 for x in range(16))  # no per-voice 0x60 on engine B
    s.note_off(64, channel=10)
    s.note_off(67, channel=10)
    m.all_off()


# -- Part B with MPE off plays as stock --------------------------------------------------------


def play(s, mpe):
    """Multi, Part A an MPE part (Lower 2-6) on channel 1, Part B normal on 10.
    Both parts play and get every kind of expression at once."""
    s.set_soft_thru(True)
    s.set_global(G_MEMBERS, 5, run_ms=0)
    s.set_global(G_ZONE, 1)
    s.set_mode("multi")
    s.set_channels(global_=16, part_a=1, part_b=10)
    s.set_patch_byte(FLAG, 1 if mpe else 0, 0)
    s.tick(5)
    for i, n in enumerate((60, 64, 67)):
        s.note_on(n, channel=2 + i)  # zone members: Part A on the patch, dropped on stock
        s.note_on(n - 12, channel=10)
        s.tick(4)
    s.note_on(72, channel=1)
    s.tick(20)
    # Part B's controls change once per step and settle within it (stock
    # smooths the bend by 1/16 per tick): the value sequences then don't
    # depend on which tick a message lands in. Part A moves in between.
    for step in range(1, 6):
        s.bend(1600 * step, channel=10)
        s.channel_pressure(20 * step, channel=10)
        s.cc(1, 20 * step, channel=10)
        s.cc(74, 15 * step, channel=10)
        s.tick(75)
        s.bend(-1600 * step, channel=3)
        s.bend(800 * step, channel=1)
        s.channel_pressure(24 * step, channel=2)
        s.channel_pressure(10 * step, channel=1)
        s.cc(1, 18 * step, channel=1)
        s.cc(74, 24 * step, channel=4)
        s.tick(75)
    s.note_on(55, channel=10)
    s.tick(30)
    for i, n in enumerate((60, 64, 67)):
        s.note_off(n, channel=2 + i)
        s.note_off(n - 12, channel=10)
    s.note_off(72, channel=1)
    s.note_off(55, channel=10)
    s.tick(150)
    s.bend(0, channel=10)
    s.tick(150)
    s.cc(1, 0, channel=10)
    s.tick(300)


def engine_b(events):
    """Value sequences of Part B's registers. Broadcasts it sends (engine B,
    targets 0x19/0x1A; 0x18 is main-loop-rate status traffic whose count is
    timing, see tests/test_mpe_off.py) by register, 0x861 by its last value. Its voices (8-15) as the
    sorted per-voice sequences of each param: which idle voice a note takes
    depends on envelope states read at EXTI15-timed points, and Part A's
    extra notes on the patch shift that timing."""
    seq = changes(events)
    out = {k: v for k, v in seq.items() if k[1] >= 0x19 and k[0] == "B" and k[2] != AT_PART}
    out[("B", "last", AT_PART)] = [e.value for e in events if e.param == AT_PART and e.engines == "B"][-1]
    for (engines, target, param), values in seq.items():
        if 8 <= target < 0x10:
            out.setdefault(("voices", param), []).append(values)
    for k in out:
        if k[0] == "voices":
            out[k] = sorted(out[k])
    return out


@pytest.mark.slow
def test_the_normal_part_plays_exactly_as_stock(tmp_path_factory):
    built(tmp_path_factory)
    out = []
    for s, mpe in ((stock_summit(), False), (mpe_summit(tmp_path_factory).s, True)):
        s.reset()
        play(s, mpe)
        out.append((s.fpga_events(), [m.data for m in s.midi_out() if m.data[0] & 0x0F == 9]))
    (stock, stock_midi), (patched, patched_midi) = out
    a, b = engine_b(stock), engine_b(patched)
    assert len(a) > 30 and any(k[2] == 0x60 for k in a)
    assert set(b) == set(a)
    assert [k for k in a if a[k] != b[k]] == []
    assert patched_midi == stock_midi  # Part B's soft thru


for _name, _test in list(globals().items()):
    if _name.startswith("test_") and _name not in QUICK:
        globals()[_name] = pytest.mark.slow(_test)
