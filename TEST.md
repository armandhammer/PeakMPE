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

## Series AL: ratchet chance (image `MPEg Ver`)

New image v0.42 (boot screen `MPEg Ver 108.469`). Series A to AK are done
(results in [docs/hardware-log.md](docs/hardware-log.md)).

What v0.42 adds: Settings > `ARP RATCHET` > `Chance` (10 % to 100 %, default
100 %). With a ratchet on, each ratcheted note plays its repeats only by
chance; otherwise it plays once, on the same grid.

### AL1. Boot

1. Switch the Peak on. Expected boot screen: `MPEg Ver 108.469`.
2. Turn the **Patch select** knob to **D002**.

### AL2. The page

1. Press **Settings**, then **Page right** until the top line reads
   `ARP RATCHET    14/44`. Expected: Select 1 line `Ratchet    Off`,
   Select 2 line `Every        1`, Select 3 line `Chance     100%`.
2. Press **Select 1** and turn the value encoder one click clockwise.
   Expected Select 1 line: `Ratchet    x2`.
3. Press **Select 3** and turn the value encoder five clicks anticlockwise.
   Expected Select 3 line: `Chance      50%`.
4. Press **Settings** to leave. Don't save.

### AL3. Rig (I play)

Say **GO rig**. I run `work/ratchet_chance_check.py` (about 15 s): arp on,
one note held for 40 steps, the Peak's arp notes read from its MIDI out.
Expected: every step sounds, and about half of them (between 8 and 32 of
40) sound twice, always on the half step.

Done 2026-11-23 (AL1 to AL3): 23 of 48 steps twice, none missing, all on
the grid.

### AL4. Back as before (your hands, after I report AL3)

1. Press **Settings**, then **Page right** or **Page left** until the top
   line reads `ARP RATCHET    14/44`. Press **Select 3** and turn the value
   encoder five clicks clockwise: `Chance     100%`. Press **Select 1** and
   turn the value encoder one click anticlockwise: `Ratchet    Off`.
2. Press **Settings** to leave. Don't save.

### AL5. Regression (I play)

Say **GO rig**. I run `hwrig run --stage all` (expected 136 pass, 0 fail,
5 info) and `tools/editor_check.py` (expected: nothing changed against
AK6's run).
