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

## Series Z: panel patch changes on the bar (image `MPEW Ver`, no new image)

No flash: the Peak keeps v0.32. Series A to Y are done (results in
[docs/hardware-log.md](docs/hardware-log.md)).

What this checks: a patch chosen with the **Patch +** button while a DAW's
clock plays waits for the next bar line, as program changes did in series X
and Y. The rig plays the DAW's clock (60 BPM, a bar every 4 s) and the patch
dumps show which clock each load came on.

### Z1. The settings

1. Turn the **Patch select** knob to **D002**.
2. Press **Settings**, then **Page right** until the top line reads
   `PATCH DUMP`. Press **Select 1** and turn the value encoder until `Send`
   reads `USB`.
3. Press **Page right** once (`PATCH TIMING`). Press **Select 1** and turn
   the value encoder until `Change at` reads `Bar`.
4. Press **Settings** to leave, back to the patch screen. Don't save.

### Z2. Rig and panel together (I play the clock, you press)

1. Say **GO clock**. I start `work/ptime_panel.py`: Start, then 60 s of
   clock at 60 BPM, then Stop. Nothing else is sent.
2. **Wait about 10 s** after saying GO, then press **Patch +** once.
   Expected: the screen shows `PATCH TIMING`, then `D003`, then
   `at the next bar`; within 4 s the patch changes to D003.
3. When it has changed, wait a few seconds and press **Patch +** again
   (D004), and later a third time (D005). Finish within about 50 s of
   saying GO.
4. Tell me when you're done. Expected (I read it from the dumps): 3 loads,
   each on a bar line.
5. Turn the **Patch select** knob back to **D002**.

### Z3. Back to stock behaviour

1. Settings > `PATCH TIMING`: `Change at` back to `Now`. Settings >
   `PATCH DUMP`: `Send` back to `Off`. Press **Settings** to leave.
