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

## Series AI: the filter steps seen in J2 (no new image)

The synth stays on v0.40 (boot screen `MPEe Ver 108.469`). Series A to AH
are done (results in [docs/hardware-log.md](docs/hardware-log.md)).

What this checks: in J2, after the filter Frequency came down from 255 to 40
under a held note, the level fell in steps over about 1.4 s instead of at
once. This series asks whether that happens with the filter set directly.

### AI1. Rig (I play)

1. Leave the Peak as it is after AH (D002 selected; nothing to set).
2. Say **GO rig**. I run `work/filter_step_check.py` (about 20 s). It builds
   a saw in the edit buffer (nothing saved), holds note 48 and moves the
   filter Frequency four times: 255 to 40, 255 to 100, 40 to 255, 100 to 40.
   Expected if nothing is wrong: each move settles within about 0.1 s, with
   no drops of 3 dB or more after that.

Done 2026-11-23: the filter set directly closes cleanly (no slow fall).

### AI2. The morph (your hands, then I play)

1. Turn the **Patch select** knob to **D001**, then back to **D002** (this
   discards my AI1 edits).
2. Press **Settings**, then **Page right** until the top line reads
   `MORPH          12/43`. Expected Select 1 line: `Morph      Off`.
3. Press **Select 1** and turn the value encoder one click clockwise.
   Expected Select 1 line: `Morph      ModWheel`.
4. Press **Settings** to leave, back to the patch screen. Don't save.
5. Hands off. Say **GO morph**. I run `work/morph_step_check.py` (about
   20 s): note 48 three times. First dull after a bright start (the filter
   closed directly), then twice: dull, bright (the wheel up), dull again
   (the wheel down).

Done 2026-11-23: through the morph the filter closes cleanly too.

### AI3. Back as before (your hands, after I report AI2)

1. Press **Settings**, then **Page right** or **Page left** until the top
   line reads `MORPH          12/43`. Press **Select 1** and turn the value
   encoder one click anticlockwise. Expected Select 1 line: `Morph      Off`.
2. Press **Settings** to leave. Don't save.
3. Turn the **Patch select** knob to **D001**, then back to **D002**.
