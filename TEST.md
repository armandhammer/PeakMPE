# TEST.md: hands-on tests for you

Tests only you can do (they need the panel or your eyes). Each series has its
own letter. Report the result of each step ("F2.3: ok", "F2.3: showed X").
Once I'm satisfied with a series I delete it from this file and the next series
uses the next letter, so a test label never means two things.

Every step names the control, the value and the text you should see. If the
screen differs, report the exact text. Report only deviations, plus the
readings a step asks for. The three buttons beside the screen are **Select
1**, **Select 2** and **Select 3**, top to bottom; a screen line is named
by its button ("the Select 1 line") or as "the top line".

Setup for all series: **quit Ableton and any other MIDI app.**

---

## Series R: section randomiser (image `MPEQ Ver`)

New image v0.26 (boot screen `MPEQ Ver 108.469`). Series A to Q are done
(results in [docs/hardware-log.md](docs/hardware-log.md)).

What v0.26 adds: a new Settings page, `RANDOMISE`, with `Section`,
`Amount` and `Roll`. Turning `Roll` up rolls new values for the chosen
section of the sound in the edit buffer. Nothing is saved; **Mod** +
**Page ◄** takes the roll back. Also fixed: PARAM LOCK's `Lock FX` now
keeps the chorus Mode (Chorus/Flanger/Phlanger); before, `Lock Arp` kept it.

**The whole series uses D002** (the test patch: the Init sound with `MPE`
On). Nothing is saved, so D002 stays as it is stored.

### R1. Boot

1. Switch the Peak on. Expected boot screen: `MPEQ Ver 108.469`, then the
   patch screen as usual.

### R2. The Settings page

1. Select patch **D002**.
2. Press **Settings** and press **Page ►** until the top line reads
   `RANDOMISE      16/38` (one page after `RELEASE VEL    15/38`).
   Expected:
   - Select 1 line: `Section    Osc 1`
   - Select 2 line: `Amount      50%`
   - Select 3 line: `Roll       Off`
3. Press **Page ►** once. Expected top line `MIDI ENABLE    17/38`. Press
   **Page ◄** once to come back to `RANDOMISE      16/38`.
4. Press **Select 1** and turn the **Value** knob clockwise one click at a
   time. **Tell me if the Select 1 line differs from this order:** `Osc 1`,
   `Osc 2`, `Osc 3`, `Mixer`, `Filter`, `Amp Env`, `Mod Env1`, `Mod Env2`,
   `LFO 1`, `LFO 2`, `FX`, `All`. Further clicks stay on `All`.
5. Press **Select 2** and turn the **Value** knob clockwise until the line
   reads `Amount     100%`, then anticlockwise until it reads
   `Amount      10%` (the lowest; further clicks stay there).

### R3. A roll, by ear (LinnStrument)

1. Press **Select 1** and turn the **Value** knob until the Select 1 line
   reads `Section    Filter`. Press **Select 2** and turn until
   `Amount     100%`.
2. Play and hold a note on the LinnStrument. Keep the Init sound in your
   ear, then let go.
3. Press **Select 3** and turn the **Value** knob **one click clockwise**.
   Expected screen for about 3 s:
   - top line `RANDOMISE`
   - next line `Filter`
   - next line a number and `controls changed`, for example
     `9 controls changed`
   - bottom line `Undo: Mod+Page left`

   Then the page comes back with `Roll       Off`.
4. Play the note again. Expected: the tone has changed (brighter, darker,
   resonant or thinner), and it still sounds. **Tell me if it is silent or
   painfully loud.**
5. Repeat step 3 and step 4 five more times. **Tell me how many of the six
   rolls sounded silent, harsh or clipped, if any.**
6. Hold **Mod** and press **Page ◄**. Expected screen: `UNDO`,
   `Back one change`. Play the note: it sounds as it did before the last
   roll.

### R4. All sections, by ear

1. Press **Select 1** and turn the **Value** knob to `Section    All`.
   Leave `Amount     100%`.
2. Press **Select 3** and turn the **Value** knob one click clockwise. Play
   a few notes, slowly and fast. Do it ten times in all.
3. **Tell me how many of the ten sounded silent, clipped or unbearable,
   and anything that came up more than once** (for example "always a
   long fade in", "often detuned").
4. Turn `Amount` down to `Amount      20%` (Select 2), then roll `All` five
   times from the patch you have. Expected: each roll is a small variation
   of the sound before it, not a new sound. **Tell me if it isn't.**
5. Select patch **D001**, then **D002** (back to the stored test patch).

### R5. Rig (I play)

Say **GO rig**. I run two things:

- the regression run, `hwrig run --stage all`. Expected: 136 pass,
  0 fail, 5 info, as on v0.25.
- then `work/rand_check.py` (about 12 minutes): the rig can't press Roll,
  so it runs a copy of the same rules on the computer, sends each rolled
  sound into the edit buffer over MIDI (not saved), plays a note and
  measures it. 150 rolls with the rules and, mixed in, 50 rolls with the
  same controls set at random and no rules. Expected: no roll with the
  rules silent or clipped, and the free rolls clearly worse.
