# Summit 2.2 (build 2121) — findings

Target image for the MPE mod. Flash base `0x0800C000`, 278,976 bytes (ends at
`0x080501C0`). The container and image layout are in
[../firmware-format.md](../firmware-format.md). The names used here are in
[../symbols/summit-2.2-2121.csv](../symbols/summit-2.2-2121.csv), and
`scripts/ghidra-import.sh` applies them.

**Confidence:**
- **observed:** read directly from decompiled code or bytes;
- **emulated:** checked in `emu/` tests;
- **inferred:** a reasoned interpretation, not yet tested.

Most of this is static analysis of the MCU firmware; "emulated" items were
checked in `emu/` (since phase 3, mostly with the simulated Summit,
[../SIMULATOR.md](../SIMULATOR.md)). The FPGA is a black box.

## The MIDI path: byte → voice

```
DIN:  USART6 IRQ 0x08010C40 ─ ring 0x200050CC ─┐
                                                ├─ midi_poll_din 0x0801A8CC ─ midi_route 0x0801D610(b, mode)
USB:  OTG IRQs ─ usb_midi_rx 0x08021100 (4-byte packets) ──────────────┐            │ (forward: usb_tx_byte, din_tx_byte)
                                                                        ▼            ▼
                                    midi_in_queue_push 0x08010B9C(b, src)   src 0 = USB, 1 = DIN
                                                     │   queues: 2 × 0x110 B at 0x20004D8C
                                    midi_drain 0x08010874(src) ─ 0xF8 clock handled apart
                                                     │
                                    midi_parse_byte 0x080107B0   (running status, table driven)
                                                     │   descriptor = midi_status_desc 0x08010114(status)
                                    midi_channel_filter 0x08010710   ◄── MPE hook #1
                                                     │
            RAM table 0x200002D0  (8 B per entry: handler, data length, flags)  ◄── MPE hook #2
             8x note_off 0x080109CC   9x note_on 0x08010AB0   Ax poly_at 0x0801021C   Bx cc 0x080102C0
             Cx pgm 0x08010278       Dx chan_at 0x08010234   Ex bend 0x08010258
```

| Function | Address | Confidence | Notes |
|---|---|---|---|
| `usart6_irq` (DIN MIDI) | `0x08010C40` | observed | USART6 (`0x40011400`). 256-byte TX and RX rings in a struct at `0x200050CC`; RX byte at `+0x104+head`; overflow counter at `+0x204` |
| `din_rx_byte` | `0x08010CE8` | observed | Pops one RX byte. With soft-thru on (`+0x205`), echoes it out through `din_tx_byte` `0x08010CBC` |
| `midi_poll_din` | `0x0801A8CC` | observed | Main-loop poll: `midi_route(byte, 2)` until the ring is empty |
| `midi_route` | `0x0801D610` | observed | Switch on mode: forward to USB (`usb_tx_byte` `0x080212D8`) and/or DIN out, and/or deliver internally (`midi_in_queue_push`). Mode 2 = DIN in → internal source 1 |
| `usb_midi_rx` | `0x08021100` | observed | Reads 4-byte USB-MIDI packets and pushes `CIN`-length data bytes as source 0 |
| `usb_tx_byte` | `0x080212D8` | emulated | **USB-MIDI output** packetizer: byte stream → `[CIN, b0, b1, b2]` packets, then `0x08021294`. Earlier docs and `tests/test_midi_parser.py` called it the input parser. It's used for forwarding/out, not input |
| `midi_in_queue_push` | `0x08010B9C` | observed | Selects the queue with `midi_queue_select` `0x080100F4(src)`. Queue `src` is at `0x20004D8C + src*0x110`; the current-queue pointer is at `0x20004D88+0x334` |
| `midi_drain` | `0x08010874` | observed | Pops bytes from one source; `0xF8` → clock handlers (`0x080131E0` DIN, `0x080131C8` USB); anything else → `midi_parse_byte` |
| `midi_parse_byte` | `0x080107B0` | observed | Per-source parser state in the queue struct (`+0x104` write pointer, `+0x108` bytes left, `+0x10A` status, `+0x10B` data) |
| `midi_status_desc` | `0x08010114` | observed | `status < 0xF0` → `0x200002D0 + ((status & 0x7F) >> 4) * 8`; otherwise `0x20000308 + (status & 0xF) * 8` |
| `midi_channel_filter` | `0x08010710` | observed | **Single mode:** the handler runs only if channel == global channel (`0x20004B2A`); all other channels are **dropped**. **Multi** (`0x20004B20 != 0`): Part A channel (`0x20004B2B`) → part 0, Part B (`0x20004B2C`) → part 1, global channel → `multi_global_dispatch` `0x080104EC` (split/layer to both parts). Current part is written to `0x20004D88` before the call |
| Channel handler table | RAM `0x200002D0` (init from flash `0x0804C050`) | observed | In `.data`, so patchable by changing its flash initializer. System-message table at `0x20000308` |

## Notes and voices

