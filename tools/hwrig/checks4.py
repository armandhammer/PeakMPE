"""Stage-4 checks (docs/hw-test-rig.md, "Stage 4"): MPE v1.1's channel
reuse (F1).

The voices of the Summit are digital and play the same note identically,
except for the patch's **Diverge**: `osc_pitch` adds Diverge x a fixed s8
per voice and oscillator >> 5, in 8.8 semitones. The table is at
0x200007CC (.data, initialised from flash; for Osc 1, voices 0-7 and again
8-15: +1 -8 +4 -2 +6 -6 +9 -11; observed in the image, unchanged at run
time in the simulator). At Diverge 127 that's -17 to +14 cents, at least
2.7 cents between any two of the eight values (emulated in
tests/test_hwrig_run4.py). So the pitch of a note, re its nominal pitch,
says which voice (modulo 8) plays it, to the rig's hundredths of a cent.

Expected (docs/mpe-design.md, "Channel reuse, v1.1"): a note on a member channel
whose voice has finished its release goes to the stock allocator, which
rotates: two notes in a row never take the same voice. A note while the
channel's voice still releases takes that voice over.
"""
from . import analysis as an
from . import checks
from .checks import Check, fmt_c, row
from .stimulus import Timeline, note_off, note_on

FIND_C = 40.0         # Diverge moves a note by up to 17 c
SAME_C = 0.5          # two notes on one voice: the same deviation
OTHER_C = 1.0         # two voices: at least 2.7 c apart at Diverge 127
QUIET_DB = 50.0       # the release has ended: nothing within this of the note before the next note-on


