# Peak MPE: plan for a Peak-only port of gipfel_mpe

Source studied: `michaelkollmann/gipfel_mpe` at `25e2f56` (cloned to `gipfel_mpe/`).
Target: **Novation Peak, firmware 2.2 build 2108** (catalogue id 155,
SHA-256 `f9d50b42…1bc4de26e`) with **FPGA 2.1 build 469**. Both are already
pinned in `scripts/fetch-firmware.sh --all`.

## 1. What the upstream project is

A binary patch on top of Novation's official Summit firmware 2.2/2121. It
leaves the stock code where it is, adds ~5 KB of C in the free flash after
the image, and redirects about 40 call sites into that C (`bl` rewrites and
literal-pointer swaps), plus a few byte patches to menu and descriptor
tables. Everything hangs off one hand-built firmware map:

| Piece | Summit-specific? | Where |
|---|---|---|
| Update container codec (`.syx` ⇄ image) | No, already handles Peak (header `00 7e …`) | `tools/syx.py`, `web/src/core/syx.ts` |
| Flasher (Components protocol) | Mostly no: Peak product ID `0x007E` and identity templates already there | `tools/flash.py`, `web/src/flash/protocol.ts` |
| Patch toolchain (compile, link, hook, re-encode) | Lightly: one symbols CSV path, one `STARTUP_HOOKS` entry, image end | `tools/patch.py`, `tools/patch_build.py`, `patches/common/` |
| Firmware map: 236 named addresses with confidence labels | **Entirely** | `docs/symbols/summit-2.2-2121.csv`, `docs/findings/summit-2.2-build2121.md` (1,450 lines) |
| MPE patch: 40 hook sites, 6 byte patches, C prototypes | **Entirely** (addresses), and partly in logic (16 voices, 2 engines, Multi) | `patches/mpe/`, `patches/common/firmware.h` |
| Simulator (Unicorn: MIDI in, FPGA SPI, OLED, panel, DataFlash) | **Yes**: ~75 hard-coded addresses, Summit panel and chip-select model | `emu/` |
| Tests | **Yes**: ~92 hard-coded addresses, Multi tests, golden screens | `tests/` |
| Web patcher | Text and the pinned hash | `web/` |
| Hardware test rig | Port names, a few params | `tools/hwrig/` |

The Peak has only a 27-line findings file (`docs/findings/peak-2.2-build2108.md`):
reset handler, the 8-voice steal loop, the USB-MIDI out packetiser, the SysEx
receiver, pot scanning. The MIDI input path and voice allocator are listed as
"Open". **None of the addresses the MPE patch needs is known for the Peak.**

## 2. What changes on a Peak

Facts from the repo (observed in its docs) and from the instrument:

| | Summit 2.2 / 2121 | Peak 2.2 / 2108 | Consequence |
|---|---|---|---|
| Image | 278,976 B, ends `0x080501C0` | 249,056 B, ends `0x08048CE0` | ~93 KB free up to the sector-6 limit `0x08060000` (vs 63.5 KB). Room is not a problem |
| Load base, SP | `0x0800C000`, `0x20030000` | same | same MCU class (ReplicantPeak says STM32F429), CCM patch RAM should still apply. Verify no CCM use |
| Voices / engines | 16 voices, 2 engines (FPGA CS PB7 and PB6) | 8 voices, 1 engine | arrays shrink to 8; no engine split in Slide; FPGA queue has more headroom |
| Timbrality | Single + Multi (2 parts) | single part only | drop all Multi routing, the two-zone part mapping, `CH CLASH` for parts |
| Keybed, wheels | yes (USART3 keybed link) | none (desktop) | master bend and mod only arrive by MIDI; keybed paths don't exist |
| FPGA bitstream | build 778 | build 469 | the per-voice `0x60` Slide trick and the per-voice `0x61`/`0x000–0x002` writes were proven on the Summit FPGA only. **Must be re-proven on a Peak** |
| Patch format | 0x201 B, flag at `0x1A2` | close relative (Summit has `peak_patch_convert`, touches `0x164–0x1A1`) | Peak's descriptor table may end earlier, so `patch_param_desc[0x1A2]` may not exist. Verify before choosing the flag byte |
| Settings menu | 33 pages (35 with MPE) | different page set | the page-number hooks (Calibrate, Pot calibrate, Backup, tuning) need Peak equivalents |
| Product ID / reboot | `0x0133` | `0x007E` (Components waits longer for a Peak to reboot) | flasher already parameterised; timeouts to check |

