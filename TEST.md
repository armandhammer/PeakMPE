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

## Series V: main-loop headroom (image `MPET Ver`)

New image v0.29 (boot screen `MPET Ver 108.469`). Series A to U are done
(results in [docs/hardware-log.md](docs/hardware-log.md)).

What v0.29 changes: nothing you should hear or see. The patch's own checks
(the screen, the MPE settings, the arp rhythm) run once a millisecond
instead of on every pass of the main loop.

### V1. Boot and a quick look

1. Switch the Peak on. Expected boot screen: `MPET Ver 108.469`, then the
   patch screen as usual.
2. Select patch **D002**. Turn the **Frequency** knob of the filter a little.
   Expected: the knob screen with its value bar on the bottom line, as
   before (the bar's characters are loaded by one of the checks that now
   run once a millisecond).
3. Press **Settings**, then **Page right** until the top line reads `MPE`.
   Press **Select 1** (the `Zone` line) and note its value. Turn the value encoder
   one step right: expected, the value changes at once (`Off` -> `Lower`,
   `Lower` -> `Upper`, or it stays at `Upper`). Turn it one step left:
   expected, back to the value you noted.
4. Press **Settings** again to leave. Nothing is saved.

### V2. Rig (I play)

Say **GO rig**. I run the regression run, `hwrig run --stage all`, then
`tools/editor_check.py` against the baseline from series U.
Expected: 136 pass, 0 fail, 5 info, and the editor check unchanged.
