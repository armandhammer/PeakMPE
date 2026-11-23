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

## Series AK: what was only ever checked in the simulator (no new image)

The synth stays on v0.41 (boot screen `MPEf Ver 108.469`). Series A to AJ
are done (results in [docs/hardware-log.md](docs/hardware-log.md)).

What this checks: the status audit of 2026-11-23 found four things never
tried on a Peak: Keep Low with Unison 8, the arp echo filter's v0.20 change
(with and without a loop), and USB IN `CC` = `Off`. (DIN IN `Patch` = `Off`
stays untried: the rig has no DIN output and the LinnStrument sends no
program change.)

### AK1. Keep Low on (your hands)

1. Press **Settings**, then **Page right** until the top line reads
   `VOICE STEAL    22/44`. Press **Select 1** and turn the value encoder
   one click clockwise. Expected Select 1 line: `Keep Low   On`.
2. Press **Settings** to leave, back to the patch screen. Don't save.

### AK2. Rig (I play)

Say **GO rig**. I run, in order (about 1 minute, hands off; you will hear
the arp):
- `work/unison_keep_check.py`: a sine with Unison 8, note 60, then note 64.
  Expected: 64 sounds and 60 is cut.
- `work/arp_noloop_check.py`: arp on, chord C E G held 3 s, let go.
  Expected: arp notes while held, none later than 0.3 s after letting go.
- `work/loopback_test.py`: the same with every arp note sent straight back
  to the Peak, as a DAW with a routing loop would. Expected: no runaway,
  the arp stops after letting go.
- `work/cc_filter_check.py --control`: with USB IN `CC` still `On`, a filter
  CC and an NRPN change the edit buffer. Expected: both change.

### AK3. USB IN CC off (your hands, after I report AK2)

1. Press **Settings**, then **Page right** or **Page left** until the top
   line reads `VOICE STEAL    22/44`. Press **Select 1** and turn the value
   encoder one click anticlockwise. Expected Select 1 line:
   `Keep Low   Off`.
2. Press **Page left** three times. Expected top line:
   `USB IN         19/44`. Press **Select 2** and turn the value encoder
   one click anticlockwise. Expected Select 2 line: `CC         Off`.
3. Press **Settings** to leave. Don't save.

### AK4. Rig (I play)

Say **GO rig**. I run `work/cc_filter_check.py`. Expected: the filter CC and
the NRPN leave the edit buffer unchanged, and a note sent over USB still
sounds.

### AK5. Back as before (your hands)

1. Press **Settings**, then **Page right** or **Page left** until the top
   line reads `USB IN         19/44`. Press **Select 2** and turn the value
   encoder one click clockwise. Expected Select 2 line: `CC         On`.
2. Press **Settings** to leave. Don't save.

### AK6. Editor check (I play)

Say **GO rig**. I run `tools/editor_check.py`. Expected: nothing changed
against AJ5's run (the settings back as they were).
