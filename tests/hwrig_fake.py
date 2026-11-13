"""A fake MPE Summit for the rig's tests: port + recorder, rendered from MIDI.

It follows what the rig sends, the way the MPE firmware does
(docs/mpe-design.md; the behaviours checked in the simulator in
tests/test_hwrig_run.py):

- `setup`: CC 32 + program change select a base slot, whose MPE flag is
  `mpe_programs` (the config's D002 on, D003 off); matrix slot 1
  (NRPN 1:0/1:2/1:3), Osc1Level (CC 23), O1Range (CC 3: 65 = an octave up),
  Mode (NRPN 0:2: 1 = MonoLG);
- RPN 0 (bend ranges), RPN 6 (MCM: zones), NRPN 62:0 (Single/Multi);
- per-channel bend, pressure, CC 74; poly pressure on a channel counts as
  that channel's pressure (the Peak patch, for the LinnStrument's Z); the master channel's bend (±2) moves
  every voice of its zone; Part B's channel bend moves Part B (±12, the
  Init BendRange);
- Multi: Part A (MPE) takes the zone, Part B plays on its Part channel; a
  note on the global channel inside a zone goes to the zone only;
- mono legato: one voice, the newest held note, with its channel's
  expression; back to the previous note on release;
- voices (16, or 8 per part in Multi): the stock allocator's rotation over
  idle ones; MPE v1.1's channel reuse (a note takes over its channel's
  voice only while it sounds or releases); Diverge (NRPN 0:9) as the
  firmware's per-voice pitch offset (checks4.py); the amp release time
  from AmpRelease (CC 89; fake: 0 = 5 ms, 64 = 0.4 s).

It renders one pure sine per voice (1 ms attack, 5 ms release, then a
-66 dB leak as on the hardware), plus hum and noise.

`faults` injects the failures the checks must catch:
  broadcast_bend   a member's bend moves every voice
  range24          the note bend range is 24, whatever RPN 0 says
  clamp3000        per-note pitch offsets stop at ±3000 cents
  pressure_all     pressure on any member applies to every voice
  stuck            channel 5's voices never release
  b1_drop          the first note-on after an MCM is lost (B1)
  b1_fast          the same, only when it comes within 1.5 ms of the MCM (during a take)
  master_ignored   the master channel's bend does nothing
  partb_follows    Part B also takes the zone master's bend
  global_layers    a note on the global channel also plays Part B
  partb_double     a note on Part B's channel also plays Part A
  mono_stale_bend  mono fallback takes the bend from when the note was played
  no_matrix        the recipe's matrix slot never arrives (no routing)
  lose_first_rpn   the first RPN select (CC 101) after the port opens is lost, and the
                   note range is the Settings' ±49 (the DIN run of 2026-11-08)
  mcm_range49      an MCM resets the note bend range to ±49 (as the synth's Upper Zone
                   came out, 2026-11-08), not to ±48
  pinned_voice     MPE v1's channel reuse: a note takes over its channel's voice even
                   when it is idle (the same voice every time, L5)
  rotate_in_release  a note on a channel whose voice still releases takes another voice
  poly_ignored     poly pressure does nothing (stock: no per-note pressure)
  master_all_zones a master channel's bend moves both zones' voices
  slow_release     releases last 2.25 x as long: P7's (AmpRelease 64) about 0.9 s, as on
                   the synth (2026-11-08)

`stored_flags` (Part A, Part B MPE flags) is the stored Multi that NRPN
62:0 = 1 loads. With both parts MPE, the firmware splits the channels
itself (Lower 2-8 for A, Upper 9-15 for B) unless MCM set both zones
explicitly, and a program change or a parameter CC on a member channel
is dropped: what caught the first Multi setup on the synth (2026-11-08).
"""
import numpy as np

from hwrig import analysis as an

SR = 48000
PITCH_FULL_C = 1200.0  # fake: full matrix depth = ±1 octave at value 127
LEVEL_FULL_DB = 12.0
MASTER_RANGE = 2
PART_BEND_RANGE = 12
DIVERGE_OSC1 = (1, -8, 4, -2, 6, -6, 9, -11)  # s8 at 0x200007CC + 3v, voices 0-7 and 8-15


def diverge_cents(amount, voice):
    """Osc 1's Diverge term: amount x s8 >> 5, in 1/256 semitone."""
    return (amount * DIVERGE_OSC1[voice % 8] >> 5) / 256.0 * 100.0


