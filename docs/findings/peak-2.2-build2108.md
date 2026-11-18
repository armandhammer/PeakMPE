# Peak 2.2 (build 2108) — findings

The feasibility study was done on this image. The Peak is the Summit's
8-voice desktop sibling, so its landmarks guide the Summit work. Addresses are
flash addresses (base `0x0800C000`). Unless noted, each finding comes from the
llvm-objdump disassembly (`scripts/disasm.sh`), not a decompiler.

| Landmark | Address | Confidence | Notes |
|---|---|---|---|
| Reset handler | `0x0801D6C4` | observed | `.bss` zero loop, then `.data` copy |
| 8-voice candidate search (`voice_candidates`) | fn `0x08011B70`, loop `0x08011C0A–0x08011C90` | observed | Ranks the 8 voices by the sound chip's envelope state and level, not by age: see [Voice allocation and stealing](#voice-allocation-and-stealing-2026-11-15) |
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
  recomputed only on a parameter change). Until 2026-11-15 the simulator ran
  the Peak's timers at twice its own milliseconds (arp step 62.5 sim-ms vs
  125 ms on hardware); fixed, see
  [Timers and the 1 kHz tick](#timers-and-the-1-khz-tick-2026-11-15).

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
  (0 or 1). `saved` is the stored patch's value (`saved_value_read`
  `0x080190F8(id)`), which is what the "saved val" row shows. Returns 1 = the
  knob value is applied, 0 = pickup pending (nothing applied); **the caller
  writes the knob's value into the patch when it returns 1** (emulated,
  2026-11-16: a hook that changes `cur` changes only what is drawn).
- **Where the stored value comes from (2026-11-16, observed).** Not from a
  buffer in RAM: `saved_value_read` reads the patch memory on every knob
  move. The record number is (bank - 1) × 128 + number, from `patch_select`
  `0x20002D14` +4 (bank, 1-based) and +5; a record is 512 bytes at
  `record << 9` in the external DataFlash, and byte k of it is patch offset
  k (the function reads at `id + record * 0x200`; a patch load reads the
  whole record with `ext_flash_read_page` `0x0800EA64` into the shared
  buffer `0x20003CA4` and copies it into the patch). `ext_flash_read`
  `0x0800E978(addr, buf, len)` is the read underneath (DataFlash command
  3). The patch's morph (`morph.c`) reads a record with it.
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
- **LCD bus speed (2026-11-16).** The display is on **SPI2**
  (`0x40003800`): `lcd_spi_init` `0x0800ED0C` (only caller `lcd_init`)
  enables the SPI2 clock (`RCC_APB1ENR` bit 14) and stores `CR1 = 0x3AF`:
  master, LSB first, software NSS, clock **PCLK1/64** (observed). With PCLK1
  at 30 MHz (inferred, the Summit's clock tree) that is 469 kHz. One
  character is three SPI bytes (`lcd_spi_tx` `0x0800ED64` waits for TXE and
  writes `SPI2_DR`; `lcd_spi_wait` `0x0800ED7C` then waits for not busy), all
  busy-waited in the main loop: about 51 µs of bus time per character, so
  **a full redraw of the four rows (80 characters and the cursor commands)
  keeps the main loop for about 4.5 ms plus the formatting** (inferred from
  the bit rate). The modulation tick is not caught up (`mod_tick`), so each
  full redraw costs about four of the 1 kHz ticks. **On the synth (v0.17,
  2026-11-16, observed):** the patch's late-tick counter (`diag.c`, Settings
  > MOTION) read a longest gap between two modulation ticks of 6 ms over an
  interval holding two page draws and nothing else, twice, and 9 lost ticks
  in each such 10 s interval; with a motion lane writing Filter Frequency
  about 60 times a second the same 9. So a page draw holds the main loop
  for about 5 ms, an otherwise idle main loop keeps its 1 kHz tick, and
  parameter writes at that rate cost no ticks.
- **Simulator.** The LCD model decodes this driver, so tests read the DDRAM
  codes and `lcd.glyph(code)` bitmaps; the pots are not modelled, so a
  test calls `knob_overlay` directly with the arguments above, as `knob_poll`
  does.
- **Who writes to the LCD (2026-11-17, observed in the disassembly).** All
  text goes through two calls in the escape layer: `0x0800D1FA` (the
  wrapper `0x0800D1F8` → `lcd_putc`; wrapper callers `lcd_putc_esc`
  `0x0800D23C` and three in `0x0800D5FE`-`0x0800D620`) and `0x0800D216`
  (the wrapper `0x0800D214` → `lcd_cursor`, about 70 callers, the cursor
  escape among them). `lcd_putc` has one other caller, `lcd_init`'s clear
  (`0x08016A28`); `lcd_cursor` none. The direct callers of `lcd_write_cmd`
  are `lcd_load_cgram`, `lcd_cursor`, `lcd_putc`'s clear, `lcd_init`, and two
  small functions: `lcd_display_on` `0x08016924` (if the display is off:
  `lcd_power_on` `0x08016804`, which sets PB1, a 1 ms wait, command `0x0C`)
  and `lcd_display_off` `0x08016950` (command `0x08`, `lcd_power_off`, called
  by the screen-saver timeout `0x08016970` when more than 599,999 counts of
  the ms counter, literal `0x08016994`, have passed since the last
  `lcd_display_on`: about 10 minutes). PB1 is likely the panel's supply
  (inferred); whether the display keeps its RAM while it is off was not
  checked. `lcd_write_data` is called only by `lcd_load_cgram`, `lcd_putc` and
  `lcd_init`. `lcd_init` (through `0x0800D200`) has one caller, `0x0800E7E2`.
  The 1 ms waits poll a u16 that only the timer interrupt advances
  (`0x20003BA2`, delay `0x0800E50C`).
- **Stock redraws unchanged text (2026-11-17, emulated,
  `work/_overlay_writes.py`).** A knob event with the overlay already up
  rewrites the parameter name and both value rows: 34 data writes and 3
  cursor commands on Filter Frequency, of which 33 data writes put back the
  character the cell already held. v0.22's bar row made it 68. A Settings
  page drawn over itself: 56 writes, all unchanged. At about 51 µs a write
  (above), that is about 1.9 ms of a stock knob event and 3.5 ms of v0.22's,
  in the main loop, against the 1 ms modulation tick; series M7 measured
  about half the ticks lost while a knob turned on v0.21 (observed).
