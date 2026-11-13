"""Stage-2 checks (docs/hw-test-rig.md#checks): stimulus and analysis.

Each check has a recipe (the sound `setup` builds first), a timeline of
MIDI with named marks, and an analysis that turns the recorded take into
report rows. The analysis measures relative to a baseline from the same
take (the same voice before the change), so the interface's clock offset
(+0.13 c on the user's rig) and the Summit's tuning cancel out.

Layout assumed: an MPE patch on the Lower Zone, master channel 1, members
from 2 (the Summit's fallback with Zone Off, or Lower 15). The run sets the
bend ranges itself (RPN 0: notes ±48, master ±2) before the first check.
"""
from dataclasses import dataclass, field
import random

from . import analysis as an
from .stimulus import Timeline, bend, bend_cents, cc, note_off, note_on, pressure

MASTER = 1
NOTE_RANGE = 48
PRE_S = 0.5          # pre-roll: the noise and spectrum reference for silence
SETTLE_S = 0.35      # after a change, before measuring (bend smoothing, 0x61 smoothing)
WIN_S = 0.3          # measuring window
TAIL_S = 1.0         # after the last note-off
STUCK_REL_DB = 40.0  # a partial within this of the loudest note after the last note-off = stuck
FIND_TOL_C = 60.0    # how far from the expected pitch a partial may be to count as that note


@dataclass
class Row:
    check: str
    item: str
    expected: str
    measured: str
    tol: str
    status: str      # "pass", "fail" or "info" (exploratory, never fails the run)
    note: str = ""


def row(check, item, expected, measured, tol, ok, note="", info=False):
    status = "info" if info else ("pass" if ok else "fail")
    return Row(check, item, expected, measured, tol, status, note)


def fmt_c(v):
    return "-" if v is None else f"{v:+.2f} c"


class Check:
    name = ""
    recipe = "p1"
    about = ""

    changes_layout = False  # True: the run restores Single mode and the zone after it

    def timeline(self, cfg):
        raise NotImplementedError

    def analyze(self, take, cfg):
        raise NotImplementedError

    def timelines(self, cfg):
        """The takes this check records (most checks: one)."""
        return [self.timeline(cfg)]

    def analyze_takes(self, takes, cfg):
        return self.analyze(takes[0], cfg)

    def save_failures(self, takes, logs, rows, out_dir):
        """Write the takes of a failing check (WAV + sent MIDI); returns the names."""
        from .audio import write_wav
        names = []
        for k, (take, log) in enumerate(zip(takes, logs)):
            name = self.name if len(takes) == 1 else f"{self.name}-{k + 1}"
            write_wav(out_dir / f"{name}.wav", take.audio, take.sr)
            (out_dir / f"{name}.midi.txt").write_text(
                "".join(f"{s:8.4f} {e.data.hex(' ').upper():<9} {e.label}\n" for e, s in log if e.data), encoding="utf-8")
            names.append(name)
        return names

    # -- shared analysis ----------------------------------------------------

    @staticmethod
    def partials(take, t0, t1, expect_hz, tol_c=FIND_TOL_C, fmax=16000.0):
        seg = take.window(t0, t1)
        found = an.peaks(seg, take.sr, fmin=20.0, fmax=fmax, rel_db=-40.0)
        return an.match_voices(found, expect_hz, tol_c)

    def silence_rows(self, take, loudest_db, after_s=0.5, until_s=None):
        """The take is silent from *after_s* to *until_s* (default TAIL_S)
        after the last note-off: no note left on. A check whose recipe has a
        long release starts the window after it."""
        pre = take.window(0.0, take.time("pre") - 0.02)
        t_end = take.time("last_off")
        tail = take.window(t_end + after_s, t_end + (TAIL_S if until_s is None else until_s))
        s = an.silence(tail, pre, take.sr, min_db=loudest_db - STUCK_REL_DB)
        tones = ", ".join(f"{p.hz:.1f} Hz {p.db - loudest_db:+.0f} dB" for p in s.tones[:3])
        return [row(self.name, "silent after the last note-off", "no partial within 40 dB of the notes",
                    f"tail {s.rms_db:.1f} dBFS (pre-roll {s.floor_db:.1f})" + (f"; {tones}" if tones else ""),
                    "RMS +6 dB", s.silent)]


