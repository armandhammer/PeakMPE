"""Stage-3 checks (docs/hw-test-rig.md#stage-3-checks): B1, master channel,
Multi, mono/legato.

Same rules as stage 2 (checks.py): a recipe, timelines with marks, rows
measured relative to the same take. Checks that move the zone or switch to
Multi set `changes_layout`, and the run restores Single mode, the
configured zone (`mpe.zone`) and centred channels after them, and again
whenever it ends or stops.

Expected behaviour from docs/mpe-design.md, checked in the simulator with
the MPE patch (tests/test_hwrig_run3.py, emulated): the master channel's
bend (±2) moves every note of its zone, master-channel notes included; a
member's bend only its note; in Multi, Part B's channel bend (Init
BendRange 76 = ±12) only Part B; a global-channel note inside a zone goes
to the zone only, and the display shows CH CLASH (`mpe_clash` bit 2); mono
legato plays the newest note with its channel's bend and falls back to the
previous note with that channel's current bend.
"""
import random

from . import analysis as an
from .checks import PRE_S, SETTLE_S, TAIL_S, WIN_S, Check, chord_off, chord_on, fmt_c, row
from .recipes import RECIPES
from .stimulus import Timeline, bend, cc, note_off, note_on, rpn

MASTER_HALF_C = 100.0     # master bend +4096 at ±2 semitones
PART_HALF_C = 600.0       # Part B channel bend +4096 at BendRange 76 (±12), emulated
FIND_C = 30.0
STEP_S = SETTLE_S + WIN_S + 0.05


def measure_notes(take, t, expect_hz, tol_c=FIND_C):
    seg = take.window(t, t + WIN_S)
    found = an.peaks(seg, take.sr, fmin=20.0, fmax=16000.0, rel_db=-30.0)
    return an.match_voices(found, expect_hz, tol_c), found


def hz_after(base_hz, cents):
    return base_hz * 2 ** (cents / 1200.0)


class MovesCheck(Check):
    """A held set of notes, then steps that move some of them by known
    amounts: each step's rows say which note moved by how much, and that
    the others didn't. Subclasses give NOTES [(label, channel, MIDI note,
    sounding octave shift)] and STEPS [(mark, [(channel, value)] bends,
    {label: expected cents})]."""
    NOTES = []
    STEPS = []
    ABSENT = []   # [(label, hz offset in semitones from a NOTE, why)]: partials that must not sound

    def timeline(self, cfg):
        tl = Timeline()
        tl.mark(PRE_S, "pre")
        t = PRE_S
        for label, ch, n, _ in self.notes(cfg):
            tl.at(t, note_on(ch, n), f"on_{label}")
        tl.mark(t + SETTLE_S, "base")
        t += STEP_S
        for mark, bends, _ in self.STEPS:
            for k, (ch, v) in enumerate(bends):
                tl.at(t, bend(ch, v), mark if k == 0 else "")
            t += STEP_S
        notes = [(ch, n) for _, ch, n, _ in self.notes(cfg)]
        chord_off(tl, t, notes)
        tl.duration = t + TAIL_S + 0.1
        return tl

    def notes(self, cfg):
        return self.NOTES

    def analyze(self, take, cfg):
        rows = []
        notes = self.notes(cfg)
        exp = [an.note_hz(n + 12 * octv) for _, _, n, octv in notes]
        base, found = measure_notes(take, take.time("base"), exp)
        names = [f"{label} ({an.note_name(n + 12 * o)} on ch {ch})" for label, ch, n, o in notes]
        rows.append(row(self.name, "all notes sound", f"{len(notes)} notes", f"{sum(b is not None for b in base)}",
                        f"±{FIND_C:.0f} c", all(b is not None for b in base)))
        for label, ref_label, semis, why in self.ABSENT:
            ref = [k for k, (lb, *_rest) in enumerate(notes) if lb == ref_label][0]
            hz = exp[ref] * 2 ** (semis / 12.0)
            hit = an.match_voices(found, [hz], FIND_C)[0]
            rows.append(row(self.name, f"no {label}", f"nothing at {hz:.1f} Hz ({why})",
                            "none" if hit is None else f"{hit.db - max(p.db for p in found):+.1f} dB re loudest",
                            "within 30 dB", hit is None))
        if not all(base):
            return rows + self.silence_rows(take, max((p.db for p in found), default=-60.0))
        for mark, _, want in self.STEPS:
            t = take.time(mark) + SETTLE_S
            hz = [hz_after(b.hz, want.get(label, 0.0)) for b, (label, *_r) in zip(base, notes)]
            got, _ = measure_notes(take, t, hz, tol_c=FIND_C)
            for k, (b, p) in enumerate(zip(base, got)):
                w = want.get(notes[k][0], 0.0)
                m = None if p is None else float(an.cents(p.hz, b.hz))
                tol = 1.0 if w else 0.5
                ok = m is not None and abs(m - w) <= (2.0 if abs(w) >= PART_HALF_C else tol)
                rows.append(row(self.name, f"{mark}: {names[k]}" + ("" if w else " unchanged"), fmt_c(w),
                                fmt_c(m), f"±{2.0 if abs(w) >= PART_HALF_C else tol:g} c", ok))
        return rows + self.silence_rows(take, max(b.db for b in base))


