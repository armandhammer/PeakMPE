"""MPE traffic for the simulator: senders, a player and an invariant checker.

Reusable by any test that plays MPE into the patched Summit (tests/mpe_sim.py).

**Senders** build a timed message list, ``[(time_ms, bytes)]``, modelled on
the MPE 1.0 spec and on what PLAN.md ("Input sources") documents of the
user's two sources:

* :func:`live`: Ableton Live (played from Push 3). One zone per track,
  Lower (master 1) or Upper (master 16), member notes rotating over the
  free channels (least recently used first). Before each note-on the
  channel's pressure, CC 74 and bend; during the note, pressure and CC 74
  every few ms and bend now and then. No MPE Configuration Message (MCM)
  unless asked: Live has none documented. The order before a note-on
  (pressure, CC 74, bend, note) and the ~6 ms controller spacing are taken
  from the user's capture ``work/capture/MPE from ableton.mmon``
  (observed); the rest is inferred.
* :func:`hapax`: Squarp Hapax. Lower (members 2-15) or Upper (members 15
  down to 2), its MCM optional, and up to four MPE tracks on one output. How
  the tracks share the member channels isn't documented: by default they
  take channels from one pool (no two notes on one channel); with
  ``shared_pool=False`` each track rotates on its own and they collide, a
  sender reusing a channel before its release.
* :func:`reset_burst`: Live's bend-centre burst (16 x ``E0 00 40``, as in
  the capture); :func:`mcm`, :func:`rpn`: RPN 6 and RPN 0.

**Rendering** for a port: :func:`din_bytes` (running status, optional
interleaved clock and SysEx) and :func:`play`, which feeds a message list
into a SimulatedSummit at its times.

**Checker** (:class:`Invariants`): hooks the patch's channel filter and
checks after every main-loop pass in which a message was handled or a
modulation tick ran, so the firmware's state is never looked at halfway
through a handler. See its docstring for the invariants.
"""

from __future__ import annotations

import collections
import random
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from bend_play import FPGA_MOD_WRITE, MOD_TICK_FIRST_UPDATE, QUEUE_ENTRIES, QUEUE_RD, QUEUE_WR
from mpe_expr_sim import OSC, OSC_MAX, OSC_MIN, PART_BEND_SMOOTHED, slide
from mpe_sim import FLAG, MODE, NONE, UNISON

Events = List[Tuple[float, bytes]]

VOICE_LOOP_INDEX = 0x200057E2
VOICE_STATE = 0x200057D8
VOICE_ACTIVE = VOICE_STATE + 0x334
VOICE_AT = VOICE_STATE + 0xE4
VOICE_AT_SMOOTH = VOICE_STATE + 0x104
WHEEL = VOICE_STATE + 0xCA        # s16 per engine, +4e: the stock-smoothed mod wheel
PARTS, PART_SIZE = 0x20013388, 0x288
VOICE_NOTE = 0x20014950
# The queue's 128 entries wrap without a check. Stock itself reaches 122 when
# a long MIDI handler (CC 120, a program change: ~80,000 instructions) delays
# a tick so that two ticks' writes arrive 0.35 ms apart (emulated, swept over
# the USB frame phase in tests/test_mpe_stress.py); the invariant is that the
# patch never takes it closer to the wrap than that.
QUEUE_LIMIT = QUEUE_ENTRIES - 4
# After a voice is allocated, a refresh of its old pitch that the tick before
# had queued can still drain after voice_alloc's direct note-on writes: stock
# plays the previous note's pitch for ~2 ms after a steal (emulated, also on
# stock). The jump check leaves that window out.
STALE_MS = 2.5


# -- messages -------------------------------------------------------------------------


def note_on(ch, note, vel=100):
    return bytes([0x90 | (ch - 1), note, vel])


def note_off(ch, note, vel=0):
    return bytes([0x80 | (ch - 1), note, vel])


def cc(ch, num, value):
    return bytes([0xB0 | (ch - 1), num, value])


def bend(ch, value):
    """-8192..8191."""
    v = max(-8192, min(8191, value)) + 8192
    return bytes([0xE0 | (ch - 1), v & 0x7F, v >> 7])


def pressure(ch, value):
    return bytes([0xD0 | (ch - 1), value])


def rpn(ch, msb, lsb, value, null=True):
    """RPN msb:lsb = value (data MSB), then RPN null as senders do."""
    out = [cc(ch, 101, msb), cc(ch, 100, lsb), cc(ch, 6, value)]
    if null:
        out += [cc(ch, 101, 127), cc(ch, 100, 127)]
    return out


def mcm(master, members):
    """MPE Configuration Message: RPN 6 on channel 1 (Lower) or 16 (Upper)."""
    return rpn(master, 0, 6, members)


def at(t, msgs):
    return [(t, m) for m in msgs]


