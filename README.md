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

**MPE for Peak 0.1**, for Peak firmware **2.2 (build 2108)** only, with FPGA
build 469. Tested on one Peak ([docs/hardware-log.md](docs/hardware-log.md)):
every check of the automated hardware test rig that applies to the Peak
passes (136 of 136 measured rows over USB), a 600-run stress soak left no
stuck note, and a LinnStrument played it over DIN in one and two zones. Not
tested on other firmware versions or other units.

## What you get

- **MPE receiver (MPE 1.0):** a Lower and an Upper Zone, set by the
  sender's MPE Configuration Message or on the Peak's Settings MPE pages
  (zone, member count, bend ranges), saved with the global settings. Both
  zones (a LinnStrument split in two) play the one sound and share its 8
  voices; each zone's master channel bends only its own notes.
- **Per note:** pitch bend (±48 semitones by default, set by RPN 0),
  pressure (channel pressure, or polyphonic aftertouch on a member channel)
  and Slide (CC 74, arriving as the voice's mod wheel), on top of the master
  channel's bend.
- **Per sound:** an `MPE` switch on the VOICE page. With it off, the sound
  plays exactly as on stock.
- **Boot screen** `MPE1 Ver 108.469`, so you can see the patch is installed.

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
- Set the zone on the Settings MPE pages, or let the sender's MPE
  Configuration Message set it (a LinnStrument sends one).
- **LinnStrument:** connect its MIDI OUT to the Peak's MIDI IN with a 5-pin
  MIDI cable. A step-by-step guide for first-time LinnStrument users:
  [docs/linnstrument.md](docs/linnstrument.md).

## How it works

The official firmware stays as it is. The patch is our own C code,
compiled for the synth's Cortex-M4 and linked against the addresses of the
firmware functions it calls. It goes into free flash at the end of the
image, and the firmware's call sites (37 on the Peak) are redirected into it. The
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
| `docs/peak-features.md` | Features beyond MPE: what stock 2.2 already does, and the build order |
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
