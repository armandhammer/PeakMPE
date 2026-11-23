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

## Series AJ: keep the lowest note (image `MPEf Ver`)

New image v0.41 (boot screen `MPEf Ver 108.469`). Series A to AI are done
(results in [docs/hardware-log.md](docs/hardware-log.md)).

What v0.41 adds: Settings > `VOICE STEAL` > `Keep Low`. With it `On`, when
voices run out a new note never takes the lowest note that sounds (a key
held down or a note a pedal holds). `Off` (the default) plays as v0.40.

### AJ1. Boot

1. Switch the Peak on. Expected boot screen: `MPEf Ver 108.469`.
2. Turn the **Patch select** knob to **D002**.

### AJ2. The new page

1. Press **Settings**, then **Page right** until the top line reads
   `VOICE STEAL    22/44`. Expected Select 1 line: `Keep Low   Off`.
2. Press **Select 1** and turn the value encoder one click clockwise.
   Expected Select 1 line: `Keep Low   On`.
3. Press **Settings** to leave, back to the patch screen. Don't save.

### AJ3. Rig (I play)

Say **GO rig**. I run `work/keep_low_check.py` (about 10 s): builds the
rig's sine in the edit buffer (nothing saved) and plays two takes. Take 1:
eight keys held, 48 the lowest and the first, then a 9th. Expected: it cuts
53, not 48. Take 2: 48 played and held by the sustain pedal (CC 64), seven
more the pedal holds, a 9th. Expected: it cuts 53, not 48.

Done 2026-11-23 (AJ1 to AJ3): both takes cut 53 and kept 48.

### AJ4. Back to Off (your hands, after I report AJ3)

1. Press **Settings**, then **Page right** or **Page left** until the top
   line reads `VOICE STEAL    22/44`. Press **Select 1** and turn the
   value encoder one click anticlockwise. Expected Select 1 line:
   `Keep Low   Off`.
2. Press **Settings** to leave. Don't save.

### AJ5. Regression (I play)

Say **GO rig**. I run `hwrig run --stage all` (expected 136 pass, 0 fail,
5 info) and `tools/editor_check.py` (expected: nothing changed against
AH2's run, or only the settings dump's byte for Keep Low).
