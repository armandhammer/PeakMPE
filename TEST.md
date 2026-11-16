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

## Series J: patch morph (image `MPEI Ver`)

Image v0.18 `9df89b4d…` (boot screen `MPEI Ver 108.469`). Series A to I are
done (results in [docs/hardware-log.md](docs/hardware-log.md)). Rows are
counted as in Novation's guide: the title is Row 1, the three items are Rows
2 to 4, chosen with the three buttons left of the screen. Nothing is saved.

What it does: with `Morph` set to `ModWheel`, the mod wheel (MIDI CC 1) blends
the patch as you have edited it (wheel at 0) towards the patch as it is
stored (wheel at 127). In this series I send the wheel positions from the
computer, each time you write the **GO** line of a step.

### J1. The new page

1. Select patch **D001**, then patch **D002** again (so D002 is as stored,
   nothing edited). Press **Settings**. Press **Page ►** or **Page ◀** until
   the top line reads `MORPH          12/34`. Expected: Row 2
   `Morph      Off`, Row 3 `Position     0`, Row 4 `Differ       0`.
2. Press **Row 2**. Turn the **Value** knob one click clockwise. Expected Row
   2: `Morph      ModWheel`.

### J2. The blend, measured (I play)

1. Hands off the synth. Write **GO check**. I hold one note for about 13
   seconds. Expected sound: dull at first; then five steps, each brighter
   than the one before (the wheel going up); dull again; then the same five
   steps once more (the filter set directly, for comparison); then dull and
   silence. I compare the two staircases from the recording.

### J3. A knob while the wheel is up (your hands, I set the wheel)

J1 and J2 are done (J2: the wheel's blend measured the same as the filter
set directly, at all five positions). After J2 the filter Frequency is edited
to a low value (dull), and the stored D002 has it fully open (bright).

1. Hold one pad on the LinnStrument from here to the end of J3. Expected: a
   dull note.
2. Write **GO wheel 127**. Expected: within a quarter of a second the note
   turns bright. Row 3 reads `Position   127`, Row 4 `Differ       1`.
3. Write **GO wheel 64**. Expected: the note is in between. Row 3 reads
   `Position    64`.
4. Turn the filter **Resonance** knob from fully anticlockwise to 12 o'clock
   (pointer straight up). Expected on the screen: top line `FiltResonance`,
   and the `current` number ends near 32, about half of what this knob
   position normally gives (about 64). Expected sound: a little resonance.
   **Tell me the `current` number.**
5. Write **GO wheel 0**. Expected: the note goes dull again and the
   resonance gets stronger (now the full value of the knob's position).
6. Move the **Resonance** knob a hair. Expected: the `current` number is now
   near 64. **Tell me the number.**

### J4. `LateTicks` under a wheel sweep (I play)

1. Let go of the pad. Press **Page ◀** once: top line `MOTION         11/34`.
   **Tell me both `LateTicks` numbers.** Leave this page showing.
2. Hands off. Write **GO stress**. I change 24 controls, hold a note and
   sweep the wheel up and down once a second for 10 seconds. Expected
   sound: one note whose tone, envelope and effects pulse once a second,
   without clicks or dropouts. **Tell me if you hear clicks or stutter.**
3. When it is silent again, press **Page ►** once and **Page ◀** once (top
   line `MOTION         11/34` again). **Tell me both numbers.**
4. Select patch **D001**, then **D002** again (this discards my edits).

### J5. Regression run (I play)

1. Press **Settings**, go to `MORPH          12/34`, press **Row 2** and turn
   the **Value** knob one click anticlockwise. Expected Row 2:
   `Morph      Off`.
2. Write **GO rig**. I run `tools/hwrig run --stage all --yes` (about 5
   minutes, Ableton and Focusrite Control closed, hands off). Expected: 136
   pass, 0 fail, 5 info, as on v0.17.
