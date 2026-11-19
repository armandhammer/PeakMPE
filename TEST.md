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

## Series W: patch dump on patch change (image `MPEU Ver`)

New image v0.30 (boot screen `MPEU Ver 108.469`). Series A to V are done
(results in [docs/hardware-log.md](docs/hardware-log.md)).

What v0.30 adds: Settings > `PATCH DUMP` > `Send`. With `USB`, each patch
the Peak loads by program change or by its patch buttons goes out over USB
in the editor's format. Off by default.

### W1. Boot and the setting

1. Switch the Peak on. Expected boot screen: `MPEU Ver 108.469`, then the
   patch screen as usual.
2. Press **Settings**, then **Page right** until the top line reads
   `PATCH DUMP` (the page after `RANDOMISE`). Expected: the **Select 1**
   line reads `Send` with `Off`.
3. Press **Select 1** and turn the value encoder one step right. Expected:
   `Send` reads `USB`. Turn it further right: it stays at `USB`.
4. Press **Settings** to leave. Don't save: `Send` stays `USB` until the
   Peak is switched off.

### W2. Rig with Send = USB (I play)

Say **GO rig**. I run, in order:
- `tools/editor_check.py --pdump`: selects D002 by program change and
  listens. Expected: 1 patch dump, equal to D002 as stored.
- the regression run, `hwrig run --stage all`. Expected: 136 pass, 0 fail,
  5 info.
- `tools/editor_check.py` against the baseline. Expected: only the
  `settings` answer changed (the new `Send` byte), plus the current patch.

### W3. Send = Off (I play)

1. Press **Settings**, go to `PATCH DUMP` as in W1, press **Select 1** and
   turn the value encoder one step left. Expected: `Send` reads `Off`.
   Press **Settings** to leave.
2. Say **GO pdump**. I run `tools/editor_check.py --pdump` once more.
   Expected: 0 patch dumps.