## 2a. Target sender: LinnStrument

The acceptance test is "play the Peak from a LinnStrument". What the
LinnStrument sends (Roger Linn Design support pages, software 2.3.x):

| LinnStrument does | What the Peak patch must do |
|---|---|
| Quick MPE setup (hold ChPerNote): left split = Lower Zone, master ch 1, members **2–8**; right split = Upper Zone, master 16, members **9–15** | Lower Zone alone with 7 members fits the 8 voices exactly. **Both splits at once = two zones on one part**: upstream's Single mode doesn't fully handle this ("Single mode with two zones" is an open question there). Peak v1 must play both zones on the one patch, sharing 8 voices |
| Sends RPN 6 (MPE Configuration Message) and RPN 0 on change | Already handled by the core (live state, `*` marks on the Settings page) |
| Note bend range ±48 by default (±24 before LS 2.2.2), any 1–96 | ±48 default matches; the RPN 0 path covers the rest |
| Y → CC 74 | Slide. Upstream sends it through the per-voice **ModWheel** source (`0x60`), so on the Peak it's "ModWheel" in the mod matrix: a patch needs ModWheel routed (e.g. to filter) to hear Y |
| Z → channel pressure (default); options: poly aftertouch, CC 11 | Channel pressure is handled. **Add: poly AT on a member channel → that voice's pressure**, so all Z options work |
| Members can be set to 15 by hand | 15 channels on 8 voices exercises voice stealing much more than on the Summit's 16. Needs its own tests |
| Connects to the Peak over **DIN** (both are USB devices, so USB needs a computer or a USB host box in between); MIDI I/O must be set to MIDI JACKS | DIN at 31,250 baud is the weak point: upstream saw a stuck note from dense MPE over DIN (Live). The DIN path needs stress tests with LinnStrument-like traffic, and the receive ring's overflow counter should be watched (see 2b) |

Add to the test suite: a replayed LinnStrument capture (one split, both
splits, Z as poly AT), like upstream's pinned Ableton capture, and a rig
check with the real instrument over DIN.

## 2b. Stock-firmware issues and improvement ideas

**Possible stock bugs.** Upstream found these in the **Summit** 2.2 firmware.
The Peak shares the code base, so they're likely in the Peak too, but none is
confirmed on the Peak yet (inferred). Phase 1 checks each one.

1. **FPGA write queue has no overflow check.** *(Summit only: the Peak has
   no queue, see section 7.)* 128 entries, and the write
   index just wraps. Replaying a dense Ableton capture on *stock* Summit
   took it to 126 of 128 (emulated), so a little more traffic would overwrite
   queued sound-chip writes. Effect would be a wrong parameter for a moment.
   The Peak queues fewer writes per tick (8 voices, one part), so it may never
   get close. Measure it.
2. **Oscillator pitch overflow.** The 16-bit pitch sum in `osc_pitch` wraps
   without a clamp, in stock too: a high note + octave up + transpose + full
   bend can jump to a very low pitch (inferred from the formula, never
   played). The MPE patch clamps its own part. A stock fix (clamp the sum) is
   a small hook.
3. **DIN receive overrun.** The DIN ring is 256 bytes with an overflow
   counter (`+0x204`). If it overflows, bytes are lost, and a lost note-off is
   a stuck note. Unconfirmed whether that caused upstream's stuck note.
4. **Blank settings chip.** `settings_load` trusts stored indices, so a
   blank DataFlash makes it copy from arbitrary RAM. Only matters on a
   factory-fresh or wiped chip.

**Improvement ideas** (beyond MPE v1, roughly by value for LinnStrument play):

- **Diagnostics page** in Settings: DIN overflow count, max FPGA queue depth,
  the zone in effect. Cheap, and it turns "a note stuck once" into data.
- **Poly AT and CC 11 as pressure** on member channels (see 2a).
- **Pressure curve** setting: stock squares aftertouch; LinnStrument players
  tune Z on the instrument, but a linear option on the synth helps.
