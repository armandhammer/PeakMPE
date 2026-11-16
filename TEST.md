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

## Series G: messages clear and last about 3 seconds (image `MPEF Ver`)

Image v0.15 `dee61e50…` (boot screen `MPEF Ver 108.469`). Series F is done and
removed (results in docs/hardware-log.md). Rows are counted as in Novation's
guide: the title is Row 1, the three items are Rows 2 to 4, chosen with the
three buttons left of the screen.

### G1. The Done and UNDO messages go away (they stayed for good on v0.14)

1. Select patch **D002**. Press **Settings**. Press **Page ►** or **Page ◀**
   until the top line reads `COPY SECTION    9/32`. Row 2 reads
   `Section    -`.
2. Press **Row 2**. Turn the **Value** knob one click clockwise. Expected Row
   2: `Section    Osc1>2`.
3. Press **Row 3**. Turn the **Value** knob one click clockwise. Expected, for
   about 3 seconds (count "one-thousand-one" to "one-thousand-three"): `COPY
   SECTION`, `Done:`, `Osc1>2`, `Undo: Mod+Page left`. Then the page comes
   back by itself: `COPY SECTION    9/32`, `Section    Osc1>2`,
   `Do it      Off`.
4. Hold **Mod** and press **Page ◀**. Expected, for about 3 seconds: `UNDO`,
   `Back one change`, `Mod+Page left: undo`, `Mod+Page right: redo`. Then
   the message goes away by itself and a Mod menu page is shown (pressing
   Mod opens that menu, as on stock).

### G2. Knob messages last twice as long as before

1. Press **Settings**. Press **Page ◀** or **Page ►** until the top line reads
   `SYSTEM          2/32`. Row 2 should read `Msg Time    64`.
2. Turn the filter **Frequency** knob a little and let go. Expected: the knob
   message (top line `FiltFreq`) stays about 1.5 seconds after you let go
   (on v0.14 and stock: about 0.75 s). At `Msg Time   127` it would now be
   about 3 seconds. **Tell me whether 1.5 s at your setting of 64 is what you
   want**, or whether you would rather keep stock's speed at 64 and only
   have 127 reach 3 s.

### G3. Regression run (I play)

1. Write **GO rig**. I run `tools/hwrig run --stage all --yes` (about 5
   minutes, Ableton and Focusrite Control closed, hands off). Expected: 136
   pass, 0 fail, 5 info, as on v0.14.
