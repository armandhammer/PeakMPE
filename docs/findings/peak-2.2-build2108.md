# Peak 2.2 (build 2108) — findings

The feasibility study was done on this image. The Peak is the Summit's
8-voice desktop sibling, so its landmarks guide the Summit work. Addresses are
flash addresses (base `0x0800C000`). Unless noted, each finding comes from the
llvm-objdump disassembly (`scripts/disasm.sh`), not a decompiler.

| Landmark | Address | Confidence | Notes |
|---|---|---|---|
| Reset handler | `0x0801D6C4` | observed | `.bss` zero loop, then `.data` copy |
| 8-voice "oldest voice" search | fn `0x08011B70`, loop `0x08011C0A–0x08011C90` | inferred | Iterates `r2 = 0..7`, keeps the voice with the largest 16-bit age counter: voice-stealing candidate |
| MIDI byte stream → USB-MIDI packets | `0x0801D484` | observed | `status >> 4 − 8` indexes a data-length table; builds 4-byte `[CIN, status, d1, d2]` packets; handles running status and SysEx |
| USB-MIDI packet → TX FIFO | `0x0801D440` | inferred | Writes 4 bytes to an endpoint FIFO: MIDI **out** / thru path, not input |
| SysEx receive state machine | `0x08019114` | observed | Matches the Novation header, `0x7F` command byte |
| SysEx command switch | `0x0800D040` | observed | 9-way `tbb`; some cases loop over `0x4F` entries (patch/parameter dumps?) |
| Front-panel pot scanning | `0x0800E054`, dead-zone helper `0x0800E024` | inferred | ADC values with a centre-detent dead zone (`±0x1F0`); not MIDI |

## Dead ends

- `cmp r4, #0xf0` hits at `0x08011CA4` and `0x0801258C` are literal pools
  (RAM pointers) that the linear disassembler decoded as instructions.
- Status compare clusters at `0x080457C0+` lie in the data region.

## Open

- MIDI **input** dispatch (note on/off, bend, channel pressure, CC).
- Note-on → voice allocation call chain; per-voice struct layout.