- **Pitch clamp** for item 2 above, in stock (non-MPE) sounds too.
- **Bigger DIN receive ring** in patch RAM, if item 3 shows overflows.
- **MPE mono/legato:** per-channel glide for single-voice lead patches.
- **Release velocity** (LinnStrument sends it) → release time. Speculative:
  depends on an FPGA parameter nobody has found yet.

## 3. Recommended shape

**A Peak-only fork**, as you asked: same toolchain, Peak firmware map, and
a simpler MPE patch (one part, 8 voices, one engine). Keep the "target"
seams (`SOURCE` → symbols CSV, `STARTUP_HOOKS[SOURCE]`) so it could go back
upstream as a second target later. The Multi-mode code is the main thing
to delete, and deleting it removes most of the routing's complexity.

The work is mostly **reverse engineering, not C**. About 80 % of the effort
is phase 1 (the Peak map), and phase 6 needs your Peak on a desk with the
test rig.

## 4. Phases

Each phase ends with something checkable. Confidence labels (observed /
emulated / inferred) as upstream's `CLAUDE.md` requires.

### Phase 0. Baseline (½ day)
- Fork, `scripts/fetch-firmware.sh --all`, decode both images.
- Confirm Peak image end, free flash, that no code references CCM
  (`0x10000000–0x1000FFFF`), the `.data` initialiser range, and Reset_Handler's
  `bl main_loop` (the startup hook site).
- Import into Ghidra (`scripts/ghidra-import.sh`), with Summit symbols applied
  to the Summit project for side-by-side work.

### Phase 1. Peak firmware map (the bulk: 1–3 weeks)
Goal: `docs/symbols/peak-2.2-2108.csv` and `docs/findings/peak-2.2-build2108.md`
covering everything the patch, the simulator and the tests use.

- **Carry names over from the Summit** (shared code base, same Novation
  generation, builds 2108 vs 2121): Ghidra Version Tracking or BSim, or a
  masked-byte function matcher (mask `bl`/`ldr` literals, compare
  instruction streams). Expect most UI, MIDI parser and voice code to match
  near 1:1, with Multi branches missing on the Peak.
- **Priority list** (what `patches/mpe/patch.py` and `firmware.h` need):
  1. MIDI path: `midi_parse_byte`, `midi_channel_filter` and its two call
     sites, the channel handler table (`.data` init), `note_on`, `note_off`,
     `cc`, `bend`, `chan_at`, `poly_at`.
  2. Voices: `voice_trigger` (+3 callers), `voice_alloc` and its forced-voice
     argument, `voice_glide` call site, `voice_candidates` → `voice_env_read`,
     `voice_release` (+4 call sites in `note_off`), `voice_note`,
     `voice_pitch`, `voice_state` SoA offsets (`+0x334` active, `+0xE4`
     aftertouch, `+10` loop index, `+0x312` last alloc), `voice_env_state/level`.
  3. Modulation: `osc_pitch` (+6 call sites, its literal for the part bend),
     `mod_update`, `mod_tick`, `fpga_mod_write`, `fpga_voice_write`,
     `fpga_queue` indices, the broadcast-`0x60` site, the wheel value.
  4. Settings and UI: `globals`, `settings_load/save`, `globals_apply_poll`,
     `mode_request_poll`, `main_loop`, `menus`, `settings_menu`,
     `global_param_desc` (+3 literal sites), `ui_value_change` (+5 sites),
     `ui_current_page_index` (+ the sites that act on Settings page numbers),
     `format_value`, `lcd_puts`, `ui_draw_values`, `ui_message_active`,
     `mark_changed`, `ui_state`.
  5. Patch data: `patches` buffer, `patch_param_desc` init, whether entry
     `0x1A2` exists, the VOICE menu page records and their free item slots,
     the version strings for the boot-screen mark.
  6. Simulator landmarks: `tim6_isr`, `fpga_queue_drain`, FPGA SPI and chip
     selects, OLED SPI and pins, panel GPIO chain, DataFlash pins and
     layout, USART6, USB endpoint buffers, `factory_initialise`, `delay_ms`.
