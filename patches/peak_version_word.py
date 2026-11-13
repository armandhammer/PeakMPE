"""Peak, second patch: raise the firmware version word 2108 -> 2109, nothing else.

The Peak counterpart of patches/version_word.py: does the Peak bootloader
check the image header region (vector table, "MAIN" tag, version word)? The
version-string patch (on hardware 2026-11-12) showed it accepts changed bytes
elsewhere. This one changes one byte of that region, plus the matching digits
of the 0x71 header, so the file stays self-consistent like an official
release (Peak 2108/2108).

Addresses (observed in the Peak 2.2/2108 image, docs/symbols/peak-2.2-2108.csv):
  0x0800C1AC "MAIN", 0x0800C1B0 u16 LE 0x2108, as on the Summit.
  fw_version 0x0801890C returns it (one literal, 0x08018914); its only
  callers are boot_screen 0x0800E568, format_value 0x08017C6E and
  identity_reply 0x0801970E. No other literal points at the word.

The word is BCD-like, one decimal digit per nibble, so 0x2109 is "2109":
  identity reply digits:  02 01 00 08  ->  02 01 00 09
  boot screen:            " Version 108.469"  ->  " Version 109.469"
  Settings 2/26 SYSTEM:   108.469  ->  109.469
(emulated in tests/test_peak_version_word.py.) One more than stock keeps a
later official release counting as newer.
"""

SOURCE = "peak-firmware-2.2-build2108.syx"
NAME = "version-word"

# (flash address, original bytes, new bytes, why)
PATCHES = [
    (0x0800C1B0, b"\x08\x21", b"\x09\x21",
     "version word behind the MAIN tag, u16 LE 0x2108 -> 0x2109; read only by "
     "fw_version 0x0801890C (identity reply, boot screen, Settings version)"),
]

# (original body, new body, why)
HEADER = (bytes.fromhex("007e000002010008"), bytes.fromhex("007e000002010009"),
          "0x71 header: product 00 7E, version digits 2108 -> 2109 to match the image word")
