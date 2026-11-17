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

## Series N: Osc Fine over MIDI (image `MPEM Ver`)

New image v0.22 `e7b5ec86…` (boot screen `MPEM Ver 108.469`). Series A to M
are done (results in [docs/hardware-log.md](docs/hardware-log.md)).

What v0.22 changes: stock ignores Osc 1, 2 and 3 Fine values from −100 to
about −73 cents when they arrive over MIDI (CC 15, 18, 21); only the panel
reaches them. v0.22 takes the whole −100 to +100. The panel can't send
that, so the rig checks it (N3). Your part: the boot label, and that the
Fine knob itself behaves exactly as before.

### N1. Boot

1. Switch the Peak on. Expected boot screen: `MPEM Ver 108.469`.

### N2. The Fine knob is unchanged

1. Select patch **D002** (the test patch: the Init sound with `MPE` On).
2. Turn **Osc 1**'s **Fine** knob (Oscillator section) fully anticlockwise.
   If the bottom line shows an arrow (`<` or `>`), Pickup is holding the
   knob back: keep turning until the arrow is gone. Expected: top line
   `O1Fine`, second line `  current -100`, bottom line a bar from the middle
   to the left edge.
3. Turn it fully clockwise. Expected: `  current +100`, the bar from the
   middle to the right edge.
4. Turn it back until the second line reads `  current   +0`. Expected:
   no bar on the bottom line. Don't save: the rig builds its own sound.

### N3. Rig (I play)

Tell me what is plugged in (as for M8), then say **GO rig**. I run two
things over USB, with you hands off:

- `work/fine_check.py`: holds A5 on the rig's sine and sends CC 15 through
  64, 28, 14, 64, 20, 64, 0, 114, 127, 64, measuring the pitch each time.
  Expected: CC 14 about 28 cents below CC 28 (−100 against −72), CC 0
  the same as CC 14, CC 127 the same as CC 114, and CC 20 moves the pitch.
- The regression run, `hwrig run --stage all`. Expected: 136 pass, 0 fail,
  5 info, as on v0.21.
