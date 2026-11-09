"""Demo C patch: count note-ons, then run the stock handler.

Proves the patch toolchain (docs/patch-howto.md); not meant
for hardware. Addresses are in docs/findings/summit-2.2-build2121.md, "The
MIDI path" and "Notes and voices".

  pointer hook: entry 9x of the channel-handler table. Its .data initialiser
                at flash 0x0804C058 is copied to RAM 0x200002D8 at boot, so
                every note-on from USB or DIN reaches demo_note_on first.
  bl hook:      note_on's call to voice_trigger at 0x08010B0A now calls
                demo_voice_trigger, for every caller of note_on (the handler
                table and the keybed/arp path at 0x08010B30).

tools/patch.py also adds the startup hook every C patch gets (Reset_Handler
calls __patch_start, which zeroes patch RAM and runs patch_init).
Emulated in tests/test_patch_toolchain.py.
"""

SOURCE = "summit-firmware-2.2-build2121.syx"
NAME = "demo-note-hook"

PATCHES = []

SOURCES = ["demo.c"]

# (kind, site, expected original, patch symbol, why)
#   "pointer": the 32-bit word at site, expected = its stock value
#   "bl":      the BL at site, expected = its stock call target
HOOKS = [
    ("pointer", 0x0804C058, 0x08010AB1, "demo_note_on",
     "channel-handler table entry 9x (note on), .data initialiser of RAM 0x200002D8"),
    ("bl", 0x08010B0A, 0x08017244, "demo_voice_trigger",
     "note_on -> voice_trigger(note, vel, part)"),
]
