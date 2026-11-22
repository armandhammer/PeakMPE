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

## Series AD: chords on the master channel (image `MPEa Ver`)

New image v0.36 (boot screen `MPEa Ver 108.469`: the letters A to Z are used
up, so it goes on in lower case). Series A to AC are done (results in
[docs/hardware-log.md](docs/hardware-log.md)).

What v0.36 changes: with MPE on, a chord sent on the zone's master channel
(channel 1 with no zone set) plays in full; before, its notes took each
other's voice and only the last one sounded. Member channels are unchanged.

### AD1. Boot, and just intonation back to Off

1. Switch the Peak on. Expected boot screen: `MPEa Ver 108.469`.
2. Turn the **Patch select** knob to **D002**.
3. Press **Settings**, then **Page right** until the top line reads
   `JUST TUNE`. Expected: `Mode` ... `Adapt` (as AC4 left it; Settings are
   kept through the flash). Press **Select 1** and turn the value encoder
   until `Mode` reads `Off`.
4. Press **Settings** to leave.

### AD2. Rig

1. Say **GO rig**. I run the full rig (about 10 minutes) and the editor
   check; nothing to press.

### AD3. Chords on the master channel (I play)

1. Say **GO master**. I build the rig's sine sound in the edit buffer and
   play four short takes over USB: a chord on channel 1, the same chord
   with one note let go, a chord on member channels 2 to 4, and two notes
   on one member channel. Nothing to press.
