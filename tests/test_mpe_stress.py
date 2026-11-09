"""MPE stress: long seeded random plays, the FPGA queue and CPU at the worst
case, and MPE off against stock under MPE traffic (patches/mpe).

* **Random plays** (seeded, reproducible: a failure names its layout and
  seed; MPE_STRESS_SEEDS and MPE_STRESS_PHRASES play more): phrases from the Live and Hapax senders (tests/mpe_traffic.py)
  with random edge cases mixed in (RPN 0, an MCM, sustain, all-notes-off,
  more notes than channels), under the Invariants checker after every
  main-loop pass; at each phrase's quiet point every voice's expression is
  checked, and after its release nothing may sound. Four layouts: Single
  Lower (Live, USB), Single Upper (Hapax with MCM, four colliding tracks,
  DIN with running status and clock), Multi with two zones, Multi with one
  MPE part and one normal part.
* **Worst case:** 16 voices, every channel's bend, pressure and CC 74 at
  the densest rate USB carries (16 packets per 1 ms frame), the master wheel
  moving: writes per tick, queue depth, and instruction counts per tick and
  per main-loop pass (tests/mpe_traffic.py's CpuWatch). Then the same with a
  CC 120 at the USB frame phases where it delays a tick, against stock doing
  the same (docs/mpe-design.md, "Step 4").
* **MPE off is stock** under the same senders, compared the way
  test_mpe_off.py compares (settled registers at every quiet point, MIDI
  out, final state).

Emulated; all slow.
"""

import os
import random

import pytest

from mpe_sim import FLAG, G_MEMBERS, G_ZONE, Mpe, built, mpe_summit, stock_summit
from mpe_traffic import (QUEUE_LIMIT, CpuWatch, Invariants, QueueWatch, Zone, at, base_pitch_table, bend, by_time,
                         cc, freeze, hapax, live, mcm, note_off, note_on, play, pressure, rpn)
from test_mpe_off import Checkpoints, same_where_settled, snapshot

pytestmark = pytest.mark.slow

SLOT = 6000           # instructions per 50 µs slot in the board's time model
TICK = 20 * SLOT      # 120,000 per 1 ms tick
PHRASES = int(os.environ.get("MPE_STRESS_PHRASES", "2"))  # 4 for a longer hunt


@pytest.fixture
def m(tmp_path_factory):
    return mpe_summit(tmp_path_factory).reset()


@pytest.fixture
def base(tmp_path_factory):
    return base_pitch_table(mpe_summit(tmp_path_factory))


# -- layouts -------------------------------------------------------------------------------


def single_lower(m, rng):
    m.zone_setting(1, 15)
    m.flag()
    return dict(port="usb", senders=lambda rng, span: live(Zone("lower", 15), rng, rng.randint(8, 20), span_ms=span),
                masters=(1,), members=list(range(2, 17)))


def single_upper(m, rng):
    m.zone_setting(0)
    m.flag()
    return dict(port="din", din_kw=dict(clock_ms=5),
                senders=lambda rng, span: hapax(Zone("upper", 14), rng, rng.randint(6, 14), span_ms=span,
                                                tracks=4, shared_pool=False, rate_ms=15.0),
                masters=(16,), members=list(range(2, 16)))


def multi_two_zones(m, rng):
    m.zone_setting(1, 7)
    m.s.set_mode("multi")
    m.s.to_pass_start()
    m.flag(True, 0)
    m.flag(True, 1)
    return dict(port="usb",
                senders=lambda rng, span: by_time(hapax(Zone("lower", 7), rng, rng.randint(4, 10), span_ms=span,
                                                        mcm_first=False)
                                                  + live(Zone("upper", 7), rng, rng.randint(4, 10), span_ms=span)),
                masters=(1, 16), members=list(range(2, 16)))