@dataclass(frozen=True)
class Zone:
    """An MPE zone as a sender sees it, channels 1-16."""
    kind: str                 # "lower" or "upper"
    members: int

    @property
    def master(self):
        return 1 if self.kind == "lower" else 16

    @property
    def channels(self):
        """Member channels in the order a sender takes them."""
        if self.kind == "lower":
            return list(range(2, 2 + self.members))
        return list(range(15, 15 - self.members, -1))


def reset_burst(t, ch=1, n=16):
    """Live's bend reset: n x bend centre on one channel (the capture has 16
    x ``E0 00 40`` on channel 1 at the start of a play)."""
    return at(t, [bend(ch, 0)] * n)


# -- senders --------------------------------------------------------------------------


@dataclass
class Gesture:
    """One note with its expression, as a sender plays it."""
    start: float
    length: float
    note: int
    velocity: int
    bend_to: int = 0          # the bend it glides to while held
    pressure_peak: int = 100
    slide_from: int = 64
    slide_to: int = 64


def gestures(rng, n, *, start=0.0, span_ms=1000.0, length=(40, 400), notes=(36, 96), bend_range=8191):
    out = []
    for _ in range(n):
        t = start + rng.uniform(0, span_ms)
        out.append(Gesture(t, rng.uniform(*length), rng.randint(*notes), rng.randint(1, 127),
                           rng.randint(-bend_range, bend_range) if rng.random() < 0.6 else 0,
                           rng.randint(0, 127), rng.randint(0, 127), rng.randint(0, 127)))
    return sorted(out, key=lambda g: g.start)


class ChannelPool:
    """Member channel allocation: least recently released first (Live's and,
    by default, the Hapax's rotation). With every channel busy, the oldest
    note's channel is taken again before its note-off: a channel reuse."""

    def __init__(self, channels):
        self.free = collections.deque(channels)
        self.busy: Dict[int, float] = {}   # channel -> when its newest note started
        self.notes = collections.Counter()  # channel -> notes sounding on it

    def take(self, t):
        if self.free:
            ch = self.free.popleft()
        else:
            ch = min(self.busy, key=self.busy.get)
        self.busy[ch] = t
        self.notes[ch] += 1
        return ch

    def give(self, ch):
        self.notes[ch] -= 1
        if self.notes[ch] == 0 and ch in self.busy:
            del self.busy[ch]
            self.free.append(ch)


def expressive_note(ch, g: Gesture, *, rate_ms=6.0, bend_every=3, release_bend=False):
    """One gesture on channel ch: pressure, CC 74 and bend just before the
    note-on (the capture's order), then pressure and CC 74 every rate_ms,
    bend every bend_every-th step, ramping to their targets, then the
    note-off."""
    out = [(g.start, pressure(ch, 0)), (g.start, cc(ch, 74, g.slide_from)), (g.start, bend(ch, 0)),
           (g.start, note_on(ch, g.note, max(1, g.velocity)))]
    steps = max(1, int(g.length / rate_ms))
    for i in range(1, steps):
        t = g.start + i * rate_ms
        x = i / steps
        out.append((t, pressure(ch, int(g.pressure_peak * (1 - abs(2 * x - 1))))))
        out.append((t, cc(ch, 74, int(g.slide_from + (g.slide_to - g.slide_from) * x))))
        if g.bend_to and i % bend_every == 0:
            out.append((t, bend(ch, int(g.bend_to * x))))
    end = g.start + g.length
    out.append((end, note_off(ch, g.note)))
    if release_bend:
        out.append((end, bend(ch, 0)))
    return out


def by_time(events: Events) -> Events:
    return sorted(events, key=lambda e: e[0])   # stable: same-time messages keep their order


def zone_play(zone: Zone, gs: Sequence[Gesture], pool: Optional[ChannelPool] = None, **kw) -> Events:
    """Gestures on a zone's member channels, allocated by a pool."""
    pool = pool or ChannelPool(zone.channels)
    out = []
    ends = []  # (end, ch) not yet given back
    for g in gs:
        for end, ch in sorted(ends):
            if end <= g.start:
                pool.give(ch)
                ends.remove((end, ch))
        ch = pool.take(g.start)
        out += expressive_note(ch, g, **kw)
        ends.append((g.start + g.length, ch))
    return out


def live(zone: Zone, rng: random.Random, n_notes=40, *, start=10.0, span_ms=1500.0, master=True,
         burst=True, mcm_first=False, **kw) -> Events:
    """Ableton Live, one MPE track: see the module docstring. *master* adds
    the master channel's own controls (mod wheel, a bend now and then, a
    pressure), as Live's track-level automation would send them."""
    out = reset_burst(0.0, zone.master) if burst else []
    if mcm_first:
        out += at(1.0, mcm(zone.master, zone.members))
    out += zone_play(zone, gestures(rng, n_notes, start=start, span_ms=span_ms), **kw)
    if master:
        for i in range(int(span_ms / 50)):
            t = start + i * 50 + rng.uniform(0, 10)
            r = rng.random()
            if r < 0.4:
                out.append((t, cc(zone.master, 1, rng.randint(0, 100))))
            elif r < 0.6:
                out.append((t, bend(zone.master, rng.randint(-8192, 8191))))
            elif r < 0.75:
                out.append((t, pressure(zone.master, rng.randint(0, 127))))
        out.append((start + span_ms + 450, bend(zone.master, 0)))
        out.append((start + span_ms + 450, cc(zone.master, 1, 0)))
        out.append((start + span_ms + 450, pressure(zone.master, 0)))
    return by_time(out)


