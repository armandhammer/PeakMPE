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

## Series P: release velocity (image `MPEO Ver`)

New image v0.24 (boot screen `MPEO Ver 108.469`). Series A to O are done
(results in [docs/hardware-log.md](docs/hardware-log.md)).

What v0.24 adds: a new Settings page, `RELEASE VEL`, with one item,
`Source` (`Off`, `ExprPED1`, `BrthPED2`). Set to a pedal source, each
note-off's velocity (how fast the note is let go, if the controller sends
it) goes into that mod source, for that note's voice only. Route the
source to `AmpEnv R` in the mod matrix and each note gets its own release
time. While it's on, that pedal (or its CC: 11 for ExprPED1, 2 for
BrthPED2) no longer drives the source.

### P1. Boot

1. Switch the Peak on. Expected boot screen: `MPEO Ver 108.469`, then the
   patch screen as usual.

### P2. The Settings page

1. Press **Settings** and press **Page ►** until the top line reads
   `RELEASE VEL    15/37` (one page after `ARP RATCHET    14/37`).
   Expected Select 1 line: `Source     Off`.
2. Press **Select 1** and turn the **Value** knob one click clockwise.
   Expected Select 1 line: `Source     ExprPED1`.
3. Turn the **Value** knob one more click clockwise. Expected:
   `Source     BrthPED2`. Leave it there for P4 and P5.
4. Press **Page ►** once. Expected top line `MIDI ENABLE    16/37` (the
   first stock page after ours).

### P3. Does the LinnStrument send release velocity?

Only if the LinnStrument is connected (DIN into the Peak).

1. In Settings, go to the page whose top line reads
   `MIDI MONITOR   10/37`.
2. Press one LinnStrument pad and **lift your finger quickly**. **Tell me
   the Select 1 line** (`Last msg` and three hex numbers, for example
   `Last msg  80 3C 5A`).
3. Press the same pad and **lift your finger slowly**. **Tell me the
   Select 1 line again.** If the first number starts with `8` and the last
   number differs between the two lifts, the LinnStrument sends release
   velocity. If it starts with `9` and ends in `00`, it doesn't (it sends
   note-offs as note-ons with velocity 0), and the feature has nothing to
   work with from it.

### P4. Rig (I play)

Leave `Source` at `BrthPED2` (P2). Tell me what is plugged in (as for
O5), then say **GO rig**. I run two things:

- the regression run, `hwrig run --stage all`. Expected: 136 pass,
  0 fail, 5 info, as on v0.23.
- then `work/relvel_check.py`: it builds a sine sound in the edit buffer
  (not saved) with matrix slot 1 = `BrthPED2` x `Direct` to `AmpEnv R`,
  plays one note at a time and lets each go with a different note-off
  velocity, and measures the release. Expected: a note let go at velocity
  127 rings clearly longer than one let go at velocity 1, every time.

### P5. By ear (after P4, only with the LinnStrument)

P4 leaves its sound in the edit buffer.

1. Play single pads on the LinnStrument. Lift some quickly and some
   slowly. Expected (if P3 showed release velocity): a quick lift gives a
   longer tail than a slow lift. (A negative `Depth` in the slot would
   make it the other way round.)
2. Hold two pads, lift one quickly and the other slowly. Expected: each
   note's tail has its own length.
3. Press **Settings**, go back to `RELEASE VEL    15/37`, press
   **Select 1** and turn the **Value** knob two clicks anticlockwise to
   `Source     Off`. Press **Settings** to leave. Don't save the patch.
