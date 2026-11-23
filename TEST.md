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

## Series AE: patch timing after power-up, patch dump (image `MPEb Ver`)

New image v0.37 (boot screen `MPEb Ver 108.469`). Series A to AD are done
(results in [docs/hardware-log.md](docs/hardware-log.md)).

What v0.37 fixes: after the Peak is switched on, a DAW's Continue without
a song position no longer makes PATCH TIMING guess the bar (changes load
at once until a Start or a song position comes); and a patch dump is no
longer lost when an editor asks for something at the same moment.

### AE1. Boot and the settings

1. Switch the Peak on. Expected boot screen: `MPEb Ver 108.469`.
2. Press **Settings**, then **Page right** until the top line reads
   `PATCH DUMP`. Press **Select 1** and turn the value encoder until `Send`
   reads `USB`.
3. Press **Page right** once (`PATCH TIMING`). Press **Select 1** and turn
   the value encoder until `Change at` reads `Bar`. Press **Settings** to
   leave. Don't save.
4. Don't play anything or start a DAW before AE2: the first check needs no
   Start since power-up.

### AE2. Rig (I play)

Say **GO rig**. I run, in order:
- `work/powerup_check.py` (about 12 s): a Continue with no song position,
  clock at 60 BPM, D001 asked after clock 10. Expected: D001 loads at once.
  Then song position 0, Continue, D002 asked after clock 10. Expected:
  D002 loads on clock 96. Then six program changes, each sent together
  with an identity request. Expected each time: one patch dump and one
  identity reply. It ends on D002.
- the regression run, `hwrig run --stage all`. Expected: 136 pass, 0 fail,
  5 info.
- `tools/editor_check.py`. Expected: only `settings` changed.

### AE3. Back to stock behaviour

1. Press **Settings**, then **Page right** until the top line reads
   `PATCH DUMP`. Press **Select 1** and turn the value encoder until `Send`
   reads `Off`.
2. Press **Page right** once (`PATCH TIMING`). Press **Select 1** and turn
   the value encoder until `Change at` reads `Now`. Press **Settings** to
   leave.
