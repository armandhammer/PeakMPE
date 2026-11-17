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

## Series L: Compare and Save during a morph (image `MPEJ Ver`)

New image v0.19 `fb36f0fb…` (boot screen `MPEJ Ver 108.469`). Series A to K
are done (results in [docs/hardware-log.md](docs/hardware-log.md)). Why a new
image: in the simulator v0.18 lost your edit when **Compare** was let go with
the row up. v0.19 mends that and settles what **Save** does: it stores the
sound you hear, and from then on that sound is the patch.

**The whole series uses D002**, the Init sound with `MPE` On that you saved
for the rig. (My first version used D003 and assumed it was an unused Init
Patch. It is not: it holds "Element Song", and it is silent from the
LinnStrument because its `MPE` setting is Off. Nothing in this series
touches D003 now.) L3 saves over D002; L3.12 makes it the Init sound with
`MPE` On again.

**Done so far (2026-11-16): L1, L2.1 to L2.4** (`Position` 64). My first
L2.5 was wrong: it had you hold a pad and expected the note to go on. The
Peak ends all notes when it loads a patch, and pressing **Compare** loads the
stored one, so the note stops and the pad has to be pressed again (stock
does the same in the simulator; what you saw is not a fault of v0.19). The
steps from L2.5 on are rewritten for that. **Go on at L2.5**; nothing needs
to be set up again if the Peak is as you left it (Frequency at about
10 o'clock, row in the middle).

Setup: the LinnStrument as in series K (Low Row **X=CC1**), with the hidden
setting on **FDR** (K4), so the row keeps its position and both hands are
free. I send nothing until L4. Rows on the Peak are counted as in Novation's
guide: the title is Row 1, the three items are Rows 2 to 4.

### L1. Flash

1. Run the flash command I gave you. Expected boot screen:
   `MPEJ Ver 108.469`.

### L2. Compare with the row up

1. Select patch **D001**, then **D002** (so D002 is as stored, nothing
   edited). Press **Settings**. Press **Page ►** or **Page ◀** until the top
   line reads `MORPH          12/34`. If Row 2 reads `Morph      Off`:
   press **Row 2** and turn the **Value** knob one click clockwise. Expected
   Row 2: `Morph      ModWheel`.
2. Touch the lowest row of the LinnStrument at its left end and lift.
   Expected Row 3: `Position     0`.
3. Hold one pad that is not on the lowest row. Turn the filter
   **Frequency** knob down to about 10 o'clock. Expected: a dull note.
4. Touch the lowest row in the middle and lift. Expected: the note is
   half-way bright. Row 4 reads `Differ       1`. **Tell me the `Position`
   number on Row 3** (somewhere near 64).
5. Lift the pad. Press **Compare** and keep it held. While holding it,
   press one pad (not on the lowest row) and keep that held too. Expected:
   the fully bright note of the stored D002. The screen stays on the MORPH
   page.
6. Let go of **Compare**; keep the pad held. Expected: the note goes on
   sounding and turns half-way bright, as in step 4. Row 3
   `Position    64`, Row 4 `Differ       1`.
7. Still holding the pad, touch the lowest row at its right end and lift.
   Expected: bright note, Row 3 `Position   127`.
8. Press **Compare** and let go. Expected: the note stops when you press
   (the Peak's own behaviour). Lift the pad and press it again, and hold
   it. Expected: the bright note as in step 7. Row 4 still reads
   `Differ       1`.
9. Still holding the pad, touch the lowest row at its left end and lift.
   Expected: the dull note of step 3 is back; Row 3 `Position     0`. (On
   v0.18 the simulator kept the note bright here: the edit was gone.)
10. Lift the pad. Press **Compare** and keep it held. While holding it,
    touch the lowest row at its right end and lift, then press a pad and
    keep it held. Expected: bright. Let go of **Compare**; keep the pad
    held. Expected: still bright (`Position   127`); a very short dull
    blip at the moment you let go is expected here (the morph starts from
    your edit and takes about an eighth of a second to reach the row's
    position). Touch the row at its left end and lift: dull again.

### L3. Save with the row up (saves over D002)

1. Still holding a pad, row at the left end (`Position     0`): turn the
   filter **Resonance** knob from fully anticlockwise to 12 o'clock.
   Expected on the screen: top line `FiltResonance`. **Tell me the
   `current` number** (about 64).
2. Touch the lowest row in the middle and lift. Wait until the MORPH page is
   back (about 3 seconds). Expected: half-way bright with a little
   resonance; Row 4 `Differ       2`. **Tell me the `Position` number.**
3. Press the **Patch** menu button. (Save pressed while the Settings menu is
   open stores the settings, not the patch.) Expected: Row 2
   `Patch      002`, Row 3 `Bank       D`.
4. Press **Save**. Expected top line: `SAVE RENAME      1/3`.
5. Press **Save**. Expected top line: `SAVE LOCATION    2/3`, Row 2
   `Patch      002`, Row 3 `Bank       D`. If it names another location,
   stop and tell me.
6. Lift the pad. Press **Compare** and keep it held. While holding it,
   press a pad and keep it held. Expected: the bright note without
   resonance (what is stored at D002 now). Let go of **Compare**; keep the
   pad held. Expected: the note goes on sounding and turns half-way bright
   with a little resonance again.
7. Press **Save**. Expected top line: `SAVE CATEGORY    3/3`.
8. Press **Save**. Expected top line: `Patch Saved To D002`, then the Patch
   page again. The sound does not change at any of the four presses.
9. Touch the lowest row at its left end and lift. Expected: the sound does
   **not** change (what you saved is the patch now).
10. Touch the lowest row at its right end and lift, then at its left end
    again. Expected: no change either time.
11. Press **Settings** (the MORPH page). Expected: Row 3 `Position     0`,
    Row 4 `Differ       0`. Then move the **Resonance** knob a hair.
    Expected: the `saved val` number is about half of the number from step
    1 (with 64 in step 1 and `Position` 64 in step 2: 32). **Tell me the
    `saved val` number.**
12. Put D002 back: let go of the pad. Press **Initialise**. Press the
    **Voice** menu button. Expected top line `VOICE            1/4` (if it
    shows another page number, press **Page ◀** until it reads `1/4`) and
    Row 4 `MPE        Off`. Press **Row 4** and turn the **Value** knob one
    click clockwise. Expected Row 4: `MPE        On`. Press the **Patch**
    menu button. Press **Save** four times. Expected top line after the
    fourth press: `Patch Saved To D002`. Hold a pad: the plain bright Init
    note.

### L4. Regression run (I play)

1. Press **Settings**, go to `MORPH          12/34`, press **Row 2** and turn
   the **Value** knob one click anticlockwise. Expected Row 2:
   `Morph      Off`.
2. Tell me what is plugged into the Peak and the computer now (the rig needs
   the USB cable and the audio cables as in J5). Then write **GO rig**. I
   run `tools/hwrig run --stage all --yes` (about 5 minutes, Ableton and
   Focusrite Control closed, hands off). Expected: 136 pass, 0 fail, 5
   info, as on v0.18.

To put things back afterwards: `Morph` as you like it; on the LinnStrument
Low Row **NORMAL** if you want the row to play notes again.
