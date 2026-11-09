"""Second patch: raise the firmware version word 2126 -> 2127, nothing else.

Tests whether the Summit bootloader checks the image header region (docs/findings/summit-2.2-build2121.md,
"Version word patch"). The version-string patch showed there
is no CRC or signature over the whole image, but it left the vector table, the
"MAIN" tag at 0x0800C1AC and the version word at 0x0800C1B0 untouched. This
patch changes one byte of that region, and the matching digits of the 0x71
header, so the file stays self-consistent like an official release (Summit
2126/2126, Peak 2108/2108). Addresses and the reasoning are in
docs/findings/summit-2.2-build2121.md, section "Version word patch".

The word is BCD-like, one decimal digit per nibble, so 0x2127 is "2127":
  identity reply digits:  02 01 02 06  ->  02 01 02 07  (still >= 2121, the
                          catalogue build Components requires)
  boot screen, row 3:     " Version 126.778"  ->  " Version 127.778"
  Settings 2/33 SYSTEM:   126.778  ->  127.778
(emulated in tests/test_version_word.py, not yet seen on hardware). Only
fw_version 0x0800EA00 reads the word (literal at 0x0800EA08), and its only
callers are boot_screen, format_value and identity_reply.
"""

SOURCE = "summit-firmware-2.2-build2121.syx"
NAME = "version-word"

# (flash address, original bytes, new bytes, why)
PATCHES = [
    (0x0800C1B0, b"\x26\x21", b"\x27\x21",
     "version word behind the MAIN tag, u16 LE 0x2126 -> 0x2127; read only by "
     "fw_version 0x0800EA00 (identity reply, boot screen, Settings version)"),
]

# (original body, new body, why)
HEADER = (bytes.fromhex("0133000002010206"), bytes.fromhex("0133000002010207"),
          "0x71 header: product 01 33, version digits 2126 -> 2127 to match the image word")