class MasterChannel(MovesCheck):
    """Single mode: the global channel 1 is the Lower Zone's master. Its
    bend moves every note of the zone, a note played on it included; a
    member's bend moves only its note."""
    name = "master_channel"
    recipe = "p1"
    about = "Single: G3, E4 on members 2-3 and C5 on master 1; master bend, then a member bend"
    NOTES = [("G3", 2, 55, 0), ("E4", 3, 64, 0), ("C5", 1, 72, 0)]
    STEPS = [
        ("master +4096", [(1, 4096)], {"G3": 100.0, "E4": 100.0, "C5": 100.0}),
        ("member 2 +683", [(2, 683)], {"G3": 500.2, "E4": 100.0, "C5": 100.0}),
        ("master back", [(1, 0)], {"G3": 400.2}),
        ("member 2 back", [(2, 0)], {}),
    ]


class MultiM1(MovesCheck):
    """Multi (M1): Part A, MPE, on the Upper Zone (members 9-15, master 16);
    Part B, MPE off, an octave up, on its Part channel. Expression on the
    zone moves only Part A's notes; Part B's channel bend only Part B."""
    name = "multi_m1"
    recipe = "m1"
    changes_layout = True
    about = "Multi: G3, E4 on Upper members 9-10 (Part A); C4 on Part B's channel, sounding C5"
    STEPS = [
        ("member 9 +683", [(9, 683)], {"G3 (A)": 400.2}),
        ("member 9 back", [(9, 0)], {}),
        ("Part B bend +4096", None, {"C4 (B)": PART_HALF_C}),
        ("Part B back", None, {}),
        ("master 16 +4096", [(16, 4096)], {"G3 (A)": 100.0, "E4 (A)": 100.0}),
        ("master 16 back", [(16, 0)], {}),
    ]
    ABSENT = [("doubled Part B note", "C4 (B)", -12, "Part B's note at Part A's octave")]

    def notes(self, cfg):
        return [("G3 (A)", 9, 55, 0), ("E4 (A)", 10, 64, 0), ("C4 (B)", cfg.part_b_channel, 60, 1)]

    def timelines(self, cfg):
        self.check_channels(cfg)
        b = cfg.part_b_channel
        self.STEPS = [(m, bends if bends is not None else [(b, 4096 if "+" in m else 0)], w)
                      for m, bends, w in type(self).STEPS]
        return [self.timeline(cfg)]

    def check_channels(self, cfg):
        master, members = RECIPES[self.recipe].zone_channels()
        for name, ch in (("Part A", cfg.part_a_channel), ("Part B", cfg.part_b_channel)):
            if ch == master or ch in members or ch == cfg.channel:
                raise ValueError(f"{name} channel {ch} is in the zone or on the global channel")


