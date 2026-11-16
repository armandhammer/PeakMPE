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

Needs the v0.14 image `06be5529…` (boot screen `MPEE Ver 108.469`). F0 needs
no new image and can run before the flash. In F0, F2 and F6 I send the notes from
the computer over USB; I start each only when you write **GO**. Hands off
the Peak while one runs (each takes under a minute). Rows are counted as in
Novation's guide: the title is Row 1, the three items are Rows 2 to 4, chosen
with the three buttons left of the screen.

### F0. Which note is cut when all eight voices are busy (no flash needed)

1. Write **GO F0**. I run `work/steal_check.py`: three takes of nine or ten
   sine notes on the Init-based test sound. Nothing for you to do; I report
   which note stopped in each take.

### F1. The new setting is there

1. Press **Settings**. Press **Page ►** or **Page ◀** until the top line
   reads `MPE EXTRAS      7/32`. Expected below it: Row 2 `PressCurve`, Row 3
   `EnvSync`, Row 4 `Glide      Stock`.
2. Press the **Row 4** button. Turn the **Value** knob one click clockwise.
   Expected Row 4: `Glide      LastNote`.
3. One more click clockwise. Expected: `Glide      Legato`. A third click
   changes nothing.
4. Two clicks anticlockwise. Expected: `Glide      Stock`.

### F2. Where a glide starts (I play, three runs)

For each run set Row 4 of `MPE EXTRAS      7/32` as given, then write the
word after "write". Each run plays five sine notes with a slow glide and
takes about 10 seconds; I read the result from the recording.

1. `Glide      Stock`. Write **GO stock**.
2. `Glide      LastNote` (one click clockwise). Write **GO lastnote**.
3. `Glide      Legato` (one more click clockwise). Write **GO legato**.

Expected (I check): Stock starts every note from the pitch its voice last
played; LastNote from the note before it; Legato on pitch when nothing is
held and from the held note otherwise.

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

### F6. Regression run (I play)

1. Write **GO rig**. I run `tools/hwrig run --stage all --yes` (about 15
   minutes, Ableton and Focusrite Control closed, hands off). Expected: 136
   pass, 0 fail, 5 info, as on v0.13.

### F7. By ear, with the LinnStrument (after F2)

1. On the Peak select patch **D002** (the MPE On patch). Press the Glide
   **On** button so that its LED is lit. Turn the Glide **Time** knob until
   the knob message reads `GlideTime` `current 70`.
2. Set `Glide      Legato` (F1, steps 1 to 3).
3. On the LinnStrument play one low pad, lift it, then play one pad two
   octaves higher. Expected: the high note starts on pitch, no glide.
4. Hold the low pad and, while holding it, press the high pad. Expected: the
   high note glides up from the low note's pitch in about half a second.
   **Tell me whether this feels right for a lead line**, and whether
   `LastNote` (it glides in step 3 as well) is better or worse.
