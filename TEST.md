# TEST.md: hands-on tests for you

Tests only you can do (they need the panel or your eyes). Each series has its
own letter. Report the result of each step ("F2.3: ok", "F2.3: showed X").
Once I'm satisfied with a series I delete it from this file and the next series
uses the next letter, so a test label never means two things.

Every step names the control, the value and the text you should see. If the
screen differs, report the exact text. Report only deviations, plus the
readings a step asks for.

Setup for all series: **quit Ableton and any other MIDI app.**

---

## Series H: motion recording (image `MPEG Ver`)

Image v0.16 `0f262ad9…` (boot screen `MPEG Ver 108.469`). Rows are counted as in
Novation's guide: the title is Row 1, the three items are Rows 2 to 4. Use
patch **D002** (120 BPM, so one bar is 2 seconds) with the LinnStrument on
MIDI IN. Nothing is saved.

### H1. The new page

1. Press **Settings**. Press **Page ►** or **Page ◀** until the top line reads
   `MOTION         11/33`. Expected: Row 2 `Length     1 bar`, Row 3
   `Motion     Off`, Row 4 `LateTicks` and a number. **Tell me the number.**

### H2. Record one bar and hear it loop

1. Hold one pad on the LinnStrument from here to the end of H4, so a note
   sounds all the time. Turn the filter **Frequency** knob fully
   anticlockwise (the note goes dull or silent).
2. Hold **Mod** and press **Animate 1**, then let both go. Expected message:
   `MOTION`, `Move a control`, `to record it`, `Mod+Animate1: cancel`.
3. Turn the filter **Frequency** knob from fully anticlockwise to fully
   clockwise in one even move of about 2 seconds, then take your hand off.
   Expected: from then on the note sweeps from dull to bright by itself,
   once every 2 seconds, without you touching anything. **Tell me whether
   the sweep sounds like your hand movement or like steps.**
4. Press **Settings** and go to `MOTION         11/33`. Expected Row 3:
   `Motion     Play`. **Tell me the `LateTicks` number now, and again about 10
   seconds later.**

### H3. Replace part of the loop

1. While it loops, turn the filter **Frequency** knob fully anticlockwise,
   keep your hand on it for about half a second, and let go. Expected: on
   every following pass that part of the bar is dull, and the rest sweeps
   as before.

### H4. Stop

1. Hold **Mod** and press **Animate 1**. Expected message: `MOTION`,
   `Stopped`, `FiltFreq`. Expected sound: dull or silent and steady again
   (the frequency is back at fully anticlockwise, where it was before the
   recording), no more sweeping.
2. Press **Settings** and go to `MOTION         11/33`. Expected Row 3:
   `Motion     Off`.
3. Hold **Mod** and press **Animate 1**: expected `MOTION`, `Move a control`.
   Hold **Mod** and press **Animate 1** again without moving anything:
   expected `MOTION`, `Off`.

### H5. Regression run (I play)

1. Write **GO rig**. I run `tools/hwrig run --stage all --yes` (about 5
   minutes, Ableton and Focusrite Control closed, hands off). Expected: 136
   pass, 0 fail, 5 info, as on v0.15.