- **The patch's LCD cache (v0.23, `lcdcache.c`; emulated).** Hooks on the
  two escape-layer calls keep a copy of the 128 DDRAM cells: a cursor
  escape only records the position, a character equal to the copy is not
  sent, a different one is sent after an address command when the
  display's own address isn't there. Unknown cells (`0xFF`, a code
  `lcd_putc` never sends) are always written; the copy is blank after
  `lcd_init`'s clear (hook `0x0800D202`), forgotten when the panel is powered
  up after the screen saver (hook `0x08016932`), and a character past column
  19, where the controller's next address isn't known, is written at its
  address and the copy forgotten (none at boot). Fed the same random stream
  of characters, cursor escapes, clears and ignored codes, stock and the
  patch end with the same 128 cells after every chunk
  (`tests/test_peak_lcdcache.py`). A knob turn of 40 events on Filter
  Frequency: stock 37 writes per event, the patch 2 to 7 (average 3.8),
  about 0.2 ms; a page drawn over itself: 0. The bar's seven characters
  (56 writes) now load one per main-loop pass, so no pass holds more than a
  stock knob event (`work/_turn_cost.py`, `tests/test_peak_disp.py`).
  **On the synth (v0.23, 2026-11-17, observed):** the M7 measurement again,
  `LateTicks` read before and after about 5 s of turning Filter Frequency:
  17 ticks lost (`253 5` → `270 4`), the idle rate, against 2,645 on v0.21,
  and the longest gap 4 ms against 9. No leftover characters on the
  overlay or the Settings pages, and the overlay complete after the screen
  saver (user, series O). So the lost ticks were the screen writes
  (inferred: the cache is the only change between the two images that
  touches the main loop's knob path).

## Voice allocation and stealing (2026-11-15)

From the Ghidra decompile, the literal pools read from the image, and the
simulator (`tests/test_peak_voice_steal.py`, `work/_a1_alloc.py`). The code is
the Summit's allocator with one engine
([Summit findings, "Voice allocation reads the FPGA"](summit-2.2-build2121.md#the-fpga-bus-spi1)).
Code structure is **observed**. What the sound chip (FPGA) replies was
inferred when this was written (the simulator models the replies, it does
not emulate the chip); the three predictions that follow from it were then
**observed on the synth** the same day (below).

**Stock is already tail-aware.** A new note takes the quietest voice that is
in its release before it touches a held one. Plan step 18 as written
("prefer an idle voice, then one in release") is what stock does.

- **Call chain.** `note_on` `0x0800F53C` → `voice_dispatch` `0x08012984` →
  `voice_trigger` `0x080128C0` (one `voice_alloc` per unison voice; patch
  `+0x23` 0–3 = 1–4 voices, 4 = 8) → `voice_alloc` `0x080122B0`
  `(note, vel, part, voice, unison)` → `voice_candidates` `0x08011B70`
  `(start, mask, unison)` → `voice_env_read` `0x0801162C`.
- **Voice mode** is patch `+0x22`: 0 Mono, 1 MonoLG, 2 Mono2, 3 Poly, 4 Poly2
  (the names stand in this order from `0x0804396C`, 8 bytes each; the code agrees: 0/1 keep
  one voice and 1 skips the envelope restart when legato, 2 is a strict
  round robin `(last + 1) & 7` that reads nothing, 4 looks for the voice
  already playing the note).
- **What is read from the sound chip, on every allocation** (not in mode 2,
  not with a forced voice): `voice_env_read` waits until the timer
  `FUN_0800E6F4` has advanced by 2 since the last read (`voice_state+0x1E8`;
  at most 10,000 passes), then makes three reads `fpga_write(8, 0x10, n)`,
  n = 1, 2, 0. The nine reply words give a 16-bit **level** per voice
  (`voice_env_level` `0x20012774`) and 2 bits of **envelope state** per
  voice (`voice_env_state` `0x2001228C`).
- **The ranking** (`voice_candidates`, voices scanned in the order
  `(start + i) & 7`, `start` = the part's last pick `0x200002F4+0x2E0` + 1):

  | State | Kept | Candidate byte (`0x0F` = none) |
  |---|---|---|
  | 3 (release; idle is 3 at level 0) | lowest level, first in scan order on a tie | `0x200127C0` |
  | 1 or 2 (held: decay, sustain) | lowest level, first in scan order on a tie | `0x20012294` |
  | 0 (attack) | **largest** start stamp, so the newest note | `0x200127AC` |
  | any, voice in `mask` | highest level above `0x200` (Poly2's same note; the mono modes) | `0x20012CF0` |

  For unison the state-3 voices are also listed and sorted by level
  (voices `0x20012334`, levels `0x2001279C`).
- **The choice** (`voice_alloc`, Poly, unison 1): the state-3 candidate; if
  that is the voice taken last (`0x200002F4+0x2EC`), the second quietest of
  the sorted list; with no state-3 voice the state-1/2 candidate; then the
  state-0 candidate; then voice 0.
- **A steal sends no release.** The taken voice gets only the three
  envelope start commands (`0x3F`, `0x42`, `0x45`, state 0) and its new
  pitch and velocity (emulated: the FPGA writes of a stealing note-on are
  those of any note-on). Whether the chip restarts the envelope from zero
  or from its current level is inside the chip (unknown).
- **Per-voice state on the MCU** (`voice_state` `0x20004650`, observed):

  | Field | Address | Meaning |
  |---|---|---|
  | gate | `+0x1F4+v` | 1 from the note start (`FUN_08011964`) until the release command (`voice_clear_at` `0x08011980`); stays 1 while a pedal holds the note |
  | pedal-held | `+0x23C+v` | 1 = key is up, the sustain pedal holds the note (`voice_release_part` sets it when `0x200127D4+0x1CD` is nonzero; `FUN_08011ED0` releases those voices at pedal up) |
  | sostenuto-held | `+0x244+v` | 1 = held by the sostenuto pedal (`FUN_08011F6C` marks the gated voices at pedal down, `FUN_08011F90` clears at pedal up) |
  | start stamp | `+0x218+4v` (u32) | a note counter (`+0x214`), stored at each envelope start by `FUN_080119D8(voice, 0, 0)`. Larger = newer. Stock uses it only for state-0 voices |
  | envelope command counters | `+0x1FC+3v+env` | 6 bits, sent with each command (`env_command` `0x080119A4`: `fpga_write(voice, {0x3F, 0x42, 0x45}[env], cmd + counter × 4)`, cmd 0 = start, 3 = release) |
  | unison group | `+0x250+v` | which note-on the voice belongs to (`parts+0x13`) |
  | note | `voice_note` `0x20012794+v`; `0x200002F4+0x2E4+v` | the note; the second copy is what Poly2 compares |

  The MCU keeps **no release time and no level**. The only "how loud is this
  voice" it ever has is the chip's reply at the moment of an allocation.
- **Emulated results** (stock image, replies modelled: a held voice reads
  state 2 at a fixed level, a released one state 3 falling to 0 over 1 s):
  - 8 held, one let go, then a 9th note: the 9th takes the released voice.
    No held note is cut.
  - Two voices releasing: the one released earlier (quieter) goes first.
  - 8 held at one level, 9th note: the voice after the last pick is cut.
    After eight notes taken in turn that is the first note played (the
    user's A6 observation on the synth, 2026-11-14). It is rotation order,
    not age: with a pick in the middle (a released voice taken), the next
    steal cuts the voice after it although older notes are held.
  - Sustain pedal down, 8 notes played and let go, 9th note: as "8 held"
    (the chip isn't told about the pedal; the MCU's pedal-held flag is not
    used in the ranking).
  - 8 voices still in state 0 (attack), 9th and 10th note: each takes the
    **newest** voice, so the 10th cuts the 9th.
- **On the synth (observed, 2026-11-15, image v0.14, `work/steal_check.py`,
  recordings in `work/hw-runs/steal-2026-11-15_192047/`):** sine notes 48,
  53, 58, 63, 68, 73, 78, 83 played in that order, MPE off, release about
  -10 dB/s; each pitch's level measured against its held level.
  - **Release first.** 58 let go, a 9th note 0.25 s later: 58 is at -56 dB
    (cut; its release alone would have it at about -6 dB), all seven held
    notes at +0 dB. The 9th note took the releasing voice.
  - **Rotation, not age.** A 10th note then cut 63, the note on the voice
    after the last pick, while the older 48 and 53 kept sounding. So held
    voices at full sustain do tie on the real chip.
  - **All held:** a 9th note cut 48 and a 10th cut 53, the first and
    second notes played.
  - **Attack: the newest goes.** With a slow attack (Amp Attack 110) and
    all eight still rising, a 9th note 0.4 s later cut 83, the note just
    played; the other eight and the 9th all reached the same level.
  So states 3 (release), 1/2 (held) and 0 (attack) mean on the chip what
  the code's ranking implies.
- **Where a patch could do better than stock** (ideas, nothing built): a
  tie between held voices could go to the oldest by start stamp instead of
  rotation order; a note the pedal holds with its key up could go before a
  note whose key is down; the lowest held note could be protected. All
  three use MCU state only. Held voices do tie on a real Peak at full
  sustain (observed above), so the rotation tie-break is what decides in
  practice. The slow-attack case is the one a player may notice: a pad's
  newest note is the one that disappears.
- **Possible stock quirk, from the code only (inferred, not run):** at
  sostenuto pedal up, `FUN_08011F90` releases every sostenuto-held voice
  whose pedal-held flag is 0, with no check that its key is still down, so a
  key held through the sostenuto pedal's release would stop sounding.

## Glide (2026-11-15)

From the decompile and the simulator (`work/_b1_glide.py`; stock image).
Code **observed**, behaviour **emulated**.

- **Parameters** (patch offsets, names from `patch_param_desc`): `+0x27`
  `GlideTime` 0–127, `+0x28` `PreGlide` 52–76 (64 = 0, in semitones), `+0x29`
  an unnamed 0/1 switch (the panel's Glide On; the code treats 0 as glide
  off).
- **State per voice:** target pitch `voice_pitch` `0x200127C4+2v` (u16,
  1/256 semitone, from the tuning table `0x20012CF4`), glide pitch
  `voice_state+0x74+4v` (s32, 16.16), rate `0x200127B0+2v` (u16), PreGlide
  offset `0x2001255C+v` (s8, semitones, used once), output
  `voice_pitch_out` `0x20012544+2v` (the glide pitch's high word).
- **`voice_glide`** `0x08010A9C`, once per voice per tick and once in
  `voice_alloc`: if the PreGlide offset is nonzero, the glide pitch jumps to
  target + offset and the offset is cleared; then the glide pitch moves
  toward the target by `rate × difference` plus a constant `0x4000` step;
  with the switch `+0x29` at 0 it is set to the target.
- **Rates:** `FUN_08012D80` (voice parameters changed) computes the patch's
  rate from `GlideTime` into `0x2001256C` (the zero-time rate if the switch
  is off) and the zero-time rate into `0x20012564` (`FUN_08011240`).
  `voice_alloc` gives the voice the patch's rate and the PreGlide offset;
  only MonoLG at the start of a phrase (`voice_state+0x24E`, set by
  `phrase_start` `0x08012024` when no other key is held) gets the zero-time
  rate and no PreGlide.
- **Where a glide starts (emulated):**
  - **Poly:** from the pitch **that voice** last had. Nothing moves the
    glide pitch between notes, and `voice_alloc` does not reset it. With
    notes rotating through eight voices the start is the note played eight
    notes ago on that voice (the guide's "unpredictable with chords").
  - After power-on every voice's glide pitch is note 60, so the first eight
    notes glide from middle C.
  - **Mono:** one voice, so always from the last note, legato or not.
  - **MonoLG:** from the last note when legato; a detached note starts on
    pitch.
  - **PreGlide** nonzero overrides all of these: the note starts at its own
    pitch plus the offset.
- **On the synth (observed, 2026-11-15, v0.14, `work/glide_check.py`,
  recordings in `work/hw-runs/glide-2026-11-15_19*`):** sine, MPE off, Glide
  on, Glide Time 110 (slow); every voice first left at note 72; then 48, 60
  and 55 detached and 67 over the held 55. Pitch 40 to 140 ms after each
  note-on:

  | Glide setting | 48 | 60 | 55 | 67 over a held 55 |
  |---|---|---|---|---|
  | Stock | 71.3 | 71.7 | 71.6 | 71.9, then down to 67.7 after 1 s |
  | LastNote | 71.4 | 50.2 | 59.4 | 55.5, then 59.2, 62.3, 64.7 at 0.3, 0.6, 1.0 s |
  | Legato | 47.9 | 60.0 | 55.0 | 55.0, then 59.0, 62.2, 64.6 |

  Stock: each note from its voice's last pitch (72), as the code reads.
  LastNote: from where the previous note's pitch is at that moment (48 had
  reached about 50 and 60 about 59.4 when the next note came). Legato:
  detached notes on pitch, the legato note from the held one. The held 55
  stays at 55.0 while the new voice glides.
- **MPE.** The patch binds a member channel to a voice in a hook on
  `voice_alloc`'s `voice_glide` call (`0x08012640`) and leaves glide alone.
  So with MPE on, a note glides from its voice's last pitch as in Poly;
  when a channel takes over its own still-sounding voice (channel reuse),
  that is the channel's previous note. The per-note bend is added in
  `osc_pitch`, after the glide, and does not enter the glide pitch.

## Timers and the 1 kHz tick (2026-11-15)

Why the simulator ran the Peak twice as fast as the synth, and what the
real rates are. Register values **observed** in the image; the 60 MHz timer
clock **inferred** as on the Summit; the result agrees with a time measured
on the synth.

- **Clock tree:** the same values as the Summit's `clock_init`:
  `RCC_PLLCFGR = 0x05401E03`, `RCC_CFGR = 0x00409402` (literals at
  `0x0800DAA4`, `0x0800DAAC`): SYSCLK 120 MHz, TIM6 clock 60 MHz (inferred,
  [Summit findings](summit-2.2-build2121.md#modulation-tick-mod_update-call-rate)).
- **TIM6** (`FUN_0800E414`): PSC 59, **ARR 99** (the Summit: ARR 49). So
  60 MHz / 6000 = **10 kHz**, half the Summit's 20 kHz.
- **TIM6 interrupt** (`0x0800E470`, vector 70): every 10th interrupt (the
  Summit: every 20th) it requests a modulation tick (`FUN_08010E40`,
  `voice_state+0xAC`), counts the millisecond counter `0x20003AD0+0x1C0`
  (low 16 bits at `+0xD2`, read by `FUN_0800E4FC`), scans the panel
  and steps the tempo clock (`FUN_0800FB80`). So the **modulation tick
  (`mod_tick`, and the patch's `mpe_mod_update`) is 1 kHz** and the counter
  counts milliseconds.
- **The tempo clock confirms 1 kHz:** `FUN_0800FB80` adds the tempo word
  (`0x20000264`, 1,717,984 per BPM) to a 32-bit accumulator on each of those
  ticks, and each overflow is one MIDI clock. 2³² × 24 / 60 / 1000 =
  1,717,987: the constant is 24 clocks per quarter note at a 1 kHz tick
  (observed in the code). On the synth an arp step at 120 BPM measured
  125 ms (observed, 2026-11-13), so the tick there is 1 kHz.
- **The simulator's error:** it raised TIM6 in every 50 µs slot, the
  Summit's rate, whatever the firmware programmed. On the Peak that made
  every firmware timer run twice as fast as simulated time: 2000
  modulation ticks per simulated second, an arp step in 62.5 ms. Fixed
  2026-11-15: `emu/board.py` takes the period from TIM6's PSC and ARR
  (`Board.tim6_period_us`). Summit timing is unchanged.
- **Message time** (`ui_msg_countdown` `0x08018ADC`, main loop): the
  countdown `ui_msg_state+2` loses one count on a main-loop pass that finds
  the millisecond counter advanced by more than 10 since the last count
  (`cmp r3, #10` at `0x08018AEA`), so **one count is 11 ms** (observed in
  the code; emulated; and on the synth `Msg Time` 127 lasted about 1.5 s by
  the user's stopwatch, 2026-11-15, against 132 × 11 ms = 1.45 s). A knob
  message starts at `Msg Time` + 5 counts (`FUN_08018A98`); `Msg Time` is
  0–127, initial value 64, which is also what the user's Peak has. The
  guide's "127 is equivalent to approx. 3 seconds" is twice what build 2108
  does. From v0.15 the patch changes the compare to 21, so a count is 22 ms
  and 127 lasts 2.9 s (the user asked for about 3 s).
- **When the page comes back.** At the end of the countdown the page is
  redrawn only if the changed flag `ui_msg_state+1` is nonzero (the same
  function; `mark_changed` `0x08018A88` sets bit 0, every parameter write
  calls it). A message drawn without any parameter change is therefore
  never cleared by stock. Stock's own messages always follow a change; the
  patch's did not: on v0.14 the `Done:` message of a section copy onto equal
  values, and the `UNDO` message after it, stayed on the screen for good
  (observed on the synth, series F4, more than 45 s; reproduced in the
  simulator: flag 0 after an Osc1>2 copy on the Init patch, 1 after
  Amp>E1). Fixed in v0.15: `ui_say` calls `mark_changed`.
  The earlier note "about 60 ms per count" came from a `Done:` message seen
  for about 0.3 s on v0.12 and assumed `Msg Time` 0; with the real 64 that
  message had at least 0.76 s of countdown, so its 0.3 s was the page
  redraw that v0.13 removed.
- **Consequences for the patch as flashed in v0.13** (constants written for
  the simulator's 2 kHz): EnvSync applied a changed choice after about 2 s
  (meant 1 s) and a tempo change after about 1 s (meant 0.5 s); the undo
  gesture window was about 4 s (meant 2 s); and the "hold" of the Do it and
  undo messages, 35 counts, was 0.4 to 0.8 s (meant 2 s). Corrected in v0.14
  (the hold is timed by the patch's own 1 kHz tick, not by stock's
  countdown); on the synth the undo window behaved as intended (series F5,
  user).
- **DIN receive ring and its overflow counter** (`0x20003EAC`, USART6
  interrupt `0x0800EDD8`, observed): `+0` receive write index, `+1` receive
  read index, `+2`/`+3` transmit read/write index (all u8), `+4` transmit
  ring (256 bytes), `+0x104` receive ring (256 bytes), **`+0x204` overflow
  counter: one byte** (`ldrb.w r2, [r3, #0x204]` at `0x0800EE2C`, `adds`,
  `strb.w` at `0x0800EE32`), counted up when the write index catches the
  read index. It wraps after 255; no other code reads or writes it (the
  diagnostics page of the patch shows it).

## Value scales for the randomiser (2026-11-18)

- **`format_value` `0x08017604` `(display, value)` prints at the LCD
  cursor** (`lcd_cursor`/`lcd_putc_esc`); it returns nothing useful.
  Called in the simulator with the cursor set and the display read back
  (emulated, `work/_rand_fmt.py`):
  - display `0x17` (Osc Coarse, 9-bit value): `0` = -12.0, `128` = +0.0,
    `255` = +12.0, about 10.6 per semitone; whole semitones at 0, 10,
    19/20, 30/31, 41/42, 52/53 (-7), 62/63, 73/74 (-5), 84/85, 94/95,
    105/106, 116/117, 127/128 (0), 138/139, 149/150, 160/161, 170/171,
    181/182 (+5), 192/193, 202/203 (+7), 213/214, 224/225, 235/236,
    245, 255 (+12).
  - display `0x04` (Fine, LFO-to-pitch, 9-bit): value - 128 (Fine's
    28-228 is -100 to +100 cents).
  - display `0x33` (`WaveMore`): 4 `BS sine` to 63 `Yeah` are the 60
    factory tables; **64-73 are `*User 1` to `*User 10`**.
  - display `0x34` (LFO 1/2 wave, `0xAF`/`0xBD`): `Triangle`, `Sawtooth`,
    `Square`, `Rand S/H`.
  - display `0x15` (Osc Range 63-66): 16', 8', 4', 2'.
  - display `0x07` (envelope Repeats): 0 `Off`, 127 `On`; `0x06` (LFO
    Repeats): 0 `Off`, 127 is 127.
  - display `0x22` (patch offset **`0xEC`**): `Chorus`, `Flanger`,
    `Phlanger`: `0xEC` is the **chorus Mode**, not an arp setting.
    PARAM LOCK v0.11-v0.25 had it in the Arp group (`0xEC-0xFA`) and its
    save buffer was 64 bytes for the 66 of all three groups (two bytes
    past it on the stack; harmless in the simulator, inferred harmless on
    the synth: series E and later passed with all locks used). v0.26
    moves `0xEC` to FX and sizes the buffer for 66.
- **Filter Shape 0/1/2 = low/band/high-pass and Slope 0/1 = 12/24 dB**
  (inferred from the string order `LOW`, `BAND`, `HIGH`, `12dB`, `24dB`
  at `0x0804440C`-`0x0804442C`; Slope 1 = 24 dB agrees with the units
  measurements, docs/peak-units.md).

## The parameter setter and 9-bit controls (2026-11-16)

Found while building the patch morph. Code **observed** (decompile), the
refusal **emulated** (`tests/test_peak_morph.py`
`test_a_low_fine_tune_comes_back`); not tried on the synth.

- **`param_set_by_id` `0x0800F6AC` `(value, id)`**, the setter behind a
  received CC, looks up the patch offset of the id (`0x0800F614`), compares
  the value with that offset's descriptor minimum and maximum, and only
  then calls `param_write` `0x0800F658` (writes the byte if it differs, ORs
  the offset's group mask into `param_dirty_groups`, `mark_changed`) and
  `pickup_arm`.
- **For the coarse byte of a 9-bit pair the descriptor holds the pair's
  range, and the setter holds the 7-bit byte against it.** Harmless where
  the range starts at 0 (FiltFreq, the levels, LFO rates: 0-255). The three
  oscillator Fine controls have 28-228 (offsets `0x33`, `0x48`, `0x5D`; CC
  15, 18, 21 by the descriptor table): their coarse byte runs 14-114, and
  **the setter refuses 14-27**. So over MIDI a stock Peak takes the Fine CC
  only from 28 up (the lowest quarter of the downward range is reachable
  from the panel only: inferred from this code, the panel path
  `0x08017488` calls `param_write` directly).
- **For the patch:** `param_put` (`section.c`), which every feature uses to
  set a patch byte, sent such a byte through the setter, so section copy,
  undo, a motion lane and now the morph could not set a Fine tune below
  that. From v0.18 the coarse byte of a 9-bit pair goes to `param_write`
  and `pickup_arm` directly.
- **Over MIDI, 2026-11-17 (emulated, `tests/test_peak_ccpair.py`):** with
  Settings receiving CCs, CC 15 at 14-27 sent over DIN through `cc`
  `0x0800F124` leaves Osc 1 Fine as it was on the stock image; 28-127 are
  stored as sent (so 115-127, above +100, are taken too). The same bug was
  reported upstream for the Summit 2.2 (michaelkollmann/gipfel_mpe pull
  request 3, open), whose fix lowers the three minimums to 14.
- **Who reads the descriptor's min and max** (every literal-pool word that
  points at `patch_param_desc` `0x200017CC` in the stock image, read in the
  decompile; observed): `param_set_by_id` (literal `0x0800F708`, the check
  above); `ui_value_change` `0x08018448` (`0x080186D0`), the menu encoder,
  which for a pair (msb `0xFE`) builds the 9-bit value and clamps it to min
  and max, so there they are 9-bit bounds as intended; two handlers of the
  stepped panel buttons, `0x08016A30` (`0x08016AAC`) and `0x08016D58`
  (`0x08016DEC`), which cycle a button's value through min to max (Fine is
  a pot, not one of them, inferred from the button table's use). The other
  readers take only the name, NRPN bytes or display type (`knob_overlay`
  `0x08016CB0`, `0x08017DB8` building the offset-to-id table, `ui_draw_page`
  `0x08018060`, `ui_draw_values` `0x080182AC`). The knob path (`knob_poll`
  `0x08016DF4`) does not read min or max. In the patch, `disp.c` draws the
  knob's value bar over min to max, and `morph.c` clamps a stored value to
  them.
- **So the fix is in the setter's caller, not the descriptors (v0.22,
  `ccpair.c`):** lowering the minimum to 14 would let the menu encoder take
  a Fine on a menu page down to 9-bit 14 (below the panel's −100) and would
  move the centre of the patch's Fine value bar. Instead `cc`'s call of
  `param_set_by_id` for a plain CC (`bl` at `0x0800F318`; the other call,
  `0x0800F30E`, is NRPN data entry with ids from `0x80`) goes to
  `ccpair_param_set`: for a CC whose patch offset (`param_offset_of_id`
  `0x08017E68`) is a pair's coarse byte, the value is clamped to half the
  pair's range (14-114 for Fine) and written through `param_write` and
  `pickup_arm`, as the setter writes; every other id goes to stock's
  setter. Emulated: CC 15, 18 and 21 store 14-114 as sent, 0-13 as 14 and
  115-127 as 114; Resonance and the FiltFreq pair (0-255) store what stock
  stores; the descriptors are stock's; a held note's oscillator pitch drops
  from Fine −73 (CC 28) to −100 (CC 14). Not yet on the synth.

## Compare and Save (2026-11-16)

Read for the morph. Code **observed** (decompile), behaviour and screens
**emulated** (`tests/test_peak_morph.py`, buttons pressed through the
firmware's event queue); not yet on the synth with a morph running.

- **Button events.** The panel scan puts one byte per event into a ring of
  64 at `0x20003AD0+0x88` (the `button_table` index, bit 7 = pressed; write
  index `+0x84`, read index `+0xDA`); `panel_event_read` `0x0800DDFC` takes
  them for `panel_button_event` `0x08016FF0`.
- **Compare** (action 8): `panel_button_event` writes `compare_held`
  `0x200111F2` (1 pressed, 0 let go), then calls `compare_action`
  `0x080188A8(pressed)`, which calls `patch_compare` `0x080130AC`.
  Pressed: the patch `0x20012340` (0x201 bytes) is copied to
  `compare_stash` `0x20012570`, then the stored record is read and loaded
  with `patch_load` (`0x0801AF10`). Let go: the stash is copied back into
  the patch and pushed to the sound chip (`0x08013044`), without
  `patch_load`. In Save mode (UI mode 9) Compare works only on page 2 and
  loads the destination's record instead (`0x0801AF44`).
- **Pressing Compare ends all notes; letting go does not.** `patch_load`
  `0x0801AEB8` calls `0x08011EA0`, which calls `voices_all_release`
  `0x08011A20`: a release command to all eight voices, gates cleared
  (code observed). Emulated on the stock image: a note held when Compare
  is pressed loses its gate, a note played while it is held sounds and
  goes on through the release (the release makes no `patch_load`); the
  same on v0.19 with `MPE` On (`work/_compare_note.py`,
  `tests/test_peak_morph.py`). On the synth with v0.19 (the user,
  2026-11-16, series L): pressing Compare stopped the held note and the
  voice LED went dark (observed; stock firmware on the synth not tried).
  The same holds for any patch load: a patch change or Initialise.
- **Save** (action 3, `settings_save_action` `0x08018FCC`): in the Settings
  menu (mode 8) it stores the settings (screen `Settings Saved With` /
  `PROTECT OFF`), not the patch. Elsewhere the first press opens Save mode
  (mode 9: `SAVE RENAME      1/3`), the next two step to
  `SAVE LOCATION    2/3` and `SAVE CATEGORY    3/3`, and the fourth calls
  `patch_save` `0x08018F10(number, bank)`: the patch's 0x200 bytes to
  record (number + (bank - 1) × 128) × 512 of the patch memory. It then
  sets `patch_select` +4/+5 to the destination and shows
  `Patch Saved To` with bank letter and number. No `patch_load`: the patch
  in RAM is not touched.
- **What that meant for the patch (v0.12 to v0.18).** The hook on
  `patch_load`'s copy (`plock_copy`) cannot tell Compare's load from a
  patch change. With a morph running, v0.18 took the stored patch as the
  new edit and, at the release, the blend that stock copied back as an edit
  again: after Compare at position 64 an edit of 100 against a stored 0 read
  25 instead of 50, and at position 127 the edit was gone (emulated on
  v0.18). From v0.19 the morph stands still while `compare_held` is set
  and starts afresh after `patch_save` (hook at `0x0801903E`).
- **The undo step and the motion lane (v0.12 to v0.19):** pressing Compare
  also cleared the undo step and stopped a motion lane, because both are
  cleared in the same hook (emulated on v0.19: after Compare `Mod` +
  Page left said `Nothing to undo`, and the MOTION page read `Off`, the
  control left at the lane's last value). From v0.20 the hook leaves all
  three alone while `compare_held` is set: nothing is recorded, undone,
  pasted or quick-assigned on the patch Compare plays, a lane keeps its
  time but writes nothing, and both go on at the release
  (`tests/test_peak_compare.py`, emulated; not on the synth).

## Arp rhythm patterns (2026-11-16)

Read for Euclidean rhythms (feature list step 17). Code **observed**
(decompile); the format **emulated** by playing patterns built to it
(`tests/test_peak_euclid.py`). Nothing on the synth yet.

- **Where the 33 rhythms are.** The word at `arp_state_ptr` `0x20000640` is
  the arp state's address (`0x200127D4`); the 33 words from `0x20000648`
  point at the patterns, in flash from `0x080427C4` (Rhythm 33) up to
  `0x08042E4C` (Rhythm 1). A pattern is a count byte, a zero byte, then
  that many two-byte events.
- **An event** is a velocity (`0x64` = 100; stock uses `0x32` to `0x68`
  for accents) and a length in arp clocks. Velocity 0 is a rest. The step
  is played at that velocity, not the key's: `arp_step` `0x080151A0` takes
  it from state `+0x1D9` whenever `+0x1E3` is set, and `arp_tick` sets
  that every tick (observed). Emulated on stock: a key struck at 30 played
  at 100 in Rhythm 1, and at 100, 100, 65, 100, 66 in Rhythm 2. Six clocks are one step of the SyncRate. A note event is always
  followed by a rest event: Rhythm 1 is `64 03 00 03` (a note of 3 clocks
  and a rest of 3, every step), and Rhythm 4 starts with a lone rest
  (`00 0C`).
- **Playing them** (`arp_tick` `0x08015554`, called once per tick from
  `tick_work` `0x0801192C`, the call at `0x08011956`): when the patch's
  Rhythm (`+0xF1`) differs from the number kept at state `+0x1D8`, the
  pattern's count goes to `+0x1D4`, the address of its events to `+8`, and
  `arp_pattern_reset` `0x08014F68` starts it from the first event. The
  reader `0x08015518` takes the event at index `+0x1D5` and wraps at the
  count. For a rest the next event time (`+0x1D6`, clocks × 256) moves on
  by its length. For a note the reader takes the next event too, moves on
  by both lengths, and sets the step's end (`+0xC`) from ArpGateTime
  (`+0xF3`): 64 gives the note's own length, 127 the whole of note and
  rest, between them a share of the rest, below 64 a share of the note.
- **Times are 16 bits**, compared by the sign of their difference, so one
  event pair must stay under 128 clocks (21 steps). Stock's longest pair is
  37 clocks.
- **The pattern free-runs.** With no key held the events are still read and
  timed; a key pressed when the arp has no notes restarts the pattern
  (`arp_reset` `0x08014FA8`), so the first step sounds at once unless the
  pattern starts with a rest.
- **Swing** works on the 6-clock grid in `arp_tick`, apart from the
  patterns.
- **Which note a step plays** is chosen at each note event by
  `arp_step_select` `0x08015408` (called from `arp_tick` at `0x0801574E`
  while the arp is on): by the Type's flags (state `+0x1DE`) it walks the
  play map up or down from the last note (`+0x1DC`, direction `+0x1DD`,
  octave `+0x1E0`), or takes the played-order list at index `+0x1CC`, at
  random for the random types (`arp_random_seed` `0x20011178`), or all of
  the list at once for the chord types. Every note event moves the choice
  on, so a pattern alone cannot repeat a note.
- **Voices for a repeated note (emulated, `work/_ratchet_voice.py`; the
  feature list's check for ratchets):** with one key held, each step takes
  the next voice in Mono2, Poly and Poly2, on stock and with MPE on
  (voices 0, 1, 2, ... 7, 0); in Mono and MonoLG every step retriggers
  voice 0. Poly2's choice depends on the levels the sound chip reports,
  which the simulator only models.
- **Ratchets (v0.21, emulated, `tests/test_peak_ratchet.py`):** the repeat
  of a note is a note event with bit 7 set in its velocity. The hook on the
  call of `arp_step_select` clears the bit and puts `+0x1CC`, `+0x1DB`,
  `+0x1DC`, `+0x1DD`, `+0x1E0` and the seed back to what they were before
  the note's first sounding, so stock chooses the same note again: checked
  for all eight Types (the chord types repeat the whole chord). If the
  chord changes between a note and its repeat, the repeat is chosen from
  the new chord.
- **A cost of the arp echo filter seen on the way (emulated):** with
  Arp>MIDI On, a key on the global channel released within 100 ms of the
  arp's own note off for the same note is taken for the echo and dropped
  (`arp_echo.c` says so). With one key held the arp plays that very note,
  so its release is at risk each time: in the simulator the arp then went
  on after the key was let go, until the key was pressed and released
  again. MPE notes arrive on member channels and are not affected.
  **Mended in v0.20 (emulated, `tests/test_peak_arp_echo.py`):** a note
  off is dropped only while a loop is known to be there, that is, within a
  minute of one of the arp's note ons coming back. With no loop a release
  always gets through; with a loop the filter works as before.

## MIDI Tuning Standard in stock (2026-11-16)

The feature list asked whether stock already takes real-time retuning. It
does, for one note per message. Code **observed** (decompile), the
single-note message **emulated** on the stock image (`work/_mts.py`);
nothing on the synth.

- **SysEx parsers.** Each received byte goes to seven parsers in turn
  (`0x0801AE0C`), each with its own header from the table at `0x08042E98`:
  Novation's `00 20 29 ...` ones, the identity request `7E 7F 06 01`, and
  two for tuning.
- **Single-note tuning change, real time** (`0x08019548`, header
  `7F 00 08 02`): `F0 7F 00 08 02 tt ll kk xx yy zz F7` with the table
  number `tt` 0 to 16. It calls `tuning_note_set` `0x08012CCC(tt, kk, xx,
  yy, zz)`: the note's entry in the table becomes `xx << 8 | yy << 1 |
  zz >> 6` (a semitone and 1/256 of one; `7F 7F 7F` means no change), and
  if `tt` is the patch's table (patch `+0x162`), voices sounding that key
  are retuned at once. Emulated: table 1, key 60 set to 61 and 50 cents
  read `0x3D80` afterwards (`0x3C00` before).
- **Limits (emulated):** the device ID must be `00`; the same message to
  `7F` (all devices) changed nothing. The parser takes exactly 11 bytes
  after `F0`, so only one note per message: with `ll` = 2 nothing changed.
- **Bulk dump, non-real time** (`0x08019B40`, header `7E 00 08`):
  sub-ID `00` with a table number answers with that table's dump
  (`0x08019A6C`); sub-ID `01` takes a whole table, 128 notes of three
  bytes after the 16-character name (observed, not emulated).
- The tables are 17 × 128 words at `0x20012CF4`; the Init values are the
  key number × 256 (equal temperament).
- **What a patch could add:** accept device ID `7F`, and more than one note
  in a message. Both are small changes to one parser; neither is built.
- **Stock's parsers in detail (observed, decompile).** Each SysEx byte
  reaches `sysex_rx_byte` from `midi_parse_byte` (`0x0800EFC0`); its calls
  of the seven parsers are at `0x0801AE12` to `0x0801AE4A`, the single-note
  one at `0x0801AE42`. `mts_single_note_rx` collects 10 bytes, compares the
  first four with `7F 00 08 02`, then needs `F7` as the 11th; `ll` is never
  read. It locks to the port of its `F0` until the message ends, and any
  other status byte ends the message (a real-time byte too, if one
  arrives). `mts_bulk_rx` takes `7E 00 08 01 tt`, then 401 bytes (name,
  data, checksum) and `F7`; it doesn't test the checksum and doesn't call
  `mark_changed` (the single-note parser does). The tables are 17 x 128
  u16 (not words).
- **The patch's parser (v0.25, `mts.c`; emulated in
  `tests/test_peak_mts.py`):** after stock's, on every byte. Device ID `7F`
  and three notes in one message reach the table (and `00` with three
  notes); device `00` with one note is still stock's; wrong lengths,
  device `10`, table 17 and a message cut by a note-on change nothing; a
  clock byte inside a message doesn't end it; the bulk dump to `7F` sets
  all 128 keys of its table only; a held note on the patch's table moves
  at once (`voice_pitch`).
- **On the synth (2026-11-18, v0.25, over USB; observed,
  `work/mts_check.py`):** with the sound on table 16, a device-`7F`
  single-note change moved A4 by +49.8 cents (target +50), a device-`00`
  message with two notes moved A4 +24.9 and C5 +99.9 cents (+25, +100),
  a device-`7F` bulk dump with every key one semitone down gave -100.2
  cents, and a held A4 retuned by a device-`7F` message moved +49.8 cents
  within the note. Reference A4 440.02 Hz.

## Main-loop pace in the simulator (2026-11-16)

**Emulated** (`work/_w_probe.py`): three broadcast writes to the sound chip
(target 24, parameters 0, 3 and 13) are paced by the main loop, 712 of each
in 100 ms idle on stock. With the patch 637 (v0.17) and 630 (v0.18): the
patch's polls and hooks add about 12% to a main-loop pass in the
simulator's count of instructions, the morph under 1% of that. Every other
write of a note on and off is the same as stock (1,947 against 1,947).
`tests/test_peak_sim.py` `test_mpe_off_writes_as_stock` compared the totals
within 2% and tripped at v0.18 (2.1%); it now holds the note's own writes
to 0.5% and the paced ones to 15%. On the synth the pace is not a concern
so far: v0.17 lost 9 modulation ticks in 10 s, all of them page draws.

## Pedal sources and the note-off velocity (2026-11-17)

From the decompile and the disassembly (**observed** unless marked).

- **`note_off` ignores the velocity.** `note_off` `0x0800F4B0` gets a
  pointer to the message's data bytes and reads only the note (`*param_1`);
  the second byte, the note-off velocity, is never read. `note_on` with
  velocity 0 calls it the same way. The arp path (`arp_note_off`) doesn't
  read it either. So stock has no use for release velocity anywhere, and
  the guide's matrix source list (Direct to Noise, 24 entries; the same
  list as the pointer table at `0x08046480`) has no release-velocity source.
- **The two pedal sources.** `mod_update` `0x0801088C` sends `n` = 2 and
  `n` = 3 (`voice_mod_write(0xA, n, value)`, parameters `0x62`/`0x63` to
  every voice) on every tick at `0x080109C0` and `0x08010A0E`, plus
  `part_mod_write(2/3)` just after. The values are `parts+8` and `parts+9`,
  each smoothed by 1/8 of the step per tick (`voice_state+0x38`/`+0x3C`,
  16.16; 127 becomes `0x7FFF`). `parts+8` is set by CC 11 (the `cc` handler's
  case `0xB`, `FUN_08011D74`) and by the pedal input code at `0x080171C4`,
  which also sends CC 11 out; `parts+9` by CC 2 (`FUN_08011D80`). So
  `0x62` is the source the guide calls `ExprPED1` and `0x63` `BrthPED2`
  (inferred from that and from the source list's order after `ModWheel`
  0x60 and `AftTouch` 0x61; the matrix source indices are 3 and 4).
  **Observed on the synth 2026-11-18** (v0.24, run
  `relvel-2026-11-18_083855`): CC 11 moves matrix source 3 (`ExprPED1`),
  and writes to `n` = 3 move matrix source 4 (`BrthPED2`).
- **The patch's release velocity (v0.24, `relvel.c`; emulated in
  `tests/test_peak_relvel.py`):** with Settings `RELEASE VEL` > `Source`
  on a pedal source, that broadcast is dropped and `mpe_note_release`
  writes the note-off's velocity (`<< 8`, 127 = `0x7FFF`; a note-on with
  velocity 0 counts as 64) into the source of each gated voice with that
  note, then calls stock's `voice_release`. In the simulator the source
  write comes right before the voice's release command (`0x3F`, command 3),
  only for the released voice, and with MPE on only for the note-off's
  channel.
- **On the synth (2026-11-18, v0.24; observed):** the chip applies the
  source value written microseconds before the release command to that
  release, so no deferral is needed. `BrthPED2` x `Direct` to `AmpEnv R`
  at +40, base release 30, one note per take: t20 by note-off velocity
  1 gives 0.118 s (twice), 40 gives 0.235, 64 gives 0.455, 100 gives
  1.571, 127 gives 3.956 and 3.736. A take at velocity 1 right after one
  at 127 is as short as the first (no carry-over). By ear (user,
  LinnStrument in MPE): two held notes lifted at different speeds keep
  their own release, so the per-voice write reaches only its voice (not
  measured).

## A blank settings chip (2026-11-18)

Roadmap step 3. The simulator normally seeds a blank DataFlash; with that
switched off (`tests/test_peak_blank.py`) the chip reads 0xFF everywhere.

- **`settings_load` reads no index from a blank chip** (observed in the
  decompile, emulated). `settings_load` `0x0801AFD8` copies the 0x200 bytes
  at `0x300000` into the globals and passes `globals+6` (u16) to the patch
  loader `0x0801AF78`, which returns at once when bit 15 is set, as it is
  for `0xFFFF`. Only `+0x1E`/`+0x1F` are forced to 1. So the Summit's "copies
  from arbitrary RAM" (port plan 2b item 4) doesn't happen on the Peak.
- **Stock itself doesn't run on a blank chip** (emulated). No patch loads,
  so the edit buffer stays 0xFF; that turns the arp on, and the arp reads
  its pattern through a null pointer (`FUN_08015518`, `pc=0x0801552A`,
  pointer at arp state `+8`). The simulator stops there, stock and patched
  alike, half a second after boot. On a unit address 0 is the boot alias,
  so it would read bytes rather than fault (inferred). A blank chip needs
  a format (Init Patch in 512 slots, multis, globals), which the Peak
  application doesn't contain; it only happens on a chip that was never
  formatted or was wiped outside the application.
- **The patch's stored settings tolerate any byte** (observed in the source,
  emulated). Globals `0x30`-`0x38`, `0x3E`-`0x40`, `0x45`-`0x4A` read 0xFF
  on a blank chip (or on a unit whose bytes were never written); every
  reader falls back to its default (`mpe.h`). With all of them at 0xFF the
  MPE pages show the defaults (Zone Off, Members 15, bend 48/2, Squared,
  Off, Stock, locks Off, 1 bar, Morph Off, Pulses Off, Steps 16, Rotate 0,
  Ratchet Off, Every 1, Source Off) and a note plays and releases as stock,
  with `BrthPED2` still broadcast.
- **Conclusion:** no guard in the patch. The patch's own part is already
  safe; the rest is stock's behaviour on an unformatted chip, and fixing it
  would mean writing a factory format into the patch for a state a user
  doesn't reach.

## Dead ends

- `cmp r4, #0xf0` hits at `0x08011CA4` and `0x0801258C` are literal pools
  (RAM pointers) that the linear disassembler decoded as instructions.
- Status compare clusters at `0x080457C0+` lie in the data region.

## Open

- The sound chip's replies in numbers: when a voice's state goes from 0 to
  1 or 2 and the level's scale. The behaviour that follows from them is
  observed (voice allocation section).
