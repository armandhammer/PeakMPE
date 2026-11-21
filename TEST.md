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

## Series AC: just intonation (image `MPEZ Ver`)

New image v0.35 (boot screen `MPEZ Ver 108.469`). Series A to AB are done
(results in [docs/hardware-log.md](docs/hardware-log.md)). If you haven't
yet: Settings > `DIN IN` > `Notes` `On`, `USB IN` > `Patch` `On`, `PATCH
DUMP` > `Send` `Off` (back to stock after series AB).

What v0.35 adds: Settings page `JUST TUNE` (after `DIN IN`) with `Mode`
(Off, Fixed, Adapt) and `Root` (C to B).

### AC1. Boot and the new page

1. Switch the Peak on. Expected boot screen: `MPEZ Ver 108.469`.
2. Turn the **Patch select** knob to **D002**.
3. Press **Settings**, then **Page right** until the top line reads
   `DIN IN`. Press **Page right** once more. Expected:
   - top line `JUST TUNE`
   - second line `Mode` ... `Off`
   - third line `Root` ... `C`
4. Press **Settings** to leave.

### AC2. Rig with Mode Off (stock behaviour)

1. Say **GO rig**. I run the full rig (about 10 minutes) and the editor
   check; nothing to press.

### AC3. Fixed, Root C (I play, you set first)

1. Press **Settings**, **Page right** to `JUST TUNE`. Press **Select 1** and
   turn the value encoder until `Mode` reads `Fixed`. `Root` stays `C`.
2. Press **Settings** to leave. The patch screen shows D002.
3. Say **GO ji fixed**. I play four chords over USB and measure each note;
   nothing to press.

### AC4. Adapt (I play, you set first)

1. Press **Settings**, **Page right** to `JUST TUNE`, **Select 1**, turn the
   value encoder until `Mode` reads `Adapt`. Press **Settings** to leave.
2. Say **GO ji adapt**. Same four chords; nothing to press.

### AC5. Back to stock behaviour

1. Settings > `JUST TUNE`: `Mode` `Off`. Press **Settings** to leave.
