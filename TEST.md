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

## Series F: glide start, message time, undo timing (image `MPEE Ver`)

Image v0.14 `06be5529…` (boot screen `MPEE Ver 108.469`). Done and removed: F0
(which note is cut), F1 and F2 (the Glide item and where a glide starts), F6
(rig regression, 136 pass). The Glide item is still on `Legato` from F2; F7
uses that. Rows are counted as in Novation's guide: the title is Row 1, the
three items are Rows 2 to 4, chosen with the three buttons left of the screen.

### F3. How long a knob message lasts (stopwatch on a phone)

1. Press **Settings**. Press **Page ◀** or **Page ►** until the top line
   reads `SYSTEM          2/32`. Row 2 reads `Msg Time` and a number. **Tell
   me the number.**
2. Press the **Row 2** button and turn the **Value** knob clockwise until Row
   2 reads `Msg Time   127`.
3. Turn the filter **Frequency** knob a little and let go; start the
   stopwatch as you let go and stop it when the knob message (top line
   `FiltFreq`) disappears and the `SYSTEM          2/32` page is back.
   **Tell me the time**, to about a quarter of a second. (The firmware's code
   says about 1.5 s, Novation's guide about 3 s.)
4. Press **Row 2** and turn the **Value** knob back to the number from
   step 1.

### F4. The Done message stays 2 seconds

1. Select patch **D002** (the copy changes Oscillator 2 in the edit buffer;
   step 4 undoes it and nothing is saved). Press **Settings**. Press
   **Page ►** or **Page ◀** until the top line reads `COPY SECTION    9/32`.
2. Press **Row 2**. Turn the **Value** knob one click clockwise. Expected Row
   2: `Section    Osc1>2`.
3. Press **Row 3**. Turn the **Value** knob one click clockwise. Expected, for
   about 2 seconds (count "one-thousand-one, one-thousand-two"): `COPY
   SECTION`, `Done:`, `Osc1>2`, `Undo: Mod+Page left`; then the page comes
   back with `Do it      Off`. **Tell me if it is much shorter or longer
   than 2 s.**
4. Hold **Mod** and press **Page ◀**. Expected, also for about 2 seconds:
   `UNDO`, `Back one change`, `Mod+Page left: undo`, `Mod+Page right: redo`.

### F5. One knob move is one undo step after a 2 second pause

1. Patch **D002**. Hold one pad on the LinnStrument through steps 2 to 5 so
   that a note sounds.
2. Turn the filter **Frequency** knob fully anticlockwise (the note goes
   dull or silent).
3. Wait 3 seconds (count them).
4. Turn the filter **Frequency** knob fully clockwise in one move (the note
   is bright).
5. Hold **Mod** and press **Page ◀** once. Expected screen: `UNDO`, `Back one
   change`; expected sound: dull or silent again (the frequency went back to
   fully anticlockwise, the value before step 4, not to where it was before
   step 2). On v0.13 the two moves counted as one, because the pause had to
   be 4 seconds, and the note would come back at its original brightness.

### F7. By ear, with the LinnStrument

1. On the Peak select patch **D002** (the MPE On patch). Press the Glide
   **On** button so that its LED is lit. Turn the Glide **Time** knob until
   the knob message reads `GlideTime` `current 70`.
2. Check the Glide item: press **Settings**, then **Page ►** or **Page ◀** until
   the top line reads `MPE EXTRAS      7/32`. Row 4 should read
   `Glide      Legato` (left there by F2).
3. On the LinnStrument play one low pad, lift it, then play one pad two
   octaves higher. Expected: the high note starts on pitch, no glide.
4. Hold the low pad and, while holding it, press the high pad. Expected: the
   high note glides up from the low note's pitch in about half a second.
   **Tell me whether this feels right for a lead line.**
5. Press **Row 4** and turn the **Value** knob one click anticlockwise: Row 4
   reads `Glide      LastNote`. Repeat step 3. Expected: the high note now
   glides up from the low note although the low pad was lifted. **Tell me
   which of the two you would rather play with.**
