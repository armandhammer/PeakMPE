# Peak MPE

An unofficial firmware patch that adds MPE (MIDI Polyphonic Expression) to
the **Novation Peak**: per-note pitch bend, pressure and Slide, switched on
per sound, so an MPE controller such as a LinnStrument plays it with
per-finger expression. It is applied on top of the official firmware, which
you download from Novation yourself, and can be undone at any time by
flashing the official file again.

**Flash it from your browser: <https://armandhammer.github.io/PeakMPE/>**

This is a port of [Summit MPE](https://github.com/michaelkollmann/gipfel_mpe)
(MPE for the Summit, by Michael Kollmann and contributors) to the Peak. The
Summit patch, its tools and its documentation are still here
(`patches/mpe/`); the Peak work is in `patches/peak_mpe/` and the documents
named below.

> **Unofficial and vibe-coded.** This project and its firmware patch were
> built with an AI coding assistant. It is not affiliated with, endorsed by
> or supported by Novation or Focusrite. "Novation", "Focusrite", "Peak"
> and "Summit" are their trademarks, used only to identify the instrument.
>
> The software and the patched firmware come **as is, without warranty of
> any kind** ([LICENSE](LICENSE)). Flashing modified firmware can void your
> warranty and may make your instrument unusable: **you do it entirely at
> your own risk.** The official firmware images are Novation's property.
> This repository never contains them; each user downloads their own copy
> from Novation.

## Status

**MPE for Peak 0.29**, for Peak firmware **2.2 (build 2108)** only, with
FPGA build 469. Tested on one Peak ([docs/hardware-log.md](docs/hardware-log.md)):
every check of the automated hardware test rig that applies to the Peak
passes (136 of 136 measured rows over USB on each release up to 0.25; on
0.26 the stress test's silence row failed once by its level rule, as it
has before, and passed when re-run; 200 randomiser rolls measured on the
rig, none silent or clipped; on 0.27, which changes only the
randomiser's band-pass and high-pass ranges, 136 of 136 again and
band-pass rolls about 6 dB louder; 0.28 adds the front-panel panic,
checked on the synth; 0.29 runs the patch's own checks once a
millisecond, to leave the synth's main loop more time, rig 136 of 136), a 600-run stress soak left no stuck note, a LinnStrument played
it over DIN in one and two zones, and each feature below was tried on the
synth (by hand, or by the rig where the panel can't do it). Not tested on other firmware versions or other units.

The patch adds 12 pages to **Settings** (38 pages instead of 26): pages 5
to 16, right after `MIDI CONTROL`, from `MPE` to `RANDOMISE`. Their
settings are saved with the global settings, as stock's are. Each feature
below names its page. The three buttons beside the
screen, Select 1 to 3, pick a line; the encoder changes it.

## What you get

### MPE

- **MPE receiver (MPE 1.0):** a Lower and an Upper Zone, set by the
  sender's MPE Configuration Message or on Settings `MPE` (zone, member
  count) and `MPE BEND RANGE` (note and master bend ranges). Both zones (a
  LinnStrument split in two) play the one sound and share its 8 voices;
  each zone's master channel bends only its own notes.
- **Per note:** pitch bend (±48 semitones by default, set by RPN 0),
  pressure (channel pressure, polyphonic aftertouch or CC 11 on a member
  channel) and Slide (CC 74, arriving as the voice's mod wheel), on top of
  the master channel's bend.
- **Per sound:** an `MPE` switch on the VOICE page. With it off, the sound
  plays exactly as on stock.
- **Pressure curve:** Settings `MPE EXTRAS` > `PressCurve` chooses stock's
  squared curve or a linear one, which gives light pressure more range.
- **Release velocity:** Settings `RELEASE VEL` > `Source` set to `ExprPED1`
  or `BrthPED2` puts each note-off's velocity (how fast a note is let go,
  if the controller sends it) into that mod source, for that note only.
  Route the source to `AmpEnv R` (or a mod envelope's release) in the mod
  matrix and each note gets its own release. While it's on, that pedal
  (or CC 11 / CC 2) no longer drives the source. Works with MPE on or off.

### Playing

- **Glide start:** Settings `MPE EXTRAS` > `Glide`. In poly modes stock
  glides each note from whatever its voice played last. `LastNote` glides
  from the previous note you played; `Legato` does that only while another
  note is held, so a detached note starts on pitch. The patch's Glide
  settings still decide whether and how fast.
- **Envelope sync:** Settings `MPE EXTRAS` > `EnvSync` sets the amp
  envelope's Decay and Release to a note length (1/2 to 1/16) at the
  current tempo.
- **MIDI loop fix:** when a DAW sends the arpeggiator's own notes back to
  the Peak, the arpeggiator ignores them instead of retriggering itself.
- **Microtuning from tuning software:** stock retunes a note of a tuning
  table over MIDI (MIDI Tuning Standard), but only when the message is
  addressed to device 00 and carries one note. The patch also takes the
  "all devices" address (7F) that tuning software usually sends, several
  notes in one message, and a whole table (bulk dump) sent to 7F. Notes
  already sounding move at once. Pick the table with the patch's
  `TuningTable`; a received tuning is kept only if you save that table on
  its Settings `TUNINGTABLE` page.
- **Panic:** hold **Mod** and press **Audition**. Every note stops at once,
  and what stock's All Sound Off leaves behind is cleared too: keys whose
  note-off never came (in Mono they would sound again), a latched or stuck
  arp chord, and each channel's per-note bend, pressure and slide. The
  screen says `PANIC` / `All notes off`. Delay and reverb tails ring out.
- **Osc Fine over MIDI:** stock ignores Osc 1, 2 and 3 Fine values from −100
  to about −73 sent as CC 15, 18 or 21 (only the panel reaches them). The
  patch takes the whole −100 to +100.

### Arpeggiator

- **Euclidean rhythms:** Settings `ARP EUCLID` sets `Pulses`, `Steps` and
  `Rotate` (for example 5 in 8). The arpeggiator then plays that many notes
  spread evenly over the steps, in place of the patch's Rhythm. `Pulses`
  Off gives the Rhythm back.
- **Ratchets:** Settings `ARP RATCHET` > `Ratchet` x2 or x3 plays each arp
  note two or three times within its step; `Every` 1 to 8 ratchets only
  every nth note.

### Editing

- **Quick-assign modulation:** hold **Mod** and move a slider or knob. Its
  destination goes into the first free mod matrix slot, and the encoder
  chooses the source.
- **Undo and redo:** **Mod** + **Page left** undoes the last change, **Mod**
  + **Page right** redoes it.
- **Section copy:** Settings `COPY SECTION` copies an oscillator, an
  envelope or an LFO onto another (Osc 1 to Osc 2, Env 2 to Env 3, and so
  on).
- **Parameter lock:** Settings `PARAM LOCK` keeps the FX, the Arp or the
  Voice settings as they are when you load another patch.
- **Section randomiser:** Settings `RANDOMISE` rolls new values for one
  section of the sound (`Osc 1`, `Osc 2`, `Osc 3`, `Mixer`, `Filter`,
  `Amp Env`, `Mod Env1`, `Mod Env2`, `LFO 1`, `LFO 2`, `FX`, or `All`).
  `Amount` goes from a nudge (10 %: each value moves a tenth of the way
  to a random one) to a fresh roll (100 %). Values stay inside ranges
  meant to keep the sound playable: Osc 2 and 3 only move by musical
  intervals, the filter isn't left closed (band-pass and high-pass keep
  the cutoff where the note comes through, measured on the synth),
  resonance stays below
  self-oscillation, the mixer and FX levels are capped together, and a
  note with no sustain still decays slowly enough to hear. Turn `Roll` up to roll;
  **Mod** + **Page left** takes it back. Nothing is saved until you save.

### Movement

- **Motion recording:** hold **Mod** and press **Animate 1** (the screen says
  `Move a control`), then move a slider or knob. Its movement is recorded
  for one loop and then plays back in time with the tempo until you press
  Mod + Animate 1 again. Moving the control while it plays replaces what
  it passes over. Settings `MOTION` > `Length` sets 1, 2 or 4 bars. Not
  stored with the patch.
- **Patch morph:** with Settings `MORPH` > `Morph` set to `ModWheel`, the mod
  wheel blends the patch as you have edited it (wheel down) towards the
  patch as it is stored (wheel up). Load a patch, turn some knobs, and the
  wheel takes your changes out and brings them back. Levels, amounts, times,
  the filter, FX amounts and mod matrix depths move; switches, waves and the
  arp stay as edited, so nothing switches halfway. **Save** stores what you
  hear.

### Screen

- **Values in units:** turning a knob shows envelope times in ms and the
  filter cutoff in Hz, with a value bar.
- **Pickup arrow:** with stock's Pickup knob mode, the screen shows which
  way to turn and how far until the knob takes over.
- **MIDI monitor:** Settings `MIDI MONITOR` shows the last message
  received, a message count and the DIN input's overflow count.
- **Lighter screen updates:** the screen is sent only the characters that
  change. Stock rewrites whole lines, and every character holds up the
  per-note modulation for about 0.05 ms. Measured on the synth, turning a
  knob for 5 s lost 17 modulation ticks, against about 2,600 before.
- **Boot screen** `MPET Ver 108.469`, so you can see the patch and its
  release are installed.

What stock 2.2 already does (and so isn't here), and the features that were
looked at and dropped: [docs/peak-features.md](docs/peak-features.md).

## Install

You need a computer with Chrome or Edge (for Web MIDI), a USB cable, and the
official Peak firmware 2.2 from Novation.

1. **Back up your sounds** with Novation Components: a firmware update can
   change or erase what's stored on the synth.
2. **Open the [web patcher](https://armandhammer.github.io/PeakMPE/).** It
   checks your official file, applies the patch in your browser (nothing is
   uploaded), verifies the result against the expected checksum and flashes
   it over Web MIDI. Or download the patched `.syx` there for another tool.
3. **Or from a checkout** (Windows, PowerShell; setup in
   [docs/SETUP.md](docs/SETUP.md)): `scripts/build-image.sh
   patches/peak_mpe/patch.py` builds and verifies the image and prints the
   one-line flash command (`scripts/flash.ps1`).

**Going back to stock:** flash the official file the same way, or with
Novation Components. If the synth doesn't start, hold the **three buttons to
the left of the screen** while switching it on: the bootloader is never
modified, and you can flash stock from there
([docs/recovery.md](docs/recovery.md#peak)).

## Playing MPE

- Switch `MPE` on for a sound on the VOICE page.
- Route the mod wheel (where Slide arrives) and aftertouch (pressure) in the
  sound's mod matrix to hear Y and Z.
- Set the zone on Settings `MPE`, or let the sender's MPE Configuration
  Message set it (a LinnStrument sends one).
- With MPE on, the patch morph listens to the mod wheel (CC 1) on the zone's
  master channel; a LinnStrument's Low Row can send it
  ([docs/linnstrument.md](docs/linnstrument.md)).
- **LinnStrument:** connect its MIDI OUT to the Peak's MIDI IN with a 5-pin
  MIDI cable. A step-by-step guide for first-time LinnStrument users:
  [docs/linnstrument.md](docs/linnstrument.md).

## How it works

The official firmware stays as it is. The patch is our own C code,
compiled for the synth's Cortex-M4 and linked against the addresses of the
firmware functions it calls. It goes into free flash at the end of the
image, and a few dozen of the firmware's call sites are redirected into it. The
build checks the official file's SHA-256 and every patched site before it
writes anything, and a simulator runs the patched firmware's main loop for
the tests. More in [docs/PLAN.md](docs/PLAN.md#how-the-patch-works).

## Development

Builds and tests run in one pinned Docker image, so you need Docker
(OrbStack, Docker Desktop or Colima), git and a browser. Setup, with pinned
versions: [docs/SETUP.md](docs/SETUP.md). The tests need the official
firmware in `firmware/` (`scripts/fetch-firmware.sh` downloads and verifies
it) and skip without it.

```bash
scripts/fetch-firmware.sh --all
```

```bash
scripts/dev python -m pytest -q -n auto
```

The first `scripts/dev` builds the image (about 3 minutes). `scripts/check`
runs everything CI runs. Flashing and the
hardware test rig run natively, from a small venv (`requirements-hw.txt`).

How to contribute: [CONTRIBUTING.md](CONTRIBUTING.md) (fork, branch,
`scripts/check`, pull request; CI runs the full suite). Anything flashed to
a real synth is built by `scripts/build-image.sh` and recorded in the
hardware log ([docs/hardware.md](docs/hardware.md)). `CLAUDE.md` holds the
instructions the AI agent follows in this repository.

| Path | Contents |
|---|---|
| `docker/`, `scripts/dev`, `scripts/check`, `.github/workflows/` | The dev image (pinned Arm toolchain, LLVM, Python, Node; arm64 and amd64), the wrapper that runs builds and tests in it, the CI entry point, and the CI and release workflows |
| `patches/peak_mpe/` | The Peak MPE patch: C sources and the patch definition (hooks, byte patches) |
| `patches/mpe/` | The Summit MPE patch (upstream) |
| `docs/peak-port-plan.md`, `docs/symbols/peak-2.2-2108.csv` | The Peak port: plan, findings, status; the Peak's symbols |
| `docs/linnstrument.md` | Playing the Peak from a LinnStrument, step by step |
| `docs/peak-features.md` | Features beyond MPE: what stock 2.2 already does, the build order, what was dropped |
| `docs/peak-motion-morph.md` | Motion recording and patch morph: what was found in the firmware, the design and its measurements |
| `TEST.md` | Hands-on test steps for the synth, while a series is open |
| `patches/peak_version_string.py`, `patches/peak_version_word.py`, `patches/peak_demo_note_hook/` (and the Summit's) | Minimal patches that test the toolchain and the bootloader |
| `tools/patch.py`, `tools/patch_build.py` | Build a patched `.syx` from the official file and a definition ([docs/patch-howto.md](docs/patch-howto.md)) |
| `tools/flash.py` | Firmware updater (the Components protocol), with a dry run against a simulated synth |
| `tools/syx.py`, `tools/find_base.py` | Decode, encode and inspect update files |
| `emu/`, `tools/sim.py` | Unicorn-based simulator of the Summit's and the Peak's firmware: MIDI in, FPGA writes, display ([docs/SIMULATOR.md](docs/SIMULATOR.md)) |
| `tools/hwrig/` | Hardware test rig: MIDI out, the synth's audio in, measured checks ([docs/hw-test-rig.md](docs/hw-test-rig.md)) |
| `tools/mmon.py`, `tools/midirec.py` | Read MIDI Monitor captures; record MIDI inputs to a log ([docs/hardware.md](docs/hardware.md#recording-midi)) |
| `web/`, `tools/web_descriptor.py` | The web patcher and flasher, and the export of its patch descriptor ([docs/web.md](docs/web.md)) |
| `tests/` | pytest suite: the simulator, the patch, the tools |
| `docs/mpe-design.md` | The MPE design and its evidence |
| `docs/findings/`, `docs/symbols/` | The firmware map, with addresses and confidence labels; the symbols CSV |
| `docs/firmware-format.md`, `docs/update-protocol.md`, `docs/recovery.md` | Update file format, update protocol, getting back to stock |
| `docs/PLAN.md`, `docs/hardware-log.md` | Where the project stands and what's open; every release flashed |
| `scripts/` | Setup, firmware download, Ghidra import, disassembly, the image build for a flash |
| `tools/ghidra/` | Ghidra scripts: memory map, symbols, decompile |
| `firmware/`, `work/` | Official images and generated output (both git-ignored) |

## License

MIT for this repository's own code and documentation ([LICENSE](LICENSE)).
It does not cover Novation's firmware, which is never part of this
repository.