def chord_on(tl, t, notes, label_prefix="on"):
    for ch, n in notes:
        tl.at(t, note_on(ch, n), f"{label_prefix}{ch}")


def chord_off(tl, t, notes):
    for ch, n in notes:
        tl.at(t, note_off(ch, n), f"off{ch}")
    tl.mark(t, "last_off")


class BendOneNote(Check):
    """Per-note bend on one note of a held chord; the others must not move."""
    name = "bend_one_note"
    recipe = "p1"
    about = "chord C4 E4 G4 on members 2-4; bend member 3 only"
    CHORD = [(2, 60), (3, 64), (4, 67)]
    TARGET = 1  # index in CHORD
    BENDS = [683, -1365, 2048, 0]  # +400 c, -800 c, +1200 c, back: never onto another chord note

    def timeline(self, cfg):
        tl = Timeline()
        tl.mark(PRE_S, "pre")
        chord_on(tl, PRE_S, self.CHORD)
        t = PRE_S + SETTLE_S + WIN_S + 0.05
        tl.mark(PRE_S + SETTLE_S, "base")
        ch = self.CHORD[self.TARGET][0]
        for i, v in enumerate(self.BENDS):
            tl.at(t, bend(ch, v), f"bend{i}")
            t += SETTLE_S + WIN_S + 0.05
        chord_off(tl, t, self.CHORD)
        tl.duration = t + TAIL_S + 0.1
        return tl

    def analyze(self, take, cfg):
        rows = []
        exp = [an.note_hz(n) for _, n in self.CHORD]
        t = take.time("base")
        base = self.partials(take, t, t + WIN_S, exp)
        names = [f"{an.note_name(n)} (ch {ch})" for ch, n in self.CHORD]
        rows.append(row(self.name, "chord before bending", "3 notes", f"{sum(p is not None for p in base)} found",
                        f"±{FIND_TOL_C:.0f} c", all(p is not None for p in base)))
        if not all(base):
            return rows + self.silence_rows(take, max((p.db for p in base if p), default=-60.0))
        tgt = self.TARGET
        for i, v in enumerate(self.BENDS):
            want_c = bend_cents(v, NOTE_RANGE)
            t = take.time(f"bend{i}") + SETTLE_S
            hz = [b.hz * (2 ** (want_c / 1200.0) if k == tgt else 1.0) for k, b in enumerate(base)]
            got = self.partials(take, t, t + WIN_S, hz)
            for k, (b, p) in enumerate(zip(base, got)):
                if k == tgt:
                    m = None if p is None else float(an.cents(p.hz, b.hz))
                    ok = m is not None and abs(m - want_c) <= 1.0
                    rows.append(row(self.name, f"bend {v:+d}: {names[k]}", fmt_c(want_c), fmt_c(m), "±1 c", ok))
                else:
                    m = None if p is None else float(an.cents(p.hz, b.hz))
                    ok = m is not None and abs(m) <= 0.5
                    rows.append(row(self.name, f"bend {v:+d}: {names[k]} unchanged", fmt_c(0.0), fmt_c(m),
                                    "±0.5 c", ok))
        return rows + self.silence_rows(take, max(b.db for b in base))


