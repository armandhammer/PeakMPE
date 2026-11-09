# Firmware update format

Observed on Summit 2.2 (build 2121) and Peak 2.2 (build 2108). Implemented by
`tools/syx.py`; both images decode and re-encode byte-identically.

## SysEx container (main firmware)

Every message is `F0 00 20 29 00 <cmd> <body> F7` (Novation manufacturer ID).

| cmd | count (Summit / Peak) | body | meaning |
|---|---|---|---|
| `0x71` | 1 / 1 | 8 bytes | header |
| `0x72` | 8717 / 7782 | 37 septets | 32 image bytes, sequential from image offset `0x20` |
| `0x73` | 1 / 1 | 37 septets | image bytes `0x00–0x1F`, sent **last** |

- **Packing:** the 37 septets form a big-endian 7-bit bitstream carrying 256
  bits followed by 3 zero bits.
- **No addresses, no per-message checksum:** blocks are positional. Decoding and
  re-encoding reproduces the file exactly, so the container has no hidden
  fields.
- **Brick safety:** the first 32 bytes are vector-table entries 0–7, which
  include the initial stack pointer and reset vector. They arrive last, so an
  interrupted update leaves an image whose vectors were never written, and the
  bootloader presumably refuses to start it. Any image we build must keep this
  ordering. `tools/syx.py encode` does.

### Header (`0x71`)

| Product | Body |
|---|---|
| Summit 2.2 / 2121 | `01 33 00 00 02 01 02 06` |
| Peak 2.2 / 2108 | `00 7e 00 00 02 01 00 08` |

- **Bytes 0–1:** the product ID (`0x0133` Summit, `0x007e` Peak). It's the
  same ID the identity reply carries as family `33 01`, LSB-first.
- **Bytes 4–7:** the version digits, one decimal digit per byte. A live
  capture showed that the Summit's application and bootloader both report
  **2126** in their identity replies: exactly these digits, even though the
  catalogue calls the build 2121 ([update-protocol.md](update-protocol.md#live-capture-2026-10-31)).
- **Bytes 2–3:** `00 00`, meaning unknown.

## Flash image

| | Summit 2.2 | Peak 2.2 |
|---|---|---|
| Load base | `0x0800C000` | `0x0800C000` |
| Size | 278,976 B | 249,056 B |
| Initial SP | `0x20030000` | `0x20030000` |
| Reset vector | `0x0801D9BD` | `0x0801D6C5` |

- **Load base:** confirmed by `tools/find_base.py`: about 900+ string pointers
  match at `0x0800C000`, against at most about 560 at any other candidate. The
  reset handler at that base is the standard `.bss`-zero / `.data`-copy
  startup.
- **Image tag and version:** after the 107-entry vector table, the image
  holds the tag `MAIN` (`0x0800C1AC`) and the u16 version `0x2126`, one digit
  per nibble (`0x0800C1B0`). The application's identity reply and its shown
  version both come from that word. See
  [findings](findings/summit-2.2-build2121.md#version-text-and-identity).
- **What sits below the image:** flash `0x08000000–0x0800BFFF` (48 KB) is not
  in the update. That is presumably the bootloader, plus possibly settings or
  calibration data.
- **CPU:** an initial SP of `0x20030000` (192 KB of SRAM) is consistent with an
  STM32F42x/F43x. The ReplicantPeak project identifies the Peak's CPU as an
  STM32F429. That is **not yet confirmed** for the Summit (board photos or the
  chip marking would settle it).

## FPGA image

FPGA updates use a different command, `0x7c`. Summit FPGA 2.1/778 has 2375
messages with bodies of 9 and 649 bytes. This format isn't decoded yet. The MPE
work shouldn't need to touch it.

## Integrity checks

No zlib CRC-32 or 32-bit byte sum of the image was found inside the image.

**Answered on hardware (observed, 2026-10-31):** the bootloader accepts and
boots a modified image. The version-string patch changed 15 bytes of string
data, and kept the `0x71` header, the vector table, the `MAIN` tag and the
version word. It was written and booted normally
([hardware-log](hardware-log.md),
[update-protocol](update-protocol.md#what-flashpy-runs-on-hardware-showed-2026-10-31-to-2026-11-08)). So
neither the container nor the bootloader enforces a checksum or signature over
the whole image.

**The header region (observed, 2026-10-31):** the version-word patch changed
the version word at `0x0800C1B0` (2126 → 2127) and the `0x71` header digits
with it, and was written and booted too; so was the official 2126 file over
it, a downgrade. So neither a checksum covering the version word nor a
version comparison (header vs. installed image) is enforced
([update-protocol](update-protocol.md#what-flashpy-runs-on-hardware-showed-2026-10-31-to-2026-11-08)).
The bootloader's identity reply reports the installed image's version word.
Not tested: a check of only the vector table or the `MAIN` tag string.
