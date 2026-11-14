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

## Arpeggiator and the MIDI loop (2026-11-13)

From the Ghidra decompile of the whole image (`scripts/ghidra-import.ps1
... -DecompileAll`, output in `work/decomp/`, never committed), read
alongside the rig tests in [peak-features.md](../peak-features.md) step 1.
Code structure is observed; field meanings marked inferred are read from
how the code uses them.

- **Held notes, global:** `held_note_add` `0x0800F364` sets bit *n* of a
  128-bit map at `0x200127D4+0xD8` and stores the velocity at `+0x58+n`;
  `held_note_clear` `0x0800EF04` clears the bit, first thing in `note_off`
  (observed).
- **Arp state:** a struct reached through the pointer at `0x20000640`
  (observed). `+0x168` 128-bit map of keys held; `+0x178` 128-bit map of
  the notes the arp plays; `+0xE8+n` velocity; `+0x188` played-order list
  of up to 32 {note, velocity} pairs, count at `+0x1CA`/`+0x1CB`; `+0x1E1`
  flags rebuilt each tick by `arp_tick` `0x08015554` from patch `+0xF5`
  (arp on, bit 0), `+0xF7` (bit 1), `+0xF6` (latch, bit 2) and a global
  setting at `0x20014494+0x13` shifted into bits 5–6 (observed; it is
  `Arp>MIDI`, see the global settings table below).
- **`arp_note_on`** `0x08015018`: if no key is held, `arp_reset`
  `0x08014FA8` starts a new sequence; then the note is added to both maps
  and appended to the played-order list, even if already there (observed).
- **`arp_note_off`** `0x08014E10`: clears the key bit; unless latched
  (`+0x1E1` bit 2), also removes the note from the play map and its first
  entry from the played-order list (observed).
- **Arp output:** `arp_step` `0x080151A0` plays one step. With `+0x1E1`
  bits 5–6 set it sends the note to MIDI through `arp_midi_note_on`
  `0x08014EA4` → `midi_send3` `0x0801740C` (status OR the global channel
  `0x20011210`), and plays it on a voice through `voice_dispatch` unless the
  byte at `0x20003768` is 0 (observed; that byte as Local Control is
  inferred). The step's release, `arp_step_release` `0x08014EC4`, sends
  `80 nn 40`: note-off velocity 64, as the rig saw (observed).
- **Why the loopback silenced the arp** (observed in code, and it matches
  the hardware count): every arp step the Peak sends and gets back arrives
  as an ordinary note. The returned note-on is added again (harmless); the
  returned note-off goes through `arp_note_off` and removes that note from
  the play map, exactly as if the player had let go of the key. Up mode
  walks the play map (`arp_step_select` `0x08015408` → `0x08015308`), so
  after one pass over C, E and G the map is empty and the arp stops: 3
  steps × 2 messages = the 6 note messages the rig recorded. The Peak
  cannot tell its own echoed notes from the player's keys.
- **No CC loop:** `midi_send3` is also what the panel uses for NRPNs
  (`0x08017454` sends 99/98/6); received CC/NRPN were not sent back out on
  the rig (observed on hardware, MPE image).

## Oscillator pitch sum and the global settings table (2026-11-13)

- **`osc_pitch`** `0x08010B60` (disassembly, observed): the pitch is a sum
  in 1/256 semitone around note 60: the voice's note pitch (u16 at
  `0x20012544+2v`, or the fixed note), the oscillator's offset
  (`osc+2+2*part`), the s16 at `0x20012278`, bend × bend range >> 6,
  `(u8 0x200129C0 × s8 0x2001278C[v]) >> 7`, `(s8 0x200002F4[0xC8+3v+osc]
  × u8 0x2001233C) >> 5`, `s8 0x20012558[osc]`, minus `0x3C00`. Each add is
  16-bit (`uxtah`) and the total is sign-extended from 16 bits (`sxth`)
  before `× 0x5555 >> 14`, so it wraps outside -32768..32767.
- A Python model of that sum, checked against stock on 54,258 simulated
  calls, matched every result in range (emulated, `work/tmp/pitch_oracle.py`).