class BendRange48(Check):
    """±48 semitones of per-note bend, in steps; exploratory beyond ±24."""
    name = "bend_range_48"
    recipe = "p1"
    about = "C5 on member 2, bend from -8192 to +8191 in 11 steps"
    NOTE, CH = 72, 2
    STEPS = [0, -2048, -4096, -6144, -7168, -8192, 2048, 4096, 6144, 7168, 8191, 0]
    STRICT_C = 2400.0  # within ±24 semitones a miss fails; beyond it is reported (FPGA range, clamp)

    def timeline(self, cfg):
        tl = Timeline()
        tl.mark(PRE_S, "pre")
        tl.at(PRE_S, note_on(self.CH, self.NOTE), "on")
        t = PRE_S + 0.05
        for i, v in enumerate(self.STEPS):
            tl.at(t, bend(self.CH, v), f"step{i}")
            t += SETTLE_S + WIN_S + 0.05
        tl.at(t, note_off(self.CH, self.NOTE), "off")
        tl.mark(t, "last_off")
        tl.duration = t + TAIL_S + 0.1
        return tl

    def measure(self, take, i, expect_hz):
        t = take.time(f"step{i}") + SETTLE_S
        seg = take.window(t, t + WIN_S)
        # the one voice's tone wherever it is: a clamp or a wrap must show as where it went
        return an.fundamental(seg, take.sr, fmin=20.0, fmax=16000.0)

    def analyze(self, take, cfg):
        rows = []
        base = self.measure(take, 0, an.note_hz(self.NOTE))
        rows.append(row(self.name, f"{an.note_name(self.NOTE)} unbent", "a tone", "found" if base else "none",
                        "", base is not None))
        if base is None:
            return rows + self.silence_rows(take, -60.0)
        measured = []
        for i, v in enumerate(self.STEPS[1:], start=1):
            want = bend_cents(v, NOTE_RANGE)
            p = self.measure(take, i, base.hz * 2 ** (want / 1200.0))
            m = None if p is None else float(an.cents(p.hz, base.hz))
            measured.append((v, want, m))
            ok = m is not None and abs(m - want) <= 1.0
            beyond = abs(want) > self.STRICT_C
            note = "" if ok else ("beyond ±24 st: exploratory (FPGA range, the patch's clamp)" if beyond else "")
            rows.append(row(self.name, f"bend {v:+d}", fmt_c(want), fmt_c(m), "±1 c", ok, note,
                            info=beyond and not ok))
        ups = [m for v, _, m in measured if v > 0 and v != 0]
        downs = [m for v, _, m in measured if v < 0]
        # each step at least as far out as the one before: a plateau (a clamp) is
        # reported above, a step back (a wrap) or a missing tone fails
        mono = all(x is not None for x in ups + downs) and \
            all(b >= a - 1.0 for a, b in zip(ups, ups[1:])) and all(b <= a + 1.0 for a, b in zip(downs, downs[1:]))
        rows.append(row(self.name, "monotonic, no jump or wrap", "each step as far out or further",
                        "yes" if mono else "no", "±1 c", mono))
        good = [want for v, want, m in measured if m is not None and abs(m - want) <= 1.0]
        rows.append(row(self.name, "range in tolerance", "-4800 c to +4799 c",
                        f"{min(good):+.0f} c to {max(good):+.0f} c" if good else "none", "±1 c", True,
                        info=True))
        return rows + self.silence_rows(take, base.db)


