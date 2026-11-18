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

## Series O: the screen sends only what changes (image `MPEN Ver`)

New image v0.23 `988f7a59…` (boot screen `MPEN Ver 108.469`). Series A to N
are done (results in [docs/hardware-log.md](docs/hardware-log.md)).

What v0.23 changes: stock rewrites whole lines of the screen every time
anything on it changes, and each character holds up the per-note
modulation for about 0.05 ms. v0.23 sends only the characters that differ
from what the screen already shows. Nothing should look different; the
point of this series is that the screen is still right everywhere, and
that turning a knob now costs far fewer modulation ticks (O4 repeats M7).

### O1. Boot

1. Switch the Peak on. Expected boot screen: `MPEN Ver 108.469`, then the
   patch screen as usual.

### O2. Knob overlay and pickup

1. Select patch **D002** (the test patch: the Init sound with `MPE` On).
2. Turn the **Filter Frequency** knob fully anticlockwise (if the bottom
   line shows an arrow, keep turning until it is gone), then slowly fully
   clockwise. Expected: top line `FiltFreq`, the second line `  current`
   with a value in Hz rising to about `23.7kHz`, the third line `saved val`
   with the patch's value, and a bar on the bottom line growing from the
   left edge to the right edge. Report any character left over from an
   earlier value (for example `23.7kHzz` or a stray digit). Don't save.
3. Wait until the screen goes back to the patch screen (about 3 s).
   Expected: the patch screen exactly as before, no bar pieces on it.
4. Turn **Amp Env Attack** (slider) up and down once. Expected: top line
   `AmpAttack`, the value in ms or s, the bar following the slider.
5. Press **Settings**, then press **Page ►** about fifteen times, one page
   at a time, then **Page ◀** back to the first page. Expected: every
   page's text complete, nothing left over from the page before (a
   leftover would look like a stray letter or digit after a shorter
   name or value). Press **Settings** again to leave.

### O3. Screen saver

1. Leave the Peak untouched until the screen goes dark (the screen
   saver; about 10 minutes by the firmware's timeout). Do this whenever it
   suits you, for example after O5. Then turn any knob. Expected: the
   screen comes back with the knob's overlay complete (name, `  current`,
   `saved val`, bar), not a partly blank or garbled screen.

### O4. Late ticks while a knob turns (as M7)

1. Press **Settings** and go to `MOTION         11/36`. **Tell me the
   bottom line** (it reads `LateTicks` and two numbers).
2. Press **Page ►** once (the MORPH page). Turn the **Filter Frequency**
   knob back and forth for about five seconds without stopping. Wait until
   the MORPH page is back (about 3 seconds).
3. Press **Page ◀** once (the MOTION page). **Tell me the bottom line
   again.** On v0.21 the two readings were `5012 6` and `7657 9` (about
   2,600 ticks lost in those 8 s, longest gap 9 ms); v0.23 should lose far
   fewer.

### O5. Rig (I play)

Tell me what is plugged in (as for N3), then say **GO rig**: the
regression run, `hwrig run --stage all`. Expected: 136 pass, 0 fail,
5 info, as on v0.22.

Afterwards press **Settings** to leave the menu; nothing in this series
changes a setting or the patch.
