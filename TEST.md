# TEST.md: hands-on tests for you

Tests only you can do (they need the LinnStrument, the panel or your ears).
Each series has its own letter. Tell me the result of each step in a message
("C2.3: ok", "C4.2: the arrow was wrong"). Once I'm satisfied with a series I
delete it from this file and the next series uses the next letter, so a test
label never means two things.

Setup for all series: the Peak runs image `94629b81…` (boot screen
`MPE6 Ver`), the LinnStrument is on the Peak's **MIDI IN** over a 5-pin DIN
cable, and nothing else sends MIDI to the Peak (**quit Ableton and any other
MIDI app**: it caused a false rig failure on 2026-11-14). LinnStrument
settings are in [docs/linnstrument.md](docs/linnstrument.md).

---

## Series E: section copy, undo and the MIDI monitor

Image `MPEC Ver` (boot screen). Use D002 (or any patch you don't mind
changing; nothing is saved until you press Save).

### E1. Copy a section

1. Set **LFO 1** to something obvious (rate, waveform, phase). Note LFO 2's
   rate.
2. Settings > **COPY SECTION**. Item **Section**: turn the value to **LFO1>2**.
   Tell me what it shows for each click (expected: `-`, `Osc1>2`, `Osc1>3`,
   `Osc2>1`, `Osc2>3`, `Osc3>1`, `Osc3>2`, `Amp>E1`, `E1>Amp`, `Amp>E2`, `E2>Amp`,
   `E1>E2`, `E2>E1`, `LFO1>2`, `LFO2>1`).
3. Move to item **Do it** and turn it up once. Tell me what the screen says
   (expected: COPY SECTION, `Done:`, `LFO1>2`, `Undo: Mod + Page left`).
4. Open the LFO 2 pages and tell me whether LFO 2 now matches LFO 1 (rate,
   waveform, phase, fade).
5. Try one oscillator copy (`Osc1>2`) and one envelope copy (`Amp>E1`) the
   same way and tell me whether the target now matches.

### E2. Undo and redo

1. After a copy: **hold Mod** and press **Page left**. Tell me what the screen
   says (expected: UNDO, `Back one change`) and whether the section is back as
   it was.
2. Hold **Mod** and press **Page right**. Expected: REDO, `Change restored`,
   the copy is back.
3. Press **Page right** again. Expected: `Nothing to redo`.
4. Move a knob or slider (for example Filter Freq) a long way in one go, then
   wait about three seconds. Hold **Mod** and press **Page left**. Tell me
   whether the whole move is undone in one step.
5. Move Filter Freq, then move Resonance right away. Undo once and tell me which
   one goes back (expected: Resonance only).
6. Select another patch, then try the undo. Expected: `Nothing to undo`.
7. Does Mod + Page still work as page buttons in the Mod menu when you press
   Page without anything to undo? (Expected: while Mod is held the Page buttons
   only undo or redo; release Mod and they page again.)

### E3. MIDI monitor

1. Settings > **MIDI MONITOR**. Play a note on the LinnStrument. Tell me what
   **Last msg** shows (expected: a status byte and two data bytes in hex, for
   example `91 3C 64`) and how **Msg count** changes.
2. Bend a note. Tell me what Last msg shows (expected an `E` status).
3. **DIN ovfl** should be 0. Play something dense for a minute and tell me
   whether it changes.
