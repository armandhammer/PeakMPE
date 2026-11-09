# Plan

**Goal:** an MPE mode for the Novation Summit that can be switched on and
off, added as a patch on top of the official firmware:

1. Build the patch from our own C code and the user's own copy of the
   official firmware.
2. Test it in emulation.
3. Flash it with our own updater (`tools/flash.py`, or the web patcher).
4. Always keep the stock firmware one re-flash away.

Nothing goes onto a real Summit until the emulator tests pass on that exact
build ([hardware.md](hardware.md)).

## Where it stands

**MPE v1.2 is hardware-verified** on one Summit (firmware 2.2, build 2121,
FPGA 778): per-note pitch bend (±48), pressure and Slide, a per-patch MPE
switch, Settings MPE pages, Lower and Upper Zone, Single and Multi mode, and
idle voices that rotate as on stock ([hardware-log.md](hardware-log.md)).
The design and its evidence are in [mpe-design.md](mpe-design.md).

What the project is built on:

| Part | Docs |
|---|---|
| Update format and the Components update protocol | [firmware-format.md](firmware-format.md), [update-protocol.md](update-protocol.md) |
| Firmware map: MIDI → voice → FPGA, settings, display, free space | [findings](findings/summit-2.2-build2121.md), [symbols](symbols/summit-2.2-2121.csv) |
| Simulator: the firmware's main loop with MIDI in, FPGA writes, display | [SIMULATOR.md](SIMULATOR.md) |
| Patch toolchain: C patches linked against the firmware's symbols, hooks, re-encode | [patch-howto.md](patch-howto.md) |
| Flasher and recovery | [update-protocol.md](update-protocol.md), [recovery.md](recovery.md) |
| Hardware test rig: MIDI out, the Summit's audio in, measured checks | [hw-test-rig.md](hw-test-rig.md) |
| Web patcher and flasher | [web.md](web.md) |

### How the patch works

We don't have the source, and decompiler output is a reading aid, not code
that can be recompiled. So the shipped firmware stays as it is and we add
to it:

1. **Hook points:** the few call sites where MIDI messages are dispatched,
   voices are allocated and per-voice pitch and modulation are computed.
2. **New code in C** (`patches/`), compiled with `arm-none-eabi-gcc`
   (Thumb-2, freestanding) and linked against a symbols file that gives
   firmware functions and globals their fixed addresses. It goes into free
   flash at the image end.
3. **Hooks redirected:** `tools/patch.py` checks each site holds the expected
   call and replaces it with a call into the patch code.
4. **Re-packed** as a `.syx`, checked by hash, and tested in the simulator
   before it's flashed.

Only patch sources and tools are in the repository, never firmware or
patched images. Every user builds from their own download of the official
file.

## Open

- **More senders:** captures of other MPE controllers (and the Squarp
  Hapax, complete) as test vectors, replayed like the pinned Ableton Live
  capture in `tests/test_mpe_conformance.py`.
- **B1:** twice on hardware, the first chord after a Hapax zone change
  played one note fewer. Not reproduced since (600 rig trials, simulator).
- **Web patcher:** one real flash with the web flasher before it's
  published, and deployment with the release workflow ([web.md](web.md)).
- **Version mark for C patches** is a byte patch in each definition, not
  automatic.
- **Analysis:** a diff against Peak 2.2 to carry names over (shared code
  base); an STM32F429 SVD file for peripheral names; calling single firmware
  functions directly from the harness.
- **Simulator:** pots and pedals (ADC1, multiplexer, DMA); a measured FPGA
  reply model (envelope states) and EXTI15 rate in place of the inferred
  ones.
- **Test rig:** latency calibration with a loopback cable; replaying dense
  captures and failing takes ([hw-test-rig.md](hw-test-rig.md#status-and-open-items)).
- **Prior art:** ReplicantPeak emulates the Peak's STM32F429 firmware in
  Rust (MIT). Worth studying for its peripheral map and FPGA interface.

## Risks and how we handle them

| Risk | Mitigation |
|---|---|
| The bootloader rejects modified images | Answered: it accepts changed bytes, a changed version word and longer images, and stock restores over them ([update-protocol.md](update-protocol.md#6-checksums-and-validation-what-would-reject-a-modified-image)). A check of only the vector table or the `MAIN` tag isn't ruled out |
| A bad image bricks the synth | The update writes the vector table last, so an interrupted write never boots, and the bootloader (`< 0x0800C000`) is never touched: hold the three buttons left of the screen at power-on and flash stock ([recovery.md](recovery.md)) |
| Not enough free flash | The patch uses about 5 KB at the image end, below `0x08060000` ([findings](findings/summit-2.2-build2121.md#integrity-and-free-space)) |
| Firmware updates from Novation | Patches target one pinned build, checked by SHA-256; a new build needs its symbols re-mapped |
| Legal | Never redistribute Novation's firmware; ship only our patch code, its hashes and the tooling |

## Decisions

- **Binary patch, not a rebuild:** see "How the patch works" above.
- **Opening the Summit:** not needed. The MCU is identified from firmware
  evidence (peripheral addresses, RAM size), and the bootloader's
  integrity checks were answered by flashing modified images.
- **FPGA:** never touched. The patch only changes what the MCU sends to it.
