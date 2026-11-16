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

## Series K: the morph from the LinnStrument's Low Row (image `MPEI Ver`)

No new image: v0.18 `9df89b4d…` (boot screen `MPEI Ver 108.469`) stays on the
synth. Series A to J are done (results in
[docs/hardware-log.md](docs/hardware-log.md)). The LinnStrument is set up as
in [docs/linnstrument.md](docs/linnstrument.md) section 4 (one split, MPE)
and plugged into the Peak's MIDI IN. I send nothing in this series. The
LinnStrument steps follow Roger Linn Design's manual (software 2.3.4); I have
not seen them work, so report what differs. Rows on the Peak are counted as
in Novation's guide: the title is Row 1, the three items are Rows 2 to 4.

### K1. Make the lowest row a mod wheel

1. On the LinnStrument press **Per-Split Settings**. In columns 12 and 13,
   **Low Row**, press the pad for **X=CC1** so it is lit. Press **Per-Split
   Settings** again to leave. Expected: the lowest row of pads is lit in its
   own colour and no longer plays notes.

### K2. Does it reach the Peak as CC 1 on channel 1?

1. On the Peak press **Settings**. Press **Page ►** or **Page ◀** until the
   top line reads `MIDI MONITOR   10/34`.
2. Press the lowest row near its left end, slide your finger about 7 pads to
   the right and keep it down. Expected Row 2: `Last msg   B0 01 7F` (`B0` =
   a controller on channel 1, `01` = CC 1, and the last pair climbs from
   `00` to `7F` as you slide). **Tell me the three pairs you see at the
   end of the slide.**
3. Lift the finger. Expected Row 2: `Last msg   B0 01 00`.

### K3. Morph with the thumb

1. Select patch **D001**, then **D002** again (so nothing is edited).
2. Press **Settings**, go to `MORPH          12/34`, press **Row 2** and turn
   the **Value** knob one click clockwise. Expected Row 2:
   `Morph      ModWheel`.
3. Hold one pad that is not on the lowest row, from here to the end of K3.
   Turn the filter **Frequency** knob down to about 10 o'clock. Expected: a
   dull note.
4. Press the lowest row with your thumb and slide slowly about 7 pads to
   the right. Expected: the note gets brighter as you slide, up to the
   fully open filter of the stored D002. Row 3 follows your finger up to
   `Position   127`; Row 4 reads `Differ       1`.
5. Lift the thumb. Expected: within a quarter of a second the note is dull
   again, and Row 3 reads `Position     0`.
6. **Tell me:** does it follow the thumb smoothly, and is this way of
   playing it (lean in to go to the stored sound, let go to come back)
   what you want, or would you rather the row held its position?

### K4. Optional: the row as a fader that keeps its position

1. Press **Per-Split Settings** and hold the **X=CC1** pad. The manual says
   the screen then shows the setting in large characters: swipe up or down
   to choose between the two hidden settings (the mode and the CC number),
   swipe left or right to change the one shown. Choose Fader mode. (I do
   not know the exact letters it shows for this setting; for the similar
   XYZ setting the manual gives `HLD` for Hold and `FDR` for Fader. Leave
   the CC number at 1.) Press **Per-Split Settings** again to leave.
2. Hold a pad as in K3. Touch the lowest row at its left end, in the middle
   and at its right end, lifting the finger each time. Expected: dull, in
   between, bright; the sound and `Position` stay where you left them
   (about `0`, `64`, `127`).

To put things back: Low Row **NORMAL** on the LinnStrument, `Morph` `Off` on
the Peak.