def release_s(value):
    return 0.005 + value / 64.0 * 0.4


class Port:
    def __init__(self, synth):
        self.synth, self.closed = synth, False

    def send(self, data):
        self.synth.receive(bytes(data))

    def close(self):
        self.closed = True


class Part:
    def __init__(self):
        self.mpe = True
        self.src, self.depth, self.dest, self.osc1 = 0, 64, 0, 127
        self.octave = 0
        self.mono = False
        self.diverge, self.release = 0, 0


class FakeMpeSummit:
    def __init__(self, faults=(), inputs=(1, 2), mpe_programs=(2,), global_ch=1, part_chans=(2, 3),
                 stored_flags=(False, False)):
        self.stored_flags = stored_flags
        self.sr, self.inputs, self.faults = SR, list(inputs), set(faults)
        self.mpe_programs = set(mpe_programs)
        self.global_ch, self.part_chans = global_ch, part_chans
        self.opened, self.sent = 0, []
        self.now = 0.0
        self.recording = False
        self.single, self.parts = Part(), [Part(), Part()]
        self.multi = False
        self.ranges = {"lower": 48, "upper": 48}  # note bend range per zone kind
        self.lost = False
        if "lose_first_rpn" in self.faults:
            self.ranges = {"lower": 49, "upper": 49}
        self.zones = {}          # "lower"/"upper" -> members (count), set by MCM; {} = fallback Lower 15
        self.sel = {}            # ch -> ("rpn"|"nrpn", msb, lsb)
        self.state = {"bend": {}, "pressure": {}, "cc74": {}, "last_bend": 0}
        self.voices, self.done = [], []
        self.slots = [{"held": False, "until": float("-inf"), "bound": None} for _ in range(16)]
        self.last_slot = [15, 7]  # the allocator's last pick per part
        self.mono_stack = []     # [(ch, note)] for a mono part
        self.mcm_pending, self.mcm_t = False, None
        self.split_parts = False  # True with 4 inputs: Part B only on inputs 3/4
        self.timed = []

    # -- port -----------------------------------------------------------------

    def open_port(self):
        self.opened += 1
        return Port(self)

    def receive(self, d):
        self.sent.append(d)
        if "lose_first_rpn" in self.faults and d[0] & 0xF0 == 0xB0 and d[1] == 101 and not self.lost:
            self.lost = True
            return
        if self.recording:
            self.timed.append((self.now, d))
        self.handle(d)

    # -- layout -----------------------------------------------------------------

    def both_mpe(self):
        return self.multi and self.parts[0].mpe and self.parts[1].mpe

    def zone_map(self):
        """{ch: ("lower"/"upper", is_master)} for the zones in use."""
        z = self.zones or {"lower": 15}
        if self.both_mpe() and not (z.get("lower") and z.get("upper")):
            z = {"lower": 7, "upper": 7}  # the firmware's own split
        out = {}
        if "lower" in z and z["lower"]:
            out[1] = ("lower", True)
            for c in range(2, 2 + z["lower"]):
                out[c] = ("lower", False)
        if "upper" in z and z["upper"]:
            out[16] = ("upper", True)
            for c in range(15, 15 - z["upper"], -1):
                out[c] = ("upper", False)
        return out

    def mpe_part(self):
        """Index of the part that takes the zone: 0 (Single or Multi A) or None."""
        if not self.multi:
            return 0 if self.single.mpe else None
        return 0 if self.parts[0].mpe else (1 if self.parts[1].mpe else None)

    def part(self, i):
        return self.single if not self.multi else self.parts[i]

    # -- messages -----------------------------------------------------------------

    def handle(self, d):
        kind, ch = d[0] & 0xF0, (d[0] & 0x0F) + 1
        if kind == 0xB0:
            self.cc(ch, d[1], d[2])
        elif kind == 0xC0:
            self.program(ch, d[1])
        elif kind == 0x90 and d[2]:
            self.note_on(ch, d[1])
        elif kind == 0x80 or kind == 0x90:
            self.note_off(ch, d[1])
        elif kind == 0xE0:
            v = (d[1] | d[2] << 7) - 8192
            self.state["bend"][ch] = v
            self.state["last_bend"] = v
            self.resegment()
        elif kind == 0xD0:
            self.state["pressure"][ch] = d[1]
            self.resegment()
        elif kind == 0xA0 and "poly_ignored" not in self.faults:
            self.state["pressure"][ch] = d[2]
            self.resegment()

    def target_part(self, ch):
        """Which part a setup message on `ch` edits (None: dropped)."""
        if not self.multi:
            return self.single
        zm = self.zone_map()
        if self.mpe_part() is not None and ch in zm and not zm[ch][1]:
            return None  # a member channel: program change and CCs are dropped
        if ch == self.part_chans[0]:
            return self.parts[0]
        if ch == self.part_chans[1]:
            return self.parts[1]
        return None

    def program(self, ch, prog):
        p = self.target_part(ch) if self.multi else (self.single if ch == self.global_ch else None)
        if p is not None:
            p.__init__()
            p.mpe = prog in self.mpe_programs

    def cc(self, ch, num, val):
        if num == 74:
            self.state["cc74"][ch] = val
            self.resegment()
            return
        if num in (99, 98, 101, 100):
            t = "nrpn" if num in (99, 98) else "rpn"
            s = list(self.sel.get(ch, (t, 0, 0)))
            if s[0] != t:
                s = [t, 0, 0]
            s[1 if num in (99, 101) else 2] = val
            self.sel[ch] = tuple(s)
            return
        p = self.target_part(ch)
        if num == 6 and ch in self.sel:
            t, msb, lsb = self.sel[ch]
            if t == "nrpn":
                if (msb, lsb) == (62, 0):
                    if not self.multi and ch == self.global_ch:
                        self.multi = val == 1
                        if self.multi:  # the stored Multi's parts
                            for prt, f in zip(self.parts, self.stored_flags):
                                prt.__init__()
                                prt.mpe = bool(f)
                    elif self.multi and ch in self.part_chans:
                        self.multi = val == 1
                elif p is not None and msb == 1 and "no_matrix" not in self.faults:
                    if lsb == 0:
                        p.src = val
                    elif lsb == 2:
                        p.depth = val
                    elif lsb == 3:
                        p.dest = val
                elif p is not None and (msb, lsb) == (0, 2):
                    p.mono = val in (0, 1, 2)
                elif p is not None and (msb, lsb) == (0, 9):
                    p.diverge = val
            elif t == "rpn" and (msb, lsb) == (0, 0) and ch not in (1, 16):
                # a member channel sets its zone kind's range; outside a zone, the configured
                # layout's (Settings Zone Off: Lower), as the firmware does
                self.ranges[self.zone_map().get(ch, ("lower", False))[0]] = val
            elif t == "rpn" and (msb, lsb) == (0, 6) and ch in (1, 16):
                me, other = ("lower", "upper") if ch == 1 else ("upper", "lower")
                self.zones[me] = val
                self.ranges[me] = 49 if "mcm_range49" in self.faults else 48  # the Settings' value
                if other in self.zones or not self.zones.get(other):
                    self.zones[other] = max(0, min(self.zones.get(other, 0), 14 - val)) if val else \
                        self.zones.get(other, 0)
                if not any(self.zones.values()):
                    self.zones = {}
                self.mcm_pending = True
                self.mcm_t = self.now if self.recording else None
            return
        if p is None:
            return
        if num == 23:
            p.osc1 = val
        elif num == 89:
            p.release = val
        elif num == 3:
            p.octave = val - 64

    @property
    def note_range(self):
        return self.ranges["lower"]

    # -- notes ------------------------------------------------------------------

    def route(self, ch):
        """[(part index, bound channel or None)] a note on `ch` plays."""
        zm, zp = self.zone_map(), self.mpe_part()
        out = []
        if zp is not None and ch in zm:
            out.append((zp, ch))
            if self.multi and ch == self.global_ch and "global_layers" in self.faults:
                out.append((1 - zp, None))
            return out
        if not self.multi:
            return [(0, None)] if ch == self.global_ch else []
        for i in (0, 1):
            if ch == self.part_chans[i] and not (zp == i):
                out.append((i, None))
                if i == 1 and "partb_double" in self.faults:
                    out.append((0, None))
        if ch == self.global_ch and not out:
            out.append((0, None))
        return out

    def note_on(self, ch, note):
        if self.mcm_pending:
            self.mcm_pending = False
            if "b1_drop" in self.faults:
                return
            if "b1_fast" in self.faults and self.mcm_t is not None and self.now - self.mcm_t <= 0.0015:
                return
        for part_i, bound in self.route(ch):
            p = self.part(part_i)
            if p.mono:
                self.mono_stack.append((ch, note, dict(self.state["bend"])))
                self.retrigger_mono(part_i)
                continue
            slot = self.allocate(part_i, bound)
            for v in list(self.voices) + [v for v in self.done if v["off"] is not None]:
                if v.get("slot") == slot and v.get("cut") is None:
                    if v in self.voices:
                        self.end(v)
                    v["cut"] = self.now  # its release tail stops: the voice plays the new note
            v = {"ch": ch, "bound": bound, "part": part_i, "note": note, "on": self.now, "off": None, "segs": [],
                 "slot": slot, "release": release_s(p.release) * (2.25 if "slow_release" in self.faults else 1)}
            self.slots[slot] = {"held": True, "until": float("inf"), "bound": bound}
            self.voices.append(v)
            self.segment(v)

    def allocate(self, part_i, bound):
        """The voice a note takes: its channel's voice while that sounds or
        releases (MPE), else the stock rotation over idle voices."""
        first, n = (8 * part_i, 8) if self.multi else (0, 16)
        now = self.now or 0.0
        mine = [k for k in range(first, first + n) if bound is not None and self.slots[k]["bound"] == bound]
        for k in mine:
            sl = self.slots[k]
            live = sl["held"] or ("rotate_in_release" not in self.faults and now < sl["until"])
            if live or "pinned_voice" in self.faults:
                return k
            sl["bound"] = None
        last = self.last_slot[part_i if self.multi else 0]
        order = [first + (last - first + 1 + i) % n for i in range(n)]
        idle = [k for k in order if not self.slots[k]["held"] and now >= self.slots[k]["until"]]
        releasing = sorted((self.slots[k]["until"], k) for k in order if not self.slots[k]["held"])
        k = idle[0] if idle else releasing[0][1] if releasing else order[0]
        self.last_slot[part_i if self.multi else 0] = k
        return k

    def retrigger_mono(self, part_i):
        for v in [v for v in self.voices if v["part"] == part_i]:
            self.end(v)
        if self.mono_stack:
            ch, note, bends = self.mono_stack[-1]
            v = {"ch": ch, "bound": ch, "part": part_i, "note": note, "on": self.now, "off": None, "segs": [],
                 "stale": bends}
            self.voices.append(v)
            self.segment(v)

    def note_off(self, ch, note):
        if "stuck" in self.faults and ch == 5:
            return
        for part_i, bound in self.route(ch):
            if self.part(part_i).mono:
                self.mono_stack = [x for x in self.mono_stack if (x[0], x[1]) != (ch, note)]
                self.retrigger_mono(part_i)
                if not self.mono_stack:
                    for v in [v for v in self.voices if v["part"] == part_i]:
                        self.end(v)
                return
        for v in list(self.voices):
            if v["ch"] == ch and v["note"] == note:
                self.end(v)

    def end(self, v):
        v["off"] = self.now
        self.voices.remove(v)
        self.done.append(v)
        k = v.get("slot")
        if k is not None and self.slots[k]["held"]:
            self.slots[k]["held"] = False
            self.slots[k]["until"] = (self.now or 0.0) + v["release"]  # now is None after an abort

    # -- pitch and level ----------------------------------------------------------

    def offsets(self, v):
        st, p = self.state, self.part(v["part"])
        cents, dbo = 1200.0 * p.octave, 0.0
        zm = self.zone_map()
        if v["bound"] is not None:
            zone, is_master = zm.get(v["bound"], (None, False))
            if not is_master:
                rng = 24 if "range24" in self.faults else self.ranges.get(zone or "lower", 48)
                bends = v.get("stale") if ("mono_stale_bend" in self.faults and v.get("stale") is not None) \
                    else st["bend"]
                b = st["last_bend"] if "broadcast_bend" in self.faults else bends.get(v["bound"], 0)
                cents += b / 8192.0 * rng * 100.0
            master = 1 if zone == "lower" else 16 if zone == "upper" else None
            if "master_all_zones" in self.faults:
                for m in (1, 16):
                    cents += st["bend"].get(m, 0) / 8192.0 * MASTER_RANGE * 100.0
            elif master and "master_ignored" not in self.faults:
                cents += st["bend"].get(master, 0) / 8192.0 * MASTER_RANGE * 100.0
            ch = v["bound"]
            pres = max(st["pressure"].values(), default=0) if "pressure_all" in self.faults \
                else st["pressure"].get(ch, 0)
            slide = st["cc74"].get(ch, 0)
            val = pres if p.src == 2 else slide if p.src == 1 else 0
            amt = (p.depth - 64) / 63.0 * val / 127.0
            if p.dest == 1:
                cents += amt * PITCH_FULL_C
            elif p.dest == 10:
                dbo = amt * LEVEL_FULL_DB
        else:
            cents += st["bend"].get(v["ch"], 0) / 8192.0 * PART_BEND_RANGE * 100.0
            if "partb_follows" in self.faults and self.multi:
                for m in (1, 16):
                    cents += st["bend"].get(m, 0) / 8192.0 * MASTER_RANGE * 100.0
        if v.get("slot") is not None and p.diverge:
            cents += diverge_cents(p.diverge, v["slot"])
        if "clamp3000" in self.faults:
            cents = max(-3000.0 + 1200.0 * p.octave, min(3000.0 + 1200.0 * p.octave, cents))
        return cents, dbo, p.osc1

    def segment(self, v):
        c, dbo, osc1 = self.offsets(v)
        v["segs"].append((self.now, c, dbo, osc1))

    def resegment(self):
        for v in self.voices:
            self.segment(v)

    # -- recorder -------------------------------------------------------------

    def record(self, duration_s, events):
        self.timed, stamps = [], []
        self.recording = True
        t_start = len(self.done)
        start_voices = list(self.voices)
        for v in start_voices:
            v["take_on"] = 0.0
        for at_s, fn in sorted(events, key=lambda e: e[0]):
            self.now = at_s + 0.0003
            fn()
            stamps.append(self.now)
        self.recording = False
        voices = self.done[t_start:] + self.voices
        if self.split_parts and len(self.inputs) == 4:
            # the user's rig: Part A (and Single) on the first pair, Part B on the second
            a = self.render(duration_s, [v for v in voices if not (self.multi and v["part"] == 1)])
            b = self.render(duration_s, [v for v in voices if self.multi and v["part"] == 1], seed=8)
            out = np.stack([a, a, b, b], axis=1)
        else:
            x = self.render(duration_s, voices)
            out = np.stack([x] * len(self.inputs), axis=1)
        self.now = 0.0
        # voices still held carry over into the next take from its start
        for v in self.voices:
            v["on"], v["segs"] = 0.0, [(0.0,) + v["segs"][-1][1:]]
        for sl in self.slots:  # the next take's clock starts at 0: releases have ended
            if not sl["held"]:
                sl["until"] = float("-inf")
        self.done = []
        return out.astype(np.float32), stamps

    def render(self, dur, voices, seed=7):
        n = int(round(dur * SR))
        t = np.arange(n) / SR
        rng = np.random.default_rng(seed)
        x = 0.0003 * np.sin(2 * np.pi * 50 * t) + rng.normal(0, 1e-5, n)
        for v in voices:
            i0 = max(0, int(v["on"] * SR))
            if i0 >= n:
                continue
            off = v["off"] if v["off"] is not None else dur
            cents, dbs, lev = np.zeros(n - i0), np.zeros(n - i0), np.zeros(n - i0)
            for when, c, dbo, osc1 in v["segs"]:
                a = max(0, int(when * SR) - i0)
                cents[a:], dbs[a:], lev[a:] = c, dbo, osc1
            f = an.note_hz(v["note"]) * 2 ** (cents / 1200.0)
            phase = 2 * np.pi * np.cumsum(f) / SR
            tt = t[i0:] - v["on"]
            env = np.clip(tt / 0.001, 0, 1) if v["on"] > 0 else np.ones(n - i0)
            rel = np.clip(1 - (t[i0:] - off) / v.get("release", 0.005), 0, 1)
            env = env * np.where(t[i0:] < off, 1.0, np.maximum(rel, 10 ** (-66 / 20)))
            if v.get("cut") is not None:  # the voice was taken over: its tail stops
                env = env * (t[i0:] < v["cut"])
            x[i0:] += 0.05 * lev / 127.0 * 10 ** (dbs / 20) * env * np.sin(phase)
        return x
