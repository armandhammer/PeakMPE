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

## Series T: front-panel panic (image `MPES Ver`)

New image v0.28 (boot screen `MPES Ver 108.469`). Series A to S are done
(results in [docs/hardware-log.md](docs/hardware-log.md)).

What v0.28 adds: hold **Mod** and press **Audition** for a panic. Every note
stops at once, and a latched or stuck arp chord and keys whose note-off
never came are forgotten. Audition on its own is unchanged (middle C).

**The whole series uses D002.** Nothing is saved.

### T1. Boot

1. Switch the Peak on. Expected boot screen: `MPES Ver 108.469`, then the
   patch screen as usual.

### T2. Audition alone, and the panic on a held note (LinnStrument)

1. Select patch **D002**. Press and hold **Audition**: middle C sounds
   while you hold it, and stops when you let go (as stock).
2. Hold a pad on the LinnStrument so a note sounds, and keep holding it.
3. With the pad still held, hold **Mod** and press **Audition**, then let
   go of Audition and then of Mod. Expected: the note stops at once, one
   voice LED goes dark, and the screen shows for about 3 s:
   - top line `PANIC`
   - next line `All notes off`

   No middle C sounds. (Pressing Mod also opens the Mod menu, as usual;
   it comes back after the message.)
4. Let go of the pad. Expected: nothing happens. Play a pad again:
   expected, it sounds as usual.

### T3. A latched arp

1. Press the Arp **On** button and the **Key Latch** button (both lit).
2. Play a chord of three pads on the LinnStrument and let go. Expected:
   the arp keeps playing the chord (Key Latch).
3. Hold **Mod** and press **Audition**. Expected: the arp stops at once and
   the screen shows `PANIC` / `All notes off`; Arp **On** and **Key Latch**
   stay lit (settings are not changed).
4. Play a chord again and let go. Expected: the arp plays the new chord.
   **Tell me if it plays the old chord too.**
5. Press **Key Latch** and Arp **On** again to turn them off. Select patch
   **D001**, then **D002** (back to the stored test patch).

### T4. Rig (I play)

Say **GO rig**. I run the regression run, `hwrig run --stage all`.
Expected: 136 pass, 0 fail, 5 info (the stress test's silence row can fail
by its level rule alone; I re-run it if so). The rig can't press buttons,
so the panic itself is checked by T2 and T3.
