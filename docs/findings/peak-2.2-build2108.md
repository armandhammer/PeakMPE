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
  the bit rate; not measured). The modulation tick is not caught up
  (`mod_tick`), so each full redraw costs about four of the 1 kHz ticks.
- **Simulator.** The LCD model decodes this driver, so tests read the DDRAM
  codes and `lcd.glyph(code)` bitmaps; the pots are not modelled, so a
  test calls `knob_overlay` directly with the arguments above, as `knob_poll`
  does.

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

## Dead ends

- `cmp r4, #0xf0` hits at `0x08011CA4` and `0x0801258C` are literal pools
  (RAM pointers) that the linear disassembler decoded as instructions.
- Status compare clusters at `0x080457C0+` lie in the data region.

## Open

- The sound chip's replies in numbers: when a voice's state goes from 0 to
  1 or 2 and the level's scale. The behaviour that follows from them is
  observed (voice allocation section).
