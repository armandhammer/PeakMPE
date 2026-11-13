# Playing the Peak MPE patch from a LinnStrument

A step-by-step guide for someone who has never used a LinnStrument. It
covers hooking it up, the LinnStrument settings, and the tests that finish
phase 6 step 6 of the [port plan](peak-port-plan.md). Every LinnStrument name
below is as printed on its panel and in Roger Linn Design's manual
([Panel Settings](https://www.rogerlinndesign.com/support/linnstrument-support-panel-settings),
software 2.3.4; [Getting Started](https://www.rogerlinndesign.com/support/linnstrument-getting-started);
[Hooking It Up](https://www.rogerlinndesign.com/support/support-linnstrument-hooking-it-up)).

Written for the full-size LinnStrument (200 pads, 25 columns). The
LinnStrument 128 (16 columns) has the same settings, but its panel is
smaller and it has no power jack. Where this guide says "column 15", count
playing columns from the left on the settings screen; the manual's panel
picture shows the labels.

## Words used here

- **Pad**: one of the square, lit touch pads. The playing surface is rows
  and columns of pads. Each row is a run of semitones, like a guitar string;
  the row above is a fourth higher (the default).
- **Control buttons**: the column of buttons at the far left, outside the
  playing surface: **Per-Split Settings**, **Preset**, **Volume**,
  **Octave/Transpose**, **Switch 1**, **Switch 2**, **Split**, **Global
  Settings** (and the step sequencer). They aren't notes.
- **Settings screen**: when you press **Per-Split Settings** or **Global
  Settings**, the button lights and the pads stop playing notes. Each column
  of pads becomes one setting, and the words printed on the panel next to
  the pads name the choices. A lit pad is the current choice; tap another
  pad in the same column to change it. Press the same control button again
  to leave the screen. (Holding it instead of tapping shows the screen only
  while you hold it.)
- **X, Y, Z**: the three things a finger does on a pad. **X** is sliding left
  and right (pitch bend, per note). **Y** is sliding up and down within the
  pad ("Timbre", sent as CC 74; the Peak patch calls it Slide). **Z** is how
  hard you press ("Loudness", sent as pressure).
- **Split**: the surface can be one instrument, or split into a left and a
  right half with their own settings. **Per-Split Settings** edits one half at
  a time.
- **MPE**: the LinnStrument sends each note on its own MIDI channel, so each
  note's X, Y and Z reach only that note. The LinnStrument calls this MIDI
  Mode **ChPerNote** (Channel Per Note). The **Main** channel carries what
  applies to all notes; the **Per-Note** channels carry the notes.
- **Zone**: MPE's name for a group of channels: one Main channel plus its
  Per-Note channels. The left split is the Lower Zone (Main channel 1), the
  right split the Upper Zone (Main channel 16).

## What you need

1. The LinnStrument and its USB cable.
2. Power for it: either the computer (the USB cable) or any standard USB
   power adapter (a phone charger). It draws about 260 mA; an unpowered USB
   hub may not be enough.
3. **A standard 5-pin MIDI cable** (round DIN plugs at both ends). The
   LinnStrument plugs straight into the Peak with it; no computer is needed
   in between.
4. The Peak with the MPE firmware on it (boot screen `MPE1 Ver 108.469`) and
   the patch slot that has VOICE `MPE` On (D002, the one you saved for the
   rig). The rig's LinnStrument sound, below, builds on it.

## 1. Connect

1. Plug the MIDI cable into the LinnStrument's **MIDI OUT** jack and into the
   Peak's **MIDI IN** jack (rear panel). Only OUT → IN matters; the
   LinnStrument's MIDI IN isn't needed.
2. Power the LinnStrument over USB (computer or USB adapter). Its pads light
   up.
3. Keep the Peak connected to the computer over USB as it is now: the rig can
   then load sounds and record while you play. It doesn't interfere; the Peak
   takes DIN and USB at once.

## 2. Reset the LinnStrument to factory settings (recommended)

So that these steps start from known settings (this doesn't touch its
sensor calibration or step sequencer):

1. Press **Global Settings** (left control column). It lights.
2. Find column 16, **Actions**. Press **NOTES OFF** and **UPDATE OS** at the
   same time.
3. Press **Global Settings** again to leave.

While you're on that column: **OS VERS** shows the LinnStrument's software
version. This guide follows 2.3.4; tell me if yours is older.

## 3. Send MIDI out of the 5-pin jack

Out of the box the LinnStrument sends MIDI over USB only.

1. Press **Global Settings**.
2. Column 15, **Power/MIDI** (on older units labelled **MIDI I/O**): press
   **MIDI JACKS** so it's lit. (Not "THRU", which is a hidden option of the
   same pad: just tap, don't hold and swipe.)
3. Press **Global Settings** again to leave.

## 4. One split in MPE (the main test)

1. Make sure the surface is one instrument: if the **Split** button is lit,
   press it once so it goes dark.
2. Press **Per-Split Settings**. In column 15, **Select Split**, make sure
   **LEFT** is lit (with Split off, the whole surface uses the left split's
   settings).
3. Column 1, **MIDI Mode**: **press and hold ChPerNote for one second**
   until it turns light blue. That one press sets MPE: Main channel 1,
   Per-Note channels 2 to 8, bend range ±48, Y as CC 74, Z as channel
   pressure. The LinnStrument also tells the Peak about the zone (an MPE
   Configuration Message), so the Peak needs no setting for it.
4. Check column 8, **Pitch/X**, so that slides are smooth:
   - **ON** lit (sliding bends pitch);
   - for testing, **QUANTIZE** off, **QUAN HOLD** off, **QHOLD FAST** off
     (no pitch correction: the pitch follows your finger exactly). You can
     turn QUANTIZE back on later for in-tune note starts.
5. Press **Per-Split Settings** again to leave.

On the Peak, load the LinnStrument sound. Either:
- tell me, and I load it over USB (`hwrig setup ls`: the Init saw with the
  filter half closed; Y opens the filter, Z opens it a little and makes the
  note louder). It goes into the edit buffer only; save it on the Peak if you
  like it; or
- select D002 (the Init sound with MPE on). It plays and bends, but Y and Z
  do nothing audible, because the Init sound routes neither the mod wheel
  (where Slide arrives) nor aftertouch anywhere.

**Play and check** (tell me what you hear for each):

| Do this | You should hear |
|---|---|
| Press one pad and hold it | one note |
| While holding, slide the finger left/right along the row | that note bends smoothly, following your finger; back where you started it's in tune |
| Hold two notes; slide only one | only that note bends; the other stays put |
| Slide a finger up/down within its pad (LS sound) | that note gets brighter/darker; held notes under other fingers don't change |
| Press one note harder (LS sound) | that note gets louder and a little brighter; the others don't |
| Hold 8 notes, then add a 9th | the 9th sounds and one held note stops (the Peak has 8 voices) |
| Let go of everything | silence: no note keeps sounding |

If a note keeps sounding after you let go, that's a stuck note: note which
pad and what you did, then stop it with **Global Settings** → column 16
**NOTES OFF** (or by changing the Peak's patch).

## 5. Both splits at once (two zones)

1. Press **Split** so it lights. To move the split point, hold **Split** and
   drag a finger across the surface; let go where you want it.
2. Press **Per-Split Settings**, set column 15 **Select Split** to
   **RIGHT**, and hold **ChPerNote** (column 1) for one second. The right half
   becomes the Upper Zone: Main channel 16, Per-Note channels 9 to 15.
3. Press **Per-Split Settings** again to leave.

Check: hold a note in each half; slide one; only it bends. Both halves play
the same Peak sound and share its 8 voices.

## 6. More Per-Note channels (15)

With **Split** off and Per-Split Settings on the LEFT split:

1. Column 2, **View**: press **PerNoteChs**. Columns 3 to 6 now show the 16
   channels; lit ones are in use (2 to 8 after the quick setup).
2. Tap channels **9 to 16** so they light too, to use channels 2 to 16 (all
   but the Main channel 1).
3. Leave with **Per-Split Settings**.

Play fast and with many notes: with 15 channels on 8 voices, the Peak hands
voices around much more. Listen for notes that don't sound, cut off early, or
keep sounding.

## 7. Z as poly pressure

Some LinnStrument users send Z as polyphonic aftertouch. The Peak patch
treats it the same as channel pressure.

1. **Per-Split Settings** → column 10, **Loudness/Z**: press **POLY PRES**.
2. Leave, play: pressing harder on one note (LS sound) should again change
   only that note.
3. Set it back to **CHAN PRES** when done (the quick setup's choice).

## 8. Long playing

Play for several minutes, densely: chords, fast runs, lots of sliding and
pressure. Tell me before you start: I can record the Peak's output during
that time and check afterwards that every note ended.

## What to tell me afterwards

For each step: what you heard, and anything odd (a note that didn't sound,
cut off, kept sounding, a jump in pitch, a click). The LinnStrument's model
(200 or 128) and software version (OS VERS) too. I record the results in the
[hardware log](hardware-log.md).

## Undo

- LinnStrument: the factory reset (step 2) undoes everything here, MIDI JACKS
  included.
- Peak: nothing is saved by these steps unless you save a sound yourself.
