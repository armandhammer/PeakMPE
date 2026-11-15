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

## Series D: parameter lock

Image `MPEB Ver` (boot screen). You need two patches that sound different, with
different FX and arp settings. Use D002 and any other patch.

### D1. The settings page

1. Open **Settings** and find the page **PARAM LOCK**. Tell me the page number
   (it comes after MPE EXTRAS).
2. It should list **Lock FX**, **Lock Arp** and **Lock Voice**, all **Off**.
   Tell me what it shows.

### D2. Lock FX

1. On D002, set the FX to something obvious: raise the **Delay** level and the
   **Reverb** level (or the Chorus level) clearly.
2. Settings > PARAM LOCK > **Lock FX** = **On**.
3. Select the other patch. Tell me whether the FX levels stayed (the delay and
   reverb you set on D002 should still be there on the other patch).
4. Select D002 again. Tell me whether D002's own saved FX levels are back or
   the ones you set (expected: the ones you set; nothing is stored in D002
   until you Save).
5. **Lock FX** = **Off**, select the other patch, and tell me whether it now
   has its own FX again.

### D3. Lock Arp

1. Set the arp tempo to **140 BPM** on D002 and turn the arp on.
2. Settings > PARAM LOCK > **Lock Arp** = **On**.
3. Select the other patch. Tell me the arp tempo and whether the arp is on.
4. **Lock Arp** = **Off**.

### D4. Lock Voice

1. On D002 set the voice **Mode** to **Mono** (VOICE page).
2. **Lock Voice** = **On**. Select the other patch. Tell me whether it plays
   mono (expected: yes).
3. **Lock Voice** = **Off**.

### D5. Saved with the Settings

1. Set **Lock FX** = **On**. Press the panel **Save** while inside Settings.
2. Power-cycle the Peak and check that **Lock FX** is still **On**. Set it back
   to **Off** and Save again.
