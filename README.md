# Summit MPE

An unofficial firmware patch that adds MPE (MIDI Polyphonic Expression) to
the Novation Summit: per-note pitch bend, pressure and Slide, switched on
per sound. It is applied on top of the official firmware, which you
download from Novation yourself, and can be undone at any time by flashing
the official file again.

> **Unofficial and vibe-coded.** This project and its firmware patch were
> built with an AI coding assistant. It is not affiliated with, endorsed by
> or supported by Novation or Focusrite. "Novation", "Focusrite" and
> "Summit" are their trademarks, used only to identify the instrument.
>
> The software and the patched firmware come **as is, without warranty of
> any kind** ([LICENSE](LICENSE)). Flashing modified firmware can void your
> warranty and may make your instrument unusable: **you do it entirely at
> your own risk.** The official firmware images are Novation's property.
> This repository never contains them; each user downloads their own copy
> from Novation.

## Status

**MPE v1.2**, for Summit firmware **2.2 (build 2121)** only, with FPGA
build 778. It has been played and measured on one Summit
([docs/hardware-log.md](docs/hardware-log.md)): every check of the
automated test rig passes over USB and DIN. It is not tested on a Peak, on
other firmware versions or on other units.

## What you get

- **MPE receiver (MPE 1.0):** Lower and Upper Zone, set by the sender's MPE
  Configuration Message or on the Summit's Settings MPE pages (zone, member
  count, bend ranges), saved with the global settings.
- **Per note:** pitch bend (±48 semitones by default, set by RPN 0),
  pressure and Slide (CC 74), on top of the master channel's bend, mod wheel
  and pressure.
- **Per sound:** an `MPE` switch on the VOICE page. With it off, the sound
  plays exactly as on stock.
- **Single and Multi mode:** one zone per part, or two zones on two parts.
- **Boot screen** `MPE3 Ver 126.778`, so you can see the patch is installed.

## Install

You need a computer with Chrome or Edge (for Web MIDI) or Python 3, a USB
cable, and the official Summit firmware 2.2 from Novation.

1. **Back up your sounds** with Novation Components: a firmware update can
   change or erase what's stored on the synth.
2. **Web patcher:** the page published from this repository (GitHub Pages,
   see [docs/web.md](docs/web.md)) checks your official file, applies the
   patch in your browser (nothing is uploaded), verifies the result against
   the expected checksum and flashes it over Web MIDI. Or download the
   patched `.syx` there for another tool.
3. **Or from a checkout:** build the image yourself and flash it with the
   included updater (setup in [docs/SETUP.md](docs/SETUP.md)):

   ```bash
   scripts/dev python -I tools/patch.py patches/mpe/patch.py --verify
   ```

   ```bash
   .venv/bin/python -I tools/flash.py flash work/patched/summit-firmware-2.2-build2121+mpe.syx --dry-run
   ```

   ```bash
   .venv/bin/python -I tools/flash.py flash work/patched/summit-firmware-2.2-build2121+mpe.syx
   ```

**Going back to stock:** flash the official file the same way, or with
Novation Components. If the synth doesn't start, hold the three buttons left
of the screen while switching it on: the bootloader is never modified, and
you can flash stock from there ([docs/recovery.md](docs/recovery.md)).

## Playing MPE

- Switch `MPE` on for a sound on the VOICE page.
- Set the zone on the Settings MPE pages, or let the sender's MPE
  Configuration Message set it. Ableton Live sends none: set the zone and
  member count to match Live's MPE settings.
- **Connect Ableton Live over USB**, not DIN: its MPE output played hard
  overruns DIN and can leave a note stuck.

Details, and what each sender does, in
[docs/mpe-design.md](docs/mpe-design.md#connecting-senders).

## How it works

The official firmware stays as it is. The patch is our own C code,
compiled for the Summit's Cortex-M4 and linked against the addresses of the
firmware functions it calls. It goes into free flash at the end of the
image, and about 40 call sites in the firmware are redirected into it. The
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
a real Summit is built by `scripts/build-image.sh` and recorded in the
hardware log ([docs/hardware.md](docs/hardware.md)). `CLAUDE.md` holds the
instructions the AI agent follows in this repository.

| Path | Contents |
|---|---|
| `docker/`, `scripts/dev`, `scripts/check`, `.github/workflows/` | The dev image (pinned Arm toolchain, LLVM, Python, Node; arm64 and amd64), the wrapper that runs builds and tests in it, the CI entry point, and the CI and release workflows |
| `patches/mpe/` | The MPE patch: C sources and the patch definition (hooks, byte patches) |
| `patches/version_string.py`, `patches/version_word.py`, `patches/demo_note_hook/` | Minimal patches that test the toolchain and the bootloader |
| `tools/patch.py`, `tools/patch_build.py` | Build a patched `.syx` from the official file and a definition ([docs/patch-howto.md](docs/patch-howto.md)) |
| `tools/flash.py` | Firmware updater (the Components protocol), with a dry run against a simulated synth |
| `tools/syx.py`, `tools/find_base.py` | Decode, encode and inspect update files |
| `emu/`, `tools/sim.py` | Unicorn-based simulator of the Summit's firmware: MIDI in, FPGA writes, display ([docs/SIMULATOR.md](docs/SIMULATOR.md)) |
| `tools/hwrig/` | Hardware test rig: MIDI out, the Summit's audio in, measured checks ([docs/hw-test-rig.md](docs/hw-test-rig.md)) |
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
