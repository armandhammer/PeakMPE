"""Slide whatever the CPU rate (patches/mpe/mpe_slide.c, MPE v1.2).

MPE v1.1 sent no Slide in a tick whose phase (timer_state+0x4A8, 100 us
steps since the tick request) read 5 or more when mpe_mod_update ran. In
the simulator's default timing every tick reads 1 there; on the synth every
tick read 5 or more and Slide was dead (observed: the rig's
slide_right_note, +0.00 c, 2026-11-08). The synth runs slower than the
default model: it executes from flash with the ART accelerator off
(FLASH_ACR = 3, 0x0801141C) and its interrupts busy-wait on SPI1. Here the
same check runs over a range of CPU rates (SimulatedSummit.set_timing),
down to the one that reproduces v1.1's failure (0.3, inferred), and each
case first checks that it reaches the tick phase it is meant to cover.

Against v1.1's mpe_slide.c these fail at 0.3 (the voice's 0x60 stays 0;
tried 2026-11-08). Emulated.
"""

import collections

import pytest

from mpe_expr_sim import MODWHEEL
from mpe_sim import mpe_summit, stock_summit, Mpe, built
from mpe_traffic import QueueWatch, mmon_events, play
from test_mpe_conformance import CAPTURE, LIVE_CAPTURE_SHA256, pinned_capture

TICK_PHASE = 0x2000577C           # timer_state+0x4A8
AFTER_MOD_UPDATE_1 = 0x08014582   # mod_tick, after its bl mod_update(1) (mpe_mod_update)

# (cpu_scale, spi_cost) -> the lowest tick phase the case must see at the
# Slide point, so that it really covers a late tick.
TIMINGS = [
    pytest.param(1.0, False, 0, id="default"),
    pytest.param(1.0, True, 0, id="spi"),
    pytest.param(0.5, True, 2, id="spi-0.5"),
    pytest.param(0.35, True, 4, id="spi-0.35"),
    pytest.param(0.3, True, 5, id="spi-0.3-as-the-synth"),
]


@pytest.fixture
def m(tmp_path_factory):
    return mpe_summit(tmp_path_factory).reset()


class Phases:
    """The tick phase each time mod_tick's mod_update(1) returns."""

    def __init__(self, s):
        self.s, self.seen = s, collections.Counter()

    def __enter__(self):
        from unicorn import UC_HOOK_CODE

        def hit(uc, _a, _s, _u):
            self.seen[uc.mem_read(TICK_PHASE, 1)[0]] += 1

        self.hook = self.s.board.uc.hook_add(UC_HOOK_CODE, hit, begin=AFTER_MOD_UPDATE_1, end=AFTER_MOD_UPDATE_1)
        return self

    def __exit__(self, *exc):
        self.s.board.uc.hook_del(self.hook)
        return False


@pytest.mark.parametrize("cpu_scale, spi_cost, min_phase", TIMINGS)
def test_slide_reaches_the_fpga_whatever_the_cpu_rate(m, cpu_scale, spi_cost, min_phase):
    """The rig's slide_right_note in short: E4 on member channel 3, then
    CC 74 0 -> 127 -> 0. The voice's 0x60 follows up and down."""
    s = m.s
    s.set_timing(cpu_scale, spi_cost=spi_cost)
    m.zone_setting(1, 15)
    m.flag()
    s.tick(20)
    s.cc(74, 0, channel=3, port="usb", run_ms=5)
    s.note_on(64, 100, channel=3, port="usb", run_ms=10)
    (v,) = s.active_voices()
    assert s.last_value(voice=v, param=MODWHEEL) == 0
    with Phases(s) as ph:
        s.cc(74, 127, channel=3, port="usb", run_ms=150)
    assert min(ph.seen) >= min_phase, f"the case doesn't reach phase {min_phase}: {dict(ph.seen)}"
    up = s.last_value(voice=v, param=MODWHEEL)
    s.cc(74, 0, channel=3, port="usb", run_ms=150)
    down = s.last_value(voice=v, param=MODWHEEL)
    print(f"cpu {cpu_scale} spi {spi_cost}: phases {dict(sorted(ph.seen.items()))}, 0x60 {up:#06x} -> {down:#06x}")
    assert up >= 0x7F00 and down <= 0x100


@pytest.mark.parametrize("cpu_scale, spi_cost, min_phase", TIMINGS[2:])
def test_slide_reaches_every_voice_of_a_chord_late(m, cpu_scale, spi_cost, min_phase):
    """Three notes on channels 2-4, then channel 3's Slide to 127: only that
    voice moves, at every rate."""
    s = m.s
    s.set_timing(cpu_scale, spi_cost=spi_cost)
    m.zone_setting(1, 15)
    m.flag()
    s.tick(20)
    for ch, note in ((2, 55), (3, 64), (4, 72)):
        s.note_on(note, 100, channel=ch, port="usb", run_ms=10)
    s.cc(74, 127, channel=3, port="usb", run_ms=150)
    by_note = {s.voice_note(v): s.last_value(voice=v, param=MODWHEEL) for v in s.active_voices()}
    assert by_note[64] >= 0x7F00 and by_note[55] == by_note[72] == 0


@pytest.mark.slow
@pytest.mark.parametrize("cpu_scale, spi_cost", [pytest.param(1.0, False, id="default"),
                                                 pytest.param(0.35, True, id="spi-0.35"),
                                                 pytest.param(0.3, True, id="spi-0.3-as-the-synth")])
def test_live_capture_queue_no_deeper_than_stock(tmp_path_factory, m, cpu_scale, spi_cost):
    """The L4 recording (Live, Push 3, both hands) over USB: the FPGA queue
    with Slide never gets deeper than stock's with the same messages on
    channel 1, at each rate. Stock reaches 126 of 128 at the default rate;
    v1.1 without its phase guard reached 127 there (emulated)."""
    capture = pinned_capture(CAPTURE, LIVE_CAPTURE_SHA256)
    built(tmp_path_factory)
    events = mmon_events(capture, max_gap_ms=30)
    depth = {}
    for name in ("stock", "mpe"):
        sim = m if name == "mpe" else Mpe(stock_summit(), m.blob)
        sim.reset()
        sim.s.set_timing(cpu_scale, spi_cost=spi_cost)
        sim.zone_setting(1, 15)
        if name == "mpe":
            sim.flag()
        sim.s.tick(20)
        ev = events if name == "mpe" else [(t, bytes([x[0] & 0xF0]) + x[1:]) for t, x in events]
        with QueueWatch(sim.s) as q:
            play(sim.s, ev, "usb")
        depth[name] = q.max_depth
    m.reset()
    print(f"cpu {cpu_scale} spi {spi_cost}: queue depth MPE {depth['mpe']}, stock {depth['stock']}")
    assert depth["mpe"] <= depth["stock"] < 128