class VoiceRotation(Check):
    """P7 (P1 with Diverge 127 and a release): a chord shows the voices'
    spread; one channel then plays the same note again and again, each
    after the previous release has ended (each a new voice), and then with
    a few ms between note-off and note-on (each the same voice)."""
    name = "voice_rotation"
    recipe = "p7"
    about = ("P7 (Diverge 127): a 4-note chord, then A4 6x on member 2 after the release, "
             "then A4/C5 4x on member 3 during the release")
    CHORD = [(2, 57), (3, 69), (4, 81), (5, 64)]   # A3 A4 A5 E4: four voices, far apart in pitch
    AFTER_CH, AFTER_NOTE, AFTER_N = 2, 69, 6
    DURING_CH, DURING_NOTES = 3, [69, 72, 69, 72]
    AFTER_GAP_S = 2.0     # note-off to the next note-on: the release ends (Init release 40; P7 64)
    DURING_GAP_S = 0.005  # note-off to the next note-on: still releasing
    # The tail checked for a note left on: after P7's release, which takes
    # about 0.9 s to the floor on the synth (observed, 2026-11-08: -50 dBFS
    # 0.08 s after the note-off, -83 at 0.58, -100 at 0.88), so the shared
    # 0.5-1.0 s window still held it. From 1.5 s, as long as AFTER_GAP_S
    # (whose "silent before each note-on" row shows the release is over).
    TAIL_FROM_S = 1.5
    TAIL_S = AFTER_GAP_S

    def hold_s(self):
        return checks.SETTLE_S + checks.WIN_S + 0.05

    def timeline(self, cfg):
        tl = Timeline()
        tl.mark(checks.PRE_S, "pre")
        t = checks.PRE_S
        for ch, n in self.CHORD:
            tl.at(t, note_on(ch, n), f"chord_on{ch}")
        tl.mark(t + checks.SETTLE_S, "chord")
        t += self.hold_s()
        for ch, n in self.CHORD:
            tl.at(t, note_off(ch, n), f"chord_off{ch}")
        t += self.AFTER_GAP_S
        for i in range(self.AFTER_N):
            tl.at(t, note_on(self.AFTER_CH, self.AFTER_NOTE), f"after{i}")
            t += self.hold_s()
            tl.at(t, note_off(self.AFTER_CH, self.AFTER_NOTE), f"after_off{i}")
            t += self.AFTER_GAP_S
        for i, n in enumerate(self.DURING_NOTES):
            tl.at(t, note_on(self.DURING_CH, n), f"during{i}")
            t += self.hold_s()
            tl.at(t, note_off(self.DURING_CH, n), f"during_off{i}")
            t += self.DURING_GAP_S
        tl.mark(t, "last_off")
        tl.duration = t + self.TAIL_S + 0.1
        return tl

    def deviation(self, take, mark, note):
        t = take.time(mark) + checks.SETTLE_S
        seg = take.window(t, t + checks.WIN_S)
        found = an.peaks(seg, take.sr, fmin=20.0, fmax=16000.0, rel_db=-30.0)
        p = an.match_voices(found, [an.note_hz(note)], FIND_C)[0]
        return (None, found) if p is None else (float(an.cents(p.hz, an.note_hz(note))), found)

    def quiet_before(self, take, mark, note, ref_db):
        """Level of the note's partial just before a note-on, re the note: the
        previous note's release has ended (the Summit's -66 dB leak may stay)."""
        t = take.time(mark)
        seg = take.window(t - 0.12, t - 0.02)
        found = an.peaks(seg, take.sr, fmin=20.0, fmax=16000.0, rel_db=-90.0, prominence_db=10.0)
        p = an.match_voices(found, [an.note_hz(note)], FIND_C)[0]
        return -120.0 if p is None else p.db - ref_db

    def analyze(self, take, cfg):
        rows = []
        chord = []
        for ch, n in self.CHORD:
            t = take.time("chord")
            seg = take.window(t, t + checks.WIN_S)
            found = an.peaks(seg, take.sr, fmin=20.0, fmax=16000.0, rel_db=-30.0)
            p = an.match_voices(found, [an.note_hz(n)], FIND_C)[0]
            chord.append(None if p is None else float(an.cents(p.hz, an.note_hz(n))))
        ok_chord = all(c is not None for c in chord)
        spread = ok_chord and min(abs(a - b) for i, a in enumerate(chord) for b in chord[i + 1:]) >= OTHER_C
        rows.append(row(self.name, "chord: four voices, Diverge spreads them", f"4 notes, each ≥ {OTHER_C:g} c apart",
                        ", ".join(fmt_c(c) for c in chord), f"±{FIND_C:.0f} c to find", spread,
                        "" if spread else "no spread: is Diverge 127 set (NRPN 0:9)? Then the rows below can't "
                        "tell voices apart"))
        ref_db = None
        after = []
        for i in range(self.AFTER_N):
            d, found = self.deviation(take, f"after{i}", self.AFTER_NOTE)
            after.append(d)
            if found and ref_db is None:
                ref_db = max(p.db for p in found)
        ok_found = all(d is not None for d in after)
        rows.append(row(self.name, f"after the release: {self.AFTER_N} x {an.note_name(self.AFTER_NOTE)} "
                        f"on ch {self.AFTER_CH}", f"{self.AFTER_N} notes", ", ".join(fmt_c(d) for d in after),
                        f"±{FIND_C:.0f} c", ok_found))
        if ref_db is not None:
            q = [self.quiet_before(take, f"after{i}", self.AFTER_NOTE, ref_db) for i in range(1, self.AFTER_N)]
            rows.append(row(self.name, "after the release: silent before each note-on",
                            f"nothing within {QUIET_DB:.0f} dB", ", ".join(f"{x:+.0f} dB" for x in q),
                            "", max(q) <= -QUIET_DB,
                            "" if max(q) <= -QUIET_DB else "the release hadn't ended: lengthen AFTER_GAP_S"))
        if ok_found:
            pairs = list(zip(after, after[1:]))
            same = [k for k, (a, b) in enumerate(pairs) if abs(a - b) < OTHER_C]
            rows.append(row(self.name, "after the release: each note on another voice than the one before",
                            f"{len(pairs)} pairs ≥ {OTHER_C:g} c apart", f"{len(pairs) - len(same)} of {len(pairs)}",
                            "", not same, "" if not same else
                            f"same voice for notes {[k + 1 for k in same]} and the next (v1: the same voice "
                            "every time, L5)"))
            distinct = 1 + sum(all(abs(a - b) >= SAME_C for b in after[:k]) for k, a in enumerate(after) if k)
            rows.append(row(self.name, "after the release: voices used", "several (stock rotation)",
                            f"{distinct} distinct", "", True, info=True))
        during = []
        for i, n in enumerate(self.DURING_NOTES):
            d, _ = self.deviation(take, f"during{i}", n)
            during.append(d)
        ok_during = all(d is not None for d in during)
        same_voice = ok_during and max(during) - min(during) <= SAME_C
        rows.append(row(self.name, f"during the release: {len(during)} notes on ch {self.DURING_CH}, "
                        f"{self.DURING_GAP_S * 1000:.0f} ms after each note-off",
                        f"one voice: the same deviation (±{SAME_C:g} c)", ", ".join(fmt_c(d) for d in during),
                        "", same_voice, "" if same_voice else "another voice: the release was not taken over"))
        return rows + self.silence_rows(take, ref_db if ref_db is not None else -60.0, after_s=self.TAIL_FROM_S,
                                        until_s=self.TAIL_S)


def stage4():
    return [VoiceRotation()]
