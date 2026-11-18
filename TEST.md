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

## Series Q: MIDI tuning (image `MPEP Ver`)

New image v0.25 (boot screen `MPEP Ver 108.469`). Series A to P are done
(results in [docs/hardware-log.md](docs/hardware-log.md)).

What v0.25 adds: stock retunes single notes of a tuning table from MIDI
(MIDI Tuning Standard), but only for messages addressed to device 00 with
one note. The patch also takes the "all devices" address (7F), several
notes per message, and a whole table sent to 7F. Nothing new on the panel.

### Q1. Boot

1. Switch the Peak on. Expected boot screen: `MPEP Ver 108.469`, then the
   patch screen as usual.

### Q2. Tuning table 16

The rig check (Q3) writes tuning table 16 in the Peak's memory. That
doesn't touch what is stored: the stored table comes back at the next
power-up, unless table 16 is saved on its Settings page. So:

1. **Tell me if table 16 holds a tuning you use.** It's safe either way as
   long as it isn't saved after Q3, but I'd rather pick another table if
   it matters to you.

### Q3. Rig (I play)

Tell me what is plugged in (as for P4), then say **GO rig**. That GO also
covers the tuning SysEx (only the two tuning messages, table 16). I run:

- the regression run, `hwrig run --stage all`. Expected: 136 pass,
  0 fail, 5 info, as on v0.24.
- then `work/mts_check.py`: it builds a sine sound in the edit buffer (not
  saved) using table 16, retunes keys of table 16 with each kind of message
  and measures the pitch. Expected: every row within 3 cents of its target
  (+50, +25, +100, -100 cents, and +50 cents on a note already held).

### Q4. Afterwards

1. Switch the Peak off and on again (this brings back the stored table 16).
   Don't save anything on the `TUNINGTABLE 16` Settings page before that.
