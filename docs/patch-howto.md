# How to write a patch

A patch adds code to the official Summit 2.2 image without recompiling it
([PLAN.md](PLAN.md#how-the-patch-works)). There
are two kinds, and one definition file can mix them:

- **byte patches:** declared (address, original, new) edits, such as
  [`patches/version_string.py`](../patches/version_string.py);
- **C patches:** C code compiled into a blob appended to the image, plus
  hooks that send firmware code into it. The example is
  [`patches/demo_note_hook/`](../patches/demo_note_hook/).

Setup: the dev image has `arm-none-eabi-gcc` (Arm GNU Toolchain 15.3.rel2)
and LLVM; run the commands through `scripts/dev` ([SETUP.md](SETUP.md)).
The official image comes from `scripts/fetch-firmware.sh`.

## Build and check

```bash
scripts/dev python -I tools/patch.py patches/demo_note_hook/patch.py --verify
```

It writes `work/patched/summit-firmware-2.2-build2121+<NAME>.syx` and prints:
- the byte runs that differ;
- every hook (site, stock target, new target);
- the flash and RAM budget;
- with `--verify`, the disassembly checks below.

Build output (objects, ELF, map, linker files) goes to `work/build/<NAME>/`.
Nothing under `work/` is committed. Before anything goes near hardware, the
emulator tests must pass, and `scripts/build-image.sh` prepares the flash
([hardware.md](hardware.md)).

## Layout

```
patches/
  common/            linked into every C patch
    patch.ld           linker script
    firmware.h         firmware prototypes and globals, with confidence notes
    start.c            __patch_start: zero patch RAM, patch_init(), main_loop
    mem.c              memset/memcpy (there is no libc)
  <name>/
    patch.py           the definition: SOURCE, NAME, PATCHES, SOURCES, HOOKS
    *.c                the patch code
```

A definition for a C patch:

```python
SOURCE = "summit-firmware-2.2-build2121.syx"
NAME = "demo-note-hook"
PATCHES = []                       # byte patches, may stay empty
SOURCES = ["demo.c"]               # relative to this file
HOOKS = [
    # (kind, site, expected original, patch symbol, why)
    ("pointer", 0x0804C058, 0x08010AB1, "demo_note_on", "handler table entry 9x"),
    ("bl",      0x08010B0A, 0x08017244, "demo_voice_trigger", "note_on -> voice_trigger"),
]
```

## Compiling

[`tools/patch_build.py`](../tools/patch_build.py) compiles with
`-mcpu=cortex-m4 -mthumb -mfloat-abi=hard -mfpu=fpv4-sp-d16 -Os
-ffreestanding -nostdlib -fno-common`, with `-Werror`. Hard float matches the
firmware
([findings, Float ABI](findings/summit-2.2-build2121.md#float-abi-and-fpu)).
It links against libgcc only.

- **Flash:** `.text` and `.rodata` go to `FREE_FLASH`, from the image end
  (`0x080501C0`, 4-byte aligned) up to `0x08060000`, the end of sector 6,
  which the update already erases. That's 65,088 bytes. `__patch_start` comes
  first.
- **RAM:** `.bss` goes to `PATCH_RAM`, the 64 KB of CCM at `0x10000000`,
  which the firmware never references
  ([findings, Patch RAM](findings/summit-2.2-build2121.md#patch-ram-stack-and-heap)).
  `__patch_start` clears it, except variables marked `PATCH_NOINIT`
  (section `.noinit`, after the cleared part): use that only for tables
  written whole before their first use (MPE step 3's Settings tables,
  built at boot).
- **The build fails** if:
  - the code overflows flash or RAM (`will not fit in region`);
  - it needs `.data` (an initialised global): patch RAM is zero-initialised
    only, so set start values in `patch_init()`;
  - it has any allocated section other than `.text` and `.bss`;
  - a patch function has the name of a firmware symbol;
  - anything else fails to compile or link.

## Calling the firmware

`fw_symbols.ld` is generated from
[`docs/symbols/summit-2.2-2121.csv`](symbols/summit-2.2-2121.csv): functions
as `address | 1` (Thumb), data at its address. So C can call any named
function and read any named global, **but only with a prototype**.
[`firmware.h`](../patches/common/firmware.h) holds the ones we're confident
about, each with its evidence. Add a prototype only with evidence: a wrong one
silently passes the wrong registers. Name a new firmware function in the CSV
first; that also names it in Ghidra.

The firmware uses AAPCS with the hard-float ABI. Arguments go in r0–r3,
float/double in s0–s15/d0–d7. r4–r11 and s16–s31 are callee-saved. GCC
handles all of this; it only matters for hand-written trampolines.

## Hooks

Each hook checks the stock instruction or word at its site before rewriting
it, so a hook written for another build refuses to apply.

| Kind | Site | Becomes | Use |
|---|---|---|---|
| `bl` | a 4-byte Thumb-2 `BL` that must call `expected` | `BL symbol` | replace one call site: wrap or replace a callee for that caller only |
| `pointer` | an aligned 32-bit word equal to `expected` | the symbol's address (Thumb bit set for functions) | function-pointer tables, or their `.data` initialisers in flash; also a literal-pool word, to make one function read a patch variable instead of a firmware global (experiment C: `osc_pitch`'s bend literal `0x08013AD4`) |
| startup | `0x0801D9F2` in Reset_Handler: `bl main_loop` | `bl __patch_start` | added to every C patch automatically |

- **`.data` tables:** a table in RAM is initialised from flash at boot, so a
  pointer hook goes on its initialiser. The flash address is
  `0x0804BD80 + (ram - 0x20000000)`. For example, the MIDI handler table at
  RAM `0x200002D0` is initialised from `0x0804C050`, and entry 9x is at
  `0x0804C058`.
- **A wrapper calls the original:** call it by its firmware name, which links
  to the stock address. A pointer hook changes every use of that pointer; a
  BL hook changes only that one call. In the demo, `note_on` is also called
  directly by the keybed/arp path `0x08010B30`, which the table hook misses
  and the BL hook catches.
- **Handlers called through tables** may receive more arguments than the
  firmware reads. Pass r0–r3 on unchanged (`midi_handler_fn` in
  `firmware.h`).
- **Startup:** `__patch_start` runs before `main_loop`'s init, with
  interrupts not yet configured and **the FPU still off** (it's enabled in
  `system_init`, at `0x0801298A`). `patch_init()` must therefore stay
  integer-only. Define it only if you need non-zero start values.
- **Not supported yet:** function-entry trampolines (overwrite the first
  instructions of a function and replay them). Use a `bl` hook at each call
  site, or a `pointer` hook, instead.

## `--verify`

After patching, `tools/patch.py --verify` checks the **patched image**
with `llvm-objdump`:

1. Each `bl` hook site disassembles to `bl <patch function>`, inside the blob.
2. Each `pointer` site holds the symbol's address, with the Thumb bit for
   functions.
3. Every entry point (`__patch_start` and each hook target) has the Thumb
   bit, lies inside the blob, and disassembles.
4. The blob in the image equals the linked ELF's `.text`.
5. Every direct branch in the blob lands inside it, or on a firmware function
   entry from the symbols CSV, and none is a `blx` to ARM state. This catches
   a call through a wrong or missing symbol. The ELF is disassembled with its
   mapping symbols, so literal pools aren't mistaken for code.

Any failure aborts the build with a list of problems.

## Tests

[`tests/test_patch_toolchain.py`](../tests/test_patch_toolchain.py) is the
pattern to copy:
- build the image with `patch.build_image(definition)`, and load
  `built.patched` into `emu.Machine`;
- `boot()`, then run the startup hook from `0x0801D9F2` to `main_loop`, the
  way it runs on hardware;
- feed MIDI through `midi_queue_select`/`midi_parse_byte`;
- compare against the stock image: RAM and peripheral traffic must match,
  apart from the patch's own state.

The tests skip when the compiler or the official image is missing. Fill CCM
with garbage first (`0xA5`), because the emulator zeroes it but the hardware
doesn't.

## Limits and risks

- **Image length:** a C patch makes the image longer, so the update carries
  more `0x72` blocks (279,136 bytes for the demo, against 278,976 stock).
  `flash.py` and its simulator accept that. **The bootloader has not yet
  been shown a longer image.** That's the first hardware question for a C
  patch.
- **Sector 6** is the end of the space the update erases (inferred from the
  F42x sector map). Writing past `0x08060000` would need an erase the
  bootloader may not do, so the build refuses it.
- **CCM** is assumed present (STM32F42x/43x, inferred from the RAM size). It
  isn't DMA-accessible, so DMA buffers can't go there.
- **Context:** MIDI handlers run in the main loop, not in interrupts
  (observed). A hook on code that runs in an ISR must be short, and must not
  share state with main-loop code without care.
- **Re-targeting:** sites and expected values are for build 2121. For a new
  Novation build, update the symbols CSV and each hook's site and expected
  value. The checks refuse stale ones.