def multi_mpe_and_normal(m, rng):
    """Part A plays the Lower Zone 2-8, Part B (MPE off) channel 10."""
    m.zone_setting(1, 7)
    m.s.set_mode("multi")
    m.s.set_channels(global_=16, part_a=1, part_b=10)
    m.s.to_pass_start()
    m.flag(True, 0)

    def senders(rng, span):
        normal = []
        for i in range(rng.randint(3, 8)):
            t = rng.uniform(0, span)
            n = rng.randint(40, 90)
            normal += [(t, note_on(10, n)), (t + rng.uniform(30, 200), note_off(10, n)),
                       (t + 5, bend(10, rng.randint(-8192, 8191))), (t + 7, pressure(10, rng.randint(0, 127)))]
        normal.append((span + 450, bend(10, 0)))
        return by_time(live(Zone("lower", 7), rng, rng.randint(6, 14), span_ms=span) + normal)
    return dict(port="usb", senders=senders, masters=(1,), members=list(range(2, 9)))


LAYOUTS = {"single-lower": single_lower, "single-upper": single_upper,
           "multi-two-zones": multi_two_zones, "multi-mpe-and-normal": multi_mpe_and_normal}


def edge_cases(rng, events, layout, span):
    """Random edge cases on top of a phrase."""
    out = list(events)
    master = rng.choice(layout["masters"])
    if rng.random() < 0.4:
        out += at(rng.uniform(0, span), rpn(rng.choice(layout["members"]), 0, 0, rng.choice((2, 12, 24, 48, 96))))
    if rng.random() < 0.3:
        out += at(rng.uniform(0, span), rpn(master, 0, 0, rng.choice((1, 2, 7, 12))))
    if rng.random() < 0.4:
        t = rng.uniform(0, span * 0.5)
        out += [(t, cc(master, 64, 127)), (t + rng.uniform(20, span), cc(master, 64, 0))]
    if rng.random() < 0.2:
        out.append((rng.uniform(span * 0.3, span * 0.6), cc(rng.choice(layout["members"] + [master]), 123, 0)))
    return by_time(out)


def random_play(m, base, name, seed):
    rng = random.Random(f"{name}-{seed}")
    layout = LAYOUTS[name](m, rng)
    port, din_kw = layout["port"], layout.get("din_kw")
    stats = {"checked": 0, "handled": 0, "max_depth": 0, "per_tick": 0}
    for k in range(PHRASES):
        span = rng.uniform(250, 450)
        ev = edge_cases(rng, layout["senders"](rng, span), layout, span)
        cut = span * rng.uniform(0.5, 0.8)
        ev = freeze(ev, cut, 300)
        ev += [(cut + 301, cc(master, 64, 0)) for master in layout["masters"]]  # no pedal left down
        with Invariants(m, base=base) as inv:
            t0 = play(m.s, [e for e in ev if e[0] <= cut], port, din_kw=din_kw)
            inv.settle(220)
            stats["checked"] += inv.expression()
            play(m.s, [e for e in ev if e[0] > cut], port, t0=t0, din_kw=din_kw)
            inv.all_released()
        stats["handled"] += inv.handled
        stats["max_depth"] = max(stats["max_depth"], inv.max_depth)
        stats["per_tick"] = max(stats["per_tick"], max(inv.per_tick))
        if k == 1 and name.startswith("single"):  # the layout changes between phrases
            play(m.s, at(0, mcm(1 if name == "single-upper" else 16, rng.randint(3, 10))))
    return stats


def seeds():
    """MPE_STRESS_SEEDS="1-50" plays more seeds (each its own xdist group);
    the default is one per layout."""
    spec = os.environ.get("MPE_STRESS_SEEDS", "1")
    lo, _, hi = spec.partition("-")
    return range(int(lo), int(hi or lo) + 1)


@pytest.mark.parametrize("name,seed", [pytest.param(name, seed, marks=pytest.mark.xdist_group(f"mpe-stress-{name}-{seed}"))
                                       for name in LAYOUTS for seed in seeds()])
