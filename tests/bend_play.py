"""A bend play test on stock firmware and the FPGA-timeline helpers the MPE
tests share (tests/test_stock_expression.py, tests/test_mpe_expr_*.py).

One sequence goes through the DIN path: a held C major chord (voices 0-2), a
new note (voice 3), bend up, bend down, another note while bent (voice 4: the
selection moves), centre, release. :func:`played` plays it on stock once per
test session and keeps the decoded FPGA timeline, MIDI out, RAM and queue
statistics.

Timing noise: patch code lengthens main-loop passes, so stock's
timing-dependent behaviour shifts. Two things move with it, in stock as in the
patches: voice_state+0x332 (incremented on every main-loop pass), and the
engine select of an occasional queued broadcast write (one engine instead of
both). :func:`changes` therefore keys broadcast targets (>= 0x10) by (target,
param) without the engine, and the RAM comparisons skip that one byte.
"""

import collections
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))


from emu.firmware import SUMMIT_2_2, load_image  # noqa: E402

VOICE_STATE = 0x200057D8
VOICE_LAST_ALLOC = VOICE_STATE + 0x312
FPGA_QUEUE_LAG = 0x200149CC  # s16: 75 per tick minus entries sent; only stored, never read
QUEUE_WR, QUEUE_RD, QUEUE_SENT = VOICE_STATE + 0xBC, VOICE_STATE + 0x144, VOICE_STATE + 0x148
FPGA_QUEUE, QUEUE_ENTRIES = 0x20013EE4, 128
FPGA_MOD_WRITE = 0x08013FCC
MOD_TICK_FIRST_UPDATE = 0x0801456E  # mod_tick: `movs r0, #0` before bl mod_update(0), once per tick
SRAM_USED = (0x20000000, 0x2001785C)  # .data + .bss

DRAIN_PER_TICK = 80  # fpga_queue_drain: 4 entries per TIM6 interrupt, 20 per tick
BEND = (0x68, 0x69, 0x868, 0x869)
PITCH = 0x67
OSC_PITCH = (0x000, 0x001, 0x002)  # per-voice oscillator pitch, the audible bend

CHORD = (60, 64, 67)  # voices 0, 1, 2
NEW_NOTE, NEW_VOICE = 72, 3
MOVE_NOTE, MOVE_VOICE = 76, 4


def play(s):
    """The play test, through DIN. Returns the times (ms) of its steps."""
    s.set_soft_thru(True)  # DIN echo, so there is MIDI out to compare
    t = {}
    for n in CHORD:
        s.note_on(n)
    s.tick(20)
    t["new"] = s.time_ms
    s.note_on(NEW_NOTE)
    s.tick(20)
    t["up"] = s.time_ms
    s.bend(8191)
    s.tick(60)
    t["down"] = s.time_ms
    s.bend(-8192)
    s.tick(60)
    t["move"] = s.time_ms
    s.note_on(MOVE_NOTE)
    s.tick(40)
    t["centre"] = s.time_ms
    s.bend(0)
    s.tick(150)
    t["release"] = s.time_ms
    for n in (*CHORD, NEW_NOTE, MOVE_NOTE):
        s.note_off(n)
    s.tick(300)
    t["end"] = s.time_ms
    return t


class Run:
    """One image playing a sequence (:func:`play` unless given), with the queue watched."""

    def __init__(self, s, blob=None, play=play):
        from unicorn import UC_HOOK_CODE

        self.blob = blob
        self.max_depth = 0
        self.per_tick = []
        self.selected = []  # (time_ms, voice_last_alloc) at each tick
        uc = s.board.uc

        def on_write(uc, _addr, _size, _user):
            wr, rd = struct.unpack("<H", uc.mem_read(QUEUE_WR, 2))[0], struct.unpack("<H", uc.mem_read(QUEUE_RD, 2))[0]
            self.max_depth = max(self.max_depth, (wr + 1 - rd) % QUEUE_ENTRIES)
            if self.per_tick:
                self.per_tick[-1] += 1

        def on_tick(uc, _addr, _size, _user):
            self.per_tick.append(0)
            self.selected.append((s.time_ms, uc.mem_read(VOICE_LAST_ALLOC, 1)[0]))

        hooks = [uc.hook_add(UC_HOOK_CODE, on_write, begin=FPGA_MOD_WRITE, end=FPGA_MOD_WRITE),
                 uc.hook_add(UC_HOOK_CODE, on_tick, begin=MOD_TICK_FIRST_UPDATE, end=MOD_TICK_FIRST_UPDATE)]
        s.reset()
        self.t = play(s)
        for h in hooks:
            uc.hook_del(h)
        self.per_tick = self.per_tick[1:-1]  # whole ticks only
        self.events = s.fpga_events()
        self.midi = [(m.port, m.data) for m in s.midi_out()]
        self.ram = s.board.read(SRAM_USED[0], SRAM_USED[1] - SRAM_USED[0])
        self.voices = s.active_voices()

    def writes(self, target, param, engines=None):
        return [e for e in self.events
                if e.target == target and e.param == param and (engines is None or e.engines == engines)]


def changes(events, skip=lambda e: False):
    """Value-change sequence per (engines, target, param); a stray single-engine
    write to a broadcast target counts as "AB" (see the docstring)."""
    both = {(e.target, e.param) for e in events if e.engines == "AB"}
    out = collections.defaultdict(list)
    for e in events:
        if skip(e):
            continue
        engines = "AB" if (e.target, e.param) in both else e.engines
        seq = out[(engines, e.target, e.param)]
        if not seq or seq[-1] != e.value:
            seq.append(e.value)
    return dict(out)


_runs = {}


def played():
    """The stock Run of :func:`play`, played once per session."""
    if "stock" not in _runs:
        if load_image(SUMMIT_2_2) is None:
            pytest.skip(f"firmware/{SUMMIT_2_2} not present")
        from emu.synth import SimulatedSummit

        _runs["stock"] = Run(SimulatedSummit())
    return _runs["stock"]