- **The wrap is out of earshot.** The limits are ±128 semitones from note 60:
  about 400 kHz and 0.16 Hz. The most the simulator reached was +31,318
  (note 127, Range 2', Coarse and Fine at maximum, bend +24 at full bend) and
  -28,816 at the other extreme (emulated). A wrap would turn an inaudible
  pitch into another inaudible one, so the stock clamp is not worth a hook
  (plan step 2 dropped). MPE voices already clamp their own bend
  (`mpe_bend_add`, `OSC_MIN`/`OSC_MAX`).
- **Global settings table:** `global_param_desc` (RAM `0x20002B7C`, .data
  initialiser at flash `0x08047D8C`) names each `globals` byte (observed):
  `+0x0C` Pickup, `+0x0D` Brightness, `+0x0E` VelShape, `+0x0F` TuneCents,
  `+0x10` Transpose, `+0x11` MidiChan, `+0x12` MidiLocal, **`+0x13`
  Arp>MIDI** (so the arp's MIDI-out flag above is observed, not inferred),
  `+0x14` CC/NRPN (0 Disabled … 3 Rec+Tran), `+0x15` Bank/Patch, `+0x16`
  to `+0x19` pedals, `+0x1A` Msg Time, `+0x1D` Initialise, `+0x1F` VolRange,
  `+0x20` TuningMode.
- **Simulator notes:** the seeded DataFlash has CC/NRPN = 0 (Disabled), so
  CCs sent to the simulator change nothing until `globals+0x14` is set to 3;
  writing patch bytes in RAM doesn't reach the oscillators (they are
  recomputed only on a parameter change); and the simulator runs the Peak's
  timers at twice its own milliseconds (arp step 62.5 sim-ms vs 125 ms on
  hardware).

## The knob overlay, pickup and the LCD (2026-11-13)

From the Ghidra decompile and the disassembly; literal-pool words and `.data`
strings read from the image (`.data` is copied from flash `0x08045210` to RAM
`0x20000000`, so RAM `0x20000B90` is flash `0x08045DA0`). Symbols in
[peak-2.2-2108.csv](../symbols/peak-2.2-2108.csv). All **observed** unless noted.

- **Who draws it.** `knob_poll` `0x08016DF4` takes one knob event (value,
  previous value, queue index), looks the knob up in the 0x20000AB8 knob table
  (`id` = patch offset; an entry can be switched by a mode byte, read from
  `patches+...`, for the 0xAB / 0xB9 pairs) and calls `knob_overlay` `0x08016B14` at `0x08016EF2` (7-bit knobs;
  the two scaled cases 3 and 4 end here too) or `0x08016F28` (9-bit knobs, last
  argument 1: value = patch[id]*2 + patch[id+1]>>6, so `FiltFreq` 131 is
  0-255, `L1Rate` 172 and the oscillator Coarse/Fine/LFO pairs too). It is the
  only caller. The encoder and the value buttons don't use it (they redraw the page
  through `ui_value_change`).
- **Arguments:** `(id, prev, cur, saved, hires)`; the fifth is a stack word
  (0 or 1). `saved` is the compare-buffer value (`FUN_080190F8(id)`), the
  patch as stored, which is what the "saved val" row shows. Returns 1 = the
  knob value is applied, 0 = pickup pending (nothing applied).
- **Pickup** (`globals+0x0C` = `Pickup`, nonzero = on): a byte per patch offset
  at `0x20014054` (`pickup_state`). Armed to 3 by `pickup_arm` `0x08016B04`
  (called from `0x0800F6AC`, so the patch/MIDI side) and the knob-group
  arming `0x08016CC0` (a button press arms its knob group; inferred). While
  nonzero, the knob is compared with the patch's value `target`: if the previous
  or the current value equals it, or it lies between them, the state becomes 0
  (picked up). A knob above it clears bit 0, below it bit 1; the state stays
  non-zero until the crossing. The **target is the patch's current value**
  (patch[id], 9-bit for hires), which the overlay labels `current` while
  pending, not the compare buffer's "saved val".
