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

## Series AB: per-input filters (image `MPEY Ver`)

New image v0.34 (boot screen `MPEY Ver 108.469`). Series A to AA are done
(results in [docs/hardware-log.md](docs/hardware-log.md)).

What v0.34 adds: Settings pages `USB IN` and `DIN IN`, each with `Notes`,
`CC` and `Patch` On or Off. Patch timing now counts the clock only from the
input Settings `Source` follows.

AB1 and AB2 passed (2026-11-21). Next: AB3.

### AB1. Boot and the new pages (done)

1. Switch the Peak on. Expected boot screen: `MPEY Ver 108.469`.
2. Turn the **Patch select** knob to **D002**.
3. Press **Settings**, then **Page right** until the top line reads
   `PATCH TIMING`. Press **Page right** once more. Expected:
   - top line `USB IN`
   - second line `Notes` ... `On`
   - third line `CC` ... `On`
   - fourth line `Patch` ... `On`
4. Press **Page right** once more. Expected the same three lines under the
   top line `DIN IN`.
5. Press **Settings** to leave. Don't save.

### AB2. Rig with everything On (stock behaviour) (done)

1. Say **GO rig**. I run the full rig (about 10 minutes) and the editor
   check; nothing to press.

### AB3. Filters set (I play, you set first)

1. Press **Settings**, **Page right** to `PATCH DUMP`. Press **Select 1**
   and turn the value encoder until `Send` reads `USB`.
2. **Page right** twice to `USB IN`. Press **Select 3** and turn the value
   encoder until `Patch` reads `Off`.
3. **Page right** once to `DIN IN`. Press **Select 1** and turn the value
   encoder until `Notes` reads `Off`.
4. Press **Settings** to leave. The patch screen shows D002.
5. Say **GO pfilter**. I play an A3 over DIN (expected: silence), then over
   USB (expected: the note), then send patch changes: D001 over USB
   (expected: nothing changes), D001 over DIN (expected: D001 loads), D002
   over DIN (expected: back to D002). Nothing to press during the run.
6. Tell me the patch screen's second line after the run (expected: D002's
   name, as before).

### AB4. Back to stock behaviour

1. Settings > `DIN IN`: `Notes` back to `On`. Settings > `USB IN`: `Patch`
   back to `On`. Settings > `PATCH DUMP`: `Send` back to `Off`. Press
   **Settings** to leave.
