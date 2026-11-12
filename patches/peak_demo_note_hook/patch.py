"""Peak demo C patch: count note-ons, then run the stock handler.

The Peak counterpart of patches/demo_note_hook: proves the patch toolchain
on the Peak image (one pointer hook, one bl hook, the startup hook). Not
meant for hardware. Addresses: docs/symbols/peak-2.2-2108.csv.

  pointer hook: entry 9x of the channel-handler table. Its .data initialiser
                at flash 0x080453C0 is copied to RAM 0x200001B0 at boot.
  bl hook:      note_on's call to voice_dispatch at 0x0800F570.
"""

SOURCE = "peak-firmware-2.2-build2108.syx"
NAME = "peak-demo-note-hook"

PATCHES = []

SOURCES = ["demo.c"]

HOOKS = [
    ("pointer", 0x080453C0, 0x0800F53D, "demo_note_on",
     "channel-handler table entry 9x (note on), .data initialiser of RAM 0x200001B0"),
    ("bl", 0x0800F570, 0x08012984, "demo_voice_dispatch",
     "note_on -> voice_dispatch(note, vel)"),
]
