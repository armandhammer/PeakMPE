"""Peak, first patch: mark the shown version text, nothing else.

The Peak counterpart of patches/version_string.py: a harmless change that
makes a modified build recognisable on the synth, to test the flash path and
the Peak bootloader's reaction to a modified image before any code runs.
Addresses: docs/symbols/peak-2.2-2108.csv (observed: the same two strings,
in the same layout, as on the Summit).

Only label strings change, in place and at the same length; the version
word and the header stay as they are.
"""

SOURCE = "peak-firmware-2.2-build2108.syx"
NAME = "version-string"

# (flash address, original bytes, new bytes, why)
PATCHES = [
    (0x080452FB, b" Version ", b"MPE0 Ver ",
     "boot screen label; .data initialiser of RAM 0x200000EB"),
    (0x080445E8, b"Version\x00", b"MPE0Ver\x00",
     "item name on Settings page 2/26 SYSTEM"),
]
