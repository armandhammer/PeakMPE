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

## Series AF: sostenuto and the first glide (image `MPEc Ver`)

New image v0.38 (boot screen `MPEc Ver 108.469`). Series A to AE are done
(results in [docs/hardware-log.md](docs/hardware-log.md)).

What v0.38 fixes, both in the Peak's own firmware: a key you still hold
when you let go of the sostenuto pedal keeps sounding (stock stopped it);
and with Glide on, the first notes after the Peak is switched on start on
pitch instead of gliding from middle C.

### AF1. Boot and the Glide setting

1. Switch the Peak on. Expected boot screen: `MPEc Ver 108.469`.
2. Turn the **Patch select** knob to **D002**.
3. Press **Settings**, then **Page right** until the top line reads
   `MPE EXTRAS`. Expected: `Glide` reads `Stock`. If it doesn't, press
   **Select 3** and turn the value encoder until it reads `Stock`.
4. Press **Settings** to leave. Don't play any note before AF2: the first
   check needs voices that haven't played since power-on.

### AF2. Rig (I play)

Say **GO rig**. I run, in order:
- `work/pedal_check.py` (about 15 s): builds the rig's sine in the edit
  buffer with a slow glide, plays 48 and then 72 over it. Expected: each
  starts on its own pitch, not from middle C. Then three takes with the
  sostenuto pedal (CC 66). Expected: a key still held at pedal up keeps
  sounding; a key let go under the pedal ends at pedal up.
- the regression run, `hwrig run --stage all`. Expected: 136 pass, 0 fail,
  5 info.
- `tools/editor_check.py`. Expected: only `settings` changed (AE2's run
  had PATCH DUMP and PATCH TIMING on).