| Function | Address | Confidence | Notes |
|---|---|---|---|
| `note_on` | `0x08010AB0` | observed | Velocity 0 → `note_off`. Arp on (patch `+5`) → `arp_note_on` `0x0800CCFC`. Otherwise `held_note_add` `0x080101B4`, last note at `part+0x126`, then `voice_trigger` |
| `note_off` | `0x080109CC` | observed | Mono modes (patch `+2 < 3`) use last-note priority via `held_note_prev` `0x08010940`; otherwise `voice_release` `0x080154F4(note)` |
| `voice_trigger` | `0x08017244` | observed | `(note, vel, part)`. Unison count from patch `+0x23` (value 4 → 8 voices); calls `voice_alloc` once per stacked voice |
| `voice_alloc` | `0x08016B40` | observed | `(note, vel, part, voice, unison)`. **`voice >= 0` forces that voice index**, which is how MPE can pin channel → voice. Modes from patch `+0x22`: 0/1/3/4 rotate through free voices (4 = reuse the voice already playing the note); 2 = strict round-robin; stealing sorts by age. 16 voices in Single mode, 8 per part in Multi (Part B = voices 8–15). Writes note → `voice_note[v]` `0x20014950`, base pitch → `voice_pitch[v]` `0x200149A8` (8.8 semitones from the tuning table `0x20014B0C`), then voice params via `fpga_voice_write` |
| `voice_release` | `0x080154F4` | emulated | Release by note: envelope commands with state 3 for the voice's three envelopes (`env_command` `0x0801536C`), then clears its aftertouch slot and active flag (`voice_clear_at` `0x0801534C`) |
| `fpga_voice_write` | `0x08012B94` | emulated | `(target, param, value)`, an SPI1 transaction (see [The FPGA bus](#the-fpga-bus-spi1)). Target 0–15 = voice; `0x18`/`0x19`/`0x1A` = broadcast or part targets. Note-on sends `0x40/0x43/0x46` (32767; called envelope gates here), `0x66` velocity (`vel << 8`), `0x67` pitch (`voice_pitch - 0x3C00`) and the envelope commands `0x3F/0x42/0x45` |
| `fpga_mod_write` | `0x08013FCC` | emulated | `(part_mask, target, param, value)`, `part_mask` `0x80` = Part A, `0x40` = Part B, 0 = by target. Queued in RAM and sent from the TIM6 interrupt |

**Voice state:** structure-of-arrays rather than a single struct. Base
`0x200057D8`:
- `+0x334 + v`: active flag
- `+0xE4 + 2v`: aftertouch value (u16)
- `+0x104 + 4v`: smoothed aftertouch
- `+0x3E0 + v`: generation stamp
- `+10`: voice loop index. `voice_alloc` leaves its pick there, but
  `mod_tick` reuses it as its loop counter every tick, so it isn't "the
  current voice" for long (observed)
- `+0x312`: `voice_last_alloc`, the last voice `voice_alloc` allocated
  (`strb` at `0x0801700A`, the only writer); also selects the part-level
  `0x867` pitch (`0x080149DE`)

Notes and pitches are at `0x20014950`/`0x200149A8`. Part structs are at
`0x20013388 + part*0x288`, and patch data is at
`0x200138A0 + (multi + part)*0x201`.

## Bend, pressure and CC: what reaches the FPGA

| Source | Path | Granularity |
|---|---|---|
| Pitch bend | `bend` `0x08010258` → `0x080158AC` → `bend_store` `0x08015860`: signed value at `part+4` → each tick `mod_update` `0x080140C4` smooths it and sends param `0x68` (up) / `0x69` (down) to target `0x1A`, plus `0x868/0x869` to `0x19` | **per part** (broadcast) |
| Pitch bend → oscillators | `mod_update` stores the smoothed bend in `part_bend_smoothed` `0x2001389C`; `osc_pitch` `0x08013A2C` adds it × `BendRange` to every voice's oscillator pitch, params `0x000`–`0x002` (see [Oscillator pitch](#oscillator-pitch-params-0x0000x002)) | **per voice**, computed on the MCU (same bend for all) |
| Mod wheel (CC1), expression (CC11), breath (CC2) | `cc` `0x080102C0` → part `+6`/`+8`/`+9` → `mod_update` sends `0x60`, `0x62`, `0x63` to `0x1A` and `0x860`/`0x862`/`0x863` to `0x19` (1 kHz tick, see [Part mod sources](#part-mod-sources-0x600x63)) | per part |
| Channel pressure | `chan_at` → `0x080159B8`: writes **every** voice's `+0xE4` aftertouch slot | per voice (same value) |
| Poly pressure | `poly_at` → `0x08015A14`: writes the slots of active voices **playing that note** | **per voice** |
| Aftertouch → FPGA | `mod_update` sends one voice per tick, round-robin: smoothed and squared, `fpga_mod_write(0, voice, 0x61, value)` | **per voice** (target = voice index) |

**Consequences for MPE**, which are inferences:
- **Pressure** is solved by the existing design. A member channel's pressure
  only needs to write the one voice bound to that channel (`+0xE4 + 2v`).
- **Per-note bend:** the FPGA accepts at least one modulation parameter
  (`0x61`) per voice, so sending `0x68`/`0x69` per voice target is the first
  thing to try. That can only be tested on hardware. The fallback is to fold
  the bend into each voice's base pitch (`0x67`, 8.8 semitones) and re-send it
  on change.
- **Slide (CC74):** there's no per-voice source for it yet. The MPE design decides
  whether to reuse a per-voice slot. **Answered (2026-11-01, observed):** the
  ModWheel source `0x60` per voice target works, without the broadcast `0x60`
  ([experiment D2](#part-mod-sources-0x600x63)).

## CC, NRPN and RPN (`cc` `0x080102C0`)

`cc` gets a pointer to `[controller, value]` and works on part
`midi_current_part` (`parts + part*0x288`). Checked in
`tests/test_cc_nrpn.py` (emulated).

**Direct switch** (`tbb` at `0x080102DC`, observed). These CCs are always
handled:

| CC | Action |
|---|---|
| 1 | mod wheel → `0x080158EC` (part `+6`) |
| 2 | breath → `0x0801596C` |
| 7 | volume → `0x080159AC` |
| 11 | expression → `0x0801592C` |
| 32 | bank LSB → `part+0x127`, only if global `Bank/Patch` receive is on (`globals+0x15` bit 0) |
| 64 | sustain → `0x08015EC8` |
| 66 | sostenuto → `0x08015FBC` |
| 114 / 115 | ≥ 64 → `0x08013CC4(part, 0/1, 0x7F)`, otherwise 0 (switch-type controls, meaning not traced) |
| 120 | all sound off (value 0) → `0x08015E00` |
| 121 | reset all controllers: accepted, ignored |
| 122 | local control → `local_control_cc` `0x0800EDBC` (0 off, 127 on, 64 = third state) |
| 123–127 | all notes off (value 0, or always for 126) → `0x08015B14` |

**Everything else** runs only when the global `CC/NRPN` setting has its
receive bit set (`globals+0x14` bit 0). Otherwise it's dropped (emulated):
- **CC 99 / 98:** NRPN MSB/LSB → `part+0x129` / `part+0x128`, stored **per
  part**.
- **CC 6:** data entry for the stored NRPN. The parameter number is
  `pnum = msb*128 + lsb + 0x80`. Rejected when either byte has bit 7 set,
  for MSB 1–20 with LSB ≥ 4, MSB 21–24, MSB 26–61, MSB 25 with LSB ≥ 0x36,
  MSB > 64, or `pnum ≥ 0x20AF`. Special numbers:
  - `0x1F80`/`0x1F81` (**NRPN 62:0 and 62:1**) → `nrpn_mode_request`
    `0x0800EF24`: a value of 0–10 sets `mode_request` `0x20004B38` =
    `value | 0x80`. The main loop (`mode_request_poll` `0x0800EF34`) then calls
    `ui_select_mode(value)` `0x0801D2E4`. **0 = Single, 1 = Multi**: it
    writes `multi_mode` `0x20004B20` and the Patch/Multi button LEDs
    `0x7A`/`0x7B`. Values 2–10 select the other front-panel menus (LEDs 0–9).
    `ui_mode_button` `0x0801D3CC` echoes the state back out as NRPN `0x1F80`
    through `0x0801D828`. (Code observed, store emulated; the menu meaning of
    values 2–10 is inferred.)
  - `0x2000`/`0x2001` (NRPN 63:0/1): ignored.
  - `0x0D36`/`0x0D37` (NRPN 25:54/55) → `tuning_nrpn_write` `0x08018124`:
    writes the MSB/LSB of a tuning-table entry, but only while the Settings
    tuning-table pages are open (UI mode 10, page > 16).
  - Anything else → `param_set_from_midi(value, pnum)` `0x08010038`.
- **Any other CC**, including **100/101 (RPN select) and 38 (data LSB)** →
  `param_set_from_midi(value, cc)`. There's no RPN state: CC 6 after
  CC 101/100 is applied to the **last NRPN** of that part (emulated).

**`param_set_from_midi` `0x08010038`** (observed) accepts `pnum < 0xA84` or
`0xD00 ≤ pnum ≤ 0xD35`, so only patch parameters.
- `param_locate` `0x0800FF98` maps pnum → (base, offset). For `pnum <
  0x2080`, base is the current patch `0x200138A0 + (multi + part)*0x201`, and
  `patch_param_offset` `0x0801D95C` gives the offset: a u16 table for CC and
  NRPN MSB 0, 4-byte slots by arithmetic for MSB 1–23, and `0x15C + …` for MSB 25. For `pnum
  ≥ 0x2080`, base is `globals` and offset is `pnum - 0x207E`.
- The value is range-checked against `patch_param_desc[offset]`.
- `param_write` `0x0800FFE0` stores it, sets a "changed" bit, and
  `0x0801A064` flags the parameter for redraw.

**Setting a whole sound over MIDI** (emulated, 2026-11-07,
`tests/test_hwrig_setup.py`; `tools/hwrig/params.py`):
- Descriptor MSB 252 is a plain CC (`lsb` = CC number), 254/253 the coarse
  and fine byte of a pair, each its own CC; 255 isn't reachable. 325 of the
  sound's parameters (`0x022`–`0x18C`) can be set; not LevelComp `0x0C8`,
  `0x0D7`, `0x0D8`, ClockRate `0x0ED`/`0x0EE`, nor the FX-matrix slots 5–8
  (`0x14C`–`0x15B`, NRPN MSB 21–24, rejected above).
- A coarse byte takes the CC value as is (0–127, though its range is
  0–255): CC 29 = 127 already gives the FPGA its top filter value (27,874;
  a poked 255 gives 27,875), so the Init Patch's 127/64 is fully open.
- RevType `0x0DA` (NRPN 0:101) loads a preset RevSize `0x0DE` (0/64/127),
  and RevSize (NRPN 0:104) sets RevType from the size.
- **Program change:** CC 32 = 1–4 selects bank A–D (with `Bank/Patch`
  receive on), the program number is the slot number the display shows
  (CC 32 = 4, PC 2 → `4-002`, patch bytes `+0x14`/`+0x15` = 4/2).
- Mod-matrix names: sources (24) pointer table `0x0804D698`, destinations
  (49) `0x0804D6F8`; oscillator waves `0x0804D860` (Sine = 0), voice modes
  `0x0804D9F0` (Mono, MonoLG, Mono2, Poly, Poly2) (observed). Matrix depth
  is bipolar, 64 = 0.

So **globals can't be set over MIDI** (`pnum ≥ 0x2080` is rejected here,
emulated): the NRPN 62:x mode switch is a special case.

**Pitch-bend range: no RPN 0.** The bend range is a **patch** parameter,
one per oscillator:

| Parameter | NRPN | Descriptor (flash) | Range |
|---|---|---|---|
| Osc 1 `BendRange` | 0:20 | `0x0804EAE4` | 40–88, centre 64 → ±24 semitones |
| Osc 2 `BendRange` | 0:29 | `0x0804EBE0` | same |
| Osc 3 `BendRange` | 0:38 | `0x0804ECDC` | same |

It's set from the panel or by NRPN. How it's applied wasn't traced further.
The MCU sends one bend value per part (`0x68`/`0x69`), and the per-oscillator
range presumably scales it on the FPGA (inferred).

**For MPE** (inferred), the patch has to:
- add an RPN state, for example a spare byte next to `part+0x128`;
- intercept CC 101/100/6/38 before the generic path, in the `cc` hook or the
  handler table;
- keep its own bend ranges: per-note ±48 by default, master ±2.

The ±24 per-oscillator patch range can't express ±48, so the per-note bend has
to be scaled by the patch code (fold it into `0x67` pitch, or into per-voice
`0x68`/`0x69` if the FPGA accepts them).

## Settings menu, global settings, save and load

All the menu tables are in `.data`, so they're in RAM and patchable through
their flash initialisers (`0x0804BD80` → `0x20000000`, `0x4440` bytes).
Observed unless marked otherwise.

```
ui_state 0x20012534 (+2 = UI mode)
  └ menus[mode] 0x20001FAC (15 ptrs; mode 0 Patch, 1 Multi, 2 Osc, 3 Env, 4 LFO, 5 Arp, 7 Voice, 8 FX, 10 Settings, 11 Save, 12 Multi save)
      └ menu {u8 cur_page; u8 n_pages; u16 pad; page* pages[n]}      Settings: 0x2000202C, 33 pages
          └ page (0x18 B) {char* title; u8 n_items; u8 pad; 4 × {u8 kind; u8 pad; u16 index}}   index = descriptor record number
              kind 1 → patch_param_desc  0x20002A4C (flash 0x0804E7CC), indexed by patch byte offset
              kind 3 → global_param_desc 0x20003DFC (flash 0x0804FB7C)
                  └ desc (12 B) {u8 min; u8 max; u8 nrpn_msb; u8 nrpn_lsb; u32 display_type; char* name}
```

- **Pages:** 90 page records from flash `0x0804DF5C` (RAM `0x200021DC`). The
  Settings pages are: SYSTEM ×2, SYNTH, MIDI CHANNEL, MIDI CONTROL, MIDI
  ENABLE, PEDAL SW MODE/SENSE, MISC SETTINGS ×2, POT CALIBRATE, OUTPUT/FX
  ROUTING, FX SOURCES, EXTERN. FX DRY, BACKUP, KEYBOARD, then TUNINGTABLE
  16…1.
- **Example, MIDI CHANNEL** (flash `0x0804E28C`): 3 items, kind 3, indices
  `0x2B` (`PartA Chan`), `0x2C` (`PartB Chan`), `0x11` (`Globl Chan`). The
  fourth item slot is free.
- **Global descriptors** use NRPN MSB `0x40`. The value lives at
  **`globals[lsb + 2]`** (`pnum - 0x207E`):

  | Setting | lsb | globals offset |
  |---|---|---|
  | `Globl Chan` | `0x0F` | `+0x11` |
  | `MidiLocal` | `0x10` | `+0x12` |
  | `CC/NRPN` | `0x12` | `+0x14` |
  | `Bank/Patch` | `0x13` | `+0x15` |
  | `AtouchForce` | `0x25` | `+0x27` |
  | `PartA Chan` | `0x29` | `+0x2B` |
  | `PartB Chan` | `0x2A` | `+0x2C` |

  `TuningMode` and `DBand Incr` have MSB `0xFF`: they aren't stored in
  `globals`. The string the task called `MidiChan` is actually `Globl Chan`.
- **Editing:** UI edits go through `param_write` `0x0800FFE0`, called from
  `0x0800EBC8`/`0x0801D838`, which writes the byte and sets the changed flag
  (`0x0800EB0C`). Running state is re-derived every main-loop pass by
  `globals_apply_poll` `0x0800EE70`. For example, `midi_channels_sync`
  `0x0800ECC0` copies `globals+0x11/+0x2B/+0x2C` into
  `midi_global_channel`/`part_a`/`part_b` (`0x20004B2A–2C`). On a change it
  sends CC 120 and all-notes-off.
- **Storage:** `globals` `0x200161A4` is a 512-byte block, a byte image of
  external flash at **`0x300000`**:
  - **Load at boot:** `settings_load` `0x08011000`, called from `main_loop`,
    is `ext_flash_read(0x300000, globals, 0x200)` `0x0800DD04`. It patches
    `+0x27 == 0 → 5` and `+0x1E/0x1F`, then restores the last patch (`+4/+5`),
    the last multi (`+6/+7`) and Single/Multi (`+3`). **There's no checksum or
    version check.**
  - **Save:** `settings_save` `0x0800F4EC` refreshes `+0x12` and `+4…+7`, then
    calls `ext_flash_write(0x300000, globals, 0x200)` `0x0800DD40`. It's
    reached from the Save button (`save_button` `0x0800F604`) in UI mode 10
    through `settings_save_action` `0x0800F5A4`, which shows "Settings Saved
    With PROTECT ON/OFF". On tuning pages (page > 16), the same button saves
    the tuning table instead (`0x08017F8C`).
  - **Initialise / factory reset:** `settings_initialise` `0x0800FAF4` writes
    the 0x30 default bytes at flash `0x08048568`, padded with **zeros to 512
    bytes**.
- **Unused space:** no code accesses `globals` at a fixed offset above `+0x2D`
  (literal-pool scan, inferred), so `globals[0x30…0x1FF]` is free and is
  saved and loaded with the block.

**Adding "MPE: Off/Lower/Upper + member count"** (design, inferred):
1. **Storage:** two bytes in the unused part of `globals`, for example `+0x30`
   = zone (0 Off, 1 Lower, 2 Upper) and `+0x31` = member count 1–15.
   - Initialise zeroes them, so the default is Off.
   - Units that were never initialised may hold anything there, so the patch
     must treat out-of-range values as Off.
   - Save and load need no change.
2. **Descriptors:** `global_param_desc` has no room. Index `0x2F` is the
   last entry; `0x2000403C` follows straight after. Two choices:
   - reuse the placeholder `text` entries (records `0x1B`/`0x1E`, lsb
     `0x19`/`0x1C`; check first that no page uses them);
   - or move the table to flash and update its three literals
     (`0x0801C9E8`, `0x0801CC9C`, `0x0801D220`), plus any range checks that
     use `0x20003DFC`.

   An entry at lsb `0x2E`/`0x2F` maps to `globals+0x30/+0x31` through the
   normal `lsb + 2` rule, so `param_write` stores it with no new code
   (`0x2080 + 0x2E < 0x20AF`). The patch then only reads the bytes.
3. **Page:** MIDI CHANNEL has a free 4th slot, which is enough for the zone.
   For zone and member count together, use a page with two free slots
   (MIDI ENABLE, MIDI CONTROL, PEDAL SW *), or add a page:
   - The Settings menu struct can't grow in place, since the next menu
     follows straight after it.
   - Instead, point `menus[10]` (`0x20001FD4`) at a new RAM menu with 34
     pages. It has to be in RAM, because byte 0 (the current page) is written.
   - Free RAM for it is still to be found.
4. **Display types** (the u32 in the descriptor, for example `0x2E` for
   channels, `0x5E` for local control) select the value formatter. A new
   Off/Lower/Upper list needs either an existing 3-value type or a new
   formatter. Not traced yet.

**Built in MPE step 3** (emulated; [mpe-design.md](../mpe-design.md#step-3-the-settings-pages)):
both tables moved to patch RAM (CCM), copied from their stock RAM copies
on the first main-loop pass; `menus[10]` (RAM `0x20001FD4`) is set then.
Observed while doing it:
- **Three literals** reference `global_param_desc` (scan of every aligned
  word for `0x20003DFC`–`0x2000403B`): `0x0801C9E8` (`ui_draw_page`, item
  name), `0x0801CC9C` (`ui_draw_values`, display type), `0x0801D220`
  (`ui_value_change`, min/max). No range checks on the record number.
- **One reference** to the Settings menu `0x2000202C`: its `menus[10]`
  initialiser at flash `0x0804DD54`. Everything else reaches it through
  `menus[ui_state[2]]`.
- **Item drawing** (`ui_draw_values` `0x0801C9EC`): kind 3 reads
  `globals[index]` (the record number is the globals offset), sets the
  cursor to column 11 of row item + 1, and calls `format_value` at
  `0x0801CBF4` with the descriptor's display byte (`ldrb`, so types are
  0–255). Then the mark at column 19: `0x10` (▶) for the selected item,
  space otherwise.
- **`format_value`** `0x0801B18C` switches on types 1–`0x60` and prints
  nothing for any other type. Type 1 is a number right-aligned in 3
  columns (`0x0800DFF0` → `0x0800DFB4(buf, 3, ' ', n)`).
- **Kind 3 edit** (`ui_value_change`): new = `globals[index]` + delta,
  clamped to min/max, then `0x0801D838(value, index + 0x207E)`
  (`param_write`, and an NRPN echo when `globals+0x14` bit 1 is set), then
  `ui_draw_values`. Delta 0 changes nothing for globals.
- **Settings page numbers in stock code**, all through
  `ui_current_page_index`: `settings_save_action` (`> 16`: tuning table
  save), `tuning_nrpn_write` (`> 16`), the item action `0x0801D428` (page 1
  row 3 Calibrate, 9 POT CALIBRATE Go, 15 BACKUP Go). Other callers check
  modes 1, 5, 11 and 12. The remote page select `0x0801D54C` is used only
  for modes 2 and 7.
- **Page list** (emulated, 0-based): 0–1 SYSTEM, 2 SYNTH, 3 MIDI CHANNEL,
  4 MIDI CONTROL, 5 MIDI ENABLE, 6 PEDAL SW SENSE, 7 PEDAL SW MODE, 8 MISC
  SETTINGS, 9 POT CALIBRATE, 10 MISC SETTINGS, 11 OUTPUT ROUTING, 12 FX
  ROUTING, 13 FX SOURCES, 14 EXTERN. FX DRY, 15 BACKUP, 16 KEYBOARD, 17–32
  TUNINGTABLE 1–16.
- **After Save** the "Settings Saved With" message gives way to the Patch
  screen, not the Settings page (emulated, stock and patched).
- Helpers: `lcd_puts` `0x0800DF54`, `ui_message_active` `0x0800EBB8` (a
  message covers the page; `ui_redraw` `0x0801CD20` skips drawing then).

## Modulation tick: `mod_update` call rate

Observed and emulated (`tests/test_mod_tick.py`); Hz values are inferred from
the clock set-up.

- **Clocks** (`clock_init` `0x08011400`):
  - `RCC_PLLCFGR = 0x05401E03` (HSE source, M = 3, N = 120, P = 2, Q = 5),
    `FLASH_ACR` latency 3, `RCC_CFGR = 0x00409402` (AHB /1, APB1 /4,
    APB2 /2).
  - The only HSE that gives 48 MHz USB with these values (and an in-spec 2 MHz
    PLL input) is **6 MHz**, so: **SYSCLK 120 MHz**, PCLK1 30 MHz, **TIM6
    clock 60 MHz**. That's consistent with 3 flash wait states at 120 MHz
    (inferred).
- **TIM6** (`tim6_init` `0x08011F34`): PSC 59, ARR 49, update IRQ (IRQ 54,
  vector 70), so the IRQ fires at 60 MHz / 3000 = **20 kHz**. Nothing else
  writes TIM6's PSC/ARR (literal scan).
- **ISR** `tim6_isr` `0x08011F90`:
  - every IRQ: `0x080144DC`, if enabled;
  - every 2nd IRQ (10 kHz): counters;
  - every 20th IRQ (**1 kHz**): `mod_tick_request` `0x080144C8`
    (`voice_state+0x14C`++), then the panel/display work.
- **Main loop:** `mod_tick` `0x080144E4` runs on every `main_loop` pass (also
  in the special loop `0x08019B54`). When `voice_state+0x14C != 0` it clears
  it and does one tick: per-voice envelopes/LFOs,
  `mod_update(0)`, `mod_update(1)`, and the FPGA writes. **Missed ticks aren't
  caught up**, so a main-loop pass longer than 1 ms merges ticks.
- **Per tick:**
  - `mod_update` per part: smooths bend (1/16 of the step per tick, so about
    16 ms to settle) and sends `0x68/0x69` and the part sources.
  - It also advances the shared aftertouch round-robin `voice_state+0xE0`.
    That happens **twice per tick** (once per part call), so **each voice's
    `0x61` pressure is refreshed every 8 ms**, smoothed by 1/4 per refresh.
  - `mod_tick` also sends params `0/1/2/0x67/0x35/0x36` for **8 voices per
    tick** (it alternates halves through `voice_state+0x2DC ^= 8`), so each
    voice's base pitch `0x67` is resent every **2 ms**.

**MPE latency** (inferred): per-note pressure reaches the FPGA within 8 ms,
plus smoothing (about 3–4 refreshes to 70 %, so about 25–30 ms).
- A patch that needs lower pressure latency can write `0x61` for the touched
  voice directly from the channel-pressure handler, or step the round-robin
  faster.
- Per-note bend folded into `0x67` gets a 2 ms update period for free.

## Version text and identity

Observed in code and bytes. The screen text was first emulated
(`tests/test_patch.py`), then **observed on the synth** with the patch below
(2026-10-31).

- **Image tag and version word:** the vector table ends at `0x0800C1AC`
  (107 entries). Right after it are the ASCII tag **`MAIN`** (`0x0800C1AC`)
  and the u16 **`0x2126`** (`0x0800C1B0`). That's the only copy of the
  version in the image, and it's BCD-like: one decimal digit per nibble.
  - `fw_version` `0x0800EA00` returns it (literal `0x0800EA08`).
  - `image_tag_check` `0x0800E468` compares the 4 bytes at `0x0800C1AC`
    (or `0x080001AC` for the bootloader area) against `TEST`, `MAIN` and
    `BOOT` (`0x08049CA4`). So the bootloader presumably carries its own tag
    and version at `0x080001AC`/`0x080001B0` (inferred, not in the update).
  - `jump_to_image` `0x0800E4BC`, reached through `0x0800E50C`/`0x0800E520`,
    writes a flag to backup SRAM `0x40024000` and jumps to `0x08000000` or
    `0x0800C000` (inferred: the reboot-to-bootloader path).
- **Identity reply** (`identity_reply` `0x0801DE18`, port 0 USB / 1 DIN):
  - It copies the 12-byte template `F0 7E 7F 06 02 00 20 29 33 01 00 00` from
    `0x0804FFE0` (`.data`), then the four nibbles of `fw_version()`, high
    first, then `F7`. That gives `… 02 01 02 06 F7` (emulated).
  - `0x0801DD7C` appends a byte; `sysex_send` `0x0801DDA4` sends the buffer.
- **Shown version**, `version_print` (display type `0x59` in
  `format_value` `0x0801B18C`, and the same code inline in `boot_screen`):
  - It prints `fw_version() & 0xFFF` as three hex digits, a dot, then a
    u16 read from external flash `0x2FFE00` (`0x0800EA0C`), also as three
    digits. With the FPGA build 778 there, that's **`126.778`**. The top digit
    `2` isn't shown (emulated, with the external flash read stubbed to
    `0x0778`).
  - **Boot screen** `boot_screen` `0x08012084`: prints `\t(5,0) Novation`,
    `\t(6,1) SUMMIT` and `\t(1,3) Version ` from `.data` (`0x0804C39C`;
    `0x09` is a cursor escape with column and row), then the digits. Row 3
    reads ` Version 126.778`. The FPGA bitstream load follows in the same
    function.
  - **Settings page 2/33 `SYSTEM`** (page record `0x0804E2BC`): items
    `Msg Time` (kind 3, 26), **`Version`** (kind 4, record 34 at flash
    `0x0804FF80`: display type `0x59`, name `0x0804B3E4`) and `Calibrate`
    (kind 5, 1). Kind-4 descriptors are a 12-byte table at RAM `0x20004068`
    (flash `0x0804FDE8`).
- **Display:** a character display. `lcd_putc` `0x08019DC8` takes a
  character, and `lcd_cursor` `0x08019DB4` sets the position with
  `col + row × 32`, sent as `0x80 | addr` (inferred).
- **What Components checks:** the identity digits only (≥ the catalogue build
  2121). The `0x71` header in the update file carries the same digits.

**The first patch** (`patches/version_string.py`) changes only label text,
in place and at the same length:
- the boot-screen label ` Version ` → `MPE0 Ver ` (`0x0804C3B7`, 9 bytes),
  so row 3 reads `MPE0 Ver 126.778`;
- the Settings item name `Version` → `MPE0Ver` (`0x0804B3E4`, 7 bytes).

It leaves the version word alone, so the identity reply stays `02 01 02 06`.
The bootloader may read that word (it also reports 2126), so changing it would
mix two questions into the first hardware test. Built from the official file
(`83b28931…`), the patched `.syx` has SHA-256
`dcbd553e6266f9151f2924d121c9e451eb59c98958ab7bd7d90e42e8dd2419c4`
(the build is deterministic).

**On hardware (observed, 2026-10-31,** tag `hw/2026-10-31-version-string`,
[hardware-log](../hardware-log.md)): flashed with `tools/flash.py`, the
bootloader accepted the image, and the application came back with identity
2126. The boot screen's row 3 read `MPE0 Ver 126.778`, Settings 2/33 `SYSTEM`
showed `MPE0Ver`, and patches, notes and knobs worked. Then the user
re-flashed stock with Components.

## Version word patch (on hardware 2026-10-31)

**Question:** does the bootloader check the image header region? The
version-string run ruled out a CRC or signature over the whole image, but it
left the vector table, the `MAIN` tag and the version word unchanged. The
second patch (`patches/version_word.py`) changes one byte there and nothing
else in the image:

| Where | Stock | Patched |
|---|---|---|
| Version word `0x0800C1B0` (u16 LE) | `26 21` = 2126 | `27 21` = 2127 |
| `0x71` header body | `01 33 00 00 02 01 02 06` | `01 33 00 00 02 01 02 07` |

Built from the official file (`83b28931…`), the `.syx` has SHA-256
`9352764666b672c03145fb0fa5a89e241b1981bbc3c12f343d212c86a984bb8c`
(deterministic). Two of its 8,719 messages differ from stock: the header, and
data block 13, which holds `0x0800C1B0`. The vector block (`0x73`, image bytes
0–31) is unchanged.

**Why 2127:** the word is BCD-like, so any change has to stay a valid digit
string, and three things should keep working:
- the identity stays ≥ 2121, so Components still accepts the device as up
  to date and `tools/flash.py`'s identity parsing is unaffected;
- the screen shows **`127.778`**, a visible marker that the new word is the
  one running;
- a later official release, presumably numbered higher, still counts as
  newer. One more than stock keeps that margin as large as possible.

**Why the header digits change too:** both official files we have carry the
same digits in the header and the image word (Summit `02 01 02 06` / `0x2126`,
Peak `02 01 00 08` / `0x2108`, observed). If the bootloader compares them, a
mismatch would fail for a reason this test isn't asking about, so the patched
file stays self-consistent like a real release. The cost: if the image is
refused, we won't know whether the header digits or the word caused it. That
would be the next, narrower test (header only, or word only).

**What the application does with the header (observed in code):** the SysEx
handler that reboots into the bootloader (`0x0801F494`, call to
`0x0800E50C` → `jump_to_image(0x08000000)`) fires after **7 bytes**, once
`00 20 29 00 71 01 33` (`0x08049B74`, read through the literal
`0x0801F77C` + `0x238`) matches. It reboots before the version digits arrive,
so the application can't refuse a file for its version, newer or older.
Returning to stock from 2127 is a downgrade only for the bootloader, which
sees the whole header.

**Who reads the word:** the image has one literal pointing at it
(`0x0800EA08`, in `fw_version` `0x0800EA00`), and `fw_version` has three
callers: `boot_screen`, `format_value` and `identity_reply`. So in the
application, the patch changes exactly the identity digits and the shown
number. Nothing saved (patches, global settings) appears to be stamped with
it (observed: no other literal `0x0800C1B0` and no other caller of
`fw_version`; an address computed at run time isn't ruled out).

**Emulated** (`tests/test_version_word.py`):
- identity reply `F0 7E 7F 06 02 00 20 29 33 01 00 00 02 01 02 07 F7`,
  which `flash.py` parses as Summit 2127;
- boot screen row 3 ` Version 127.778`; Settings version value `127.778`;
- `flash.py` dry run: the bootloader stream equals the file byte for byte,
  and the tool ends with "application back: Summit firmware 2127, as in the
  file header".

`tools/flash.py` had no version comparison yet: it only printed what came
back. It now compares the post-reboot identity with the header digits and
says whether they match, without calling a mismatch a failure. Its simulator
reports the flashed header's digits after the reboot, or keeps the old ones
with `keep_version`.

**Possible outcomes on hardware:**

| What happens | What it means |
|---|---|
| Application back, identity **2127**, screen `127.778` | The bootloader doesn't refuse a changed version word or header digits. Any checksum covering `0x0800C1B0` is ruled out. A check of only the vector table or the `MAIN` string isn't (both unchanged). |
| Application back with **2126** (`flash.py`: "not running this file's version") | The bootloader took the transfer but kept, or restored, the old image, perhaps because it refused the header digits. It sent no status report, as before. |
| Application doesn't come back within 30 s | The bootloader refuses to start the image (a header-region check, or header vs. word), or it is still in bootloader mode. Recovery below. |
| The bootloader's identity during the next flash says **2127** | The bootloader takes its reported version from the application image or the stored header, not its own. It reported 2126 in every run so far, same as the application. |

**Recovery plan:**
1. Normal case: re-flash stock **with `tools/flash.py`**, not Components. Its
   line "bootloader: … reports N" answers the last row of the table, and the
   log records the whole run.
2. If the application doesn't return: wait the 30 s, power-cycle, and check
   whether the synth shows up as `Summit Bootloader` on its own. If not, use
   the three-button entry ([recovery.md](../recovery.md)), then flash stock
   with `flash.py`, which takes the recovery path.
3. If the bootloader refuses the stock file as a downgrade (2127 → 2126), the
   transfer stalls or the application stays at 2127. Then the patched file
   itself is a stock-equivalent fallback: its code is stock, only the number
   differs. Components is the second fallback.
4. Nothing in this test writes below `0x0800C000`, so the bootloader stays
   intact in every case.

While 2127 is installed, Components compares 2127 with its catalogue: a future
official build would have to report more than 2127 to be offered as an update.
Components did re-install stock over a device reporting 2126 (also ≥ 2121),
so re-installing presumably works, but that hasn't been tried from 2127.

**On hardware (observed, 2026-10-31,** tag `hw/2026-10-31-version-word`,
[hardware-log](../hardware-log.md),
[run](../update-protocol.md#what-flashpy-runs-on-hardware-showed-2026-10-31-to-2026-11-08)):
the first row of the outcome table. `tools/flash.py` sent the patched file
(`93527646…`) byte for byte and ended with "application back: Summit firmware
2127, as in the file header". The boot screen's row 3 and Settings 2/33
`SYSTEM` showed `127.778`, and the synth played normally. Then the official
file went back on with `tools/flash.py` (recovery step 1). Before that
transfer the bootloader reported **2127** (the last row of the table), it
accepted the downgrade, and the application came back with 2126 and
`126.778`.

**Answer to the header-region question:**
- The bootloader enforces no checksum that covers the version word
  `0x0800C1B0`, and no comparison of the header digits with the installed
  version (neither upgrade nor downgrade).
- It takes the version in its own identity reply from the installed image's
  word. So the "bootloader reports 2126" seen so far was the application's
  number, not a bootloader version.
- Still not ruled out: a check of only the vector table (`0x73` block) or the
  `MAIN` tag string, which neither patch changed. (Recovery steps 2 and 3
  weren't needed. Components wasn't opened while 2127 was installed, so what
  it shows for 2127 is still unobserved.)

## Integrity and free space

- **No self-check:** no literal references the CRC peripheral (`0x40023000`)
  or the flash interface (`0x40023C00`). The application neither verifies a
  CRC in hardware nor writes its own flash, so patch storage presumably lives
  elsewhere, maybe external flash. A software checksum loop isn't ruled out.
- **The bootloader accepts modified images (observed, 2026-10-31):** the
  version-string patch (15 bytes changed in string data at `0x0804B3E4` and
  `0x0804C3B7`, header, vector table, `MAIN` tag and version word unchanged)
  was written and booted. So there's no CRC or signature over the whole image.
  A check over a narrower region (vectors, tag, version word) isn't ruled
  out. The [version word patch](#version-word-patch-on-hardware-2026-10-31)
  then ruled out a check covering the version word or the header digits,
  and any version comparison (observed, 2026-10-31). Only a check of the
  vector table or the `MAIN` string alone remains untested.
- **No references outside the image:** values that look like pointers into
  `0x08000000–0x0800BFFF` or beyond the image end are data constants
  (`0x08000800`-style patterns, Thumb opcode pairs), not pointers.
- **Free flash:** the image ends at `0x080501C0`. On an STM32F42x/43x, sector 6
  spans `0x08040000–0x0805FFFF`, so about **63.5 KB** up to `0x08060000` is
  unused in the sector the update already erases. Patch code can be appended
  to the image. Inside the image there's one 634-byte zero run at
  `0x0804C119`.

## The FPGA bus (SPI1)

Observed in code; **emulated** end to end by `emu/synth.py` (the simulated
Summit, [../SIMULATOR.md](../SIMULATOR.md)), which decodes it at the
peripheral level.

- **Transport: SPI1** (`0x40013000`), 16-bit frames, MCU master. No FMC, no
  DMA: `fpga_spi_tx16` `0x08012A84` waits for TXE and writes `SPI1_DR`
  `0x4001300C`; `fpga_spi_wait` `0x08012A9C` waits for TXE and not BSY.
- **Chip selects on GPIOB** through `GPIOB_BSRR` `0x40020418` (write
  `mask << 16` to select, `mask` to release): **PB7** (`0x80`) for voices 0–7,
  **PB6** (`0x40`) for voices 8–15, **both** (`0xC0`) for broadcasts in
  Single mode. For targets ≥ `0x10` the mask is `fpga_cs_override`
  `0x20013328` if non-zero, else `0xC0` in Single mode, else by the current
  part (`0x20004B28`: `0x40` Part B, `0x80` Part A). That there are two voice
  engines, one per select line, is inferred (the Summit is two Peak engines).
- **One write = three frames** (`fpga_spi_write` `0x08012B24`):
  `(target & 0xF) << 12 | (param & 0xFFF)`, `value >> 16`, `value & 0xFFFF`.
  The target nibble is the voice within the engine (0–7) or 8–15 for the
  `0x18–0x1F` targets. `fpga_voice_write` is just `cpsid f; fpga_spi_write;
  cpsie f`, so a write is atomic against interrupts.
- **Queued writes:** `fpga_mod_write` appends `{u8 part_mask, u8 target, u16
  param, u32 value}` to `fpga_queue` `0x20013EE4` (128 entries; write index
  `voice_state+0xBC`, read index `+0x144`, sent count `+0x148`). The TIM6
  interrupt (20 kHz) calls `tim6_fast` `0x080144DC` → `fpga_queue_drain`
  `0x08014458`, which sends up to **4 entries per interrupt** (80 per ms)
  through `fpga_spi_write`, with `part_mask` as the chip-select override.
  The drain rate is fixed by the code at **80 writes per tick** (4 per
  interrupt, 20 interrupts per tick). `mod_tick` queues **75 per tick**
  (emulated, idle and with a chord): 8 voices × 6 params, plus the part
  sources for both parts. So the queue runs at about 94 % of its capacity.
- **Consequence for MPE** (inferred): per-voice bend or slide sent through
  `fpga_mod_write` every tick (16 more writes) would exceed the drain rate and
  the 128-entry queue would overrun (the write index wraps without a check).
  Send on change only, through `fpga_voice_write` directly, or replace
  existing per-tick writes (for example fold bend into `0x67`, which is
  already sent every 2 ms).
- **Reads:** `fpga_read` `0x08012AB8` is the same transaction in full duplex
  (`fpga_spi_txrx16` `0x08012A5C`) and returns the three reply words at
  `0x2000579C`. Uses: `voice_env_poll` (below), the routines at
  `0x0800E594…0x0800E824` (target `0x18` param `0x1F`, not traced) and
  `0x08014A6C`.

**Voice allocation reads the FPGA** (observed; the reply format is the
firmware's interpretation, the FPGA side is inferred):
- `voice_candidates` `0x080155E4` first calls `voice_env_read` `0x08014E3C`
  → `voice_env_poll` `0x08014D54(part, first, wait)` for one engine (Multi) or
  both (Single). That waits until the EXTI15 edge counter
  (`timer_state+0x4B4`, `exti15_isr` `0x08012250`) has advanced by `wait`
  (2 or 3) since the last poll, bounded by 10,000 loop passes, then reads
  `fpga_read(0x18, 0x10, 1)`, `(…, 2)` and `(…, 0)`: eight u16 levels into
  `voice_env_level` `0x200148F0` and, from the third reply word of the first
  read, **2 bits per voice** into `voice_env_state` `0x20013354`.
- It then picks, per state: **3** → the quietest (preferred), **1/2** → the
  quietest, **0** → the most recently started (largest start stamp
  `voice_state+0x378+4v`, written by `env_command_stamp` `0x080153A0` on each
  note start). `voice_alloc` takes the state-3 pick, else 1/2, else 0, else
  voice 0. So state 3 is release (and idle, at level 0) and 0 is the attack.
- **Consequence for MPE:** stealing and voice reuse depend on what the FPGA
  reports, not only on MCU state. A patch that pins channel → voice with
  `voice_alloc(…, voice ≥ 0, …)` skips this. Every note-on in Single mode
  waits for 2 EXTI15 edges per engine; the edge rate is unknown, so the
  note-on latency it adds is unknown (inferred).
- **Envelope commands** (`env_command` `0x0801536C`): `fpga_voice_write(voice,
  {0x3F, 0x42, 0x45}[env], state | counter << 2)`, with a per-(voice, env)
  counter at `voice_state+0x344`. State 0 at note-on, 3 at release (emulated).

**Idle or releasing, as the allocator tells them apart** (observed in code;
what the FPGA reports is inferred; used by MPE v1.1's channel reuse,
[mpe-design.md](../mpe-design.md#channel-reuse-v11)):
- **Gate:** `voice_state+0x334+v` (`0x20005B0C+v`) is nonzero while the
  voice's note is held (or sustained by the pedal); `voice_release` clears
  it. MCU state, certain.
- **Envelope state:** `voice_env_state` `0x20013354`, u8 per (engine × 16 +
  voice in engine): the voice in Single mode, `part × 16 + (v − part × 8)`
  in Multi (`voice_env_poll(part, first, wait)` writes index `part × 16 +
  first + i`; Single reads engine B with `first` 8, then engine A with 0,
  both as part 0). State 3 is release **and** idle.
- **Level:** `voice_env_level` `0x200148F0`, u16, same index, from the other
  reply words of the same three reads (read 1: voices 1, 0, then the
  states; read 2: 4, 3, 2; read 0: 7, 6, 5). The level is what separates a
  releasing voice from an idle one. `voice_candidates` counts a voice as
  still sounding above **`0x200`** (its loudest-of-mask pick starts at
  `0x200`, `0x08015694`; the pick `0x20014B08` is what Poly2 retriggers the
  same note on, and the mono modes use). Its scale on the FPGA is unknown.
- **Only `voice_candidates` reads them** (`bl voice_env_read` at
  `0x0801562A`), at the start of every `voice_alloc` that lets the
  allocator choose; a forced voice (`voice ≥ 0`) reads nothing. Each read
  waits until `wait` EXTI15 edges (2 per engine in Single, 3 in Multi)
  have passed since the previous one (`timer_state+0x4B4` vs
  `voice_state+0x318`), so back-to-back note-ons pay the wait each time;
  the simulator's edge period (100 µs) is a guess.
- **Poly (mode 3), unison 1:** the quietest state-3 voice in rotation order
  from the part's last pick + 1; if that is the voice taken last
  (`0x20000B14`) the next quietest; then the quietest in state 1/2; then
  the newest in state 0; else voice 0. So idle voices rotate.
- **Diverge** (patch `+0x2B`, `diverge_amount` `0x20013898`) multiplies a
  fixed s8 per voice and oscillator, `0x200007CC + 3v + o` (`.data`,
  initialiser `0x0804C54C`, values observed in the image; unchanged after
  boot, a Diverge change and 32 notes, emulated; `osc_pitch` reads it as
  `0x200007A8 + 0x24 + 3v + o`): Osc 1 for voices 0–7 = +1 −8 +4 −2 +6 −6
  +9 −11, and the same 24 bytes again for voices 8–15. In the sum `>> 5`, so at
  Diverge 127 voices differ by −17.2 to +13.7 cents (emulated: the
  simulator's per-voice oscillator pitch). The hardware rig uses it to tell
  voices apart ([hw-test-rig.md](../hw-test-rig.md#stage-4-hwrig-run---stage-4-voice-rotation-f1)).
- **Queue cost of the read, emulated:** replaying the user's Live capture
  (`stuck note from ableton.mmon`, over USB) on stock, all messages on
  channel 1, takes the FPGA queue to **126** of 128 (two from the wrap):
  a dense chord's note-ons each wait for the read, a tick runs up to
  0.85 ms late, and the next follows 0.25 ms after it. The MPE v1 patch
  reached 98 on the same capture (it took reused channels' voices without
  a read); v1.1, which reads as stock, 122 (its Slide writes wait in a late
  tick, [mpe-design.md](../mpe-design.md#channel-reuse-v11)). Whether the
  real EXTI15 rate makes this worse or better is unknown.
- **Tick phase:** `timer_state+0x4A8` (`0x2000577C`) counts 100 µs steps
  since the last tick request, 0–9 (observed: `tim6_isr` `0x08011F90`
  increments the byte on every second 20 kHz interrupt, `0x08011FC4`–
  `0x08011FCC`, and at 10 clears it and calls `mod_tick_request`,
  `0x08011FD0`–`0x08011FDC`). It is real time, but what it reads inside
  `mod_tick` is how long the CPU took since the request: the tick runs
  when the main loop next calls `mod_tick`. In the simulator's default
  timing `mod_tick`'s last `mod_update` runs at phase 0 (stock) or 1 (MPE
  v1.1), 7–8 in a delayed tick (emulated). **On the synth MPE v1.1 read 5
  or more there on every tick** (inferred from the dead Slide, see
  [CPU rate](#cpu-rate-flash-and-spi-busy-waits) and
  [mpe-design.md](../mpe-design.md#slide-v12)).

#### CPU rate: flash and SPI busy-waits

What makes the synth's main thread slower than the simulator's model of
one instruction per cycle (observed in code unless marked):
- **TIM6 and the CPU share SYSCLK:** TIM6's clock is SYSCLK/2 (APB1 /4,
  timer ×2) and its interrupt SYSCLK/6000 (PSC 59, ARR 49), so a tick is
  120,000 CPU cycles and a phase step 12,000 whatever the crystal.
- **No flash accelerator:** `clock_init` stores `FLASH_ACR = 0x00000003`
  (`0x0801141C`–`0x08011422`, a plain store): 3 wait states with prefetch,
  instruction cache and data cache off. Whatever the bootloader set is
  overwritten (no other write to `FLASH_ACR` found: no literal
  `0x40023C00`, one `RCC + 0x3FC`). The code runs from flash, so on a
  Cortex-M4 at 3 wait states without ART well under one instruction per
  cycle (inferred; not measured on the unit).
- **SPI1 (FPGA):** `fpga_spi_init` `0x080129E8` sets `CR1 = 0xB0F`
  (`0x080129FA`, called with r0 = 1 from `0x08012994`): PCLK2/4, 15 MHz with
  the inferred 60 MHz PCLK2, 16-bit frames. A write is 3 frames, 3.2 µs on
  the wire, and `fpga_spi_tx16` / `fpga_spi_wait` poll TXE and BSY, so the
  CPU waits it out. The queue drain sends 75–80 writes per ms inside the
  TIM6 interrupt: about 0.26 ms per ms, 30 % of the CPU (inferred from the
  register values). The bitstream upload uses `CR1 = 0x884` (PCLK2/2, LSB
  first, `0x080120C6`).
- **SPI2 (OLED):** `lcd_spi_init` `0x08012C78` sets `CR1 = 0x3AF`
  (`0x08012C84`): PCLK1/64, 469 kHz, 8-bit: 17 µs per byte, busy-waited in
  the main loop when the display changes.
- **Interrupt code** (emulated, a note held): TIM6 about 11,300
  instructions per ms (45–4,310 per interrupt; the 1 kHz one with the
  panel work is the long one), EXTI15 246 per edge at an unknown rate.
  The simulator charges 300 per interrupt.
- **The tick's own work** (emulated, a note held): stock `mod_tick` runs
  7,000 instructions to the end of `mod_update(1)` and 8,800 in all; MPE
  v1.1 11,500 and 13,300.
- **So, on the synth** (inferred): MPE v1.1 read phase ≥ 5 at the end of
  `mod_update(1)` on every tick, so ≥ 60,000 cycles after the request for
  11,500 instructions; and ticks didn't merge (13,300 in under 120,000
  cycles). The main thread runs at about 11–19 % of the default model's
  rate. `SimulatedSummit.set_timing(0.3, spi_cost=True)` (SPI1 frames
  charged at 128 cycles, the main thread at 0.3 instructions per cycle)
  reproduces it: the Slide point runs at phase 5–8 and v1.1's Slide stays
  0 (emulated, `tests/test_mpe_slide_timing.py`); at 0.35 it is marginal,
  at 0.25 ticks merge. One observation calibrates this; nothing else on the
  unit has been timed. USB OTG, keybed and ADC interrupts, not simulated,
  may be part of it.

**USB OUT: two loads, one race** (observed in code; on the synth
inferred): `usb_out_poll` `0x08021168` loads the endpoint's received count
(`ldrh [ep,#6]`, `0x08021170`) and read index (`ldrh [ep,#8]`,
`0x08021172`) separately, and copies `received − read` bytes from the
buffer start + read. If new OUT data replaces the counts between the two
loads, it copies the new buffer's first packet plus the old buffer's
later ones: notes played again. The simulator hit this (a frame written
at that instant; fixed in the model, 2026-11-08). On the synth it depends
on how the OTG interrupt writes the counts, which isn't simulated.

## Interrupts, time base and what the simulator runs

Observed in code, and exercised by the simulator.

| Source | Handler | Rate | Work |
|---|---|---|---|
| TIM6 (IRQ 54) | `tim6_isr` `0x08011F90` | 20 kHz (inferred clock) | every IRQ `fpga_queue_drain`; every 20th the tick request, the ms counter `timer_state+0x4AC`/`+0x3BE`, `panel_scan` `0x080115E4` and the other panel/LED work |
| USART6 (IRQ 71) | `usart6_irq` `0x08010C40` | per DIN byte | RX into the ring, TX from the ring |
| EXTI15_10 (IRQ 40) | `exti15_isr` `0x08012250` | external edge, unknown | starts ADC2, bit-bangs 12 bits on GPIOE (a DAC, inferred), counts edges for `voice_env_poll` |
| USART3 (IRQ 39) | `usart3_irq` `0x0800FCD0` | keybed link | not simulated |
| OTG_FS (IRQ 67) | USB stack | USB | not simulated (endpoint buffers are, see below) |

- `delay_ms` `0x0801204C` busy-waits on the ms counter, so the boot needs
  the TIM6 interrupt.
- `main_loop` `0x0801C564`: init, then the endless loop at
  `main_loop_head` `0x0801C5D6`. In the simulator a pass takes about 22 µs
  idle (46 per ms at the assumed 1 instruction per cycle).
- **External DataFlash** on SPI4 (`0x40013400`), AT45-style commands
  (`0x03` read, `0x02` program, `0x81` page erase, `0xD7` status, `0x3D…`
  page-size configuration), two chips selected on GPIOE by the pin number at
  `0x20000088` (PE11 normally, PE15 for the update SysEx path). Globals at
  `0x300000`, patches from 0, multis at `0x380000`.
- **Blank DataFlash:** `settings_load` trusts the stored indices, so a blank
  (`0xFF`) chip makes it copy from outside RAM. On a real unit the chip was
  formatted at the factory or by `factory_initialise` `0x0800FBE8` (boot
  button combination: `0x20013318+2 & 0xC`), which writes `init_patch`
  `0x080492F4` to all 512 slots, the multis and the defaults. The simulator
  runs that routine once on a blank chip and caches the result.
- **Panel:** `panel_scan` reads the buttons through GPIOC with active-low
  inputs ([display and front panel](#display-and-front-panel)). An early simulator version read them as 0 (every button pressed);
  patch parameters then changed and NRPNs streamed out of DIN, presumably
  from those "presses". The simulator now reads all GPIO inputs as 1.
- **USB-MIDI** (`usb_midi_dev` `0x200042A4`): the OTG interrupt fills the OUT
  endpoint buffer (`usb_ep_out` `0x2000427C`); the main loop's `usb_out_poll`
  `0x08021168` copies the packets into a ring and calls `usb_midi_rx`
  `0x08021100`. Output goes through `usb_tx_packet` → ring → `usb_in_flush`
  `0x080211D4`, which fills `usb_ep_in` `0x20004288` and starts the IN
  transfer (state 2). `usb_tx_packet` drops packets unless `usb_configured`
  `0x20013045` is 1 (emulated).

**Emulated behaviour worth knowing** (stock 2.2, Init Patch, simulator):
- A DIN note-on reaches the FPGA about 0.9 ms after its first byte (the
  three bytes take 0.96 ms). USB input is delivered once per 1 ms frame in
  the simulator's model, then handled in the next main-loop pass.
- Channel pressure: `0x61` reaches all 16 voices, two per tick, so every
  voice is refreshed every 8 ms, smoothed and squared (100 → 1253, 3839,
  6702, … per refresh).
- Pitch bend: `0x68` to target `0x1A` on engine A and then B every tick,
  closing 1/16 of the remaining step per tick (4096 → 1024, 1984, 2884, …).
- In Multi mode, NRPN 62:0 on the **global** channel doesn't switch modes;
  on a Part channel it does (`multi_global_dispatch` doesn't deliver it).
- The Init Patch is poly (`Mode` +0x22 = 3). Unison 4 (NRPN 0:3 = 4) stacks
  8 voices. Poking patch bytes in RAM doesn't change unison; the NRPN path
  does (the value is applied when the parameter changes).

## Patch RAM, stack and heap

Patch code needs RAM the firmware never touches. **Answer: CCM,
`0x10000000–0x1000FFFF` (64 KB)**, used by `patches/common/patch.ld`.

**SRAM layout** (`0x20000000–0x2002FFFF`, 192 KB):

| Range | What | Confidence |
|---|---|---|
| `0x20000000–0x20004407` | `.data`, copied from flash `0x0804BD80` (`0x4408` bytes) by Reset_Handler `0x0801D9BC` (literals `0x0801DA00–0x0801DA08`) | observed |
| `0x20004408–0x2001785B` | `.bss`. The highest variables code refers to are newlib's: `errno` `0x2001784C`, `__malloc_sbrk_start` `0x20017850`, `__malloc_free_list` `0x20017854`, `heap_end` `0x20017858` | observed |
| `0x2001785C–0x2002FFFF` | heap (from `0x20017850` up) and main stack (from `0x20030000` down), about 98 KB | observed |

- **Reset_Handler** zeroes all of `0x20000000–0x20030000` (literals
  `0x20000000`, `0x20030000`), then copies `.data`. It never touches CCM.
- **No code references CCM** (observed): Ghidra's decompilation of all 843
  functions has no address in `0x10000000–0x1000FFFF`. Its eight
  `0x10000000` constants are bit masks (for example `0x08019CE0` writes it to
  GPIO `0x40020418`; `0x0800D6F4` passes it as a clock-enable mask). No
  `movt #0x1000` exists, and the nine PC-relative loads of `0x1000xxxx`
  values in raw `objdump` output are in data (`0x08028F7C` and up), past the
  end of code (`0x08026220`). CCM isn't reachable by DMA, so no DMA engine can
  write it either.
- **CCM exists on this MCU (inferred):** 192 KB of contiguous SRAM (initial
  SP `0x20030000`) means an STM32F42x/43x, which has 64 KB of CCM at
  `0x10000000`, clocked from reset (`RCC_AHB1ENR.CCMDATARAMEN` resets to 1).
  Confirming the chip would settle it.
- **CCM is not zeroed by anything**, so its contents at power-up are
  undefined. Every C patch therefore gets a startup hook: Reset_Handler's
  `bl main_loop` at `0x0801D9F2` calls `__patch_start` instead, which zeroes
  the patch `.bss` and runs `patch_init()` before `main_loop`
  (`patches/common/start.c`; emulated in `tests/test_patch_toolchain.py`).
  Patch data can't be initialised (`.data` is refused at link time).
- **Heap (observed, unused in practice: inferred):** newlib-nano `malloc`
  `_malloc_r` `0x08023C20` and `_sbrk` `0x080261E8` exist. `_sbrk` starts the
  heap at `0x20017850` and refuses to grow past SP. The only callers lead from
  `sprintf` `0x0802354C` (via `_svfprintf_r` `0x0802365C`), and `sprintf`
  uses a string FILE (`flags 0x208`, `__SSTR`), which never allocates. If it
  ever ran, the first block would overlap newlib's own variables at
  `0x20017850–0x2001785B`, so it presumably never runs. Nothing else calls
  `_sbrk`.
- **Stack (emulated, partial):** one stack, MSP from `0x20030000`; no RTOS
  and no PSP (the only `msr msp` is in `jump_to_image` `0x0800E4BC`). Deepest
  use seen in the emulator: 304 bytes for note-on/CC/bend/note-off through
  `midi_parse_byte`, 80 for `mod_tick`, at least 464 for `ui_draw_page`
  (stopped at a peripheral wait). Interrupts add their own frames. The stack
  is roughly 90 KB away from `.bss`, so the SRAM gap would also be safe for
  small patch state, but CCM needs no such argument.

**Budget:** patch RAM 64 KB (CCM); patch flash `0x080501C0–0x08060000`,
65,088 bytes.

## Float ABI and FPU

- **Hard-float ABI (observed):** `0x08023D48`, a newlib double-precision trig
  function (it calls `__ieee754_rem_pio2` `0x08024C20` and a kernel at
  `0x08025208`), takes its argument in `d0` (`vmov r2, r3, d0`) and returns in
  `d0`. Its callers in `0x0801FAB8`/`0x0801FB58` load `d0` before the call
  (`vmov d0, r0, r1` at `0x0801FAF0`) and read `d0` after it. Under softfp,
  doubles would go in `r0:r1`. The 611 VFP instructions in code are
  single-precision plus `d` moves, consistent with FPv4-SP-D16. The `r0`-based
  calls (`0x0800C1D0–0x0800CAFC`) are AEABI double helpers, which use core
  registers under every ABI.
- So patches compile with `-mfloat-abi=hard -mfpu=fpv4-sp-d16`
  (`Tag_ABI_VFP_args: VFP registers`, checked by
  `tests/test_patch_toolchain.py`). No firmware function in
  `patches/common/firmware.h` takes floats yet.
- **FPU enable (observed):** `CPACR` (`0xE000ED88`) is set to `0xF00000` at
  `0x0801298A`, inside `system_init` `0x08012954`, the first call of
  `main_loop`. Reset_Handler doesn't enable it. Code running before that
  (`__patch_start`, `patch_init`) must not use the FPU; `start.c` is built
  with `general-regs-only`.
- **Hooked code runs in thread mode (observed):** MIDI handlers run from
  `midi_drain`, which `0x08010BDC` calls for sources 0 and 1 from `main_loop`,
  and `0x08010BF4` for source 2 from UI code. The input ISRs only fill queues.
  Lazy FPU stacking is presumably at its reset default (`FPCCR` isn't written:
  no `0xE000EF34` literal), so an interrupt during patch FPU code would be
  saved correctly.

## Per-voice bend experiment

Set-up for the key unknown of the MPE design (does the FPGA take bend per voice
target?). Two experiment patches bent only the most recently allocated
voice: **A** sent `0x68`/`0x69` to that voice's target with the broadcast
neutral, **B** folded the bend into its `0x67` refresh. Both were run in the
simulator and played on the Summit; the patches are no longer in the
repository.

**Hook sites** (observed; all `bl fpga_mod_write` `0x08013FCC` unless noted):

| Site | Call | Used by |
|---|---|---|
| `0x0801414E` / `0x08014162` | `mod_update`, bend ≤ 0: `0x68` = 0 / `0x69` = −bend to `0x1A`, part mask `0x80`/`0x40` | A, B |
| `0x08014176` / `0x0801418A` | the same as `0x868`/`0x869` to `0x19` | A, B |
| `0x080141A0` / `0x080141B2` | `mod_update`, bend > 0: `0x68` = bend / `0x69` = 0 to `0x1A` | A, B |
| `0x080141C6` / `0x080141DA` | the same as `0x868`/`0x869` to `0x19` | A, B |
| `0x0801457E` | `mod_tick` → `bl mod_update` `0x080140C4` with `r0` = 1, the last bend update of a tick | A |
| `0x080145E2` | `mod_tick`'s 2 ms refresh, `fpga_mod_write(0, v, 0x67, voice_pitch_out[v] − 0x3C00)` | B |

- **The bend value** (observed): `mod_update` smooths `part+4` into a 16.16
  accumulator (`voice_state+0xC0+4·part`), stores its top half in
  `part_bend_smoothed` `0x2001389C`, and sends `acc >> 15` clamped to
  ±`0x7FFF`: positive as `0x68`, negative negated as `0x69`. The smoother can
  settle at ±1 instead of 0 after centring (emulated).
- **`voice_pitch_out` `0x20013EA4`** (observed): 16 × u16, 8.8 semitones, the
  glided pitch (`0x08013914` moves it towards `voice_pitch`). It's what goes
  to the FPGA as `0x67` (minus `0x3C00`), both at note-on (`voice_alloc`, via
  `fpga_voice_write`) and in the 2 ms refresh. Base pitch for MPE means this
  array, not `voice_pitch`.
- **Target `0x19`** (inferred): it receives an `0x8xx` copy of each part-level
  source: `0x860` mod wheel, `0x861` the round-robin voice's aftertouch,
  `0x862`/`0x863`, `0x864`/`0x865`, `0x866` the last note's velocity, `0x867`
  the last allocated voice's pitch, `0x868`/`0x869` bend. A monophonic,
  part-level destination; the experiment sends neutral there too.
- **Queue budget** (emulated, play sequence of the experiment): stock queues
  exactly 75 writes per tick, peak depth 78 of 128. The firmware tracks the
  same budget itself: `fpga_queue_lag` `0x200149CC` = `voice_state+0x314`
  (+75 per tick) − the sent count `+0x148`. It's stored at `0x08014A0A`
  through its only literal reference, and no load was found, so it's
  presumably a diagnostic (inferred). A queues 77 (79 when the selection
  moves), peak 84; B queues 75.
- **Single-engine broadcast race** (emulated, stock): a few in a thousand
  queued broadcast writes (part mask 0, target ≥ `0x10`, for example `0x1A`
  param `0x11` from `0x0801400C`) goes to one engine instead of both. The TIM6
  drain sends it while main-loop code has `fpga_cs_override` set to `0x80` or
  `0x40` (for example `0x08015CB2`, which stores `0x80` there around a
  `fpga_voice_write(0x18, 0x16, …)`). Which writes it hits depends on timing.
  Whether it happens on hardware is inferred, not observed.
- **Main-loop pass counter** (observed, emulated): `voice_state+0x332` is
  incremented about 46 times per ms (`0x080152F6`), so patched code that
  lengthens passes changes it. It's timing, not state.
- **Hardware result, 2026-11-01** (observed): A and B both sound exactly
  like stock. Every note bends by the oscillator `BendRange`, a note played
  while bent starts bent, and with `BendRange` 0 nothing bends in B, from
  the panel wheel or DIN. Neither the neutral broadcast bend, nor A's
  per-voice `0x68`/`0x69`, nor B's bent `0x67` refresh is audible.
- **Per-voice oscillator pitch: params `0x000`–`0x002`** (emulated, found
  after the hardware test). Each voice gets three values (`vmod0`–`vmod2` in
  `emu/fpga.py`), one per oscillator (inferred). They're written at note-on
  and, while the bend moves, rewritten on all 16 voices (about 135 times per
  voice in the experiment's play sequence). They follow the bend in stock,
  A and B alike, which explains the hardware result. Scale (inferred from
  the values): 4,096 per octave, 341.3 per semitone. Note-on values E4
  −622, G4 402, C5 2109, E5 3474 (voice 0's C4 write isn't in the trace).
  At `BendRange` 12 (the simulated Init sound) C5 moves from 2109 up to
  6,113 (+4,004) and down to −1,974 (−4,083), so about ±12 semitones. The writer
  is `osc_pitch`, see [Oscillator pitch](#oscillator-pitch-params-0x0000x002).
  This, not `0x67` or `0x68`/`0x69`, is the route for MPE per-note bend.
  Confirmed on hardware by [experiment C](#experiment-c-on-hardware-2026-11-01).
- **`0x67` and `0x68`/`0x69`** (inferred from the hardware result): neither
  the per-voice base pitch `0x67` refresh nor `0x68`/`0x69` on a voice or
  the broadcast target changes the audible pitch. Presumably mod sources
  (key tracking, the mod matrix's Bend), not oscillator inputs. See
  [what they are](#what-0x67-0x680x69-and-0x8680x869-are).

## Oscillator pitch (params `0x000`–`0x002`)

Found for experiment C (below), after A and B.
Read from the disassembly (observed); the formula reproduces the
simulator's values (emulated); the parameter names come from the patch
parameter descriptors at `0x0804E7CC`.

**Call chain and rate** (observed):
- `mod_tick` `0x080144E4`, once per 1 kHz tick in the main loop: for every
  voice 0–15 it sets `voice_loop_index` (`voice_state+10`, `0x200057E2`),
  then calls `0x080136E0` twice (on `voice_state+0x150`/`+0x1F0`, presumably the LFOs or envelopes, inferred), `voice_glide`
  `0x08013914`, and `osc_pitch` `0x08013A2C` three times:
  - `0x08014526`: `osc1_pitch` (`voice_state+0x290`, `0x20005A68`);
  - `0x08014530`: `osc2_pitch` (`0x20000818`);
  - `0x0801453A`: `osc3_pitch` (`0x20000864`).

  The part argument is 0, or 1 from voice 8 on in Multi mode. All 16 voices
  are recomputed every tick, before that tick's `mod_update` calls, so they
  use the previous tick's bend.
- Then it queues `fpga_mod_write(0, v, 0/1/2, osc[v])` for 8 voices per tick
  (`0x080145AE`/`…BE`/`…D0`, half toggle `voice_state+0x2DC`). **Each voice's
  `0x000`–`0x002` reach the FPGA every 2 ms.**
- `voice_alloc` `0x08016B40` does the same for the new voice at note-on
  (`osc_pitch` at `0x08016F66`/`…F72`/`…F7C`) and sends the three values
  directly with `fpga_voice_write` (`0x08016F8C`/`…F9A`/`…FAA`). It writes
  `voice_last_alloc` afterwards (`0x0801700A`).
- There are no other callers. No pointer to `osc_pitch` exists in the image,
  and `part_bend_smoothed` has exactly two literal references: `mod_update`'s
  store (`0x08014370`) and `osc_pitch`'s load (`0x08013AD4`).

**The `osc_pitch` struct** (one per oscillator, observed; written by
`patch_apply_osc` `0x08017874` from the patch, inferred names):

| Offset | Type | What |
|---|---|---|
| `+0` | u8 | oscillator index 0–2 (indexes the Diverge and Drift tables) |
| `+1 + part` | s8 | `BendRange` = patch `+0x42`/`+0x57`/`+0x6C` − 0x40 (40…88 → −24…+24) |
| `+4 + 2·part` | s16, 8.8 | oscillator offset: Range (`+0x30`, 63…66, × 0xC00 in 16 bits = −1…+2 octaves) + Coarse/Fine (`+0x31…+0x34`, via `0x08014C10`) + in Multi mode only, the part's Octave (`+0x19D`, 62…66, × 0xC00 = ±2 octaves; the flag is `multi_mode`) |
| `+8 + part` | u8 | FixedNote (`+0x41`): 0 = off, else note n − 1 |
| `+0xC + 4·v` | s32 | result per voice: param `0x000`/`0x001`/`0x002` |

**Formula** (`0x08013A2C`…`0x08013AC0`, observed), for voice
v = `voice_loop_index`, part p, oscillator o:

```
note  = FixedNote ? (FixedNote − 1) << 8 : voice_pitch_out[v]   8.8 semitones, glided
sum   = note + osc.offset[p] − 0x3C00
      + master_tune                                   0x20013330
      + part_bend_smoothed[p] × osc.BendRange[p] >> 6  bend
      + unison_detune[p] × voice_unison_spread[v] >> 7  0x200149C8 × 0x20014940
      + diverge_amount[p] × diverge_rand[v][o] >> 5     0x20013898 × s8 at 0x200007CC + 3v + o
      + osc_drift[3p + o]                               0x20013EC8
out   = (s16) sum × 0x5555 >> 14                        ×4/3: 4,096 per octave, 341.33 per semitone
```

- **Sum and clamp:** every term is added into the low 16 bits (`uxtah`) and
  sign-extended once (`sxth` at `0x08013AB0`). There's no clamp: a sum
  beyond ±32,767 (±128 semitones of 8.8) wraps. The output is an s32 in
  ±43,690.
- **Note pitch:** `voice_pitch_out` `0x20013EA4`, which `voice_glide`
  moves towards `voice_pitch` (the tuning table's 8.8 value) with glide and
  pre-glide. So **glide is in the note term** (observed).
- **Master tune** (`0x0801328C`, observed): TuneCents (`globals+0xF`, −50…+50
  cents, × 256 / 100) + Transpose (`globals+0x10`, × 256) − 0x45CF. At the
  defaults it's −1,487, so C4 comes out as −1,983, and the sum's zero is
  about F#4 (5.81 semitones above C4; presumably the FPGA's reference, inferred).
- **Diverge, Drift, unison detune** (inferred from the parameter names):
  Diverge (patch `+0x2B`) scales a per-voice, per-oscillator random s8;
  Drift (`+0x2C`, `drift_amount` `0x20014B04`) scales a slow random walk
  (`osc_drift_update` `0x08013844`, a new random target every 100 ticks);
  the unison spread per voice comes from `voice_trigger`.
- **Pitch modulation (LFOs, envelopes, mod matrix) is not in this sum**
  (observed: no other term). The MCU sends LFO/envelope values separately
  (`0x35`/`0x36` per voice), so the FPGA presumably applies pitch
  modulation itself (inferred).
- **Check against the simulator** (emulated, Init sound, Diverge, Drift and
  detune near 0): E4 (4 − 5.81) × 341.3 ≈ −617, against −622 measured; G4
  406 (402); C5 2,113 (2,109). Bent fully up at `BendRange` 12: + 16,384 ×
  12 >> 6 = 3,072 → +4,096 (measured +4,004 after 60 ms of smoothing).

**Where the part bend enters, and its units** (observed):
1. `bend` `0x08010258`: 14-bit MIDI value v, passed on as v << 2.
2. `bend_store` `0x08015860`: `(v << 2 ^ 0x8000) >> 1` = (v − 8192) × 2,
   at `part+4`. Range −16,384…+16,382; values above 0x3F7F become
   0x4000 = +16,384. So ±16,384 = full bend.
3. `mod_update` `0x080140C4`: 16.16 smoother (1/16 of the step per tick);
   `part_bend_smoothed[p]` = accumulator >> 16, the same units. (It also
   sends `acc >> 15`, clamped to ±0x7FFF, as `0x68`/`0x69`.)
4. `osc_pitch`: × `BendRange` (semitones, s8) >> 6. At full bend that's
   16,384 × R / 64 = R × 256: **R semitones in 8.8**, then × 4/3.

### Experiment C on hardware (2026-11-01)

Experiment C (a patch no longer in the repository) fed `osc_pitch`'s
bend input (`0x08013AD4`) the part bend only for `voice_last_alloc`, and 0
for every other voice; the broadcast `0x68`/`0x69`/`0x868`/`0x869` stay
stock. Played on the Summit (tag `hw/2026-11-01-bend-c`, image
`a766506c…`), **observed**:
- **Only the last-played note bends**, by `BendRange` (+2: 2 semitones;
  12: an octave). The other held notes don't move at all.
- When a new note is played while bent, it starts bent, and the previous
  one returns to pitch at once.
- No clicks, steps or zipper noise; in tune after centring and release.

So **params `0x000`–`0x002` are the oscillator pitch the FPGA plays, per
voice and oscillator, and the only path the bend takes** (observed). The
FPGA adds no part bend of its own, and the 2 ms refresh is smooth enough
for one voice bending alone. The 4,096-per-octave scale fits what was
heard (an octave at `BendRange` 12), but it's still inferred from the
values.

**For MPE per-note bend:** the patch sets each voice's bend in `osc_pitch`'s
input, or adds an offset to its result, at both call sites (`mod_tick` and
`voice_alloc`). For ±48 independent of `BendRange`, add after the shift and
clamp, as below.

### Maximum pitch offset

- **Stock bend:** ±16,384 × 24 >> 6 = ±6,144 in 8.8 = **±24 semitones** at
  `BendRange` ±24, the descriptor's limit (observed).
- **Through the same input** (`0x08013AD4`): the term is s16 × s8, so a
  patch can feed any s16. ±32,767 × 24 >> 6 = ±12,287 = **±47.996
  semitones at `BendRange` 24**. At `BendRange` 2 the same value gives only
  ±4. So MPE ±48 through this input needs `BendRange` 24 on every
  oscillator, or the patch must scale its value by 24 / `BendRange` (and
  can't at `BendRange` 0).
- **Independent of `BendRange`:** add the per-note offset to the s32 result
  after `osc_pitch` instead: ±48 semitones = ±16,384 there. That avoids the
  s16 wrap below. What range the FPGA accepts for `0x000`–`0x002` is
  unknown; stock's s16 sum keeps its output within ±43,690.
- **Overflow:** the s16 sum wraps without a clamp, **in stock too**. The
  sum relative to the reference is roughly (note − 60) × 256 − 1,487 +
  offsets. Note 127 is +17,152 − 1,487; add Range 2′ (+6,144), Octave +2 in Multi
  (+6,144), Transpose +12 (+3,072) and bend +24 (+6,144), and stock
  already passes 32,767 (inferred from the formula; not tried). A per-note
  +48 (+12,288) on note 127 with neutral offsets gives 27,953, which fits.
  With an oscillator two octaves up as well, it wraps to a very low pitch.
  An MPE patch should clamp the sum, or add after the shift.

### What `0x67`, `0x68`/`0x69` and `0x868`/`0x869` are

Static analysis, after the hardware ruled them out as oscillator pitch
(observed 2026-11-01):
- **`0x67`** = `voice_pitch_out[v]` − 0x3C00 (`voice_alloc`, and every 2 ms
  in `mod_tick` `0x080145E2`): the glided note in 8.8 semitones, relative to
  C4. No tuning, oscillator offsets or bend. It's the same note term as in
  `osc_pitch`, without the rest, so a per-voice **key-tracking source**
  (filter key tracking, the mod matrix's Note source) fits (inferred).
- **`0x68`/`0x69`** to `0x1A`: the smoothed part bend (`acc >> 15`, up to
  0x7FFF = full), split into a positive up half and a negative down half.
  Two unipolar values per part make sense as **mod sources** (the mod
  matrix's Bend, perhaps up and down separately). They don't feed
  oscillator pitch: the MCU already adds the bend there (inferred).
- **`0x868`/`0x869`** to `0x19`: the same halves as part-level `0x8xx`
  copies, next to mod wheel `0x860`, aftertouch `0x861`, velocity `0x866`
  and the last note's pitch `0x867` (`voice_pitch_out[voice_last_alloc]`).
  A monophonic, part-level source set (inferred).

What the FPGA does with them can't be read from the MCU code. For MPE bend
they no longer matter.

## Part mod sources (`0x60`–`0x63`)

Found for experiment D (below), which asked whether the FPGA takes the ModWheel source per voice, as it
takes aftertouch `0x61`. Read from the disassembly (observed) unless marked.

**From the controller to the part struct** (observed):

| Source | Handler | Store | Part byte |
|---|---|---|---|
| CC1 mod wheel | `cc_modwheel` `0x080158EC`, from `cc` (`0x08010366`) and `0x0801A708`, next to the bend call `0x0801A6E4` in the same switch (the panel wheels, inferred) | `modwheel_store` `0x080158B8` | `+6` |
| CC11 expression | `cc_expression` `0x0801592C` | `expression_store` `0x080158F8` | `+8` |
| CC2 breath | `cc_breath` `0x0801596C` (also called from `0x0800ED8C`, `0x0801B0A4`, not traced) | `breath_store` `0x08015938` | `+9` |
| CC7 volume | `cc_volume` `0x080159AC` | `volume_store` `0x08015978` | `+0xA` (not a mod source) |

- Each store is `(part, value, both)`. It writes **both** parts' byte when
  `both` is set, in Single mode (`multi_mode` 0), or when byte `0x20004B39`
  is 2; otherwise only the current part's. The CC handlers pass `both` = 0.
  A second caller at `0x080105F4`…`0x08010624` passes `both` = 1 for all four
  (it also stores the value at `voice_state+0x338`…`+0x33B`; its trigger
  wasn't traced).
- So in Single mode both parts carry the same mod wheel.

**From the part struct to the FPGA** (`mod_update` `0x080140C4`, observed):
- Per part p, per tick: `target` = `+6` << 8 (127 → `0x7FFF`), smoothed in a
  16.16 accumulator at `voice_state+0xC8+4p` by 1/8 of the step per tick
  (`lsl #13`, with a ±`0x200` round-off). Then:
  - `fpga_mod_write(p ? 0x40 : 0x80, 0x1A, 0x60, acc >> 16)` at
    `0x08014248`;
  - the same value as `0x860` to `0x19` at `0x08014264`.
- Expression (`+8`, accumulator `+0xD0`) and breath (`+9`, `+0xD8`) work the
  same: `0x62`/`0x862` (`0x080142D2`/`…2EE`) and `0x63`/`0x863`
  (`0x0801435C`/`…38A`).
- Then one voice's aftertouch, round-robin (`voice_state+0xE0`), as
  `fpga_mod_write(0, voice, 0x61, …)` and `0x861` to `0x19`.
- The order fits the mod-matrix source names at `0x0804A8E4`, 12 bytes
  apart: `Direct`, `ModWheel`, `AftTouch`, `ExprPED1`, `BrthPED2`,
  `Velocity`, `CV +/-`, …, `BendWhl+`, `BendWhl-` (inferred: `0x60`–`0x63` are
  sources 1–4, and `0x68`/`0x69` the bend wheel's two halves).
- **Rate:** 2 writes per source per part per tick, every tick, whether the
  value changed or not: 12 of the 75 queued per tick.
- **Nothing per voice:** `0x60`, `0x62`, `0x63` (and `0x860`–`0x863`) are
  written only at these sites, always to `0x1A`/`0x19`; the smoothed values
  (`voice_state+0xCA`/`+0xD2`/`+0xDA`) are read only there (offset scan
  of the disassembly; the other hits use other base registers). `0x61` is the only source sent per voice.

**The mod matrix runs on the FPGA** (emulated, inferred): in the simulator,
NRPN 1:0/1:2/1:3 (mod-matrix slot 1 source, depth, destination) make the MCU
send packed slot words to `0x1A` params `0x80`–`0x8F`, and moving CC1 changes
only `0x60` and `0x860`, both for the Init sound and with slot 1 set to
source 1 (ModWheel) at full depth
(`tests/test_stock_expression.py::test_stock_wheel_reaches_only_0x60_and_0x860`).
So the MCU applies no mod-wheel modulation itself: whatever the wheel does
to the sound, the FPGA does it from `0x60` or `0x860`.

**Experiment D** (emulated; the patch is no longer in the repository): the two
broadcast writes are hooked and send 0. After `mod_update(1)`
(`0x0801457E`), the part's mod wheel goes to `voice_last_alloc` as
`fpga_mod_write(0, voice, 0x60, value)`; the voice that loses the selection
gets 0 in the same tick, and a round-robin sends 0 to one other voice per
tick. 77 writes per tick (78 when the selection moves), peak queue depth 83
of 128.

**On hardware (2026-11-01, observed):** D moves only the last-played note's
filter: **the FPGA takes `0x60` per voice target.** That note buzzes,
though, and the chord stays dull. Presumably a broadcast `0x60` to `0x1A`
reaches every voice, so D's neutral 0 and the per-voice value alternated
every tick (inferred). Aftertouch fits that: stock sends `0x61` only per
voice. **D2** dropped the broadcast `0x60` instead of sending 0
(emulated), to tell whether the buzz goes and whether `0x860` matters.

**D2 on hardware (2026-11-01, observed):** with the broadcast `0x60` not sent
at all, only the last-played note's filter opens, **smoothly**. So a
voice-target `0x60` drives that voice's ModWheel source, and a broadcast
`0x60` reaches every voice's (inferred from D against D2, the only
difference). **For MPE, Slide is a per-voice `0x60`, and the broadcast `0x60`
must not be sent**.

**Part-level destinations** (observed on D2, 2026-11-01): an FX slot
ModWheel → `Dist Lev` does nothing while `0x860` is held at 0 and the
selected voice gets `0x60`; on stock the same slot follows the wheel
(observed, control). So FX (and presumably the other part-level
destinations) take the ModWheel from `0x860` to `0x19` or the broadcast
`0x60`, not from a voice's `0x60` (inferred; D2 removed both, so which of
the two isn't separated yet). `0x860` is the likely one: target `0x19`
carries one part-level copy of every source.

## MPE expression (step 2): what the patch relies on

Built in `patches/mpe/` (step 2, [mpe-design.md](../mpe-design.md#step-2-expression-patchesmpe)).
The facts it rests on:

- **`osc_pitch` result:** s32 at `osc + 0xC + 4v`, written for the voice in
  `voice_loop_index`; Osc 1's struct has index 0 at `+0` (observed). The
  patch adds its offset after each call and clamps to −43,691…43,689,
  stock's own output range ((s16) sum × `0x5555` >> 14, observed).
  Adding there and to `voice_alloc`'s three calls before its direct writes
  (`0x08016F8C`/`…F9A`/`…FAA`) puts the bend into the note-on values too
  (emulated).
- **`mod_tick` order:** all 16 voices' `osc_pitch` calls come before
  `mod_update(0)`/`(1)` (`0x08014570`/`…57E`) in the same tick (observed),
  so slots written from the Osc 1 call are what that tick's aftertouch
  round-robin reads.
- **AftTouch:** slot `voice_state+0xE4+2v` (value << 8), smoother
  `+0x104+4v`; `mod_update` sends `((acc >> 12) & 0xFFFF)² >> 15` as `0x61`
  to the round-robin voice (`0x080143A0`–`0x080143FE`, observed).
  `chan_at_store` `0x080159B8` writes `parts[p]+7` and every slot of the
  part (all 16 in Single; observed).
- **Mod wheel:** `mod_update`'s smoothed part wheel is the s16 at
  `voice_state+0xCA+4p` (observed); in Single mode both parts hold the same
  value (`modwheel_store`, observed). The broadcast `0x60` goes with
  part mask `0x80` (part 0, engine A) or `0x40` (part 1, engine B) at
  `0x08014248` (observed).
- **`fpga_voice_write` `0x08012B94`** (target, param, value): `voice_alloc`
  calls it with the voice index in r0 (observed); the simulator decodes the
  writes per voice (emulated).
- **Queue, emulated:** stock queues exactly 75 writes per tick with 16
  voices sounding and every control moving; the patch at most 77 (two
  broadcasts dropped, at most four per-voice `0x60`). Peak depth comes from
  a tick delayed by a long main-loop pass followed by an on-time one: 94 in
  stock at the switch to Multi, 98 with the patch (the 16 note-offs at
  once over USB, or the switch to Multi), with 77 writes per tick in that
  window.
- **Voice choice is timing:** with Part A sounding more notes on the patch,
  Part B's notes took different idle voices than on stock (emulated). Its
  per-voice value sequences are the same; only the voice indices differ. The
  envelope-state reads behind `voice_candidates` are EXTI15-timed
  ([The FPGA bus](#the-fpga-bus-spi1)).

## Display and front panel

Observed in code, and **emulated** end to end by the simulated Summit
(`emu/display.py`, `emu/panel.py`, `tests/test_screen_sim.py`): the firmware
draws on a modelled OLED and scans a modelled button chain and encoder with
its own code. The chip names are inferred from the protocol.

**Display: a 20×4 character OLED on SPI2.**
- SPI2 (`0x40003800`) is used only by the display (literal-pool scan):
  `lcd_spi_tx` `0x08012CD0` waits for TXE and writes `SPI2_DR` `0x4000380C`,
  `lcd_spi_wait` `0x08012CE8` waits for TXE and not BSY.
- `lcd_write_cmd` `0x08019D40` / `lcd_write_data` `0x08019D68`: PB11 low
  (`GPIOB_BSRR` `0x40020418`), start byte `0x1F` / `0x5F`, the byte as two
  frames (low nibble, then high nibble), wait, PB11 high. That is the serial
  interface of the US2066 / SSD1311 family (start byte `11111 RW RS 0`, LSB
  first). Inferred chip; the byte stream is observed.
- Rows at DDRAM `0x00/0x20/0x40/0x60` (`lcd_cursor` `0x08019DB4`:
  `0x80 | col + row*32`), 20 columns (`2/33` at column 16). The init sequence
  sent is only `0x0C 0x2A 0x06 0x28`, then the CGRAM load (emulated): the
  4-line mode isn't set by the firmware, so it's presumably the module's
  default (inferred).
- `lcd_load_cgram` `0x08019D90`: command `0x40`, 64 bytes from `0x20001098`,
  eight custom characters: the corners and edges of a frame (codes 0-7).
- `lcd_putc` `0x08019DC8`: `0xBA` → space, `0xBB-0xBF` → ROM `0xDA-0xD6`,
  0-7 and `0x10-0x7F` as is, `0x08` → clear (command `0x01` and 1 ms),
  `0x1F` as is, anything else dropped. The UI uses ROM `0x10` after the
  selected item (shown as `▶`) and `0x11`/`0x12` on the Save page (inferred
  `◀` and unknown).
- `lcd_wake` `0x08019E24` (called on any panel change) sets PB10 and sends
  display-on `0x0C` if the display was off; `lcd_sleep` `0x08019E54` sends
  `0x08` and clears PB10. PB10 is presumably the panel supply (inferred).
- **Boot screen** (emulated): `      Novation` / `       SUMMIT` / blank /
  `  Version 126.778`. `boot_screen` skips the FPGA upload when
  `panel_inputs` word 1 bits 6-7 are both set (buttons 20 and 21 held at
  power-on; observed in code). The simulator skips it by jumping from
  `0x080120C4` to `0x0801216C`, and seeds the FPGA build word `0x0778` at
  DataFlash `0x2FFE00`, which the version formatter reads.

**Front panel: one shift-register chain on GPIO, scanned at 1 kHz.**
- `panel_scan` `0x080115E4` (TIM6, every ms): `panel_load` `0x080110DC`
  pulses PB2 low (parallel load), then 7 words × 16 bits: read `GPIOC_IDR`
  `0x40020810` bit 11 (pressed = low), drive the next LED bit on PC12, pulse
  PC10 (`panel_clock` `0x080110C0`). `panel_latch` `0x080110F8` pulses PA15
  for the LED registers. Results go to `panel_inputs` `0x20013318` (bit *j*
  of word *r* = the input clocked out 16*r*+*j* clocks after the load); the
  LED bits come from `panel_led_words` `0x20013240`.
- **Buttons:** `panel_buttons_poll` `0x080111FC` (every 10 ms) turns words
  0-4 into events, id = `16*word + bit − 2` (ids 0-69), and
  `ui_button_event` `0x0801AC80` dispatches them through `button_table`
  `0x200010D8` (u32 per id: kind, action, s16 argument). Kind 3 = menu button
  (`ui_mode_button(arg)`); kind 4 = action: 0 octave(±1) (NRPN 0:6), 1 page
  step, 2 select item row, 3 Save, 4 patch step (both: `voices_init`), 5 value
  step (both: value 0), 6 Animate (CC 114/115), 7 (blocked while action 8 is
  held), 8 a held flag (Shift, inferred), 9/10 Multi-only part controls; kinds
  1/2 are parameter buttons.
- **Names established in the simulator** (pressed, screen read): menus
  `patch` 18, `multi` 19, `osc` 24, `mod_matrix` 25, `fx` 26, `lfo` 27,
  `voice` 28, `env` 29, `settings` 34, `save` 35, `arp` 36 (CLOCK page),
  `fx_matrix` 37; `page_next` 22 / `page_prev` 23; `item1` 14, `item2` 15,
  `item3` 6 (move the cursor to display row 1-3); `value_dec` 32 /
  `value_inc` 33; `patch_prev` 16 / `patch_next` 17. Inferred from the action
  and the MIDI sent: `octave_down` 4 / `octave_up` 5, `animate_1` 3 /
  `animate_2` 2, `shift` 20, `part_a` 10 / `part_b` 7. The legend on the real
  panel wasn't checked.
- **Boot combinations** (observed in code): `patch_prev` + `patch_next`
  (word 1 bits 2-3) → `factory_initialise`; word 2 bits 2-3 (`value_dec` +
  `value_inc`) → `0x0801C554(1)`; word 1 bits 8-9 → `0x08019BB8` with a mode.
- **Encoder:** word 0 bits 0-1 are the two phases. `encoder_sample`
  `0x08011764` (1 kHz) steps a table at `0x080494F4` into `timer_state+0`;
  `encoder_poll` `0x08011698` (every 30 ms) emits `c + sign(c)·c²` halved,
  so one detent per 30 ms is ±1 and faster turns accelerate. Detents rest at
  phase 0 and 3; B leading A raises the value (emulated). `ui_encoder_event`
  `0x0801AC18` sends index 0 to the value handler `0x0801CDE0`; index 1
  (patch step) is never fed, so there is one scanned encoder.
- **Pots and pedals** (not emulated): 72 controls through ADC1, an 8-way
  multiplexer and DMA (`0x08011A44`, DMA ISR `0x08011D20`); ids `0x44-0x47`
  are the pedal inputs. `panel_change_scan` `0x08011DD0` queues their
  changes.

**Settings, emulated through the panel:** Settings → 1/33 `SYSTEM`
(`Protect`, `Pickup` = `globals+0x0C`, `Brightness` = `globals+0x0D`);
`page_next` → 2/33 with `Version 126.778`; Save → `Settings Saved With` /
`PROTECT OFF`, and the DataFlash copy at `0x300000` matches. Selecting the
`Calibrate` item (row 3 of 2/33) starts the pot calibration.

## Still open

- What the FPGA does with each parameter, its envelope-state and level
  replies, and the EXTI15 edge rate (they feed voice allocation).
- Whether the `text` placeholder descriptors are free (not needed: MPE
  step 3 relocated the table, see
  [Settings menu](#settings-menu-global-settings-save-and-load)).
- The FPGA's input range for `0x000`–`0x002` (that they're the played
  oscillator pitch is observed, see [experiment C](#experiment-c-on-hardware-2026-11-01);
  the MPE patch's per-note offsets of ±12 semitones play cleanly and in
  tune, observed 2026-11-02, [MPE v1 run](../hardware-log.md);
  ±48 plays exactly, observed 2026-11-07, [test rig](../hw-test-rig.md#what-the-first-runs-showed-2026-11-07-observed)), and what it does with `0x67`
  and `0x68`/`0x69` (the per-oscillator `BendRange` scaling is answered: the
  MCU applies it, see [Oscillator pitch](#oscillator-pitch-params-0x0000x002)).
- Diff against Peak 2.2.

## Patch format, storage and SysEx (for a per-patch MPE flag)

Static analysis plus simulator runs (2026-11-01, branch `re/patch-mpe-flag`).

**Layout** (`patches` `0x200138A0`, 3 × 0x201: Single, Part A, Part B; from
`patch_param_desc` `0x0804E7CC`, 420 entries = offsets `0x000–0x1A3`,
observed): `+0x00/01` reserved, `+0x02–0x11` name, `+0x12` Category,
`+0x13` Genre, `+0x14/15` bank/patch, `+0x16–0x21` reserved, `+0x22…0x18C`
sound parameters (reserved gaps `0x2A 0x43 0x44 0x58 0x59 0x6D 0x6E 0x8C
0x8D 0x90 0x91 0xB8 0xC6 0xE4`), `+0x18D–0x19C` Multi name, `+0x19D` Octave,
`+0x19E` Level, `+0x19F` multi mode (Components: `multiMode`), `+0x1A0`
SplitPoint, `+0x1A1`, `+0x1A2/0x1A3` reserved, **`+0x1A4–0x1FF` no
descriptor** (a kind‑1 index there would read `global_param_desc`),
`+0x200` RAM only. Reserved entries have min = max = 0 and NRPN 255:0, so
neither the UI nor `param_set_from_midi` can write them.

**Storage** (emulated): patch slots are 512‑byte pages at ext flash
`((bank−1)·128 + slot) << 9`; `patch_save` `0x0800F478` writes
`patches[0][0x000–0x1FF]`. Multis at `0x380000 + n·0x400` hold full copies
of both part patches (`multi_save` `0x0800F494`). Loading
(`patch_load_buf` `0x08010E00`) is a 0x201‑byte memcpy from a 0x200‑byte
read: **no checks or clamps** (only `+0x19D` 0 → 0x40); byte `0x200` is
stale buffer data, so it's useless. A program change in Multi copies the
whole patch, Multi region and tail included, into the part.

**SysEx** (`sysex_rx_summit` `0x0801E988`, observed; emulated round trips):
`F0 00 20 29 01 11 01 33 cmd 00 00 x bank slot <data> F7`.
- cmd 0x00 current patch / 0x01 patch to slot: 0x200 bytes stored
  **verbatim**; 0x02/0x03 multi (0x400); 0x04 globals (written to
  `0x300000`); 0x06/0x07 tuning.
- Requests: 0x40 current patch, 0x41 patch (bank, slot), 0x42 current
  multi, 0x43 multi, 0x44 globals, 0x4A bank, others not traced.
- Data bytes ≥ 0x80 abort reception, so a flag value must be ≤ 0x7F.
- Peak patches (header `00 20 29 01 10 00 7E`) go through
  `peak_patch_convert` `0x0801F138` (Components does the same in `_ie`):
  only `0x7B 0x99 0xA2 0xAA 0x15E 0x161 0x164–0x1A1` and `0x175–0x179` change.
- Components keeps patches as raw 512‑byte blobs (`slice(14,526)`), so its
  backups keep every byte `0x000–0x1FF`. Its Multi "init part" resets only
  bytes `0–396`, treating `0x18D–0x1FF` as Multi data.

**Who reads the candidate bytes** (emulated): a memory‑read watch on all
three patch buffers through boot, chords, bend, pressure, CCs, sustain,
mono/legato/unison, Multi with two parts, program change and dump
requests: none of the reserved bytes above, `0x1A2–0x1FF` included, is read
except by the dump loops. A literal/immediate scan of the 66 functions that
address the patch buffers finds no constant access to `0x22–0x200`
reserved offsets (the small‑offset hits are other structs). Setting every
candidate byte to 0x01 or 0x7F changes nothing: 22,317 FPGA writes and MIDI
out are identical, and RAM differs only in the MIDI rings and SysEx buffer.
Init Patch (Summit `0x080492F4`, Peak 2.2) is zero in all of them.

**Menus** (items are `{u8 kind; u8 pad; u16 index}` from page `+6`):
VOICE (UI mode 7) page 1 is Unison, UniDetune and two free slots; pages 3
and 5 also have free slots. Display type `0x0F` is the Off/On list used by
KeySync/FadeSync/Common: table `0x200017FC` + 8, strings `Off`
`0x08049E08` and `On` `0x08049E0C` (observed).

**Editing a kind‑1 item at `0x1A2` needs code** (emulated, 2026-11-01,
`patches/mpe`): with the descriptor filled in, the VOICE item shows `MPE
Off`, but the encoder doesn't change it. `ui_value_change` `0x0801CDE0`
(the value handler behind the encoder, the value buttons and
`ui_page_step`) turns the patch offset into an NRPN number through a u16
table at `0x20015E60`, which a boot loop (`0x0801D8B0`, bound `cmp.w r3,
#0x1a2` at `0x0801D8EE`) fills only for offsets `0x000–0x1A1`; the entry for
`0x1A2` is past its end, in `globals[0..1]` (observed). The write then goes
through `param_write` → `param_locate` → `patch_param_offset`, which maps
NRPN numbers only up to `0xD35` (`0x1A1`). `ui_value_change` computes the
edited patch as `patches[multi_mode + edit_part]`, where `edit_part`
`0x20004B28` is the part `param_locate` addresses; `midi_channel_filter`
sets it per message in Multi and restores it (observed).
