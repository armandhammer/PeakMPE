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

## Series M: Save in a morph, Compare, Euclidean arp (image `MPEK Ver`)

New image v0.20 `323f03fb…` (boot screen `MPEK Ver 108.469`), built in
the night of 2026-11-16. Series A to K are done, and L1 and L2 of series
L (results in [docs/hardware-log.md](docs/hardware-log.md)). L3 (Save) and
L4 (the rig run) were not done on v0.19; they are M2 and M7 here, unchanged
apart from the page numbers, so one flash covers everything.

What v0.20 adds:

- **Compare** no longer clears the undo step or stops a motion lane (M3,
  M4). In the simulator v0.19 did both.
- **Euclidean arp rhythms** (M5): Settings > ARP EUCLID, a new page. The
  Settings menu now has 35 pages, so MORPH reads `12/35`.
- **Arp echo filter**: with Arp>MIDI on and no MIDI loop, a key let go just
  after the arp's own note off is no longer ignored. Nothing to test by
  hand (it needs a keyboard on the Peak's own MIDI channel).

**The whole series uses D002**, the Init sound with `MPE` On. M2 saves over
D002 and M2.12 puts it back. Nothing touches any other patch.

Setup: the LinnStrument as in series K and L (Low Row **X=CC1** on **FDR**).
I send nothing until M7. Rows on the Peak are counted as in Novation's
guide: the title is Row 1, the three items are Rows 2 to 4. Remember that
the Peak ends all notes when it loads a patch, and pressing **Compare**
loads one: a pad is pressed again while **Compare** is held.

### M1. Flash

1. Run the flash command I gave you. Expected boot screen:
   `MPEK Ver 108.469`.

### M2. Save with the row up (saves over D002)

1. Select patch **D001**, then **D002**. Press **Settings**. Press
   **Page ►** or **Page ◀** until the top line reads `MORPH          12/35`.
   If Row 2 reads `Morph      Off`: press **Row 2** and turn the **Value**
   knob one click clockwise. Expected Row 2: `Morph      ModWheel`. Touch
   the lowest row of the LinnStrument at its left end and lift. Expected
   Row 3: `Position     0`.
2. Hold one pad that is not on the lowest row, from here to step 5. Turn
   the filter **Frequency** knob down to about 10 o'clock (a dull note),
   then the filter **Resonance** knob from fully anticlockwise to
   12 o'clock. Expected on the screen: top line `FiltResonance`. **Tell me
   the `current` number** (about 64).
3. Touch the lowest row in the middle and lift. Wait until the MORPH page
   is back (about 3 seconds). Expected: half-way bright with a little
   resonance; Row 4 `Differ       2`. **Tell me the `Position` number.**
4. Press the **Patch** menu button. (Save pressed while the Settings menu
   is open stores the settings, not the patch.) Expected: Row 2
   `Patch      002`, Row 3 `Bank       D`.
5. Press **Save**. Expected top line: `SAVE RENAME      1/3`. Press **Save**
   again. Expected top line: `SAVE LOCATION    2/3`, Row 2
   `Patch      002`, Row 3 `Bank       D`. If it names another location,
   stop and tell me.
6. Lift the pad. Press **Compare** and keep it held. While holding it,
   press a pad and keep it held. Expected: the bright note without
   resonance (what is stored at D002 now). Let go of **Compare**; keep the
   pad held. Expected: the note goes on sounding and turns half-way bright
   with a little resonance again.
7. Press **Save**. Expected top line: `SAVE CATEGORY    3/3`.
8. Press **Save**. Expected top line: `Patch Saved To D002`, then the Patch
   page again. The sound does not change at either press.
9. Touch the lowest row at its left end and lift. Expected: the sound does
   **not** change (what you saved is the patch now).
10. Touch the lowest row at its right end and lift, then at its left end
    again. Expected: no change either time.
11. Press **Settings** (the MORPH page). Expected: Row 3 `Position     0`,
    Row 4 `Differ       0`. Then move the **Resonance** knob a hair.
    Expected: the `saved val` number is about half of the number from step
    2 (with 64 there and `Position` 64 in step 3: 32). **Tell me the
    `saved val` number.**
12. Put D002 back: let go of the pad. Press **Initialise**. Press the
    **Voice** menu button. Expected top line `VOICE            1/4` (if it
    shows another page number, press **Page ◀** until it reads `1/4`) and
    Row 4 `MPE        Off`. Press **Row 4** and turn the **Value** knob one
    click clockwise. Expected Row 4: `MPE        On`. Press the **Patch**
    menu button. Press **Save** four times. Expected top line after the
    fourth press: `Patch Saved To D002`. Hold a pad: the plain bright Init
    note.

### M3. Compare keeps the undo step

1. Press **Settings**, go to `MORPH          12/35`, press **Row 2** and
   turn the **Value** knob one click anticlockwise. Expected Row 2:
   `Morph      Off`. Select patch **D001**, then **D002**.
2. Hold a pad. Turn the filter **Frequency** knob down to about
   10 o'clock. Expected: a dull note. Lift the pad.
3. Press **Compare** and keep it held. While holding it, press a pad and
   keep it held. Expected: the bright note of the stored D002. Let go of
   **Compare**; keep the pad held. Expected: the dull note again.
4. Hold **Mod** and press **Page ◀**. Expected screen: top line `UNDO`,
   second line `Back one change`. The note turns bright (the Frequency
   move is undone). On v0.19 the screen said `Nothing to undo` here.
5. Hold **Mod** and press **Page ►**. Expected: top line `REDO`, second
   line `Change restored`; the note is dull again.
6. Press **Compare** and keep it held (the note stops). While holding it,
   hold **Mod** and press **Page ◀**. Expected: top line `UNDO`, second
   line `Not during Compare`. Let go of everything.

### M4. Compare leaves a motion lane playing

1. Select patch **D001**, then **D002**. Hold a pad. Hold **Mod** and press
   **Animate 1**. Expected screen: top line `MOTION`, second line
   `Move a control`.
2. Still holding the pad, sweep the filter **Frequency** knob down and up
   once, taking about two seconds. Expected: after that the sweep repeats
   by itself, once every two seconds.
3. Press **Settings** and go to the page whose top line reads
   `MOTION         11/35`. Expected Row 3: `Motion     Play`.
4. Lift the pad. Press **Compare** and keep it held. While holding it,
   press a pad and keep it held. Expected: a steady bright note, no sweep
   (the stored patch as it is). Row 3 still reads `Motion     Play`.
5. Let go of **Compare**; keep the pad held. Expected: the sweep goes on.
   Row 3 `Motion     Play`. On v0.19 the sweep was gone here and Row 3
   read `Motion     Off`.
6. Hold **Mod** and press **Animate 1**. Expected screen: top line
   `MOTION`, second line `Stopped`. The note is steady and bright again.

### M5. Euclidean arp rhythm

1. Select patch **D001**, then **D002**. Press the **On** button of the
   arpeggiator (it lights). Hold a pad. Expected: the note repeats
   steadily, eight times a second.
2. Press **Settings** and go to the page whose top line reads
   `ARP EUCLID     13/35` (one page after MORPH). Expected: Row 2
   `Pulses     Off`, Row 3 `Steps       16`, Row 4 `Rotate       0`.
3. Press **Row 3** and turn the **Value** knob eight clicks anticlockwise.
   Expected Row 3: `Steps        8`.
4. Press **Row 2** and turn the **Value** knob three clicks clockwise.
   Expected Row 2: `Pulses       3`. Hold a pad. Expected: three notes a
   second in a long-long-short rhythm (3 + 3 + 2 steps, the "tresillo"),
   repeating every second.
5. Turn the **Value** knob two more clicks clockwise. Expected Row 2:
   `Pulses       5`; five notes a second, uneven (x.x.xx.x).
6. Turn the **Value** knob four clicks anticlockwise. Expected Row 2:
   `Pulses       1`. Lift the pad and press it again. Expected: one note at
   once, then one every second.
7. Press **Row 4** and turn the **Value** knob four clicks clockwise.
   Expected Row 4: `Rotate       4`. Lift the pad and press it again.
   Expected: half a second of silence, then one note every second.
8. Turn the **Value** knob four clicks anticlockwise (`Rotate       0`).
   Press **Row 2** and turn the **Value** knob one click anticlockwise.
   Expected Row 2: `Pulses     Off`; with a pad held the steady eight
   notes a second are back. Press the arpeggiator's **On** button again
   (it goes dark).

### M6. What turning a knob costs (two readings)

An open question from series I: the screen that pops up while a knob is
turned may keep the Peak from its modulation work (pitch bend and pressure
smoothing). Two numbers answer it.

1. Press **Settings** and go to `MOTION         11/35`. **Tell me Row 4**
   (it reads `LateTicks` and two numbers).
2. Press **Page ►** once (the MORPH page). Turn the filter **Frequency**
   knob back and forth for about five seconds without stopping. Wait until
   the MORPH page is back (about 3 seconds).
3. Press **Page ◀** once (the MOTION page). **Tell me Row 4 again.**

After M3.1 and M5.8 the settings are back where they were (`Morph      Off`,
`Pulses     Off`, the arpeggiator off). The Euclid settings are stored with
the other settings only when you press **Save** inside the Settings menu;
there is no need to.

### M7. Regression run (I play)

1. Tell me what is plugged into the Peak and the computer now (the rig
   needs the USB cable and the audio cables as in J5). Then write
   **GO rig**. I run `tools/hwrig run --stage all --yes` (about 5 minutes,
   Ableton and Focusrite Control closed, hands off). Expected: 136 pass,
   0 fail, 5 info, as on v0.18.

To put things back afterwards: `Morph` as you like it; on the LinnStrument
Low Row **NORMAL** if you want the row to play notes again.