class GlobalMasterMulti(MultiM1):
    """F5: in Multi, the global channel 1 is also the Lower Zone's master
    (Part A, members 2-4). A note on it goes to the zone (Part A) only,
    not to Part B; its bend moves Part A only. The display's CH CLASH is
    not visible to the rig (emulated: shown)."""
    name = "global_master_multi"
    recipe = "f5"
    about = "Multi, global 1 = Lower master: G3 on ch 1, E4 on member 2 (Part A); C4 on Part B's channel"
    STEPS = [
        ("master 1 +4096", [(1, 4096)], {"G3 (A)": 100.0, "E4 (A)": 100.0}),
        ("master 1 back", [(1, 0)], {}),
        ("Part B bend +4096", None, {"C4 (B)": PART_HALF_C}),
        ("Part B back", None, {}),
    ]
    ABSENT = [("global note on Part B", "G3 (A)", 12, "the global channel's note at Part B's octave"),
              ("doubled Part B note", "C4 (B)", -12, "Part B's note at Part A's octave")]

    def notes(self, cfg):
        return [("G3 (A)", 1, 55, 0), ("E4 (A)", 2, 64, 0), ("C4 (B)", cfg.part_b_channel, 60, 1)]

    def analyze(self, take, cfg):
        rows = super().analyze(take, cfg)
        return rows + [row(self.name, "CH CLASH on Settings page 5", "shown (emulated: mpe_clash bit 2)",
                           "not visible to the rig", "", True, "look at the Summit's MPE page", info=True)]


class MonoLegato(Check):
    """P6 (MonoLG): the voice plays the newest note with its own channel's
    bend; bending the held-back note's channel changes nothing; on release
    it goes back to that note with the channel's current bend."""
    name = "mono_legato"
    recipe = "p6"
    about = "mono: C4 on member 2, legato E4 on member 3 (bent -200 c), release back to C4"
    def timeline(self, cfg):
        tl = Timeline()
        tl.mark(PRE_S, "pre")
        t = PRE_S
        tl.at(t, bend(3, -341), "pre3")
        tl.at(t + 0.01, note_on(2, 60), "ref")
        t += STEP_S
        tl.at(t, bend(2, 683), "bent")
        t += STEP_S
        tl.at(t, note_on(3, 64), "legato")
        t += STEP_S
        tl.at(t, bend(2, 1365), "held bent")
        t += STEP_S
        tl.at(t, note_off(3, 64), "fallback")
        t += STEP_S
        tl.at(t, note_off(2, 60), "off2")
        tl.mark(t, "last_off")
        t += 0.01
        tl.at(t, bend(2, 0), "")
        tl.at(t, bend(3, 0), "")
        tl.duration = t + TAIL_S + 0.1
        return tl

    def analyze(self, take, cfg):
        rows = []
        t = take.time("ref") + SETTLE_S
        ref = an.fundamental(take.window(t, t + WIN_S), take.sr)
        rows.append(row(self.name, "C4 sounds", "a tone", "found" if ref else "none", "", ref is not None))
        if ref is None:
            return rows + self.silence_rows(take, -60.0)
        want_c = {"bent": 400.2, "legato": 400.0 - 341 / 8192 * 4800, "held bent": 400.0 - 341 / 8192 * 4800,
                  "fallback": 1365 / 8192 * 4800}
        for mark, w in want_c.items():
            t = take.time(mark) + SETTLE_S
            seg = take.window(t, t + WIN_S)
            found = an.peaks(seg, take.sr, fmin=20.0, fmax=16000.0, rel_db=-30.0)
            rows.append(row(self.name, f"{mark}: one voice", "1 partial", f"{len(found)}", "within 30 dB",
                            len(found) == 1))
            m = float(an.cents(found[0].hz, ref.hz)) if found else None
            rows.append(row(self.name, f"{mark}: pitch re C4", fmt_c(w), fmt_c(m), "±1 c",
                            m is not None and abs(m - w) <= 1.0))
        return rows + self.silence_rows(take, ref.db)


