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

## Series I: motion recording, second round (image `MPEH Ver`)

Image v0.17 `e5e9e652…` (boot screen `MPEH Ver 108.469`). Rows are counted as in
Novation's guide: the title is Row 1, the three items are Rows 2 to 4. Use
patch **D002** (120 BPM, so one bar is 2 seconds) with the LinnStrument on
MIDI IN. Nothing is saved.

What changed since series H: the recorded movement now plays back as a ramp
from step to step (v0.16 jumped, and jumped hardest where the loop starts
again), and `LateTicks` now shows two numbers that stand still while you look
at them: the count, and the longest single stall in milliseconds since the
last time the page was drawn. Turning to the next page and back takes a new
reading.

### I1. `LateTicks` with nothing playing

1. Press **Settings**. Press **Page ►** or **Page ◀** until the top line reads
   `MOTION         11/33`. Expected: Row 2 `Length     1 bar`, Row 3
   `Motion     Off`, Row 4 `LateTicks` followed by two numbers that do not
   move. **Tell me both numbers.**
2. Press **Page ►** once (the top line ends in `12/33`). Wait 10 seconds.
   Press **Page ◀** once (top line `MOTION         11/33` again). **Tell me
   both numbers.**

### I2. Record one bar: is the click gone?

1. Hold one pad on the LinnStrument from here to the end of I5, so a note
   sounds all the time. Turn the filter **Frequency** knob fully
   anticlockwise (the note goes dull or silent).
2. Hold **Mod** and press **Animate 1**, then let both go. Expected message:
   `MOTION`, `Move a control`, `to record it`, `Mod+Animate1: cancel`.
3. Turn the filter **Frequency** knob from fully anticlockwise to fully
   clockwise in one even move of about 2 seconds, then take your hand off.
   Expected: from then on the note sweeps from dull to bright by itself,
   once every 2 seconds, and at the end of each sweep it falls back to dull
   quickly but without a click. **Tell me: is the click gone? Does the rise
   sound like your hand movement or like steps?**

### I3. `LateTicks` while the loop plays

1. Press **Settings** and go to `MOTION         11/33`. Expected Row 3:
   `Motion     Play`. **Tell me both `LateTicks` numbers.**
2. Press **Page ►** once, wait 10 seconds, press **Page ◀** once. **Tell me
   both numbers.**

### I4. Stop

1. Hold **Mod** and press **Animate 1**. Expected message: `MOTION`,
   `Stopped`, `FiltFreq`. Expected sound: dull or silent and steady again, no
   more sweeping.

### I5. Replace part of a loop: a dip that repeats

1. Turn the filter **Frequency** knob to 12 o'clock (pointer straight up).
   Expected: a steady, medium-bright note.
2. Hold **Mod** and press **Animate 1**, then let both go. Expected message:
   `MOTION`, `Move a control`, `to record it`, `Mod+Animate1: cancel`.
3. Turn **Frequency** a little clockwise, to about 1 o'clock, and take your
   hand off. Wait 4 seconds. Expected: a steady note; a slight flicker in
   brightness once every 2 seconds is normal (that is the small move you
   just recorded).
4. Now turn **Frequency** fully anticlockwise and straight back to about
   1 o'clock, the whole dip within about 1 second, and take your hand off.
   Expected: from then on the same dip (bright, dull, bright) repeats by
   itself once every 2 seconds, always at the same place in the bar.
   **Tell me whether the dip repeats; if not, what you hear instead.**
5. Hold **Mod** and press **Animate 1**. Expected message: `MOTION`,
   `Stopped`, `FiltFreq`. Expected sound: steady, at the 12 o'clock
   brightness from step 1 (the value before the recording).

### I6. Regression run (I play)

1. Write **GO rig**. I run `tools/hwrig run --stage all --yes` (about 5
   minutes, Ableton and Focusrite Control closed, hands off). Expected: 136
   pass, 0 fail, 5 info, as on v0.16.
