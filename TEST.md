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

## Series AA: the patch-timing message (image `MPEX Ver`)

New image v0.33 (boot screen `MPEX Ver 108.469`). Series A to Z are done
(results in [docs/hardware-log.md](docs/hardware-log.md)).

What v0.33 fixes: the `PATCH TIMING` message showed `D 55` while D003
waited (series Z). The patch that loaded was right; the number in the
message came from bytes stock leaves in a register.

### AA1. Boot and the settings

1. Switch the Peak on. Expected boot screen: `MPEX Ver 108.469`.
2. Turn the **Patch select** knob to **D002**.
3. Press **Settings**, then **Page right** until the top line reads
   `PATCH DUMP`. Press **Select 1** and turn the value encoder until `Send`
   reads `USB`.
4. Press **Page right** once (`PATCH TIMING`). Press **Select 1** and turn
   the value encoder until `Change at` reads `Bar`.
5. Press **Settings** to leave, back to the patch screen. Don't save.

### AA2. Rig and panel together (I play the clock, you press)

1. Say **GO clock**. The clock starts at once and runs for 60 s.
2. About 10 s later, tap **Patch +** once. Expected:
   - top line `PATCH TIMING`
   - second line `D003`
   - third line `at the next bar`

   Within 4 s the patch changes to D003 (`Element Song`).
3. Tap **Patch +** twice more, a few seconds apart, waiting for each change.
   Expected second lines: `D004`, then `D005`. Use only **Patch +**.
4. Tell me the three second lines you saw.

### AA3. Back to stock behaviour

1. Settings > `PATCH TIMING`: `Change at` back to `Now`. Settings >
   `PATCH DUMP`: `Send` back to `Off`. Press **Settings** to leave.