class B1ZoneChange(Check):
    """B1: the first chord after an MCM zone change sometimes lost a note
    (H3, never reproduced). Many trials: an MCM pair (the other zone to 0,
    then this zone to n, each after CC 121, as the Hapax sends it), a delay,
    then a chord of 3-6 notes on the new zone's members; count the notes.

    Delays: 'burst' (the chord in the same scheduler pass as the MCM, and the
    MCM without RPN nulls, as the Hapax's capture), 0 (same pass, with
    nulls), 1, 5 and 20 ms. Trials are interleaved over the delays and
    seeded, so a run is repeatable. A 0 % drop rate is a result, not a
    failure of the check."""
    name = "b1_zone_change"
    recipe = "p1"
    changes_layout = True
    DELAYS = ("burst", 0, 1, 5, 20)
    LAYOUTS = [("lower", 15), ("upper", 15), ("lower", 9), ("upper", 6), ("lower", 3), ("upper", 13),
               ("lower", 7), ("upper", 14)]
    HOLD_S, GAP_S, WIN_START_S, WIN_LEN_S = 0.35, 0.2, 0.07, 0.25
    PER_TAKE = 30
    SEED = 1_2026_11_07

    def __init__(self, trials_per_delay=60):
        self.trials_per_delay = trials_per_delay
        self.about = (f"{trials_per_delay} trials per delay {list(self.DELAYS)}: MCM zone change, then a chord "
                      "of 3-6 notes on the new zone; count the notes")
        self.trials = []

    @staticmethod
    def members(zone, n):
        return list(range(2, 2 + n)) if zone == "lower" else list(range(15, 15 - n, -1))

    @staticmethod
    def mcm(zone, n, null=True):
        me, other = (1, 16) if zone == "lower" else (16, 1)
        r = (lambda ch, v: rpn(ch, 0, 6, v)) if null else \
            (lambda ch, v: [cc(ch, 101, 0), cc(ch, 100, 6), cc(ch, 6, v)])
        return [cc(other, 121, 0)] + r(other, 0) + [cc(me, 121, 0)] + r(me, n)

    def plan_trials(self):
        rng = random.Random(self.SEED)
        order = [d for d in self.DELAYS for _ in range(self.trials_per_delay)]
        rng.shuffle(order)
        trials, prev = [], None
        for i, d in enumerate(order):
            layout = rng.choice([x for x in self.LAYOUTS if x != prev])
            prev = layout
            members = self.members(*layout)
            k = rng.randint(3, min(6, len(members)))
            chans = rng.sample(members, k)
            notes = []
            while len(notes) < k:
                n = rng.randint(55, 88)
                if all(abs(n - m) >= 3 for m in notes):
                    notes.append(n)
            trials.append({"i": i, "delay": d, "zone": layout[0], "members": layout[1],
                           "chord": list(zip(chans, notes))})
        return trials

    def timelines(self, cfg):
        self.trials = self.plan_trials()
        tls = []
        for start in range(0, len(self.trials), self.PER_TAKE):
            tl = Timeline()
            tl.mark(PRE_S, "pre")
            t = PRE_S
            for tr in self.trials[start:start + self.PER_TAKE]:
                tr["take"] = len(tls)
                i, d = tr["i"], tr["delay"]
                for k, m in enumerate(self.mcm(tr["zone"], tr["members"], null=(d != "burst"))):
                    tl.at(t, m, f"t{i}_mcm" if k == 0 else f"t{i}_m")
                tc = t + (0 if d == "burst" else d / 1000.0)
                for k, (ch, n) in enumerate(tr["chord"]):
                    tl.at(tc, note_on(ch, n), f"t{i}_chord" if k == 0 else f"t{i}_n")
                toff = tc + self.HOLD_S
                for k, (ch, n) in enumerate(tr["chord"]):
                    tl.at(toff, note_off(ch, n), f"t{i}_off" if k == 0 else f"t{i}_o")
                t = toff + self.GAP_S
            tl.mark(t - self.GAP_S, "last_off")
            tl.duration = t + TAIL_S
            tls.append(tl)
        return tls

    def judge(self, take, tr):
        t = take.time(f"t{tr['i']}_chord") + self.WIN_START_S
        seg = take.window(t, t + self.WIN_LEN_S)
        found = an.peaks(seg, take.sr, fmin=20.0, fmax=16000.0, rel_db=-30.0, min_sep_cents=60.0)
        exp = [an.note_hz(n) for _, n in tr["chord"]]
        got = an.match_voices(found, exp, FIND_C)
        missing = [ch for (ch, _), g in zip(tr["chord"], got) if g is None]
        extra = [p for p in found if all(abs(an.cents(p.hz, e)) > FIND_C for e in exp)]
        tr.update(found=len(found) - len(extra), missing=missing, extra=[round(p.hz, 1) for p in extra])
        return not missing and not extra

    def analyze_takes(self, takes, cfg):
        rows, fails = [], []
        for tr in self.trials:
            tr["ok"] = self.judge(takes[tr["take"]], tr)
            if not tr["ok"]:
                fails.append(tr)
        # B1 is a note missing from the chord; an extra partial (a note from an earlier
        # trial still sounding: a lost note-off, as over DIN on 2026-11-08) is another fault
        for d in self.DELAYS:
            ts = [tr for tr in self.trials if tr["delay"] == d]
            short = [tr for tr in ts if tr["missing"]]
            label = "burst (same pass, no RPN null)" if d == "burst" else f"{d} ms"
            note = "; ".join(f"t{tr['i']} {tr['zone']} {tr['members']}: missing ch {tr['missing']}"
                             for tr in short[:4])
            rows.append(row(self.name, f"chords complete, delay {label}", f"0 / {len(ts)} short",
                            f"{len(short)} / {len(ts)} ({100.0 * len(short) / max(1, len(ts)):.1f} %)", "0",
                            not short, note))
        extra = [tr for tr in self.trials if tr["extra"]]
        rows.append(row(self.name, "no extra partials (a note still sounding from an earlier trial)",
                        f"0 / {len(self.trials)}", f"{len(extra)} / {len(self.trials)}", "0", not extra,
                        "; ".join(f"t{tr['i']} ({tr['delay']}): {tr['extra']} Hz" for tr in extra[:4])))
        total = len(self.trials)
        short_all = [tr for tr in self.trials if tr["missing"]]
        rows.append(row(self.name, "B1 (a note lost after a zone change)", "never seen in this run",
                        f"{len(short_all)} of {total} trials"
                        + (" (not reproduced)" if not short_all else " REPRODUCED"), "", True, info=True))
        silent = [self.silence_rows(t, -40.0)[0] for t in takes]
        bad_takes = [k + 1 for k, r in enumerate(silent) if r.status != "pass"]
        rows.append(row(self.name, "silent after each take", f"{len(takes)} takes", "all" if not bad_takes
                        else f"not take {bad_takes}", "", not bad_takes))
        self.failed = fails
        return rows

    def save_failures(self, takes, logs, rows, out_dir):
        from .audio import write_wav
        names = []
        for tr in getattr(self, "failed", []):
            take, log = takes[tr["take"]], logs[tr["take"]]
            t0 = take.time(f"t{tr['i']}_mcm") - 0.2
            t1 = take.time(f"t{tr['i']}_off") + 0.3
            a, b = int(t0 * take.sr), int(t1 * take.sr)
            name = f"{self.name}-t{tr['i']}-{tr['delay']}"
            write_wav(out_dir / f"{name}.wav", take.audio[max(0, a):b], take.sr)
            pref = f"t{tr['i']}_"
            (out_dir / f"{name}.midi.txt").write_text(
                f"# trial {tr['i']}: delay {tr['delay']}, {tr['zone']} {tr['members']}, chord {tr['chord']}, "
                f"missing {tr['missing']}, extra {tr['extra']}; times re the clip start\n" +
                "".join(f"{s - t0:8.4f} {e.data.hex(' ').upper():<9} {e.label}\n"
                        for e, s in log if e.data and e.label.startswith(pref)))
            names.append(name)
        bad_takes = [r for r in rows if r.item == "silent after each take" and r.status == "fail"]
        if bad_takes:
            names += super().save_failures(takes, logs, rows, out_dir)
        return names


def stage3(b1_trials=60):
    return [MasterChannel(), MonoLegato(), B1ZoneChange(b1_trials), MultiM1(), GlobalMasterMulti()]


def all_checks(b1_trials=60):
    from .checks import stage2
    from .checks4 import stage4
    return {c.name: c for c in stage2() + stage3(b1_trials) + stage4()}
