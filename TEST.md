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

## Series M: the rig run again (image `MPEL Ver`, v0.21)

M1 to M7 passed on 2026-11-17 (results in
[docs/hardware-log.md](docs/hardware-log.md)). The rig run (M8) gave 126
pass, 3 fail: in the Slide check every note was 2 semitones sharp, which is
what the mod wheel at full does in that test sound. The LinnStrument's
lowest row in Fader mode keeps the last value you slid to, and the rig never
set the wheel back to 0. It does now, at the start of every check.

### M8. Regression run, second try (I play)

1. Touch the LinnStrument's lowest row at its left end and lift (the wheel
   to 0, in case). Keep your hands off the LinnStrument and the Peak while
   the run plays.
2. Write **GO rig**. I run `tools/hwrig run --stage all --yes` (about
   5 minutes, Ableton and Focusrite Control closed). Expected: 136 pass,
   0 fail, 5 info, as on v0.18.

To put things back afterwards: on the LinnStrument Low Row **NORMAL** if you
want the row to play notes again.