class ExpressionRightNote(Check):
    """Pressure or Slide on one member of a chord changes that note only.

    First a single note measures the response (so the matrix depth doesn't
    matter), then the chord: the target must move by the same amount, the
    others not at all."""
    kind = "pitch"     # "pitch" (cents) or "level" (dB)
    CHORD = [(2, 55), (3, 64), (4, 72)]  # G3 E4 C5: the target (E4) has 8-9 semitones of room
    TARGET = 1

    def send(self, ch, value):
        raise NotImplementedError

    def timeline(self, cfg):
        tl = Timeline()
        ch, n = self.CHORD[self.TARGET]
        tl.mark(PRE_S, "pre")
        t = PRE_S
        tl.at(t, self.send(ch, 0), "solo0")
        tl.at(t + 0.01, note_on(ch, n), "solo_on")
        t += SETTLE_S + WIN_S + 0.05
        tl.at(t, self.send(ch, 127), "solo127")
        t += SETTLE_S + WIN_S + 0.05
        tl.at(t, self.send(ch, 0), "solo_back")
        tl.at(t + 0.01, note_off(ch, n), "solo_off")
        t += 0.4
        chord_on(tl, t, self.CHORD)
        tl.mark(t + SETTLE_S, "base")
        t += SETTLE_S + WIN_S + 0.05
        tl.at(t, self.send(ch, 127), "chord127")
        t += SETTLE_S + WIN_S + 0.05
        tl.at(t, self.send(ch, 0), "chord_back")
        t += SETTLE_S + WIN_S + 0.05
        chord_off(tl, t, self.CHORD)
        tl.duration = t + TAIL_S + 0.1
        return tl

    def value(self, p, ref):
        return float(an.cents(p.hz, ref.hz)) if self.kind == "pitch" else p.db - ref.db

    def fmt(self, v):
        if v is None:
            return "-"
        return f"{v:+.2f} c" if self.kind == "pitch" else f"{v:+.2f} dB"

    def analyze(self, take, cfg):
        rows = []
        unit_tol = (2.0, 0.5, 1.0) if self.kind == "pitch" else (0.5, 0.2, 0.3)
        ch, n = self.CHORD[self.TARGET]
        hz = an.note_hz(n)
        t0 = take.time("solo0") + SETTLE_S
        t1 = take.time("solo127") + SETTLE_S
        s0 = self.partials(take, t0, t0 + WIN_S, [hz])[0]
        tol_find = FIND_TOL_C if self.kind == "level" else 1300.0
        s1 = self.partials(take, t1, t1 + WIN_S, [hz], tol_c=tol_find)[0] if s0 else None
        if s0 is None or s1 is None:
            rows.append(row(self.name, "single note response", "a tone", "none", "", False))
            return rows + self.silence_rows(take, s0.db if s0 else -60.0)
        if self.kind == "pitch":  # take the partial nearest the expected moved one
            s1 = self.moved(take, t1, s0)
        resp = self.value(s1, s0)
        min_resp = 5.0 if self.kind == "pitch" else 1.0
        rows.append(row(self.name, f"single note {an.note_name(n)}: response to 127", f"|r| ≥ {self.fmt(min_resp)}",
                        self.fmt(resp), "", abs(resp) >= min_resp,
                        "" if abs(resp) >= min_resp else "no effect: check the recipe's matrix slot and routing"))
        exp = [an.note_hz(m) for _, m in self.CHORD]
        tb = take.time("base")
        base = self.partials(take, tb, tb + WIN_S, exp)
        rows.append(row(self.name, "chord", "3 notes", f"{sum(p is not None for p in base)} found", "",
                        all(p is not None for p in base)))
        if not all(base):
            return rows + self.silence_rows(take, max((p.db for p in base if p), default=-60.0))
        names = [f"{an.note_name(m)} (ch {c})" for c, m in self.CHORD]
        moved_hz = [b.hz * (2 ** (resp / 1200.0) if (k == self.TARGET and self.kind == "pitch") else 1.0)
                    for k, b in enumerate(base)]
        collide = any(k != self.TARGET and abs(an.cents(moved_hz[self.TARGET], b.hz)) < FIND_TOL_C
                      for k, b in enumerate(base))
        for label, mark, want_t in (("at 127", "chord127", resp), ("back at 0", "chord_back", 0.0)):
            t = take.time(mark) + SETTLE_S
            target_hz = moved_hz if mark == "chord127" else [b.hz for b in base]
            got = self.partials(take, t, t + WIN_S, target_hz)
            for k, (b, p) in enumerate(zip(base, got)):
                m = None if p is None else self.value(p, b)
                if k == self.TARGET:
                    tol = unit_tol[0] if mark == "chord127" else unit_tol[2]
                    ok = m is not None and abs(m - want_t) <= tol
                    rows.append(row(self.name, f"{label}: {names[k]}", self.fmt(want_t), self.fmt(m),
                                    f"±{self.fmt(tol)[1:]}", ok, info=collide and not ok,
                                    note="moved onto another chord note: inconclusive" if collide and not ok else ""))
                else:
                    ok = m is not None and abs(m) <= unit_tol[1]
                    rows.append(row(self.name, f"{label}: {names[k]} unchanged", self.fmt(0.0), self.fmt(m),
                                    f"±{self.fmt(unit_tol[1])[1:]}", ok))
        return rows + self.silence_rows(take, max(b.db for b in base))

    def moved(self, take, t, ref):
        seg = take.window(t, t + WIN_S)
        found = an.peaks(seg, take.sr, fmin=20.0, fmax=16000.0, rel_db=-20.0)
        return found[0] if found else ref