def test_random_play_keeps_every_invariant(m, base, name, seed):
    stats = random_play(m, base, name, seed)
    print(name, seed, stats)
    assert stats["handled"] > 75 * PHRASES and stats["checked"] >= 1  # the Hapax phrases are sparse
    assert stats["max_depth"] <= QUEUE_LIMIT and stats["per_tick"] <= 78


# -- the worst case ------------------------------------------------------------------------


def dense(duration_ms=200, master_wheel=True):
    """16 notes (master and members 2-16), then every channel's bend,
    pressure and CC 74 as densely as USB carries them: 48 messages per
    round, 16 packets per frame, so each channel moves every 3 ms."""
    ev = [(i * 0.5, note_on(1 + i, 40 + 3 * i)) for i in range(16)]
    t = 20.0
    k = 0
    while t < 20 + duration_ms:
        hi = k % 2 == 0
        for ch in range(1, 17):
            ev += [(t, bend(ch, 8191 if hi else -8192)), (t, pressure(ch, 127 if hi else 0)),
                   (t, cc(ch, 74, 100 if hi else 0))]
        if master_wheel:
            ev.append((t, cc(1, 1, 27 if hi else 0)))
        t += 3.0
        k += 1
    return ev


_dense = {}


def on_channel_1(ev):
    """The same messages, all on channel 1: what stock plays of them."""
    return [(t, bytes([m[0] & 0xF0]) + m[1:]) for t, m in ev]


@pytest.fixture
def worst(m, base):
    """The dense play once per worker, on the patch (MPE on, Lower 15) and on
    stock (the same messages on channel 1): queue and CPU."""
    if "mpe" not in _dense:
        for name in ("stock", "mpe"):
            sim = m if name == "mpe" else Mpe(stock_summit(), m.blob)
            sim.reset()
            sim.zone_setting(1, 15)
            if name == "mpe":
                sim.flag()
            sim.s.tick(20)
            ev = dense(100) if name == "mpe" else on_channel_1(dense(100))
            with QueueWatch(sim.s) as q, CpuWatch(sim.s, m.blob) as cpu:
                if name == "mpe":
                    inv = Invariants(m, base=base).__enter__()
                t0 = play(sim.s, ev[:16], "usb", until=20)
                mark = len(cpu.passes), len(cpu.ticks), len(q.per_tick)
                play(sim.s, ev[16:], "usb", t0=t0)
                if name == "mpe":
                    inv.__exit__()
            _dense[name] = dict(per_tick=q.per_tick[mark[2]:], max_depth=q.max_depth, passes=cpu.passes[mark[0]:],
                                burst=cpu.passes[:mark[0]],
                                ticks=cpu.ticks[mark[1]:], isr=dict(cpu.isr),
                                handled=inv.handled if name == "mpe" else None)
        m.reset()
    return _dense


@pytest.mark.xdist_group("mpe-stress-worst")
def test_worst_case_queue(worst):
    """Every voice's 0x60 moves every tick here: the Slide module adds at
    most 4 writes per tick and drops both broadcasts (77, drain 80). The
    depth peaks where a pass handling a frame of 16 USB messages delays a
    tick, as on stock with the same messages."""
    w, stock = worst["mpe"], worst["stock"]
    assert w["handled"] > 1500
    assert max(w["per_tick"]) <= 77 and max(stock["per_tick"]) == 75
    assert w["max_depth"] <= max(stock["max_depth"] + 2, 0) <= QUEUE_LIMIT
    print(f"worst case: writes per tick max {max(w['per_tick'])}, mean {sum(w['per_tick']) / len(w['per_tick']):.1f};"
          f" queue depth max {w['max_depth']} (stock, the same messages on channel 1: {stock['max_depth']})")


