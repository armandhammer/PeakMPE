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

## Series S: randomiser band-pass (image `MPER Ver`)

New image v0.27 (boot screen `MPER Ver 108.469`). Series A to R are done
(results in [docs/hardware-log.md](docs/hardware-log.md)).

What v0.27 changes: only the `RANDOMISE` page's filter rolls. On v0.26 a
roll that picked band-pass came out about 12 dB quieter than the rest
(measured on the rig). Now band-pass and high-pass keep the cutoff where
the note comes through, and band-pass brings some resonance.

**The whole series uses D002.** Nothing is saved, so D002 stays as it is
stored.

### S1. Boot

1. Switch the Peak on. Expected boot screen: `MPER Ver 108.469`, then the
   patch screen as usual.

### S2. Filter rolls, by ear (LinnStrument)

1. Select patch **D002**. Press **Settings** and press **Page ►** until
   the top line reads `RANDOMISE      16/38`.
2. Press **Select 1** and turn the **Value** knob until the Select 1 line
   reads `Section    Filter`. Press **Select 2** and turn until
   `Amount     100%`.
3. Press **Select 3** and turn the **Value** knob **one click clockwise**
   (expected: `RANDOMISE`, `Filter`, a number and `controls changed`,
   `Undo: Mod+Page left`, then `Roll       Off`). Play and hold a note,
   then let go.
4. Repeat step 3 nine more times (ten rolls in all). **Tell me how many
   of the ten were clearly quieter than the others, and whether any was
   silent or clipped.**
5. Select patch **D001**, then **D002** (back to the stored test patch).

### S3. Rig (I play)

Say **GO rig**. I run two things:

- the regression run, `hwrig run --stage all`. Expected: 136 pass,
  0 fail, 5 info (the stress test's silence row can fail by its level
  rule alone; I re-run it if so).
- then `work/rand_check.py` (about 12 minutes), with the new rules: 150
  rolls with the rules and 50 free rolls. Expected: none silent or
  clipped, and band-pass rolls now within about 6 dB of low-pass (12 dB
  under on v0.26).
