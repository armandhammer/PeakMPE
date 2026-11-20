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

## Series Y: review fixes (image `MPEW Ver`)

New image v0.32 (boot screen `MPEW Ver 108.469`). Series A to X are done
(results in [docs/hardware-log.md](docs/hardware-log.md)).

What v0.32 fixes (from a review of v0.28 to v0.31): a program change that
arrives right on a bar line loads at once instead of a bar later, Continue
without a song position counts on correctly, and smaller things nobody
would hear.

### Y1. Boot and the settings

1. Switch the Peak on. Expected boot screen: `MPEW Ver 108.469`.
2. Press **Settings**, then **Page right** until the top line reads
   `PATCH DUMP`. Press **Select 1** and turn the value encoder until `Send`
   reads `USB`.
3. Press **Page right** once (`PATCH TIMING`). Press **Select 1** and turn
   the value encoder until `Change at` reads `Bar`. Press **Settings** to
   leave. Don't save.

### Y2. Rig (I play)

Say **GO rig**. I run, in order:
- `work/ptime_check.py`: Start, 310 clock bytes at 120 BPM (about 6.5 s);
  program changes after clocks 10 (D001), 150 (D002) and 288 (D001, just
  after bar 4's line), then Stop. Expected: loads on clocks 96, 192 and
  288 (the last at once).
- the regression run, `hwrig run --stage all`. Expected: 136 pass, 0 fail,
  5 info.
- `tools/editor_check.py`. Expected: only `settings` changed.

### Y3. Back to stock behaviour

1. Settings > `PATCH TIMING`: `Change at` back to `Now`. Settings >
   `PATCH DUMP`: `Send` back to `Off`. Press **Settings** to leave.
