"""Stage-5 checks: what a LinnStrument sends, played over USB
(docs/hw-test-rig.md#stage-5-checks).

The LinnStrument's two splits are two MPE zones, set by MCM from both
masters (Lower 7 + Upper 7 on a 15-member layout), and its Z axis can be
sent as polyphonic aftertouch on each member channel instead of channel
pressure. These checks play those patterns from the rig, so they run over
USB without the LinnStrument or a DIN interface:

- `two_zones_bend`: MCM Lower 7 + Upper 7; two notes in each zone. A member
  bend moves only its note; a master bend (±2) moves only its own zone's
  notes. Changes the layout, so the run restores the configured zone after.
- `poly_pressure_right_note`, `poly_pressure_level_right_note`: as stage 2's
  pressure checks, with poly aftertouch on the target note's member channel.

Expected behaviour (docs/mpe-design.md; the Peak patch counts poly pressure
on a member channel as that channel's pressure, emulated in
tests/test_peak_sim.py::test_poly_pressure_on_a_member_channel).
"""
from . import analysis as an
from .checks import (FIND_TOL_C, NOTE_RANGE, PRE_S, SETTLE_S, TAIL_S, WIN_S, Check,
                     PressureLevelRightNote, PressureRightNote, chord_off, chord_on, fmt_c, row)
from .stimulus import Timeline, bend, bend_cents, rpn

MASTER_RANGE = 2  # semitones: the master channels' bend range (MPE default)
STEP_S = SETTLE_S + WIN_S + 0.05


def poly_pressure(ch, note, value):
    return bytes([0xA0 | (ch - 1), note, value])


class TwoZonesBend(Check):
    """Two zones as a LinnStrument split sets them; bends stay in their zone."""
    name = "two_zones_bend"
    recipe = "p1"
    changes_layout = True
    about = "MCM Lower 7 + Upper 7; C4 G4 on Lower members 2-3, E5 A5 on Upper members 15-14; member and master bends"
    NOTES = [("C4 (L2)", 2, 60), ("G4 (L3)", 3, 67), ("E5 (U15)", 15, 76), ("A5 (U14)", 14, 81)]
    LOWER, UPPER = (0, 1), (2, 3)
    # (label, channel, bend value, notes that move, cents each moves)
    STEPS = [
        ("Lower member ch 3 +683", 3, 683, (1,), bend_cents(683, NOTE_RANGE)),
        ("Upper member ch 14 -1365", 14, -1365, (3,), bend_cents(-1365, NOTE_RANGE)),
        ("Lower master ch 1 +4096", 1, 4096, LOWER, bend_cents(4096, MASTER_RANGE)),
        ("Upper master ch 16 -4096", 16, -4096, UPPER, bend_cents(-4096, MASTER_RANGE)),
    ]

    def timeline(self, cfg):
        tl = Timeline()
        t = 0.05
        for m in rpn(16, 0, 6, 0) + rpn(1, 0, 6, 7) + rpn(16, 0, 6, 7):   # MCM: Lower 7, Upper 7
            tl.at(t, m, "mcm")
        t += 0.05
        for ch, v in ((2, NOTE_RANGE), (15, NOTE_RANGE), (1, MASTER_RANGE), (16, MASTER_RANGE)):
            for m in rpn(ch, 0, 0, v):
                tl.at(t, m, "ranges")
        t = max(t + 0.05, PRE_S)
        tl.mark(t, "pre")
        chord_on(tl, t, [(ch, n) for _, ch, n in self.NOTES])
        tl.mark(t + SETTLE_S, "base")
        t += STEP_S
        for i, (_, ch, v, _, _) in enumerate(self.STEPS):
            tl.at(t, bend(ch, v), f"step{i}")
            t += STEP_S
            tl.at(t, bend(ch, 0), f"back{i}")
            t += STEP_S
        chord_off(tl, t, [(ch, n) for _, ch, n in self.NOTES])
        tl.duration = t + TAIL_S + 0.1
        return tl

    def analyze(self, take, cfg):
        rows = []
        exp = [an.note_hz(n) for _, _, n in self.NOTES]
        t = take.time("base")
        base = self.partials(take, t, t + WIN_S, exp)
        rows.append(row(self.name, "both zones sound", "4 notes", f"{sum(p is not None for p in base)} found",
                        f"±{FIND_TOL_C:.0f} c", all(p is not None for p in base)))
        if not all(base):
            return rows + self.silence_rows(take, max((p.db for p in base if p), default=-60.0))
        for i, (label, _, _, movers, want_c) in enumerate(self.STEPS):
            for mark, moving in ((f"step{i}", True), (f"back{i}", False)):
                t = take.time(mark) + SETTLE_S
                hz = [b.hz * (2 ** (want_c / 1200.0) if (moving and k in movers) else 1.0)
                      for k, b in enumerate(base)]
                got = self.partials(take, t, t + WIN_S, hz)
                for k, (b, p) in enumerate(zip(base, got)):
                    m = None if p is None else float(an.cents(p.hz, b.hz))
                    name = self.NOTES[k][0]
                    if moving and k in movers:
                        ok = m is not None and abs(m - want_c) <= 1.0
                        rows.append(row(self.name, f"{label}: {name}", fmt_c(want_c), fmt_c(m), "±1 c", ok))
                    elif moving:
                        ok = m is not None and abs(m) <= 0.5
                        rows.append(row(self.name, f"{label}: {name} unchanged", fmt_c(0.0), fmt_c(m), "±0.5 c", ok))
                    elif k in movers:
                        ok = m is not None and abs(m) <= 1.0
                        rows.append(row(self.name, f"{label}, back: {name}", fmt_c(0.0), fmt_c(m), "±1 c", ok))
        return rows + self.silence_rows(take, max(b.db for b in base))


class PolyPressureRightNote(PressureRightNote):
    name = "poly_pressure_right_note"
    about = "poly aftertouch (LinnStrument Z) on a member -> pitch, on one note of G3 E4 C5"

    def send(self, ch, value):
        return poly_pressure(ch, self.CHORD[self.TARGET][1], value)


class PolyPressureLevelRightNote(PressureLevelRightNote):
    name = "poly_pressure_level_right_note"
    about = "poly aftertouch (LinnStrument Z) on a member -> level, on one note of G3 E4 C5"

    def send(self, ch, value):
        return poly_pressure(ch, self.CHORD[self.TARGET][1], value)


def stage5():
    return [TwoZonesBend(), PolyPressureRightNote(), PolyPressureLevelRightNote()]
