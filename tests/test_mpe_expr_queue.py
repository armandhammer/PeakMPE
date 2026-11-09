"""The FPGA queue with every voice's expression moving (patches/mpe).

Stock queues 75 writes per tick and the drain sends 80 (findings, "The FPGA
bus"); the queue has 128 entries and its write index wraps without a check.
MPE adds per-voice 0x60 writes (Slide plus the master's wheel; since v1.2
straight to the FPGA, not queued) and drops the broadcast 0x60 for MPE
engines. The worst case is every voice's 0x60 moving
at once: 16 notes, all member channels sliding, bending and pressing, and the
master wheel sweeping. Measured per tick (fpga_mod_write calls) and as the
peak depth. Bend and pressure take no extra queue writes (bend is in the
existing 0x000-0x002 refresh, pressure in stock's 0x61 round-robin).

Emulated; run as slow (plays 600 ms on two layouts).
"""

import struct

import pytest

from bend_play import DRAIN_PER_TICK, FPGA_MOD_WRITE, QUEUE_ENTRIES, QUEUE_RD, QUEUE_WR, Run
from mpe_expr_sim import MODWHEEL
from mpe_sim import FLAG, G_MEMBERS, G_ZONE, built, mpe_summit, stock_summit

pytestmark = pytest.mark.slow

STOCK_PER_TICK = 75
SLIDE_PER_TICK = 4  # mpe_slide.c


def everything_moving(multi):
    def play(s):
        s.set_global(G_MEMBERS, 15 if not multi else 0, run_ms=0)
        s.set_global(G_ZONE, 1 if not multi else 0)
        if multi:
            s.set_mode("multi")
        s.to_pass_start()  # the flags change between passes, as from the VOICE item
        for part in ((0, 1) if multi else (0,)):
            s.set_patch_byte(FLAG, 1, part)
        s.tick(5)
        channels = range(1, 17)  # Single: master 1 + members 2-16; Multi: 1, 2-8 / 9-15, 16
        for i, ch in enumerate(channels):
            s.note_on(40 + 3 * i, channel=ch, port="usb")
            s.tick(3)
        s.tick(20)
        t = {"moving": s.time_ms, "jumps": []}
        for step in range(24):  # every 25 ms all channels jump: every voice's 0x60 moves
            hi = step % 2 == 0
            t["jumps"].append(s.time_ms)
            for ch in channels:  # Slide and wheel move together and stay below the clamp
                s.cc(74, 100 if hi else 0, channel=ch, port="usb")
                s.bend(8191 if hi else -8192, channel=ch, port="usb")
                s.channel_pressure(127 if hi else 0, channel=ch, port="usb")
            for master in ((1, 16) if multi else (1,)):
                s.cc(1, 27 if hi else 0, channel=master, port="usb")
            s.tick(25)
        t["still"] = s.time_ms
        for i, ch in enumerate(channels):
            s.note_off(40 + 3 * i, channel=ch, port="usb")
        s.tick(300)
        return t
    return play


class DepthRun(Run):
    """Run, plus the queue depth at each write with its time."""

    def __init__(self, s, play):
        from unicorn import UC_HOOK_CODE

        self.depths = []

        def on_write(uc, _addr, _size, _user):
            wr, rd = (struct.unpack("<H", uc.mem_read(a, 2))[0] for a in (QUEUE_WR, QUEUE_RD))
            self.depths.append((s.time_ms, (wr + 1 - rd) % QUEUE_ENTRIES))

        hook = s.board.uc.hook_add(UC_HOOK_CODE, on_write, begin=FPGA_MOD_WRITE, end=FPGA_MOD_WRITE)
        try:
            super().__init__(s, play=play)
        finally:
            s.board.uc.hook_del(hook)

    def moving_depth(self):
        return max(d for t, d in self.depths if self.t["moving"] <= t <= self.t["still"])


_runs = {}


@pytest.fixture
def runs(tmp_path_factory, layout):
    """Stock's and the MPE patch's run for *layout*, played once per worker.
    Each layout is its own xdist group, so the two play in parallel."""
    if layout not in _runs:
        built(tmp_path_factory)
        mpe = mpe_summit(tmp_path_factory).s
        multi = layout == "multi"
        _runs[layout] = {
            "stock " + layout: DepthRun(stock_summit(), play=everything_moving(multi)),
            layout: DepthRun(mpe, play=everything_moving(multi)),
        }
    return _runs[layout]


LAYOUTS = [pytest.param(layout, marks=pytest.mark.xdist_group(f"mpe-expr-queue-{layout}"))
           for layout in ("single", "multi")]


@pytest.mark.parametrize("layout", LAYOUTS)
def test_stock_reference(runs, layout):
    assert max(runs["stock " + layout].per_tick) == STOCK_PER_TICK


@pytest.mark.parametrize("layout", LAYOUTS)
def test_all_16_voices_move_at_once(runs, layout):
    run = runs[layout]
    assert run.voices == []
    t = run.t
    writes = [e for e in run.events if e.target < 0x10 and e.param == MODWHEEL and t["moving"] < e.time_ms < t["still"]]
    assert {e.target for e in writes} == set(range(16))
    # Right after each jump every voice is moving: 16 voices at 4 per tick,
    # round-robin; a voice whose value didn't change in a tick is passed
    # over, so a voice waits 4-6 ms (emulated; v1.1 the same, worst 6.05).
    # Each gets a write in every 6 ms window, give or take 0.1 ms: since
    # v1.2 the writes land at the tick itself (here 0.05 ms before the
    # windows' start), v1.1's queued ones up to ~0.5 ms later.
    for jump in t["jumps"][1:]:
        for start in (jump + 2, jump + 8):
            assert {e.target for e in writes if start - 0.1 <= e.time_ms < start + 6.1} == set(range(16))


@pytest.mark.parametrize("layout", LAYOUTS)
def test_queue_stays_within_the_drain_rate(runs, layout):
    run = runs[layout]
    # Single: both broadcasts 0x60 dropped (-2). Multi with two MPE parts:
    # the same. Since v1.2 the per-voice 0x60 writes go to the FPGA directly
    # (fpga_voice_write), not through the queue: 73 per tick with MPE on,
    # stock's 75 in the set-up before the flags (v1.1: up to 77).
    assert max(run.per_tick) <= STOCK_PER_TICK < DRAIN_PER_TICK
    # While everything moves: the 32-entry margin the experiments kept
    # (emulated: Single 86, Multi 88; stock 82 with fewer notes sounding).
    stock = runs["stock " + layout]
    assert run.moving_depth() < QUEUE_ENTRIES - 32
    # Overall peak (emulated, 98 in both layouts): a tick delayed by a long
    # main-loop pass (16 note-offs at once, or the switch to Multi) followed
    # by an on-time one, so two ticks' writes arrive faster than the
    # timer-driven drain (v1.1, which queued Slide: 77 writes per tick,
    # peak 98). Stock peaks the same way
    # (94 at the switch to Multi). At least 24 entries stay free.
    assert run.max_depth < QUEUE_ENTRIES - 24
    print(f"{layout}: per tick max {max(run.per_tick)}, depth moving {run.moving_depth()} "
          f"(stock {stock.moving_depth()}), peak {run.max_depth} (stock {stock.max_depth})")


@pytest.mark.parametrize("layout", LAYOUTS)
def test_broadcast_0x60_never_sent_while_mpe(runs, layout):
    run = runs[layout]
    t = run.t
    assert not [e for e in run.events if e.target == 0x1A and e.param == MODWHEEL
                and t["moving"] - 20 < e.time_ms < t["still"]]