def hapax(zone: Zone, rng: random.Random, n_notes=40, *, tracks=1, mcm_first=True, shared_pool=True,
          start=10.0, span_ms=1500.0, **kw) -> Events:
    """Squarp Hapax: one output, 1-4 MPE tracks in one zone; see the module
    docstring. The Hapax's members are 2-15 (Lower) or 15-2 (Upper)."""
    out = at(0.0, mcm(zone.master, zone.members)) if mcm_first else []
    shared = ChannelPool(zone.channels)
    kw.setdefault("rate_ms", 10.0)
    for _ in range(tracks):
        gs = gestures(rng, n_notes // tracks, start=start, span_ms=span_ms)
        out += zone_play(zone, gs, pool=shared if shared_pool else ChannelPool(zone.channels), **kw)
    return by_time(out)


def mmon_events(path, since_s=0.0, max_gap_ms=None, directions=(">",), channel_only=False) -> Events:
    """The messages of a MIDI Monitor capture (tools/mmon.py), with gaps
    longer than max_gap_ms shortened to it. Each message is cut to its
    status's length (MIDI Monitor keeps two data bytes for channel
    pressure). *directions*: ">" what the host sent ("To X"), "<" what a
    device sent ("From X"). *channel_only*: channel messages and the clock
    and transport bytes only, no SysEx (a firmware update capture must not
    reach the simulated Summit)."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    import mmon

    out, last, shift = [], None, 0.0
    for t, d, _port, data in mmon.messages(path):
        if d not in directions or t < since_s or not data:
            continue
        if channel_only and data[0] >= 0xF0 and data[0] not in (0xF8, 0xFA, 0xFB, 0xFC):
            continue
        ms = t * 1000.0
        if last is not None and max_gap_ms is not None and ms - shift - last > max_gap_ms:
            shift = ms - last - max_gap_ms
        last = ms - shift
        if data[0] < 0xF0:
            data = data[:2 if data[0] & 0xE0 == 0xC0 else 3]
        out.append((last, bytes(data)))
    t0 = out[0][0] if out else 0.0
    return [(t - t0, m) for t, m in out]


# -- rendering --------------------------------------------------------------------------


def din_bytes(events: Events, *, running_status=True, clock_ms=None, sysex_ms=None,
              rng: Optional[random.Random] = None) -> List[Tuple[float, bytes]]:
    """The byte chunks a DIN sender writes: running status (a status byte
    only when it changes), timing clock F8 every clock_ms, also in the
    middle of a message, and a SysEx (a Universal non-realtime message for
    another device) every sysex_ms, between messages. A SysEx cancels
    running status, so the next message carries its status again."""
    rng = rng or random.Random(0)
    out: List[Tuple[float, bytes]] = []
    status = None
    next_clock = 0.0 if clock_ms else None
    next_sysex = sysex_ms if sysex_ms else None
    for t, m in events:
        if next_sysex is not None and t >= next_sysex:
            out.append((t, bytes([0xF0, 0x7E, 0x55, 0x09, 0x01, 0xF7])))  # GM on, for device 0x55
            status = None
            next_sysex += sysex_ms
        data = bytes(m)
        if running_status and data[0] < 0xF0 and data[0] == status:
            data = data[1:]
        if data and data[0] & 0x80:
            status = data[0] if data[0] < 0xF0 else None
        if next_clock is not None and t >= next_clock:
            cut = rng.randint(0, len(data))   # real-time bytes may come between any two bytes
            data = data[:cut] + b"\xf8" + data[cut:]
            while next_clock <= t:
                next_clock += clock_ms
        out.append((t, data))
    return out


def play(s, events, port="usb", *, until=None, t0=None, din_kw=None):
    """Feed timed messages into the simulator, ticking up to each one's time
    (relative to *t0*, default now), then on to *until* (default: 5 ms
    after the last message, so it has been handled). Returns t0, so a list
    can be played in parts against one time base."""
    t0 = s.time_ms if t0 is None else t0
    if until is None and events:
        until = max(t for t, _ in events) + 5
    chunks = din_bytes(events, **(din_kw or {})) if port == "din" else events
    for t, data in chunks:
        dt = t0 + t - s.time_ms
        if dt >= 0.05:
            s.tick(dt)
        s.midi_in(data, port=port)
    if until is not None and t0 + until > s.time_ms:
        s.tick(t0 + until - s.time_ms)
    return t0


def freeze(events: Events, at_ms: float, hold_ms: float) -> Events:
    """The events up to *at_ms*, then silence for *hold_ms* while the notes
    sounding then stay held, then their note-offs: a quiet point with notes
    held at whatever expression they had. Notes not started by then are
    left out."""
    started = set()
    out = []
    for t, m in events:
        kind = m[0] & 0xF0
        off = kind == 0x80 or (kind == 0x90 and m[2] == 0)
        if t <= at_ms:
            if kind == 0x90 and m[2]:
                started.add((m[0] & 0x0F, m[1]))
            elif off:
                started.discard((m[0] & 0x0F, m[1]))
            out.append((t, m))
        elif off and (m[0] & 0x0F, m[1]) in started:
            started.discard((m[0] & 0x0F, m[1]))
            out.append((at_ms + hold_ms, m))
    return by_time(out)


# -- invariants -------------------------------------------------------------------------


class QueueWatch:
    """The FPGA queue on any image (stock too): its depth at every
    fpga_mod_write (``max_depth``, ``depths`` as (time_ms, depth)) and the
    writes per modulation tick (``per_tick``). A context manager."""

    def __init__(self, s, keep=False):
        self.s = s
        self.max_depth = 0
        self.per_tick: List[int] = []
        self.depths: List[Tuple[float, int]] = []
        self.keep = keep
        self.on_tick = None       # extra callback per tick
        self.hooks = []

    def __enter__(self):
        from unicorn import UC_HOOK_CODE

        def on_tick(uc, _a, _s, _u):
            self.per_tick.append(0)
            if self.on_tick:
                self.on_tick()

        def on_write(uc, _a, _s, _u):
            wr, rd = (struct.unpack("<H", uc.mem_read(a, 2))[0] for a in (QUEUE_WR, QUEUE_RD))
            depth = (wr + 1 - rd) % QUEUE_ENTRIES
            self.max_depth = max(self.max_depth, depth)
            if self.keep:
                self.depths.append((self.s.time_ms, depth))
            if self.per_tick:
                self.per_tick[-1] += 1

        uc = self.s.board.uc
        for begin, cb in ((MOD_TICK_FIRST_UPDATE, on_tick), (FPGA_MOD_WRITE, on_write)):
            self.hooks.append(uc.hook_add(UC_HOOK_CODE, cb, begin=begin, end=begin))
        return self

    def __exit__(self, *exc):
        for h in self.hooks:
            self.s.board.uc.hook_del(h)
        self.hooks = []
        return False


class InvariantError(AssertionError):
    pass


@dataclass
class _Model:
    """What the sender has played, from the messages the firmware handled."""
    held: Dict[int, List[int]] = field(default_factory=lambda: collections.defaultdict(list))
    sustained: Dict[int, set] = field(default_factory=lambda: collections.defaultdict(set))
    order: Dict[int, List[int]] = field(default_factory=lambda: collections.defaultdict(list))  # note-ons, oldest first
    note_part: Dict[Tuple[int, int], int] = field(default_factory=dict)   # (ch, note) -> part it plays
    pedal: List[bool] = field(default_factory=lambda: [False, False])
    bend: List[int] = field(default_factory=lambda: [0] * 17)
    pressure: List[int] = field(default_factory=lambda: [0] * 17)
    slide: List[int] = field(default_factory=lambda: [0] * 17)
    last_change: float = 0.0  # time of the last expression or note message


class Invariants:
    """Watches a patched SimulatedSummit (an :class:`mpe_sim.Mpe`) and checks
    after every main-loop pass in which the firmware handled a channel
    message or ran a modulation tick:

    * **binding:** an active (gated) voice bound to a channel plays a note
      that channel holds or the pedal sustains (in the poly modes the newest
      note-on of those),
      belongs to a part with MPE on, and, unless the layout or a flag changed
      since its note-on, its channel is in that part's zone. One channel's
      active voices are at most one unison stack. An unbound active voice
      of an MPE part needs a note held on a channel outside the zones.
    * **pitch never wraps:** every 0x000-0x002 write lies in osc_pitch's
      range, and between two writes of one voice (no note-on in the last
      STALE_MS, no layout or flag change) it moves less than the smoothing
      allows, far less than a wrap (~87,000).
    * **0x60** stays in 0..0x7FFF; the **FPGA queue** never holds more than
      ``queue_limit`` entries (``max_depth``, ``per_tick`` record the
      worst case).
    * :meth:`expression` (called by a test at a quiet point): each member
      voice's 0x000-0x002, AftTouch slot, 0x61 and 0x60 are what its own
      channel's bend, pressure and CC 74 plus the master's controls give,
      and a master voice's what the master's give; so a voice depends on
      nothing else.
    * :meth:`all_released`: no voice gated after every note-off.

    Use as a context manager; the hooks go when it ends.
    """

    def __init__(self, m, *, queue_limit=QUEUE_LIMIT, base=None):
        self.m, self.s = m, m.s
        self.model = _Model()
        self.queue_limit = queue_limit
        self.base = base          # note -> (osc1, osc2, osc3) at no bend (see base_pitch_table)
        self.queue = QueueWatch(self.s)
        self.checks = 0
        self.handled = 0
        self.pending: List[Tuple[float, bytes]] = []
        self.allocated: Dict[int, float] = {}
        self.started: Dict[int, float] = {}
        self.layout_time = -1.0
        self.last_osc: Dict[Tuple[int, int], Tuple[float, int, bool]] = {}
        self.event_index = len(self.s.board.fpga.events)
        self.dirty = False
        self.layout = self._layout()
        self.hooks = []

    # -- hooks --------------------------------------------------------------------------

    def __enter__(self):
        from unicorn import UC_HOOK_CODE
        from unicorn.arm_const import UC_ARM_REG_R2

        from emu.board import MAIN_LOOP_HEAD

        uc = self.s.board.uc

        def on_filter(uc, _a, _s, _u):
            msg = bytes(uc.mem_read(uc.reg_read(UC_ARM_REG_R2), 3))
            if msg[0] < 0xF0:
                self.pending.append((self.s.time_ms, msg))

        def on_alloc(uc, _a, _s, _u):
            self.allocated[uc.mem_read(VOICE_LOOP_INDEX, 1)[0] & 0x0F] = self.s.time_ms

        def on_tick():
            self.dirty = True

        def on_pass(uc, _a, _s, _u):
            if self.pending or self.dirty:
                self.dirty = False
                self.check()

        def fn(name):
            return self.m.addr(name) & ~1

        for begin, cb in ((fn("mpe_channel_filter"), on_filter), (fn("mpe_alloc_glide"), on_alloc),
                          (MAIN_LOOP_HEAD, on_pass)):
            self.hooks.append(uc.hook_add(UC_HOOK_CODE, cb, begin=begin, end=begin))
        self.queue.on_tick = on_tick
        self.queue.__enter__()
        return self

    def __exit__(self, *exc):
        for h in self.hooks:
            self.s.board.uc.hook_del(h)
        self.hooks = []
        self.queue.__exit__()
        return False

    @property
    def max_depth(self):
        return self.queue.max_depth

    @property
    def per_tick(self):
        return self.queue.per_tick

    # -- state --------------------------------------------------------------------------

    def _layout(self):
        s = self.s
        return (self.m.s.board.read(self.m.addr("mpe_zones"), 8), s.multi_mode,
                s.patch_byte(FLAG, 0), s.patch_byte(FLAG, 1), self.m.s.board.read(self.m.addr("mpe_live"), 6))

    def _zone_of(self, ch):
        """(part, master) of the zone channel ch (1-16) is in, or None."""
        for part, master, first, last in self.m.zones().values():
            if ch == master or first <= ch <= last:
                return part, master
        return None

    def _stock_part(self, ch):
        g, a, b = self.s.channels
        if not self.s.multi_mode:
            return 0 if ch == g else None
        if ch == a:
            return 0
        if ch == b:
            return 1
        return None  # the global channel's split/layer isn't modelled

    def _apply(self, t, msg):
        md = self.model
        status, ch = msg[0] & 0xF0, (msg[0] & 0x0F) + 1
        zone = self._zone_of(ch)
        part = zone[0] if zone else self._stock_part(ch)
        if status == 0x90 and msg[2]:
            if msg[1] in md.held[ch]:
                md.held[ch].remove(msg[1])
            md.held[ch].append(msg[1])
            md.sustained[ch].discard(msg[1])
            if msg[1] in md.order[ch]:
                md.order[ch].remove(msg[1])
            md.order[ch].append(msg[1])
            md.note_part[(ch, msg[1])] = part
            md.last_change = t
        elif status == 0x80 or status == 0x90:
            if msg[1] in md.held[ch]:
                md.held[ch].remove(msg[1])
                p = md.note_part.get((ch, msg[1]))
                if p is not None and md.pedal[p]:
                    md.sustained[ch].add(msg[1])
            md.last_change = t
        elif status == 0xB0:
            num, value = msg[1], msg[2]
            member = zone and ch != zone[1]
            if num == 74 and member:
                md.slide[ch] = value
            elif num == 64 and not member and part is not None:
                md.pedal[part] = value >= 64
                if not md.pedal[part]:
                    for c in md.sustained:
                        md.sustained[c] = {n for n in md.sustained[c] if md.note_part.get((c, n)) != part}
            elif num in (120, 123) and part is not None:
                for c in list(md.held):
                    for n in list(md.held[c]):
                        if md.note_part.get((c, n)) == part:
                            md.held[c].remove(n)
                            if md.pedal[part] and num == 123:
                                md.sustained[c].add(n)
                if num == 120:
                    for c in md.sustained:
                        md.sustained[c] = {n for n in md.sustained[c] if md.note_part.get((c, n)) != part}
            md.last_change = t
        elif status == 0xD0:
            md.pressure[ch] = msg[1]
            md.last_change = t
        elif status == 0xE0:
            md.bend[ch] = ((msg[2] << 7) | msg[1]) - 8192
            md.last_change = t

    def fail(self, what):
        raise InvariantError(f"{self.s.time_ms:.2f} ms: {what}")

    def check(self):
        self.checks += 1
        layout = self._layout()
        if layout != self.layout:
            self.layout = layout
            self.layout_time = self.s.time_ms
            self.last_osc.clear()
        for t, msg in self.pending:
            self._apply(t, msg)
            self.handled += 1
        self.pending = []
        for v, t in self.allocated.items():
            self.started[v] = t
        self.allocated.clear()
        self._check_binding()
        self._check_writes()

    def _check_binding(self):
        s, m, md = self.s, self.m, self.model
        b = s.board
        active = b.read(VOICE_ACTIVE, 16)
        notes = b.read(VOICE_NOTE, 16)
        vc = b.read(m.addr("voice_channel"), 16)
        per_channel = collections.defaultdict(list)
        unbound = collections.Counter()
        for v in range(16):
            if not active[v]:
                continue
            part = 1 if s.multi_mode and v >= 8 else 0
            on = s.patch_byte(FLAG, part) == 1
            if vc[v] == NONE:
                if on:
                    unbound[part] += 1
                continue
            ch = vc[v] + 1
            if not on:
                self.fail(f"voice {v} of part {part} (MPE off) is bound to channel {ch}")
            held, sus = md.held.get(ch, []), md.sustained.get(ch, set())
            sounding = [n for n in md.order.get(ch, []) if n in held or n in sus]  # in note-on order
            poly = s.patch_byte(MODE, part) >= 3
            if poly and sounding:  # the channel's newest note-on, held or under the pedal
                ok = notes[v] == sounding[-1]
            else:
                ok = notes[v] in held or notes[v] in sus
            if not ok:
                self.fail(f"voice {v} bound to channel {ch} plays {notes[v]}; the channel holds {held}, sustained {sorted(sus)}")
            if self.started.get(v, -1) > self.layout_time:
                zone = self._zone_of(ch)
                if not zone or zone[0] != part:
                    self.fail(f"voice {v}: channel {ch} isn't a zone channel of part {part}")
            per_channel[ch].append(v)
        for ch, voices in per_channel.items():
            part = 1 if s.multi_mode and voices[0] >= 8 else 0
            u = s.patch_byte(UNISON, part)
            stack = 8 if u == 4 else u + 1
            if len(voices) > stack:
                self.fail(f"channel {ch} holds voices {voices}, more than a stack of {stack}")
        for part, n in unbound.items():
            stock_notes = sum(1 for c in range(1, 17) if not self._zone_of(c)
                              for x in (*md.held.get(c, []), *md.sustained.get(c, ()))
                              if md.note_part.get((c, x)) == part)
            u = s.patch_byte(UNISON, part)
            if n > stock_notes * (8 if u == 4 else u + 1):
                self.fail(f"part {part}: {n} unbound active voices, {stock_notes} notes held outside the zones")

    def _check_writes(self):
        events = self.s.board.fpga.events
        new, self.event_index = events[self.event_index:], len(events)
        live = self.layout[4]
        span = 16383 * max(live[2], live[3]) / 24 + 16383 * max(live[4], live[5]) / 48
        limit = 0.75 * span + 3000  # a full swing smoothed over up to 4 ticks (68 %), the master, rounding; a wrap is ~87,000
        for e in new:
            if e.target >= 0x10:
                continue
            if e.param in OSC:
                if not OSC_MIN <= e.value <= OSC_MAX:
                    self.fail(f"voice {e.target} param {e.param:#x} = {e.value}, outside osc_pitch's range")
                key = (e.target, e.param)
                last = self.last_osc.get(key)
                fresh = e.time_ms - max(self.started.get(e.target, -1e9), self.layout_time) < STALE_MS
                if last and not fresh and not last[2] and abs(e.value - last[1]) > limit:
                    self.fail(f"voice {e.target} param {e.param:#x} jumped {last[1]} -> {e.value} "
                              f"at {e.time_ms:.2f} ms (limit {limit:.0f}): a wrap?")
                self.last_osc[key] = (e.time_ms, e.value, fresh)  # a stale write may be among the fresh ones
            elif e.param == 0x60 and not 0 <= e.value <= 0x7FFF:
                self.fail(f"voice {e.target} 0x60 = {e.value}")
        if self.max_depth > self.queue_limit:
            self.fail(f"FPGA queue depth {self.max_depth} > {self.queue_limit}")

    # -- checks a test calls ----------------------------------------------------------------

    def quiet(self):
        """ms since the last note or expression message was handled."""
        return self.s.time_ms - self.model.last_change

    def settle(self, ms=200, max_ms=2000):
        """Run until no note or expression message was handled for *ms*
        (a DIN backlog drains first)."""
        end = self.s.time_ms + max_ms
        while self.quiet() < ms:
            if self.s.time_ms > end:
                self.fail(f"still busy after {max_ms} ms")
            self.s.tick(max(1.0, ms - self.quiet()))

    def expression(self, settled_fpga=True):
        """At a quiet point (no message for >= 200 ms, so every smoother has
        settled): each member and master voice gets what its own channel and
        the master give, from RAM and from the FPGA writes. Returns the
        number of voices checked."""
        s, m, md = self.s, self.m, self.model
        if self.base is None:
            raise ValueError("expression() needs the base pitch table")
        b = s.board
        live = m.live()
        vc = m.voice_channel()
        checked = 0
        for v in s.active_voices():
            part = 1 if s.multi_mode and v >= 8 else 0
            ch = vc[v]
            zone = self._zone_of(ch) if ch else None
            if ch is None or s.patch_byte(FLAG, part) != 1 or not zone or zone[0] != part:
                continue
            master = zone[1]
            kind = 0 if master == 1 else 1
            member = ch != master
            note = s.voice_note(v)
            pbs = struct.unpack("<h", b.read(PART_BEND_SMOOTHED + 2 * (part if s.multi_mode else 0), 2))[0]
            mp = b.u8(PARTS + (part if s.multi_mode else 0) * PART_SIZE + 7)
            bend_ = md.bend[ch] if member else 0
            off = cdiv(bend_ * live["note_range"][kind], 24) + cdiv(pbs * live["master_range"][kind], 48)
            want_osc = tuple(max(OSC_MIN, min(OSC_MAX, x + off)) for x in self.base[note])
            where = f"voice {v} (channel {ch}, note {note}, part {part})"
            stack = [x for x in s.active_voices() if vc[x] == ch and s.voice_note(x) == note]
            if len(stack) == 1:
                got_osc = tuple(s.last_value(voice=v, param=p) for p in OSC)
                if got_osc != want_osc:
                    self.fail(f"{where}: osc {got_osc}, expected {want_osc} (bend {bend_}, part bend {pbs})")
            else:  # a unison stack, detuned around the note: its mean
                got_osc = tuple(round(sum(s.last_value(voice=x, param=p) for x in stack) / len(stack)) for p in OSC)
                if any(abs(a - b) > 1 for a, b in zip(got_osc, want_osc)) and OSC_MIN < want_osc[0] < OSC_MAX:
                    self.fail(f"{where}: unison stack {stack} osc mean {got_osc}, expected {want_osc}")
            slot = struct.unpack("<H", b.read(VOICE_AT + 2 * v, 2))[0]
            want_slot = (max(md.pressure[ch], mp) if member else mp) << 8
            if slot != want_slot:
                self.fail(f"{where}: AftTouch slot {slot:#x}, expected {want_slot:#x}")
            if settled_fpga:
                # stock's smoother (1/4 per 8 ms refresh) stops a few units
                # short of its target, so 0x61 is checked against it, and it
                # against the slot
                smooth = struct.unpack("<I", b.read(VOICE_AT_SMOOTH + 4 * v, 4))[0]
                if abs((smooth >> 16) - (want_slot >> 4)) > 1:
                    self.fail(f"{where}: AftTouch smoother {smooth >> 16}, slot {want_slot:#x}")
                x = (smooth >> 12) & 0xFFFF
                at = s.last_value(voice=v, param=0x61)
                if at != (x * x >> 15) & 0xFFFF:
                    self.fail(f"{where}: 0x61 = {at}, the smoother gives {(x * x >> 15) & 0xFFFF}")
                wheel = struct.unpack("<h", b.read(WHEEL + 4 * (v >> 3), 2))[0]
                want_mw = max(0, min(0x7FFF, wheel + (slide(md.slide[ch]) if member else 0)))
                mw = s.last_value(voice=v, param=0x60)
                if mw != want_mw:
                    self.fail(f"{where}: 0x60 = {mw}, expected {want_mw} (wheel {wheel}, CC 74 {md.slide[ch]})")
            checked += 1
        return checked

    def all_released(self, release_ms=300):
        self.s.tick(release_ms)
        left = self.s.active_voices()
        if left:
            vc = self.m.voice_channel()
            self.fail(f"voices still gated after every note-off: {[(v, vc[v], self.s.voice_note(v)) for v in left]}")


def cdiv(a, b):
    """C's integer division (towards zero)."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


_base = {}


def base_pitch_table(m):
    """note -> (osc1, osc2, osc3) of an unbent Init Patch voice, measured
    once per worker with MPE off (stock's path), 16 notes at a time."""
    if "table" not in _base:
        s = m.reset().s
        table = {}
        for first in range(0, 128, 16):
            notes = range(first, min(first + 16, 128))
            for n in notes:
                s.note_on(n, channel=1, port="usb")
            s.tick(30)
            for v in s.active_voices():
                table[s.voice_note(v)] = tuple(s.last_value(voice=v, param=p) for p in OSC)
            for n in notes:
                s.note_off(n, channel=1, port="usb")
            s.tick(40)
        assert len(table) == 128
        _base["table"] = table
        m.reset()
    return _base["table"]


# -- CPU ----------------------------------------------------------------------------------

CODE = (0x0800C000, 0x08060000)  # the image and the patch blob after it


def thumb_count(code: bytes) -> int:
    """Instructions in a block of Thumb-2 code: a halfword whose top five
    bits are 0b11101, 0b11110 or 0b11111 starts a 32-bit instruction."""
    n = i = 0
    while i + 1 < len(code):
        hw = code[i] | code[i + 1] << 8
        i += 4 if hw >> 11 in (0x1D, 0x1E, 0x1F) else 2
        n += 1
    return n


class CpuWatch:
    """Instructions executed, counted per basic block (Unicorn block hook,
    Thumb-2 decoded once per block), split into the main thread and the
    interrupt handlers, with the patch blob's share of each:

    * ``passes``: per main-loop pass (MAIN_LOOP_HEAD to MAIN_LOOP_HEAD),
      (time_ms, main instructions, of them in the blob);
    * ``ticks``: per modulation tick (mod_tick's first mod_update to the
      next), (main, blob) in the main thread;
    * ``isr``: (instructions, blob) per interrupt name.

    A block cut short by the board's slot budget counts in full, so counts
    are a few instructions high per slot. The board's time model gives the
    main thread 6,000 instructions per 50 µs slot (120,000 per 1 ms tick,
    120 MHz at one instruction per cycle, inferred); so instructions / 120
    is µs of that model. A context manager."""

    def __init__(self, s, blob):
        self.s = s
        self.blob = (blob.origin, blob.origin + len(blob.data))
        self.passes: List[Tuple[float, int, int]] = []
        self.ticks: List[Tuple[int, int]] = []
        self.isr = collections.defaultdict(lambda: [0, 0])
        self._sizes: Dict[Tuple[int, int], int] = {}
        self._in_isr = None
        self._main = self._main_blob = 0
        self._tick = self._tick_blob = 0
        self._started = False
        self.hooks = []

    def __enter__(self):
        from unicorn import UC_HOOK_BLOCK, UC_HOOK_CODE

        from emu.board import MAIN_LOOP_HEAD

        board = self.s.board
        uc = board.uc
        lo, hi = self.blob

        def on_block(uc, addr, size, _u):
            key = (addr, size)
            n = self._sizes.get(key)
            if n is None:
                n = self._sizes[key] = thumb_count(bytes(uc.mem_read(addr, size)))
            in_blob = lo <= addr < hi
            if self._in_isr is not None:
                c = self.isr[self._in_isr]
                c[0] += n
                c[1] += n if in_blob else 0
            else:
                self._main += n
                self._tick += n
                if in_blob:
                    self._main_blob += n
                    self._tick_blob += n

        def on_head(uc, _a, _s, _u):
            if self._started:
                self.passes.append((self.s.time_ms, self._main, self._main_blob))
            self._started = True
            self._main = self._main_blob = 0

        def on_tick(uc, _a, _s, _u):
            if self._tick_started:
                self.ticks.append((self._tick, self._tick_blob))
            self._tick_started = True
            self._tick = self._tick_blob = 0

        self._tick_started = False
        run_isr = board.run_isr

        def counted_isr(addr, name=""):
            self._in_isr = name or hex(addr)
            try:
                run_isr(addr, name)
            finally:
                self._in_isr = None

        board.run_isr = counted_isr
        self.hooks = [uc.hook_add(UC_HOOK_BLOCK, on_block, begin=CODE[0], end=CODE[1]),
                      uc.hook_add(UC_HOOK_CODE, on_head, begin=MAIN_LOOP_HEAD, end=MAIN_LOOP_HEAD),
                      uc.hook_add(UC_HOOK_CODE, on_tick, begin=MOD_TICK_FIRST_UPDATE, end=MOD_TICK_FIRST_UPDATE)]
        uc.ctl_flush_tb()  # blocks translated before the hook was added wouldn't call it
        return self

    def __exit__(self, *exc):
        for h in self.hooks:
            self.s.board.uc.hook_del(h)
        self.hooks = []
        del self.s.board.run_isr
        return False

    def longest_pass(self):
        return max(self.passes, key=lambda p: p[1])