@pytest.mark.xdist_group("mpe-stress-worst")
def test_worst_case_cpu(worst):
    """Instruction counts at the worst case (the board's model: 120,000 per
    1 ms tick). The main loop serves one tick per pass; a pass longer than
    a tick would hold a tick back by more than a tick."""
    w, stock = worst["mpe"], worst["stock"]
    longest, stock_longest = (max(p[1] for p in r["passes"]) for r in (w, stock))
    burst, stock_burst = (max(p[1] for p in r["burst"]) for r in (w, stock))
    blob_in_pass = max(p[2] for p in w["passes"])
    blob_per_tick = [b for _, b in w["ticks"]]
    print(f"worst case CPU: 16 note-ons in 8 ms, longest pass {burst} instructions ({burst / TICK:.0%} of a tick;"
          f" stock {stock_burst}, {stock_burst / TICK:.0%}); controllers, longest pass {longest} ({longest / TICK:.0%};"
          f" stock {stock_longest}, {stock_longest / TICK:.0%}), patch code in a pass up to {blob_in_pass};"
          f" patch per tick max {max(blob_per_tick)} ({max(blob_per_tick) / TICK:.1%}), mean"
          f" {sum(blob_per_tick) / len(blob_per_tick):.0f}; interrupts {w['isr']}")
    assert burst < TICK and longest < TICK
    assert max(blob_per_tick) < 0.15 * TICK


@pytest.mark.xdist_group("mpe-stress-worst")
def test_idle_cpu(m):
    """The patch's cost with nothing playing (MPE on): the main-loop hooks
    run every pass, mod_tick's every tick."""
    m.zone_setting(1, 15)
    m.flag()
    m.s.tick(20)
    with CpuWatch(m.s, m.blob) as cpu:
        m.s.tick(50)
    blob = [b for _, b in cpu.ticks]
    idle = sorted(p[2] for p in cpu.passes)
    print(f"idle: patch per tick mean {sum(blob) / len(blob):.0f} ({sum(blob) / len(blob) / TICK:.1%}),"
          f" per main-loop pass {idle[len(idle) // 2]} (median), {len(cpu.passes) / 50:.0f} passes per ms")
    assert sum(blob) / len(blob) < 0.1 * TICK


def long_handler_depths(sim, on, phases, message):
    """The worst queue depth per USB frame phase (µs): 16 notes, every
    channel's bend and CC 74 moving every 3 ms, and *message* (CC 120, a
    program change) in the middle. Stock plays it all on channel 1."""
    out = []
    for ph in phases:
        sim.reset()
        sim.zone_setting(1, 15)
        if on:
            sim.flag()
        sim.s.tick(5)
        sim.s.usb_phase_us = ph
        ev = [(i * 0.5, note_on(1 + i, 40 + 3 * i)) for i in range(16)]
        for k in range(10):
            ev += [(20 + 3 * k, bend(1 + i, 4000 if k % 2 else -4000)) for i in range(16)]
            ev += [(20 + 3 * k, cc(1 + i, 74, 100 if k % 2 else 0)) for i in range(16)]
        ev.append((32, message))
        if not on:
            ev = on_channel_1(ev)
        with QueueWatch(sim.s) as q:
            play(sim.s, ev, "usb", until=70)
        out.append(q.max_depth)
    return out


@pytest.mark.parametrize("message", [pytest.param(cc(1, 120, 0), id="cc120",
                                                  marks=pytest.mark.xdist_group("mpe-stress-long-cc120")),
                                     pytest.param(bytes([0xC0, 5]), id="program",
                                                  marks=pytest.mark.xdist_group("mpe-stress-long-program"))])
