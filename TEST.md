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

## Series U: Components and the editor baseline (image `MPES Ver`, no new image)

No flash: the Peak keeps v0.28 (boot screen `MPES Ver 108.469`). Series A
to T are done (results in [docs/hardware-log.md](docs/hardware-log.md)).

What this checks: Novation Components still reads the Peak with the MPE
patch in it, and a first recording of the Peak's answers to the editor's
requests, kept as a regression check for later images.

**Read only.** In Components, don't press anything that sends to the Peak,
saves to it, restores it or updates it. **If Components offers a firmware
update, decline it** (it would put back the stock firmware). I haven't seen
Components' screens with a Peak, so the steps name what to look for, not
the exact buttons: tell me the exact text where it differs.

### U1. Components finds the Peak

1. Quit Ableton and any other MIDI app. In Chrome, open
   `components.novationmusic.com` and choose the Peak (allow MIDI access if
   Chrome asks).
2. Expected: Components shows the Peak as connected. **Tell me the
   firmware version it shows**, and whether it offers an update.

### U2. Patches

1. Open the Peak's patch list in Components and let it read the patches
   from the Peak.
2. Expected: Bank D lists **D003 `Element Song`**, and D002 is the rig's
   test patch. **Tell me if it shows an error, reads only part of a bank,
   or shows any patch names you don't expect.**

### U3. Wavetables

1. Open the Peak's wavetable page in Components.
2. Expected: the user wavetable slots are listed with their names (stock:
   `User 1` to `User 10` unless you've loaded your own). **Tell me what it
   lists**, or any error.

### U4. Rig (I send)

1. **Close the Components tab** (Chrome holds the Peak's MIDI port while it
   is open).
2. Say **GO rig**. I run `tools/editor_check.py`: 152 read requests (the
   identity, the current patch, D002, the settings, every wavetable block and
   name, the 17 tuning tables, all of bank D) and one write of the current
   patch back into the edit buffer, unchanged. Nothing is stored. The screen
   may show a message about a received patch; the sound doesn't change.
   This first run is the baseline later images are compared with.
