# TEST.md: hands-on tests for you

Tests only you can do (they need the LinnStrument, the panel or your ears).
Each series has its own letter. Tell me the result of each step in a message
("A2.3: ok", "A4.2: the arrow was wrong"). Once I'm satisfied with a series I
delete it from this file and the next series uses the next letter, so a test
label never means two things.

Setup for all series: the Peak runs image `94629b81…` (boot screen
`MPE6 Ver`), the LinnStrument is on the Peak's **MIDI IN** over a 5-pin DIN
cable, and nothing else sends MIDI to the Peak (**quit Ableton and any other
MIDI app**: it caused a false rig failure on 2026-11-14). LinnStrument
settings are in [docs/linnstrument.md](docs/linnstrument.md).

---

## Series B: EnvSync on other tempos

The knob overlay can't show the synced value (its "saved val" is the stored
patch, and "current" follows the knob once Pickup is armed), so you set things
on the panel and I measure the sound. Each test ends with you saying "go";
then don't touch the synth or PC for about 30 seconds while I play one note
over USB and measure the Decay and Release times from a recording.

Already measured (series A, 1/8 at 120 BPM, 2026-11-14): Decay 264 ms,
Release 272 ms. Expected 250 ms, within the table's step size.

### B1. Tempo changes

1. Settings > MPE EXTRAS > EnvSync = **1/8**. Arp tempo (ClockRate) = **60
   BPM**. Wait 2 seconds. Say "go". Expected: about 500 ms each.
2. Set the tempo to **240 BPM**. Wait 3 seconds. Say "go". Expected: about
   125 ms each.

### B2. Off, and manual edits

1. Set **EnvSync** to **Off**. Set the tempo to **90 BPM**. Wait 3 seconds.
   Say "go". Expected: the same values as at the end of B1 (125 ms), because
   Off changes nothing.
2. Set **EnvSync** to **1/4** at **120 BPM**. Wait 2 seconds. Say "go".
   Expected: about 500 ms each.
3. Turn **Amp Decay** by hand to a clearly different value (a quarter turn).
   Say "go". Expected: Decay now differs from 500 ms, Release is still about
   500 ms, and neither changes by itself.

### B3. Patch change and Save

1. EnvSync **1/8**, tempo **120 BPM**, wait 2 seconds.
2. Select another patch, then back to D002. Say "go". Tell me what you did;
   I measure which values the patch has (saved or synced). Either is fine,
   I need to know which.
3. Press **Save** on D002, power-cycle the Peak. Open Settings > MPE EXTRAS and
   tell me whether EnvSync is still **1/8**.
