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

## Series C: quick-assign modulation

Image `MPE8 Ver` (boot screen). Use any sound; D002 with the `mt` sound is fine.
Before you start, look at **Mod menu** slots 1 to 3 (Mod button, then Page
buttons) and tell me what they hold. Empty slots read `Direct`, `Direct`,
depth 0.

### C1. Hold Mod and move a control

1. Press and **hold** the **Mod** button. The Mod menu appears as usual.
2. While holding it, move the **Filter Freq** control. Tell me what the screen
   says (expected: QUICK ASSIGN, a slot number, `Lfo1+`, `FiltFreq`).
3. Let go of Mod. Page through the Mod menu to the slot it named. Tell me
   what Source A, Source B, Depth and Destination show (expected: Lfo1+,
   Direct, +32, FiltFreq).
4. Play a note. Tell me whether the filter now moves with LFO 1.

### C2. Choosing the source

1. Hold **Mod** and turn the **encoder**. Tell me what the screen says each
   click (the source name should change). Stop on **Mod Env 1**.
2. Still holding Mod, move the **Amp Release** slider. Tell me the slot,
   source and destination it reports.
3. Release Mod and check that slot in the Mod menu.

### C3. Edge cases

1. Hold **Mod** and move **Filter Freq** again, twice. Tell me whether it
   makes a second slot (expected: no).
2. Hold **Mod** and move **Key Track**. Tell me what the screen says
   (expected: "No mod destination").
3. Without holding Mod, move a control and turn the encoder. Tell me whether
   everything behaves as before (no slot is created, the encoder edits values).
4. Does moving a control while holding Mod change that control's value as
   well? Tell me what you saw (known: it does, as the control always moves).