class PressureRightNote(ExpressionRightNote):
    name = "pressure_right_note"
    recipe = "p2"
    about = "pressure (channel pressure on a member) -> pitch, on one note of G3 E4 C5"

    def send(self, ch, value):
        return pressure(ch, value)


class SlideRightNote(ExpressionRightNote):
    name = "slide_right_note"
    recipe = "p3"
    about = "Slide (CC 74 on a member) -> pitch, on one note of G3 E4 C5"

    def send(self, ch, value):
        return cc(ch, 74, value)


class PressureLevelRightNote(ExpressionRightNote):
    name = "pressure_level_right_note"
    recipe = "p4"
    kind = "level"
    about = "pressure -> level, on one note of G3 E4 C5"

    def send(self, ch, value):
        return pressure(ch, value)


class StuckNotesStress(Check):
    """A dense random MPE stream on all 15 members, then every note off:
    nothing may keep sounding. Rate kept under 60 % of DIN."""
    name = "stuck_notes_stress"
    recipe = "p1"
    about = "3 s of random notes, bends, pressure and Slide on members 2-16, then all off"
    SEED = 2026_11_07
    SECONDS = 3.0
    RATE = 300  # messages per second, 900 B/s: under 60 % of DIN's 3,125 B/s

    def timeline(self, cfg):
        rng = random.Random(self.SEED)
        tl = Timeline()
        tl.mark(PRE_S, "pre")
        held = {}
        n = int(self.SECONDS * self.RATE)
        for i in range(n):
            t = PRE_S + i / self.RATE
            ch = rng.randint(2, 16)
            kind = rng.random()
            if ch in held and kind < 0.3:
                tl.at(t, note_off(ch, held.pop(ch)))
            elif ch not in held and kind < 0.6:
                note = rng.randint(48, 84)
                held[ch] = note
                tl.at(t, note_on(ch, note, rng.randint(30, 127)))
            elif kind < 0.8:
                tl.at(t, bend(ch, rng.randint(-2048, 2047)))
            elif kind < 0.9:
                tl.at(t, pressure(ch, rng.randint(0, 127)))
            else:
                tl.at(t, cc(ch, 74, rng.randint(0, 127)))
        t = PRE_S + self.SECONDS
        tl.mark(t - 0.5, "busy")
        for k, (ch, note) in enumerate(sorted(held.items())):
            tl.at(t + k * 0.002, note_off(ch, note))
        t += 0.05
        for ch in range(2, 17):  # back to neutral for the next check
            tl.at(t, bend(ch, 0))
            tl.at(t, pressure(ch, 0))
            tl.at(t, cc(ch, 74, 0))
            t += 0.003
        tl.mark(t, "last_off")
        tl.duration = t + TAIL_S + 0.1
        return tl

    def analyze(self, take, cfg):
        t = take.time("busy")
        loud = an.rms_db(take.window(t, t + 0.4))
        rows = [row(self.name, "notes sounded during the stream", "sound", f"{loud:.1f} dBFS", "",
                    loud > -80.0)]
        # the loudest single voice is about the stream's level minus a few dB; be strict
        return rows + self.silence_rows(take, loud)


def stage2():
    return [BendOneNote(), BendRange48(), StuckNotesStress(), PressureRightNote(), SlideRightNote(),
            PressureLevelRightNote()]


def by_name():
    return {c.name: c for c in stage2()}
