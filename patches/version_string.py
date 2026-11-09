"""First patch: mark the shown version text, nothing else.

A deliberately harmless change that makes a modified build recognisable on the
synth, so the whole flash path and the bootloader's reaction to a modified
image can be tested on hardware. Addresses are documented in
docs/findings/summit-2.2-build2121.md, section "Version text and identity".

Only label strings change, in place and at the same length. The version word
0x2126 at 0x0800C1B0 (behind the "MAIN" image tag) stays as it is: it feeds
both the shown digits and the Universal Identity reply, and the bootloader may
read it too, so leaving it alone keeps the identity reply at 2126 and
isolates the hardware test to "does the bootloader accept changed bytes".

On the synth (emulated in tests/test_patch.py, not yet seen on hardware):
  boot screen, row 3:          " Version 126.778"  ->  "MPE0 Ver 126.778"
  Settings 2/33 SYSTEM, row 2: "Version"           ->  "MPE0Ver"
"126" is the low three digits of 0x2126; ".778" is read from external flash
(presumably the FPGA build).
"""

SOURCE = "summit-firmware-2.2-build2121.syx"
NAME = "version-string"

# (flash address, original bytes, new bytes, why)
PATCHES = [
    (0x0804C3B7, b" Version ", b"MPE0 Ver ",
     "boot screen label; .data initialiser, copied to RAM 0x20000637 and printed "
     "at cursor (1,3) by boot_screen 0x08012084 before the version digits"),
    (0x0804B3E4, b"Version\x00", b"MPE0Ver\x00",
     "item name on Settings page 2/33 SYSTEM (kind-4 descriptor 34, flash "
     "0x0804FF80, display type 0x59 = version formatter)"),
]
