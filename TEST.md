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

## Series AH: which held note is stolen (image `MPEe Ver`)

New image v0.40 (boot screen `MPEe Ver 108.469`). Series A to AG are done
(results in [docs/hardware-log.md](docs/hardware-log.md)).

What v0.40 changes: when every voice is held and equally loud, a new note
takes a note the sustain or sostenuto pedal is holding (key let go) before a
key you are still holding down, and otherwise the oldest note. Stock took
them in rotation order.

### AH1. Boot

1. Switch the Peak on. Expected boot screen: `MPEe Ver 108.469`.
2. Turn the **Patch select** knob to **D002**.

### AH2. Rig (I play)

Say **GO rig**. I run, in order:
- `work/held_steal_check.py` (about 15 s): builds the rig's sine in the edit
  buffer and plays two takes. Take 1: eight notes held, the third let go, a
  9th and a 10th. Expected: the 10th cuts 48, the oldest (stock: 63). Take
  2: 48 and 53 held down, the sustain pedal (CC 64) holding six more, a 9th.
  Expected: it cuts 58, the oldest note the pedal holds (stock: 48).
- the regression run, `hwrig run --stage all`. Expected: 136 pass, 0 fail,
  5 info.
- `tools/editor_check.py`. Expected: nothing changed against AG2's run.
