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

## Series X: patch change timed to the clock (image `MPEV Ver`)

New image v0.31 (boot screen `MPEV Ver 108.469`). Series A to W are done
(results in [docs/hardware-log.md](docs/hardware-log.md)).

What v0.31 adds: Settings > `PATCH TIMING` > `Change at`. While a DAW's MIDI
clock plays, a patch change waits for the next beat or bar line. The rig
plays the DAW: it sends the clock and the program changes, and the patch
dump (Settings > `PATCH DUMP`) tells it when each patch loaded.

### X1. Boot and the settings

1. Switch the Peak on. Expected boot screen: `MPEV Ver 108.469`.
2. Press **Settings**, then **Page right** until the top line reads
   `PATCH DUMP`. Press **Select 1** and turn the value encoder until `Send`
   reads `USB`.
3. Press **Page right** once. Expected: the top line reads `PATCH TIMING`,
   the **Select 1** line `Change at` with `Now`.
4. Press **Select 1** and turn the value encoder two steps right. Expected:
   `Beat`, then `Bar`. Leave it at `Bar`. Press **Settings** to leave.
   Don't save.

### X2. Rig (I play)

Say **GO rig**. I run, in order:
- `work/ptime_check.py`: Start, 230 clock bytes at 120 BPM (about 5 s), a
  program change for D001 at position 10 and one for D002 at position 150,
  then Stop. Expected: D001 loads on clock 96 and D002 on clock 192. The
  screen shows `PATCH TIMING` with the waiting patch for a moment each time.
- the regression run, `hwrig run --stage all`. Expected: 136 pass, 0 fail,
  5 info.
- `tools/editor_check.py`. Expected: only `settings` changed.

### X3. Back to stock behaviour

1. Settings > `PATCH TIMING`: turn `Change at` back to `Now`. Settings >
   `PATCH DUMP`: turn `Send` back to `Off`. Press **Settings** to leave.
   Nothing is saved, so switching off would also reset them.
