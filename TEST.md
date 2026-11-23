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

## Series AG: voice stealing in a slow attack (image `MPEd Ver`)

New image v0.39 (boot screen `MPEd Ver 108.469`). Series A to AF are done
(results in [docs/hardware-log.md](docs/hardware-log.md)).

What v0.39 changes: when all eight voices are still in their attack (a slow
pad), a new note takes the oldest note. Stock cut the note played just
before it.

### AG1. Boot

1. Switch the Peak on. Expected boot screen: `MPEd Ver 108.469`.
2. Turn the **Patch select** knob to **D002**.

### AG2. Rig (I play)

Say **GO rig**. I run, in order:
- `work/attack_steal_check.py` (about 10 s): builds the rig's sine in the
  edit buffer with Amp Attack 110, plays eight notes, then a 9th and a 10th
  while all are still rising. Expected: the 9th and 10th cut the first two
  notes (48 and 53); stock cut the 8th and then the 9th.
- the regression run, `hwrig run --stage all`. Expected: 136 pass, 0 fail,
  5 info.
- `tools/editor_check.py`. Expected: nothing changed against AF2's run.