def test_a_long_handler_delays_a_tick_no_worse_than_stock(tmp_path_factory, m, message):
    """CC 120 (all sound off) and a program change take ~80,000 instructions
    in stock's MIDI handling; at some USB frame phases that delays a tick
    so that two ticks' writes arrive ~0.35 ms apart (emulated). Over all 20
    phases stock reaches 122 (CC 120) and 121 (program change) of the 128
    entries. Regression (step 4): the patch's Slide writes in such a tick
    took it to 126 (CC 120 at 150 µs); mpe_slide.c then held them back for
    a tick when the queue was still full (118 at worst). Since v1.2 Slide
    isn't queued at all (114 / 102 at worst, emulated)."""
    built(tmp_path_factory)
    phases = (150, 350, 750, 900)
    stock = long_handler_depths(Mpe(stock_summit(), m.blob), False, phases, message)
    mpe = long_handler_depths(m, True, phases, message)
    print(f"{message.hex(' ')} at USB phases {phases}: stock depth {stock}, MPE {mpe}")
    assert max(stock) >= 118  # the effect is there
    assert max(mpe) <= max(stock) <= QUEUE_LIMIT


# -- MPE off is stock ----------------------------------------------------------------------


def off_play(s, multi):
    """Live and Hapax traffic with every flag 0: a Lower 15 zone in the
    Settings, an MCM, RPN 0 on the members. Single: only the global channel
    1 plays (the master's bends, pressure and wheel). Multi: Part A channel 1,
    Part B channel 2, so a member channel plays Part B."""
    c = Checkpoints(s)
    s.set_soft_thru(True)
    s.set_global(G_MEMBERS, 15, run_ms=0)
    s.set_global(G_ZONE, 1)
    if multi:
        s.set_mode("multi")
        s.set_channels(global_=16, part_a=1, part_b=2)
    rng = random.Random(11)
    for k in range(2):
        span = 300
        ev = live(Zone("lower", 15), rng, 12, span_ms=span, master=True, burst=k == 0) if k != 1 else \
            hapax(Zone("lower", 14), rng, 12, span_ms=span)
        ev = by_time(ev + at(span * 0.3, rpn(3, 0, 0, 24)))
        cut = span * 0.6
        ev = freeze(ev, cut, 200)
        t0 = play(s, [e for e in ev if e[0] <= cut], "usb", until=cut + 150)
        c.note()
        play(s, [e for e in ev if e[0] > cut], "usb", t0=t0, until=cut + 600)
        c.note()
    return c.points


def off_record(s, multi):
    s.reset()
    points = off_play(s, multi)
    assert all(s.patch_byte(FLAG, p) == 0 for p in (0, 1))
    return {"events": s.fpga_events(), "state": s.fpga_state(), "points": points,
            "midi": [(x.time_ms, x.port, x.data) for x in s.midi_out()], "voices": s.active_voices()}


@pytest.mark.parametrize("multi", [pytest.param(False, marks=pytest.mark.xdist_group("mpe-stress-off-single")),
                                   pytest.param(True, marks=pytest.mark.xdist_group("mpe-stress-off-multi"))])
def test_mpe_off_plays_mpe_traffic_as_stock(tmp_path_factory, multi):
    built(tmp_path_factory)
    stock = off_record(stock_summit(), multi)
    mpe = off_record(mpe_summit(tmp_path_factory).s, multi)
    assert len(stock["points"]) == len(mpe["points"]) == 4
    compared = 0
    for i, (a, b) in enumerate(zip(stock["points"], mpe["points"])):
        voices_a, parts_a = snapshot(stock, a)
        voices_b, parts_b = snapshot(mpe, b)
        where = f"checkpoint {i}"
        assert {k: len(v) for k, v in voices_b.items()} == {k: len(v) for k, v in voices_a.items()}, where
        for key, stack in voices_a.items():
            for n, (ra, rb) in enumerate(zip(stack, voices_b[key])):
                compared += same_where_settled(ra, rb, f"{where}, note {key} voice {n}")
        compared += same_where_settled(parts_a, parts_b, f"{where}, broadcast and part registers")
    assert compared > (300 if multi else 100)  # Single: only channel 1 (the master) plays
    if multi:
        assert any(v for _, v in stock["points"])  # Part B played the member channel 2
    assert [x[1:] for x in mpe["midi"]] == [x[1:] for x in stock["midi"]]
    assert stock["voices"] == mpe["voices"] == []