- **What it draws.** Only when this knob is the one shown
  (`knob_overlay_state+4`) or the message has just ended (the return flag of
  `FUN_08018A98`); otherwise it caps the message countdown (`ui_msg_state+2`, 0x2001120A) at 10.
  Row 0: the descriptor's name (`patch_param_desc[id].name`, 12-byte records,
  +4 display type, +8 name). Pickup pending: row 3 label `   pickup ` (string
  `0x20000B90` = `09 00 03` escape, cursor to column 0 row 3) then
  `format_value(type, knob value)` at `0x08016C3C`. Picked up this call: row 3
  cleared (`0x20000BA0`). Row 1: `  current ` and `format_value(type, shown)`
  at `0x08016C72`, where `shown` is the knob value, or the patch value while
  pending. Row 2: `saved val ` and the compare value at `0x08016C90`.
  Nothing else is drawn on row 3 when no pickup is pending.
- **Timeout.** `FUN_08018A98(id, ...)` sets the countdown `ui_msg_state+2`
  to `globals+0x1A` (Msg Time) + 5; `FUN_08018ADC` (main loop) counts it down once
  per 11 ms tick; while it is nonzero a message covers the page (`ui_message_active`).
- **Display types.** `format_value` `0x08017604` switches on the descriptor's
  type byte (0x00-0x5B). Type 1 (112 of 0x1A3 patch entries, incl. every
  envelope time, filter frequency and Hold) is a plain 3-digit number
  (`FUN_0800D2C4`); 3 is value-0x40; 0x40/0x41 print a note name (letter,
  sharp, octave = note/12 - 2) through `FUN_0800D578`: `FixedNote` (patch 65,
  86, 107; 0-88) and `SplitPoint` (416) **already show note names**. Transpose
  (`globals+0x10`, type 3) is a number on a Settings page, not a knob.
- **Parameter ids** (patch offsets; 9-bit marked h): FiltFreq **131** (h, 0-255),
  FiltResonance 130, AmpAttack/Decay/Sustain/Release **146/147/148/149**, Mod
  Env 1 **155/156/157/158**, Mod Env 2 **163/164/165/166**, HoldTime 152/161/169,
  DelayTime 205 (FX), L1Rate 172 (h). The envelope **Delay** stage has no
  descriptor with a name (the guide's Delay): the `Delay` entries 378-380 are
  type 1 in the extra bank, role unconfirmed (inferred), so no ms unit for it.
- **LCD driver.** `lcd_write_cmd` `0x08016840` / `lcd_write_data` `0x08016868`
  are the Summit's pair with chip select PB12 (BSRR bit 28); start bytes 0x1F /
  0x5F, low nibble then high nibble. `lcd_load_cgram` `0x08016890` is the
  Summit's `0x08019D90`: command `0x40`, then 64 bytes from `0x20000A78`
  (flash init `0x08045C88`), the eight box-frame pieces, codes 0-7. Only
  `lcd_init` `0x080169E4` calls it. `lcd_cursor` `0x080168B4` sends
  `0x80 | col + row*32`. `lcd_putc` `0x080168C8` passes 0-7 and 0x10-0x7F
  through (0x10 = `▶`, 0x11 = `◀` in the ROM, emulator text view). Code 8
  clears. Where stock uses codes 0-7 was not traced (not seen in the
  overlay's strings, which hold no byte below 0x20 except the cursor escape
  `09`), so the display module takes them only while it draws and restores the
  stock set afterwards with `lcd_load_cgram()` (design choice; the restore
  is checked in the simulator).
- **Simulator.** The LCD model decodes this driver, so tests read the DDRAM
  codes and `lcd.glyph(code)` bitmaps; the pots are not modelled, so a
  test calls `knob_overlay` directly with the arguments above, as `knob_poll`
  does.

## Dead ends

- `cmp r4, #0xf0` hits at `0x08011CA4` and `0x0801258C` are literal pools
  (RAM pointers) that the linear disassembler decoded as instructions.
- Status compare clusters at `0x080457C0+` lie in the data region.

## Open

- MIDI **input** dispatch (note on/off, bend, channel pressure, CC).
- Note-on → voice allocation call chain; per-voice struct layout.