- **Re-check every MPE premise on the Peak** (they're Summit evidence now):
  `0x1A2` unread by stock code (memory-read watch), globals `0x30–0x34`
  unused, `voice_alloc` forced voice works the same, `osc_pitch` takes
  `(osc, part)` and reads the bend via one literal, `mod_update` count per tick.

### Phase 2. Toolchain retarget (1–2 days)
- `tools/patch_build.py`: symbols CSV chosen from the definition's `SOURCE`
  (not hard-coded); image end from the image (already passed).
- `tools/patch.py`: `STARTUP_HOOKS["peak-firmware-2.2-build2108.syx"]`.
- `emu/firmware.py`: default image `peak-firmware-2.2-build2108.syx`.
- `patches/common/firmware.h`: Peak prototypes, each with its evidence.
- Port and land the three toolchain probes first, in this order:
  `patches/version_string.py`, `patches/version_word.py`,
  `patches/demo_note_hook/`. They're tiny and each proves one link.

### Phase 3. Simulator for the Peak (3–5 days)
- `emu/board.py`, `emu/fpga.py`: one engine, Peak chip select(s), the TIM6
  and EXTI rates as found; remove the keybed assumption.
- `emu/panel.py`, `emu/display.py`, `emu/screen.py`: Peak button chain,
  encoder and OLED (check it's the same 20×4 US2066-style part).
- First green bar: stock Peak boots in the simulator, formats a blank
  DataFlash, shows its boot screen, a DIN/USB note-on reaches the FPGA.
- Regenerate `tests/golden/screens/` from stock.

### Phase 4. MPE core, Peak-only (3–5 days)
Code changes in `patches/mpe/`, beyond new addresses:
- `mpe.h`: `voice_channel[8]`, `mpe_first_voice() = 0`,
  `mpe_voice_count() = 8`, `mpe_patch() = patches[0]`; drop `multi_mode`,
  `midi_part_a/b_channel`, `edit_part`, `parts[2]` → one part.
- `mpe_route.c`: one zone in use at a time (Lower or Upper, or both from RPN 6
  mapped to the one part); delete the Multi table, `mpe_clash` part bits
  (keep only "the global channel is inside the zone" if it applies).
- `mpe_voice.c`, `mpe_bend.c`, `mpe_pressure.c`: 16 → 8, `uint16_t` voice
  masks → `uint8_t`.
- `mpe_slide.c`: one engine, no `engine_mpe(v >> 3)`, one `wheel_out`.
- `patch.py`: Peak hook list; the Multi-only hooks fall away.
- Tests: port `test_mpe_core`, `test_mpe_rotation`, `test_mpe_off`,
  `test_mpe_conformance` (Ableton capture), `test_mpe_stress`; delete
  `test_mpe_multi.py`, `test_mpe_expr_multi.py`; re-derive every hard-coded
  address in `tests/`.

### Phase 5. Expression and UI (3–5 days)
- Per-note bend (MCU-side via `osc_pitch` offset), pressure (per-voice
  `0x61` slot), Slide (per-voice `0x60`). Re-measure the FPGA queue budget:
  with 8 voices and one part there should be far more headroom than the
  Summit's 75-of-80 writes per tick.
- VOICE page item `MPE Off/On`, Settings MPE pages inserted at the right
  place in the Peak's Settings menu, page-number hooks remapped.
- If `patch_param_desc[0x1A2]` doesn't exist on the Peak: either relocate
  the descriptor table to CCM (as upstream already does for
  `global_param_desc`), or pick another verified-unused byte.
- Boot-screen mark (e.g. `MPE1 Ver …`) so you can see the patch is installed.

### Phase 6. Hardware, in small steps (your Peak; 1–2 weeks elapsed)
Each step only from `scripts/build-image.sh`, logged in `docs/hardware-log.md`,
and you run the flash yourself. Know the recovery path first.
1. **Recovery dry run:** enter the Peak bootloader and flash stock 2.2 with
   Components. Confirm the button combination for the Peak (upstream only
   documents the Summit's).
2. **Version-string patch:** proves the Peak bootloader accepts a modified
   image (proven for the Summit only).
3. **Version-word patch**, then **demo note hook**: proves C code and hooks run.
4. **FPGA experiments**, Peak FPGA 469: per-voice osc pitch offset
   (Summit "experiment C"), per-voice `0x60` without the broadcast
   (Summit "D2"). If `0x60` per voice doesn't work on 469, Slide needs
   another per-voice source. This is the largest technical risk.
5. MPE core, then expression, with the test rig (`tools/hwrig`), over USB
   and DIN.
6. **LinnStrument over DIN:** one split (7 members), both splits, 15 members,
   Z as channel pressure and as poly AT; long dense playing with a check for
   stuck notes and the DIN overflow counter.

### Phase 7. Release (2–3 days)
- `web/`: Peak strings, pinned Peak hash, `FakeSummit` → a Peak fake, the
  descriptor (`tools/web_descriptor.py`, `web/patches/mpe.json`).
- README, recovery doc, `docs/hardware.md` for the Peak.

## 5. Risks

| Risk | Likelihood | Handling |
|---|---|---|
| Peak FPGA 469 ignores per-voice `0x60` (Slide) | medium | Phase 6 step 4 before building UI polish; fall back to another per-voice mod source or drop Slide in v1 |
| Peak bootloader checks something the Summit's doesn't | low | Phase 6 step 2 is a 15-byte string patch; stock restores over it |
| `0x1A2` is read by Peak code | low (descriptor slot confirmed reserved, section 6) | memory-read watch in the simulator, phase 1 |
| Voice/modulation code differs more than it looks | low–medium | probe: shared code maps automatically; voice code is the same logic minus Multi, mapped by hand |
| Dense LinnStrument traffic over DIN drops bytes (stuck notes) | medium | diagnostics page, replayed captures in the simulator, bigger receive ring if needed |
| Novation ships Peak 2.3 | low | pinned by SHA-256; a new build means a re-map |
| Bricking | low | bootloader below `0x0800C000` is never written; vector table goes last |

## 6. Feasibility probe results (2026-11-12)

Novation's catalogue lists **Peak firmware 2.2, build 2108** (id 155) as the
newest Peak firmware (2.1 is build 471, id 141). FPGA stays 2.1 / build 469.
Both images were fetched with `scripts/fetch-firmware.sh --all`, checksums
matched, and both decode and re-encode byte for byte. Tools and the full
address map: `probe/match.py`, `probe/dis.py`, `probe/summit-to-peak-map.json`.

**Method:** align the two images' disassembly function by function (tokens
with immediates dropped), seeded from the vector table, Reset_Handler and the
MIDI channel handler table; harvest call targets, RAM literals and
instruction addresses from aligned runs; accept pairs by vote, one to one.

| Question | Answer | Confidence |
|---|---|---|
| Free flash for the patch | Peak image ends `0x08048CE0`: **95,008 B** free up to `0x08060000` (Summit: 65,088) | observed |
| Startup hook | Reset_Handler `0x0801D6C4`, `bl main_loop` at **`0x0801D6FA`** → `main_loop` `0x0800D11C`; `.data` copied from `0x08045210`, `0x3AC4` bytes | observed |
| CCM free for patch RAM | No `movt #0x1000`; the only `0x1000xxxx` literals are the same 9 data constants as on the Summit | observed (that they're data: inferred, same pattern) |
| Per-patch MPE byte `0x1A2` | `patch_param_desc` at RAM `0x200017CC`, init `0x080469DC`; entry `0x1A2` is **reserved exactly as on the Summit** (min = max = 0, NRPN 255:0, no name). Flag descriptor at `0x08047D74`. 399 parameter names sit at the same index in both tables | observed |
| MIDI channel handler table | RAM `0x200001A8`: note_off `0x0800F4B0`, note_on `0x0800F53C`, poly_at `0x0800F328`, cc `0x0800F124`, program_change `0x0800F0EC`, chan_at `0x0800F0E0`, bend `0x0800F0C8` | observed |
| Forced-voice allocation | `voice_alloc` `0x080122B0` keeps the 5-argument form; the unison loop `0x080128C0` calls it with voice = −1 at `0x08012942` (the Summit's hook site). A wrapper `0x08012A0C` forces a voice | observed |
| Note path | note_on → `held_note_add` `0x0800F364`, `arp_note_on` `0x08015018`, voice-mode dispatcher `0x08012984` → unison loop `0x080128C0`; `voice_release` `0x08011CC8`, `held_note_prev` `0x0800F448`, `env_command` `0x080119A4`, `mod_tick` `0x0801192C` | observed (names carried by alignment: inferred) |
| Automatic coverage | **533** Peak functions paired; **115 of 165** named Summit functions, **34 of 57** named RAM globals; **15 of 40** MPE hook sites mapped and verified (the `bl` at the Peak site calls the mapped target) | emulated, no; static only |

**What maps automatically:** the MIDI parser and channel filter
(`midi_channel_filter` `0x0800EED0`, both hook sites), the menus and value
editing (`ui_value_change` `0x08018448` and 3 of its 5 call sites),
`format_value`, `ui_current_page_index`, settings load/save, the main-loop
hooks (`settings_load` site `0x0800D132`, globals poll `0x0800D1BA`, mode poll
`0x0800D1C4`).

**What needs hand mapping (phase 1 work):** the note, voice and modulation
code. It's the same logic with the two-part / Multi machinery removed, so
it no longer aligns token for token, but it reads easily side by side (see
note_on above). Outstanding: `voice_glide`, `voice_candidates` /
`voice_env_read`, `osc_pitch` and its 6 call sites plus the bend literal,
`mod_update`, `fpga_mod_write`, `fpga_queue_drain`, the 4 `note_off` release
sites, the arp/mono trigger sites, and the UI sites in `ui_page_step`,
`ui_draw_page` and `ui_draw_values`.

**Effect on the estimate:** phase 1 looks like the **short end (about a
week)**. Everything shared maps automatically, the patch byte and RAM
premises hold, and the remaining 25 hook sites sit in about 10 functions
that are already paired.

**Before flashing anything:** your Peak must run 2.2 / 2108, the build
the patch targets (the patcher refuses any other file by SHA-256). If it
shows 2.1, update it with Novation Components first.

## 7. Hook mapping results (2026-11-12)

All hook sites mapped by hand and checked against the Peak image by
`probe/peak_hooks.py` (decodes every `bl` and literal; checks every byte
patch's original bytes). Symbols with confidence labels: `probe/peak-2.2-2108.csv`.

**Result: 37 of 41 sites map and verify** (the Summit's 40 plus the startup
hook). The other 4 belong to Summit features the Peak doesn't have:

| Summit hook | Why there's no Peak site |
|---|---|
| note_off's arp-path `voice_release` | the Peak's arp calls its own note-off (`0x08014E10`) |
| `ui_page_step`'s second value change | the Peak's `ui_page_step` has one branch |
| tuning NRPN 25:54/55 page check | the Peak has no handler for that NRPN (no `0xD36` anywhere) |
| POT CALIBRATE Go | no such Settings page on the Peak |

All byte patches carry over: boot label `0x080452FB`, Settings "Version"
`0x080445E8`, flag descriptor `0x08047D74` (display Off/On is `0x0F` on both),
VOICE page 1 `0x08048648` (Unison, UniDetune, two free slots).

**Matcher pairings are leads, not facts:** three automatic pairs were wrong
and are fixed by hand (`mod_tick`, `globals_apply_poll`,
`mode_request_poll`). Everything in the hook table is now checked by reading
both functions side by side.

**What the Peak's code means for the patch (all observed unless noted):**

1. **No FPGA write queue.** `fpga_write` `0x0800EBF0` is a direct SPI1
   write (one chip select, PB6), and `mod_tick` writes every voice's pitch
   directly. So stock-bug #1 in section 2b **doesn't apply to the Peak**, and
   `mpe_slide.c` loses its whole queue/staleness machinery: Slide is a direct
   per-voice `0x60` write.
2. **The Peak has a hidden two-part voice dispatcher.** `voice_dispatch`
   `0x08012984` sends a note to part 0, splits at a note, or layers, by a mode
   byte `0x20011212`. No code stores to that byte directly (static scan), so
   it presumably stays 0: one part, all 8 voices (inferred; the simulator
   confirms it). The MPE triggers hook the *calls into* the dispatcher
   (note_on, note_off fallback, arp), so they work in any mode.
3. **`mod_update` runs before the voice loop** (the Summit's runs after). Pressure
   and Slide set in the voice loop reach the FPGA one tick (1 ms) later.
   Not audible; kept simple.
4. **Different signatures and layouts** the C code must follow:
   `mpe_wheel_write` replaces `voice_mod_write(target, n, value)`, not
   `fpga_mod_write(mask, target, param, value)`; the part bend is one `s16`;
   `voice_state` offsets are gate `+0x1F4`, aftertouch `+0x44`, smoothed AT
   `+0x54`, loop index `+9`, last alloc `+0x1E6`, wheel `+0x36`;
   `voice_env_state` `0x2001228C`, `voice_env_level` `0x20012774`, 8 voices,
   no part offset.
5. **UI:** UI mode is `ui_state[0]`, Settings is mode 8, `menus` has 11
   entries, Settings has 26 pages with the MIDI channel on MIDI CONTROL (page
   3). The MPE pages go in as pages 4 and 5; stock page numbers to translate:
   Calibrate 1, BACKUP 9, tuning pages above 8.
6. **No mode-request poll** (no NRPN 62:0 on the Peak). `mpe_ui_poll` wraps
   the per-pass SysEx poll `0x0801A47C` at `0x0800D1C4` instead.
7. **The panel has an audition button** (note 60, velocity 64) that goes
   through `voice_dispatch`. It isn't MIDI, so it plays as a stock voice, as
   the Summit's keybed does.

**Phase 1 status:** the hook map is complete. What phase 1 still owes:
confirming the inferred items in the simulator (mode byte stays 0; `0x1A2`
unread at run time), and the simulator's own landmarks (phase 3).

## 8. Fork status (2026-11-12)

Local branch `peak` in `gipfel_mpe/` (nothing committed or pushed yet).

| Done | Where |
|---|---|
| Toolchain picks the symbols file by the definition's `SOURCE`; Peak startup hook | `tools/patch_build.py`, `tools/patch.py` (24 lines) |
| Peak symbols (≈85, with confidence labels) | `docs/symbols/peak-2.2-2108.csv` |
| Peak firmware header | `patches/common/peak.h` |
| Version-string patch (labels only), builds | `patches/peak_version_string.py` |
| Version-word patch 2108 -> 2109 (word `0x0800C1B0` + header digits); emulated: Settings `109.469`, DIN identity `02 01 00 09` | `patches/peak_version_word.py`, `tests/test_peak_version_word.py` |
| Demo C hook, **audible** for hardware: MIDI notes +12 (pointer hooks, note on and off) +7 (five bl hooks on dispatch/release), armed by `patch_init`; boot mark `DEMO Ver`. Emulated: A3 sounds at stock E5 pitch, poly and mono, note-offs end it | `patches/peak_demo_note_hook/`, `tests/test_peak_demo_hook.py` |
| **MPE patch for the Peak**: builds, all 37 hooks verified, 4,412 B flash, 1,276 B RAM | `patches/peak_mpe/` |
| Upstream Summit patch still builds byte-identical to its hardware-verified release; quick suite 390 passed | |

Peak-specific changes in the MPE code: 8 voices and one part throughout;
calls go through `voice_dispatch`; the filter sets `parts+0` as stock does;
`osc_pitch` result at `+0x2C`; Slide without the queue machinery; Settings
pages after MIDI CONTROL without the CH CLASH item; poly pressure on a member
channel counts as pressure (for the LinnStrument).

**Simulator (2026-11-12): the Peak runs.** `emu/target.py` holds per-image
addresses (Summit, Peak); the board picks them by reset vector. Peak
differences in the model: OLED chip select PB12, one FPGA engine on PB6 (PB7
is held low for something else), every SPI frame reads DR (only `0x8010`
transfers count as reads), no factory initialise in the Peak application (a
blank DataFlash is seeded with the Init Patch and neutral globals: inferred
stand-in). Stock Peak boots to its patch page in 5.6 s simulated; a DIN note
reaches all 8 voices. `tests/test_peak_sim.py` (4 tests, slow) passes:
stock boot, stock note, MPE off writes as stock, MPE on: a member-channel
bend moves exactly one voice by +24 semitones. Upstream quick suite still
390 passed.

**Simulator tests, round 2 (2026-11-12): 10 of 10 pass** (`tests/test_peak_sim.py`):
one voice per channel; member pressure reaches only its voice (0x61); member
Slide reaches only its voice (0x60 = 0x7FFF at CC 74 127) and the stock
broadcast 0x60 is dropped; a note-off on one channel leaves the same note on
another channel sounding; the VOICE page shows `MPE Off` and the edit hook
switches it on; Settings pages 5/28 `MPE` (Zone Off, Members 15) and 6/28
`MPE BEND RANGE` (Note Bend 48, MasterBend 2); MIDI CONTROL unchanged at 4/28.
The display model (20×4 characters) matches the user's Peak (observed by the
user, 2026-11-12).

**LinnStrument tests (2026-11-12): 6 of 6 pass** (16 in `tests/test_peak_sim.py`):
RPN 6 from both masters sets Lower 2-8 + Upper 9-15 on the one patch; a bend
on channel 15 moves only its note; poly pressure on a member channel drives
its voice; RPN 0 = 24 halves the bend; 12 held notes on channels 2-13 keep 8
voices with unique bindings and all end; 60 overlapping notes cycling through
15 channels never bind a channel twice and leave nothing sounding; 1 s of
dense bend/pressure/Slide on 8 channels (6,400 bytes, delivered back to back
at the DIN line rate) never overflows the firmware's DIN ring and every note
ends.

**Stock-firmware finding (observed, Peak `usart6_irq` 0x0800EE24):** when the
256-byte DIN ring fills, the write index lands on the read index, so the ring
reads as empty: the whole buffered 256 bytes are lost at once (counter at
`0x20003EAC+0x204`). Not reached in the dense test; the main loop drains fast
enough in the simulator.

**Not done, in order:**
1. Hardware (below). The simulator can't settle: the FPGA's response to
   per-voice 0x60 (Slide) on build 469, the real CPU timing, real USB input.
2. Done 2026-11-12 (emulated, `test_stock_never_reads_the_flag_byte_nor_writes_the_mode_byte`):
   stock code never reads patch byte `0x1A2` and never writes the mode byte
   `0x20011212` through boot, MIDI, program changes and 54 UI pages; the
   VOICE item's `ui_value_change` hook is in and tested.
3. Hardware, step by step (phase 6): recovery, `peak_version_string`,
   `peak_version_word` (2109 accepted, and the downgrade back to 2108) and the
   demo hook (probe: A3 and A2 +1900.02 c, all hook kinds run) done
   2026-11-12. FPGA 469 questions answered by flashing `peak_mpe` itself
   (2026-11-12, rig run `2026-11-12_210333`, 23 of 23 pass): per-note bend
   moves only its note (±1 c), Slide (per-voice `0x60`, no broadcast) moves
   only its note (+199.48 c). Stage 2 in full, the stage 3/4 checks that
   apply, a 600-run stuck-note soak and stage 5 (LinnStrument patterns over
   USB) followed the same night. Stage 5 found a master bend reaching both
   zones; fixed in `patches/peak_mpe` (image `bc3bf703…`), confirmed on
   hardware 2026-11-13: all 13 applicable checks, 136 pass, 0 fail. The
   LinnStrument itself over DIN the same day (step 6, docs/linnstrument.md):
   all eight steps pass, no stuck note in 4.5 minutes of dense playing. The
   web page patches the Peak with `?synth=peak` (docs/web.md).

**Windows dev notes:** build the image with `scripts/dev --build`, run
commands with `MSYS_NO_PATHCONV=1 scripts/dev ...`; the checkout must have LF
line endings (`git config core.autocrlf false` before cloning).

## 9. First concrete step (done: see sections 6 and 7)

A one-session feasibility probe: fetch the Peak 2.2 image with the repo's own
script, decode it, measure free flash, and run a masked-byte function match
from the Summit's 236 named addresses to the Peak image. The output is a
coverage number for the phase-1 priority list and a go/no-go on whether
`patch_param_desc[0x1A2]` exists. That decides whether phase 1 is one week
or three.
