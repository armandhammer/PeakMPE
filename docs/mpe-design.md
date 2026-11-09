# MPE design

Status: step 1 (the core), step 2 (per-note expression) and step 3 (the
Settings pages) built, 2026-11-01: `patches/mpe/`, emulated in
`tests/test_mpe_*.py`, `tests/test_mpe_expr_*.py` and
`tests/test_mpe_ui_*.py`. Step 4 (conformance and stress, 2026-11-02):
`tests/test_mpe_conformance.py`, `test_mpe_stress.py`, one fix in
`mpe_slide.c`. **On hardware since 2026-11-02** (tag
`hw/2026-11-02-mpe-v1`, kept on the synth): the run plan passed from Live
and the Hapax, Single and Multi ([below](#hardware-run-2026-11-02),
[hardware-log.md](hardware-log.md)). The evidence is in
[findings](findings/summit-2.2-build2121.md#patch-format-storage-and-sysex-for-a-per-patch-mpe-flag);
the bend route in [Oscillator pitch](findings/summit-2.2-build2121.md#oscillator-pitch-params-0x0000x002),
the Slide route in [Part mod sources](findings/summit-2.2-build2121.md#part-mod-sources-0x600x63).
**v1.1** (2026-11-08, tag `hw/2026-11-08-mpe-v1.1`, on the synth): idle
voices rotate on channel reuse ([Channel reuse, v1.1](#channel-reuse-v11));
boot label `MPE2`; Slide dead on the synth. **v1.2** (2026-11-08, branch
`patch/mpe-v1.2`, emulated, not yet on hardware): Slide written per voice
straight to the FPGA, without the v1.1 tick-phase guard
([Slide, v1.2](#slide-v12)); boot label `MPE3`.

## User decisions

| Topic | Decision |
|---|---|
| On/off | **Per patch.** A Multi can have one MPE part and one normal part |
| Zone layout, member count | **Global**: Settings page MPE (globals `+0x30` zone 0 Off/1 Lower/2 Upper, `+0x31` members 1–15), plus the MPE Configuration Message (RPN 6) |
| RPN 6 received | Applied live; stored only on Settings Save |
| Note bend range | Global, default ±48; master default ±2; both settable by RPN 0 |
| Pressure | Member-channel pressure → that voice's AftTouch slot (`voice_state+0xE4+2v`); master-channel pressure → all voices of the zone. A member voice gets the **larger** of its member's and the master's pressure (decided in step 2) |
| Per-note bend | Offset added after `osc_pitch`'s s32 result, ±48 semitones (±16,384), clamped; at both call sites (`mod_tick`, `voice_alloc`) |
| Unison | All voices of a note's stack follow that note's channel |
| Slide (CC74) | **Per-voice ModWheel**: param `0x60` to the voice's target, from its member channel's CC 74. An MPE zone's part **never sends the broadcast `0x60`** (to `0x1A`): it reaches every voice and overwrites the per-voice values. The zone's master mod wheel (CC 1) is folded into each voice's value: **their sum, clamped** (decided in step 2). Experiment D2 on hardware ([findings](findings/summit-2.2-build2121.md#part-mod-sources-0x600x63)) |
| FX (distortion, chorus, delay, reverb) | Take the **master channel's mod wheel only**: `0x860` (to `0x19`) keeps carrying the part's mod wheel. The FX exist once per part, so per-note Slide has no meaning there (decided 2026-11-01) |
| Multi mode | **Version 1 requirement**, not a stretch goal: the per-patch flag, the zone mapping (both parts on: A = Lower, B = Upper; one part on: that part takes the configured zone), 8 voices per part and the channel-conflict rule ([Multi mode](#multi-mode-version-1)) |
| Mono/legato | **MPE for one note at a time.** The part's one voice takes per-note bend, pressure and Slide from the sounding note's channel, plus the master channel's controls ([Voice binding](#voice-binding)) |

## Connecting senders

- **Ableton Live: use the Summit's USB port, not DIN.** Live's MPE output
  from Push 3 played hard is too dense for DIN's 31,250 baud: up to 1,183
  bytes in 200 ms where DIN carries 625 (computed from a recording). On the
  v1 hardware run one note stuck through a USB–DIN interface and none over
  USB (L4, [below](#hardware-run-2026-11-02)).
  The patch itself released every note of that recording in the simulator,
  over USB and DIN (emulated).
- **The Hapax over DIN** played H1–H6 of the v1 run with nothing stuck
  (observed); B1, one dropped note after a zone change, is open.
- Live sends no MCM: set the Settings page MPE to Live's zone and member
  count. A sender with MCM (the Hapax) sets it live.

## Per-patch flag

**Location: patch byte `0x1A2`** (recommended), encoding `0` = off
(default for every existing patch), `1` = MPE on, **any other value = off**
(reserved for later, and a guard against foreign data).

Why `0x1A2`:
- Not read by stock code (memory-read watch and static scan, emulated);
  a nonzero value changes no FPGA write or MIDI byte.
- Saved with the patch slot, copied into Multis (each part keeps its own),
  restored on load, sent in patch and Multi SysEx dumps and received
  verbatim; Components backups keep it. Zero in the Summit and Peak Init
  Patches.
- It **has a descriptor slot** (`patch_param_desc[0x1A2]`, currently min = max
  = 0, NRPN 255:0). Rewriting that one 12-byte `.data` initialiser entry to
  `{min 0, max 1, NRPN 255:0, display 0x0F, name "MPE"}` makes the stock UI
  show it with its name and Off/On. NRPN 255 means no MIDI echo
  (as for `ClockRate`). **Editing it needs code** (emulated, 2026-11-01):
  `ui_value_change` `0x0801CDE0` writes a kind‑1 item through an offset →
  NRPN table at `0x20015E60` that the firmware builds only for offsets below
  `0x1A2` (loop bound `0x0801D8EE`), so for `0x1A2` it reads past the table
  into `globals[0..1]`; and `patch_param_offset` ends at NRPN `0xD35`
  (`0x1A1`). The patch routes the five `ui_value_change` calls through
  `mpe_ui_value_change`, which writes the flag itself (see [UI](#ui)).

Runner-up: the tail `0x1A4–0x1FF`, the same evidence and 92 bytes of room,
but it has no descriptor, so a UI item needs patch code or a relocated
descriptor table. Use it for later per-patch MPE options. Not recommended:
`0x16–0x21` and the sound-area gaps (header and per-oscillator reserves
Novation may mean for Components metadata), and `0x200` (never saved).

**Risks**
- Components' Multi "init part" keeps bytes ≥ `0x18D`, so it keeps the flag
  of that part (minor; Single-mode init clears it).
- A Peak patch imported with a nonzero `0x1A2` would read as "other value" =
  off, unless it is exactly 1. Peak 2.2's Init Patch has 0 there; Peak's own
  use of that byte isn't checked.
- Patches made by other tools or older firmware could hold 1 there by
  chance. Not seen; the strict `== 1` keeps the risk small.
- A future Novation build could assign the byte. We pin 2.2 build 2121.

## UI

Item 3 of **VOICE page 1** (UI mode 7, after Unison and UniDetune):
kind 1, index `0x1A2`. **Built in step 1:** the page record is `.data`, so
it's a change to its flash initialiser `0x0804E43C` (`n_items` 2 → 3 and
the item). Display type `0x0F` is Off/On (strings `0x08049E08`/`0x08049E0C`,
observed). The encoder, the value buttons and the two `ui_page_step`
calls go through `mpe_ui_value_change`, which edits the flag in
`patches[multi + edit_part]`, the patch `ui_value_change` would edit, so in
Multi mode each part gets its own switch (emulated in Single; Multi on
hardware still open). Value 0 (the reset gesture) is Off. Every other item
goes to the stock handler.

Checked through the panel in step 3 (`tests/test_mpe_ui_voice.py`): in
Single mode, and in Multi, where Part A/Part B select whose flag the item
shows and edits.

**Settings** (step 3, [below](#step-3-the-settings-pages)): two pages after
MIDI CHANNEL, so Settings has 35 pages.

```
MPE             5/35      MPE BEND RANGE  6/35
Zone       Off     ▶      Note Bend   48     ▶
Members     15            MasterBend   2
Channels   OK
```

- **Zone** Off/Lower/Upper (globals `+0x30`), **Members** 1–15 (`+0x31`),
  **Note Bend** and **MasterBend** 1–96 semitones (`+0x32`, `+0x33`).
  0 in the globals (never set) shows as the default: Members 15, ±48, ±2.
- **Channels:** `OK`, or `CH CLASH` when `mpe_clash` is set (a Multi part
  with MPE off, or the global channel, lies in a zone). Read only.
- **Live values:** the pages show `mpe_live`, what is in effect: the
  Settings plus what RPN 6 and RPN 0 changed. They redraw when it changes
  while they're on screen.
- **Live vs saved:** a value that differs from the Settings value has a
  `*` after it (`Upper*`, ` 5*`): set by MIDI, not in the Settings. Save
  stores the live state, and the marks go. A two-zone layout (only RPN 6
  makes one) shows both: `Lo+Up*`, `7+7*`, `48+48*`.
- **Editing** first takes the live state into the Settings, as Save would,
  then changes the one value. So an RPN 6 zone survives editing a bend
  range, and a two-zone layout becomes its Lower Zone. Edits are in RAM
  until Save, as for every stock Settings item; delta 0 (the reset
  gesture) does nothing, as stock does for globals.
- **Zone Off** is the setting, not the routing: an MPE patch with Zone
  Off still plays the Lower Zone with 15 members, and the page shows
  `Zone Off` (and `CH CLASH` in Multi if that zone takes channels).

## Multi mode (version 1)

Multi mode is a version 1 requirement. Each part reads the flag from its
own patch (`patches[1]` for Part A, `patches[2]` for Part B), so a Multi can
have two MPE parts, one, or none.

**Zone mapping**

| Part A | Part B | Routing |
|---|---|---|
| on | on | A = Lower Zone (master 1, members 2…), B = Upper Zone (master 16, members 15…) |
| on | off | A takes the configured zone; B stays on its Part B channel |
| off | on | B takes the configured zone; A stays on its Part A channel |
| off | off | stock |

- **One part on:** "the configured zone" is the global Settings layout
  (Lower or Upper, n members) or the last RPN 6. With the global zone Off,
  the part uses the Lower Zone with 15 members.
- **Both parts on:** the Lower Zone keeps its configured count n (capped at
  13), and the Upper Zone gets the remaining 14 − n member channels (at
  least 1). An RPN 6 that sets both zones explicitly overrides the split.
  The global zone setting then only sets n; Off or Upper counts as Lower
  with n = 7 (7 + 7 members, channels 2–8 and 9–15).

**Voice split:** 8 voices per part, as stock Multi already allocates (Part
A voices 0–7, Part B 8–15, `voice_alloc`). An MPE part allocates and steals
only within its own 8 voices, so a zone can hold 8 notes at once (fewer
with unison). In Single mode an MPE patch uses all 16.

**Channel-conflict rule** (version 1): the zone wins. The MPE channel filter
runs before `midi_channel_filter`. A message on a zone's master or member
channel goes only to that zone's part. A normal part whose channel lies in
the zone can't be reached until its channel is moved, and the Settings MPE
page shows "CH CLASH". This keeps MPE notes from doubling on the other
part. The global channel's split/layer dispatch (`multi_global_dispatch`)
follows the same rule: if the global channel is inside a zone, the zone
gets it.

## Voice binding

- Note-on on member channel c: `voice_trigger` with the part's voice range;
  the allocated voice(s) store c (`voice_channel[v]`, CCM). The
  per-voice bend offset, pressure and slide are read through that map.
- A new note on a channel whose voice still sounds or releases (MPE: one
  note per channel): the new note **takes over that voice** (forced voice),
  instead of releasing it and allocating another, so the channel never
  sounds twice. If the channel's voices are all **idle**, they are unbound
  and the note goes to the stock allocator, so it rotates as with MPE off
  (v1.1, [below](#channel-reuse-v11); v1 took idle voices over too).
- Unison: every voice of the stack gets the same channel.
- Mono/legato: MPE for one note at a time. The part's one voice is bound
  to the sounding note's channel and takes that channel's bend, pressure
  and Slide, plus the master channel's controls. So a pad can be bent and
  slid while it's the only note played.
  - **New note while one is held:** the voice moves to the new note's
    channel. Its bend applies at once, and legato's glide moves only the
    note pitch, not the per-note bend.
  - **Note-off with a held fallback note:** the voice goes back to the
    fallback note's channel and takes that channel's current bend,
    pressure and Slide (decided). A bent held note sounds bent again, as
    on other MPE monosynths.
  - **Unison in mono:** the whole stack follows that one channel.

## Note-off and release

- Note-off on c releases the voice bound to c and that note
  (`voice_release`), not every voice playing the note number.
- The binding stays through the release, so the per-note bend keeps
  applying; it is cleared when the voice is reallocated.
- A channel's bend and pressure are kept per channel and not reset at
  note-on: MPE senders send them just before the note-on.

## Stealing

Stock stealing (`voice_candidates`, age order) unchanged. A stolen voice
drops its old channel binding before it takes the new one.

## Step 1: the core (`patches/mpe/`)

Built 2026-11-01 on `patch/mpe-core`, emulated (`tests/test_mpe_core.py`,
`test_mpe_multi.py`, `test_mpe_off.py`). Hardware: not yet.

### Modules

| File | Does | Hooks |
|---|---|---|
| `mpe.h` | the state and interfaces shared by all modules | |
| `mpe_settings.c` | globals → live state, RPN 0 / RPN 6, Save | `globals_apply_poll` in `main_loop` `0x0801C62C`; `settings_save` in `settings_save_action` `0x0800F5CA` |
| `mpe_route.c` | zone routing, the channel filter, per-channel member values | both `midi_channel_filter` calls in `midi_parse_byte` (`0x08010804`, `0x08010864`) |
| `mpe_voice.c` | channel ↔ voice binding, reuse, release by channel | `voice_trigger` calls (`0x08010B0A` note_on, `0x08010A70` mono fallback, `0x0800D0F2` arp); `voice_alloc` in `voice_trigger` `0x080172DE`; `voice_glide` in `voice_alloc` `0x08016F5C`; `voice_release` in `note_off` (`0x08010A08`, `…A3A`, `…A4E`, `…A8E`); v1.1: `voice_env_read` in `voice_candidates` `0x0801562A` |
| `mpe_ui.c` | the VOICE item writes the flag | the five `ui_value_change` calls (`0x0801AC3A`, `0x0801ADA0`, `0x0801ADA8`, `0x0801D256`, `0x0801D27C`) |

Byte patches: `patch_param_desc[0x1A2]` (max 1, display `0x0F`, name
pointer), VOICE page 1, and the labels `MPE1 Ver` / `MPE1Ver`.

**For step 2 (expression)**, read in its own hooks (`osc_pitch`'s two call
sites, `mod_update`'s `0x60` writes):
- `voice_channel[16]` (CCM): the channel (0–15) each voice plays for,
  `0xFF` none. It's written in the `voice_glide` hook, after the voice is
  chosen and **before** `voice_alloc`'s `osc_pitch` calls, so the note-on
  pitch can include the per-note bend. It stays through the release.
- `mpe_chan_bend[16]` (−8192…8191), `mpe_chan_pressure[16]`,
  `mpe_chan_slide[16]` (CC 74): the last value per member channel. Not reset
  at note-on (senders send them just before it).
- `mpe_zones[2]` (part, master, first, last member) and `mpe_zone_of(ch)`;
  `mpe_live.note_range[]` / `master_range[]` per zone kind.
- The master channel's bend, pressure and mod wheel reach the part through
  the stock handlers (`parts[p]+4`, every voice's AftTouch slot, `+6`).
  Step 2 scales the master bend by `master_range` and must not let the
  master pressure overwrite the per-voice slots it drives.
- Weak functions to define: `mpe_member_message(z, ch, msg)` (called after
  a member bend, pressure or CC 74 is stored, and for the member messages
  the core drops) and `mpe_live_changed()`.

**For step 3 (UI)**: globals `+0x30` zone, `+0x31` members, `+0x32` note
range, `+0x33` master range (all "0 = default"; `param_write` stores a
global descriptor with NRPN lsb `0x2E`–`0x31` there); `mpe_live` for what's
in effect; `mpe_clash` (bit 0/1: Part A/B with MPE off has its channel in a
zone, bit 2: the Multi global channel is in one) for "CH CLASH";
`mpe_ui.c` for the item handler. The core picks up a Settings edit within
one main-loop pass.

### Image

Built on `patch/mpe-core` with `tools/patch.py patches/mpe/patch.py
--verify` (all 19 hooks, 18 `bl` and one pointer, and the startup hook verified), `arm-none-eabi-gcc`
16.2.0: 2,196 bytes of flash, 412 bytes of CCM.

| Image | Image bytes | SHA-256 |
|---|---|---|
| `summit-firmware-2.2-build2121+mpe.syx` (step 1) | 281,184 | `afbae35d316539634a945ba373719697a06a9e8e47c1ac5b9a1d720df8d64125` |

Not for hardware on its own: step 1 plays MPE notes without per-note
expression.

### Decisions made in step 1

- **Routing rule:** zone channels first, everything else to the stock filter
  unchanged. So the zone wins a conflict, and channels outside the zones
  behave exactly as stock, also for an MPE part: in Single mode the global
  channel, if outside the zone, still plays the MPE patch, unbound (no
  per-note expression); in Multi an MPE part's own Part channel and the
  global channel's split/layer still work outside the zones.
- **Master channel notes** play, bound to the master channel (they get the
  master's controls only).
- **Member channels:** notes, RPN, CC 120 and 123–127 (all sound/notes off,
  mode messages, part-wide) reach the part. Bend, pressure and CC 74 are
  stored per channel; everything else (other CCs including sustain and the
  mod wheel, poly pressure, program change) is dropped and passed to
  `mpe_member_message`.
- **RPN state** is kept per channel, on every channel. RPN select (CC
  101/100) and RPN data (CC 6/38 while an RPN is selected) are taken from the
  firmware only on zone channels; elsewhere it still gets them, so stock's
  "CC 6 goes to the last NRPN" stays as it was. CC 99/98 selects NRPN again,
  so NRPN keeps working on the master channel. RPN is processed regardless
  of the `CC/NRPN` receive setting. RPN null (127/127) deselects.
- **RPN 6** (only on channels 1 and 16): as the MPE spec says, the other
  zone shrinks to 14 − n members, or goes when nothing is left. It resets
  that zone's bend ranges to the Settings values (default ±48/±2). n = 0
  removes the zone; an MPE patch then falls back to Lower 15. A layout change
  releases no notes: a note-off goes first to the part of an active voice
  bound to its channel and note, wherever the channel is routed now, so
  nothing sticks (emulated, also for a flag change while holding).
- **RPN 0:** data MSB = semitones, clamped to 96; the LSB (cents) is
  ignored. On the master channel it sets the master range, on any member
  channel the note range, for that zone kind (Lower/Upper). If the channel
  isn't in a zone in use, the configured layout decides, so a range can be
  set before an MPE patch is chosen.
- **Single mode with two zones** (only RPN 6 can make that): both play the
  patch. **Multi, one part on, two zones configured:** the part takes the
  Lower one.
- **Save:** the live layout and ranges replace globals `+0x30…+0x33`. A
  two-zone layout saves as its Lower Zone; a range of 0 (RPN 0 can set it)
  saves as the default.
- **Channel reuse:** in the poly modes a new note on a channel takes over
  the voices still bound to it (sounding, releasing or idle), through
  `voice_alloc`'s forced-voice argument, one per unison voice; the allocator
  picks any more. A sender reusing a channel early so never doubles it.
  **Changed in v1.1:** idle voices are no longer taken over
  ([Channel reuse, v1.1](#channel-reuse-v11)).
- **Release by channel:** in an MPE part's poly modes, `note_off`'s
  `voice_release(note, part)` sees only the voices bound to the message's
  channel; the others playing that note number are hidden for the call (their
  `voice_note` reads `0xFF`). So two channels can hold the same note. The
  keybed and non-zone channels release only unbound voices. Mono modes
  release as stock.
- **Mono/legato:** the allocator's voice, bound to the sounding note's
  channel at each trigger, including the fallback trigger on note-off (the
  held note's channel, remembered per part and note).
- **Arpeggiator:** an arpeggiated note binds to the channel it was played on.
- **Keybed** notes on an MPE patch are unbound.

## Step 2: expression (`patches/mpe/`)

Built 2026-11-01 on `patch/mpe-expression`, emulated
(`tests/test_mpe_expr_single.py`, `test_mpe_expr_multi.py`,
`test_mpe_expr_queue.py`). Hardware: not yet. It reads the step 1 state
(`voice_channel[]`, `mpe_chan_bend/pressure/slide[]`, `mpe_zones`,
`mpe_live`) and changes none of the core's files.

### Modules

| File | Does | Hooks |
|---|---|---|
| `mpe_expr.h` | the step 2 interfaces; the voice's role | |
| `mpe_expr.c` | runs once per voice per tick and at note-on, before Osc 1's `osc_pitch`, and hands the voice's role to the three modules below | `osc_pitch` calls in `mod_tick` (`0x08014526`, `…530`, `…53A`) and `voice_alloc` (`0x08016F66`, `…F72`, `…F7C`) |
| `mpe_bend.c` | per-note and master bend as an offset after `osc_pitch` | pointer: `osc_pitch`'s literal for `part_bend_smoothed` (`0x08013AD4`) → `mpe_bend_in` |
| `mpe_pressure.c` | member pressure into the voice's AftTouch slot | (from `mpe_expr.c`) |
| `mpe_slide.c` | per-voice `0x60`, no broadcast `0x60` from an MPE engine | `mod_update`'s broadcast `0x60` write (`0x08014248`); `mod_tick`'s `mod_update(1)` (`0x0801457E`) |

`firmware.h` gains `fpga_voice_write` (`0x08012B94`, emulated), which
`voice_alloc` uses for the note-on pitch writes.

**Roles.** A voice of a part with MPE on that is bound to a member channel
of that part's zone is a *member* voice; one bound to the zone's master
channel is a *master* voice. Every other voice (MPE off, unbound: keybed,
a channel outside the zones, or a binding whose channel is no longer in the
zone) is *stock*: it gets nothing from step 2.

### Bend

- **Member voice:** offset = member bend (−8192…8191) × note range / 24,
  ±48 semitones = ±16,384 in `osc_pitch`'s result (4,096 per octave).
  Independent of the patch's `BendRange`.
- **Master bend:** the stock path (master channel → `parts[p]+4` →
  `mod_update`'s 1/16 smoother → `part_bend_smoothed`), scaled by the
  zone's master range instead of `BendRange`: offset = `part_bend_smoothed`
  × master range / 48. Member and master voices get it.
- For member and master voices `osc_pitch` reads a part bend of 0
  (`mpe_bend_in`), so stock's `BendRange` term drops out; the offset is
  added to the s32 result of all three oscillators and the sum clamped to
  what `osc_pitch` itself can return, −43,691…43,689 (its s16 sum × 4/3), so
  nothing wraps. Stock voices read `part_bend_smoothed` through the same
  literal and get no offset: bit for bit as stock.
- **Smoothing (decided):** per voice, 1/4 of the step per tick (90 % in
  8 ms), lighter than stock's 1/16, since MPE senders stream bend densely.
  Each voice's `0x000`–`0x002` still reach the FPGA every 2 ms, as stock.
- **Note-on (decided):** the voice jumps to its channel's current bend, so a
  note started while its channel is bent starts bent (`voice_alloc`'s
  direct writes already carry it). The same holds for channel reuse and
  for the mono/legato voice moving to another note's channel.
- **Unbound voices in Single mode** take the part bend as stock, through
  `BendRange`. The master channel's bend is the part bend, so they follow
  the master too (by `BendRange`, not the master range).

### Pressure

- The master channel's pressure takes the stock path unchanged
  (`chan_at_store` `0x080159B8`: every voice's slot and `parts[p]+7`).
- **Rule (decided):** every tick, before `mod_update`, a member voice's
  slot becomes max(member pressure, master pressure) << 8. The master never
  overwrites what a member drives, and a member never pushes a voice below
  the master.
- A slot written for a member goes back to the master's value as soon as
  its voice stops being a member voice (a keybed note takes it, MPE goes
  off), so nothing is left behind.
- **Note-on:** a member or master voice's AftTouch smoother
  (`voice_state+0x104+4v`) jumps to its slot and its `0x61` is written at
  once with `fpga_voice_write`, with `mod_update`'s maths. Otherwise the new
  note would start at the previous note's pressure for up to 8 ms.
- Latency and smoothing after that are stock's: the round-robin sends each
  voice's `0x61` every 8 ms, smoothed by 1/4 per refresh.
- Poly pressure on the master channel stays stock (the voices playing that
  note); member voices take their member's value again in the next tick.

### Slide

- For an engine whose voices belong to an MPE part (both engines in Single,
  the part's own in Multi), `mod_update`'s broadcast `0x60` isn't sent
  (experiment D2). `0x860` to `0x19` stays stock: the master's mod wheel,
  for the FX and the other part-level destinations.
- Each voice of such an engine gets `0x60` = the part's stock-smoothed mod
  wheel (`voice_state+0xCA+4p`) + its Slide, clamped to `0x7FFF`. Slide is
  the member channel's CC 74 << 8 (127 → `0x7FFF`), smoothed per voice by
  1/8 per tick (as stock smooths the wheel); 0 for master and stock voices,
  which so follow the wheel as on stock.
- **Sum, not the larger (decided):** the wheel moves every note and each
  note still slides on its own. A Slide that already sits near the top
  leaves the wheel little room; the clamp keeps the value in range.
- **Queue:** a voice's `0x60` is queued only when its value changed, at most
  **4 per tick**, round-robin, after `mod_update(1)`. 16 voices all moving
  are each refreshed every 4 ms. (v1.2: written directly instead of queued,
  [below](#slide-v12).)
- **Note-on:** the new voice's `0x60` is written directly
  (`fpga_voice_write`) and queued again first in the next tick, so a stale
  queued value can't be the last it gets.
- When MPE goes off for a part, its broadcast `0x60` resumes and sets every
  voice of the engine again.

### Unison and mono

Every voice of a stack is bound to the note's channel (step 1), so each
gets the channel's bend, pressure and Slide. The mono/legato voice takes
the sounding note's channel's values at each trigger, including the
fallback to a held note (emulated).

### FPGA queue budget

Emulated, worst case (`test_mpe_expr_queue.py`): 16 notes, every member
channel jumping bend, pressure and CC 74 every 25 ms, the master wheel
moving, over USB.

| | Single (Lower, 15 members) | Multi (two zones) | Stock |
|---|---|---|---|
| Writes per tick, max | **77** (75 − 2 broadcasts + 4) | **77** | 75 |
| Drain per tick | 80 | 80 | 80 |
| Peak depth while moving | 86 | 88 | 82 |
| Peak depth overall (of 128) | 98 | 98 | 94 |
| Each voice's `0x60` | every 4 ms while moving | the same | broadcast, every 1 ms |

The overall peak is a tick delayed by a long main-loop pass (the 16
note-offs at once in Single, the switch to Multi) followed by an on-time
tick, so two ticks' writes arrive faster than the timer-driven drain. Still
77 writes per tick (emulated). Stock peaks the same way at the switch to
Multi. Bend and pressure add no queue writes: bend rides in the existing
`0x000`–`0x002` refresh, pressure in stock's `0x61` round-robin.

### Image

Built on `patch/mpe-expression` with `tools/patch.py patches/mpe/patch.py
--verify` (all 28 hooks, 26 `bl` and two pointers, and the startup hook
verified), `arm-none-eabi-gcc` 16.2.0: 3,340 bytes of flash, 752 bytes of
CCM.

| Image | Image bytes | SHA-256 |
|---|---|---|
| `summit-firmware-2.2-build2121+mpe.syx` (steps 1 and 2) | 282,336 | `b2497265bc72af91e41f53b4dbf6d7e6a4e581a6d310c2b9faaa0430cddf7b6f` |

The labels stay `MPE1 Ver` / `MPE1Ver` (step 1's byte patches); bumping
them is left to whoever prepares the hardware build.

## Step 3: the Settings pages

Built 2026-11-01 on `patch/mpe-ui`, emulated (`tests/test_mpe_ui_settings.py`,
`test_mpe_ui_voice.py`, `test_mpe_ui_stock_pages.py`; golden screens
`tests/golden/screens/mpe-*.txt`). Hardware: not yet.

All new code is in `mpe_ui.c`. The core gained two functions, both used by
Save as well: `mpe_live_to_globals` (what Save stores) and
`mpe_globals_to_live` (what the main loop takes over).

| Hook | Site | Why |
|---|---|---|
| `bl` `settings_load` → `mpe_ui_boot` | `0x0801C57A` (main_loop, first call) | builds the tables below and sets `menus[10]` before the main loop runs |
| `bl` `mode_request_poll` → `mpe_ui_poll` | `0x0801C642` (main_loop) | redraws the MPE values when they change |
| `bl` `format_value` → `mpe_ui_format` | `0x0801CBF4` (ui_draw_values, kind 3) | the value formatter for display types `0xE0`–`0xE4` |
| `bl` `ui_current_page_index` → `mpe_settings_page_index` | `0x0800F5A6`, `0x0801812A`, `0x0801D460`, `0x0801D47A`, `0x0801D4C2` | stock code acting on a Settings page number gets the stock number |
| pointer `global_param_desc` → `mpe_global_desc` | `0x0801C9E8`, `0x0801CC9C`, `0x0801D220` | descriptor records `0x30`–`0x34` |

- **When:** at boot, before the main loop runs, so nothing can reach
  Settings before the tables are complete: not a button, and not an NRPN
  62:0 = 10 (Settings) that arrived while the synth started, which the
  first main-loop pass handles (`tests/test_mpe_ui_powerup.py`, with patch
  RAM filled with garbage first: building them in the first pass instead
  faults in `lcd_puts` `0x0800DF68` on a garbage name pointer). They live in
  `PATCH_NOINIT` RAM (not cleared by `__patch_start`), as does `drawn[]`,
  since all of it is written before use.
- **Descriptors:** `mpe_global_desc` (CCM) = the 48 stock records, copied
  from RAM, plus `0x30` Zone (0–2, NRPN 64:46), `0x31` Members (1–15,
  64:47), `0x32` Note Bend (1–96, 64:48), `0x33` MasterBend (1–96, 64:49) and
  `0x34` Channels (status; NRPN 255:255; `globals+0x34` is read, never
  written). The NRPNs follow the `lsb + 2` rule but aren't sent: edits
  write the globals directly instead of through `param_write` (`0x0801D838`),
  since they start from the live value, not `globals[index]`, so they send
  no NRPN echo (stock Settings edits do when CC/NRPN transmit is on).
- **Menu:** `mpe_settings_menu` (CCM) = the stock page pointers with the two
  MPE page records (CCM; byte 5, the selected item, is written) at index 4
  and 5; `menus[10]` points at it. Stock page records stay where they are.
- **Display types `0xE0`–`0xE4`** are new: stock `format_value` handles 1–`0x60`
  and prints nothing for others. Needed because the pages show live values
  and marks, not `globals[index]`. Numbers right-aligned in three columns
  and words left-aligned, as stock; the field is padded to its 8 columns.
- **Edits:** the five `ui_value_change` calls already come to
  `mpe_ui_value_change` (step 1); kind 3 items on the MPE pages go to
  `edit_setting`, clamped to the descriptor's min/max, then `mark_changed`
  (as `param_write` does), `mpe_globals_to_live` and `ui_draw_values`.
- **Page numbers in stock code** (emulated against stock in
  `test_mpe_ui_stock_pages.py`): Save on a tuning page (`> 16`), tuning
  NRPN 25:54/55 (`> 16`), Calibrate (1), POT CALIBRATE Go (9), BACKUP Go
  (15). The MPE pages answer 3 (MIDI CHANNEL, no page action), so Save on
  them saves the Settings. The other callers of `ui_current_page_index`
  act in other modes (1, 5, 11, 12) and aren't hooked.

**Core fix in step 3:** Save with Zone Off stored members 0 (the
default), losing a member count set while the zone was off. Save now keeps
the member setting when no zone is live.

### Image

Steps 1, 2 and 3 together (`patch/mpe-ui`, 2026-11-01):
`tools/patch.py patches/mpe/patch.py --verify`, 40 hooks (33 `bl`, 6
pointers, the startup hook; no call site claimed twice) and the blob's
branches verified, `arm-none-eabi-gcc` 16.2.0: 4,896 of 65,088 bytes of
flash, 1,628 bytes of CCM (752 cleared at startup, 876
`PATCH_NOINIT`). `tests/test_mpe_combined.py` plays step 2's expression at a
range set on the step 3 page, through an RPN 6, Save and a power cycle.

| Image | Image bytes | SHA-256 |
|---|---|---|
| `summit-firmware-2.2-build2121+mpe.syx` (steps 1, 2 and 3) | 283,872 | `1d0d94552ae6de265cbeb48b26dd551106727747244781ca518fd6cfa0b97f59` |

**Simulated timing.** `test_mpe_off.py` used to compare, per FPGA
register, the exact sequence of values written, against stock. That
sequence depends on where in a millisecond each input and each main-loop
pass falls, for stock itself: stock against stock with the input moved
50–100 µs gives 15–84 registers with a different sequence (both parts
sharing a register interleave differently, per-tick rotations and
smoothing start a tick earlier or later, EXTI15-timed envelope reads steer
voice allocation). It had passed by chance; the boot-time table build
tipped it. Since step 3 it compares at every quiet point of its play
(a pause of 20 ms or more) and at the end: the sounding notes and their
voices' settled registers matched by note, every settled broadcast and
part register (settled: unchanged for 12 ms), with at least 95% of stock's
settled registers settled in the patch too, plus the MIDI out byte for
byte and the final FPGA state. A run with the MPE flag on fails it at the
first checkpoint.

The same timing shift showed in `test_mpe_expr_queue.py` (Multi): the
test's flag poke landed in the middle of a main-loop `mod_tick`, so one
tick sent the old broadcast `0x60` and the new per-voice Slide (79 writes,
budget 77). On the synth the flag changes only between main-loop passes;
the test now pokes there (`SimulatedSummit.to_pass_start`).

## Step 4: conformance and stress

2026-11-02 on `feat/mpe-conformance`, emulated. The complete patch (steps
1–3) under the traffic of the user's two senders and the MPE 1.0 edge
cases, before the first hardware run.

### Test tools (`tests/mpe_traffic.py`)

- **Senders:** `live()` (Ableton Live via Push 3: one zone, Lower or Upper,
  no MCM; least recently used member channel first; pressure, CC 74 and
  bend just before each note-on, then every ~6 ms: the order and spacing of
  the user's capture, observed; the rest inferred) and `hapax()` (Lower
  2–15 or Upper 15–2, MCM optional, up to four tracks on one output, either
  sharing one channel pool or colliding, inferred), plus `reset_burst()`,
  `mcm()`, `rpn()` and `mmon_events()` for MIDI Monitor captures.
- **Rendering:** USB at the simulator's frame rate, or DIN with running
  status, timing clock (also inside messages) and SysEx for another device.
- **`Invariants`:** hooks `mpe_channel_filter` and checks after every
  main-loop pass that handled a message or ran a tick (never halfway
  through a handler): the binding against what the sender holds or the
  pedal sustains; per-voice pitch within `osc_pitch`'s range and without a
  jump a wrap would make; `0x60` in range; the queue depth. At a quiet
  point `expression()` checks every member and master voice's
  `0x000`–`0x002`, AftTouch slot and smoother, `0x61` and `0x60` against
  its own channel plus the master; `all_released()` that nothing sounds
  after every note-off.
- **`QueueWatch`, `CpuWatch`:** queue depth and writes per tick; instructions
  per main-loop pass and per tick (block hook, Thumb-2 decoded), the patch
  blob's share separately.
- **Simulator:** `SimulatedSummit.usb_phase_us` puts the USB frame anywhere
  in the ms. At 0 (the default, as before) USB input always lands on the
  tick's boundary, which hid the queue case below from stock.

### Covered

| What | Where |
|---|---|
| Live Lower and Upper without MCM; Live into a smaller Settings zone; Live's bend reset burst (no change); the user's capture replayed (members 2–13) | `test_mpe_conformance.py` |
| Hapax Lower/Upper with MCM over other Settings, without MCM, four tracks sharing or colliding | same |
| MCM changing the layout with 15 notes held; RPN 0 on member and master; channel reuse before release; 30 notes with unison on all 16 channels; sustain on the master (same note on two channels, reuse under the pedal); CC 123 and 120 on master and member; non-member channels; mono, MonoLG, Mono2; DIN running status + clock + SysEx; expression before the note-on | same |
| Seeded random plays, 4 phrases each, edge cases mixed in, every invariant after every pass: Single Lower (Live, USB), Single Upper (Hapax MCM, 4 colliding tracks, DIN with clock), Multi two zones, Multi one MPE part + one normal part | `test_mpe_stress.py` (one seed per layout in the suite; 13 per layout passed, `MPE_STRESS_SEEDS`) |
| MPE off with Live and Hapax traffic, Single and Multi: as stock | same |
| Queue and CPU at the worst case; a long handler at every USB phase against stock | same |

### Numbers (emulated; the board's model is 120,000 instructions per 1 ms tick)

| | Patch | Stock |
|---|---|---|
| Writes per tick, max (16 voices, every channel's bend, pressure and CC 74 every 3 ms, the densest USB carries) | 77 (drain 80) | 75 |
| Queue depth, that play | 86 (118 before the fix below) | 118 (the same messages on channel 1) |
| Queue depth, CC 120 or a program change at the worst USB phase (20 phases, 16 voices moving) | 117 / 118 (126 / 118 before the fix) | 122 / 121 |
| Longest main-loop pass, 16 note-ons in 8 ms | 66,718–85,609 (56–71 % of a tick; it depends on how many note-ons one pass takes) | 80,199 (67 %) |
| Longest pass, the controller stream | 29,033 (24 %), patch code 8,370 of it | 22,402 (19 %) |
| Patch code per tick, worst case | 13,255 max (11.0 %), 11,391 mean | |
| Patch code per tick, idle with MPE on | 8,260 (6.9 %): ~96 per main-loop pass (41 passes per ms) plus mod_tick's hooks | |

A pass that runs longer than the time left to the next tick request delays
that tick: the main loop serves `mod_tick` after `midi_drain_inputs`. No
pass comes near a full tick, so no tick is lost; the cost of a delay is the
queue case below.

### Findings and the fix

- **Bug, fixed: the Slide writes could take the FPGA queue to 126 of 128.**
  A long MIDI handler (CC 120 or a program change: ~80,000 instructions,
  stock code) delays a tick; the next request comes ~0.35 ms after the
  delayed tick ran, so two ticks' writes are queued at once. Stock reaches
  122 so (at some USB phases, on stock too). With every voice's Slide
  moving, the patch's 4 per-voice `0x60` writes per tick reached 126; the
  write index wraps without a check, so two more would have overwritten
  queued writes. `mpe_slide.c` now sends nothing in a tick that finds more
  than 48 entries still queued when `mod_update(1)` returns (12–21 in a
  normal tick, 25–61 after a delayed one, and ~60 of the tick's writes still
  to come); the voices stay dirty and go next tick. Worst case now 118. A
  threshold of 24 held Slide back after every burst of incoming messages, so
  16 moving voices missed their 4 ms refresh (`test_mpe_expr_queue.py`).
  Regression: `test_a_long_handler_delays_a_tick_no_worse_than_stock`.
  (v1.2: Slide is no longer queued, so this check is gone; that test now
  measures 114 / 102 against stock's 122 / 121, [Slide, v1.2](#slide-v12).)
- **Stock behaviour, not changed: after a steal, the old note's pitch for
  ~2 ms.** A refresh of the voice's `0x000`–`0x002` that the tick before
  queued drains after `voice_alloc`'s direct note-on writes (stock: 34 such
  in a 30-note steal play, the patch 30). The checker leaves 2.5 ms after
  an allocation out.
- **Stock behaviour: the queue's own margin** is 6 entries under a long
  handler at a bad phase. Hardware hosts' USB frames aren't locked to the
  Summit's timer, so on hardware stock meets this too (inferred).
- **Limitation, not changed: Single mode with two zones** (only two MCMs
  make one) plays both zones on Part A, so both masters share the part's
  bend, pressure and wheel: the Upper master bends Lower notes too. Live
  can't make this (no MCM); the Hapax can with two MPE tracks sending MCMs.
- **Member CC 121 (reset all controllers)** is dropped with the other
  member CCs, so a member's last bend, pressure and CC 74 stay until its
  next message. Harmless with both senders (they send them before every
  note-on); noted.

### Image

`tools/patch.py patches/mpe/patch.py --verify`, 40 hooks verified,
`arm-none-eabi-gcc` 16.2.0: 4,920 of 65,088 bytes of flash, 1,628 bytes of
CCM.

| Image | Image bytes | SHA-256 |
|---|---|---|
| `summit-firmware-2.2-build2121+mpe.syx` (steps 1–4) | 283,904 | `eacd0a220cd946f1acd8b5840c8aa9d7becfea3b085e35d1cf9fd5cc9f1741bd` |

## Hardware run (2026-11-02)

The complete patch on the Summit, image `eacd0a22…`, tag
`hw/2026-11-02-mpe-v1`, played by the user from Live/Push 3 and the Hapax
through a run plan of every feature ([hardware-log.md](hardware-log.md)).
Kept on the synth. What it showed (observed unless marked):

- The Settings pages, the VOICE item (also per part in Multi), the zone
  routing (Lower, Upper, mismatch, two zones in Multi, `CH CLASH`), RPN 6
  from the Hapax (live, `*`, Save) and per-note bend, pressure and Slide
  without cross-talk all behave as emulated.
- Per-note bend is smooth and lands in tune at ±12 (Live's ±48 against
  `Note Bend 48`); the ±48 extremes weren't reached.
- MPE off plays as stock.
- **DIN:** Live's MPE stream from Push 3 played hard overruns DIN (up to
  1,183 bytes in 200 ms, computed from the recording); one note stuck
  through an AF16Rig interface, none over USB. The patch released every
  note of that recording in the simulator (emulated). Use USB for Live
  ([Connecting senders](#connecting-senders)).
- **Channel reuse** binds a channel to its voice even when idle (step 1),
  so a reused channel gets the same voice each time; audible to the user
  (L5). Addressed in v1.1 ([below](#channel-reuse-v11)): only voices still
  sounding or releasing are taken over.
- **B1, open:** the first chord after an MCM zone change twice played one
  note fewer; not reproduced since, nor in 18 simulated variants. The
  simulator allocates other voices than the synth did (inferred: the
  FPGA's envelope replies are modelled).

## Channel reuse, v1.1

Built 2026-11-08 on `patch/mpe-voice-rotation` (F1, from L5 of
the v1 run), emulated (`tests/test_mpe_rotation.py`). On hardware
2026-11-08: idle voices rotate, but Slide stopped working, fixed in
[v1.2](#slide-v12) ([hardware-log.md](hardware-log.md)).

**Rule.** In an MPE part's poly modes, a note on a channel takes over the
voices bound to it only while they are **live**: sounding or releasing.
When all of them are idle, they are unbound (`voice_channel[v] = 0xFF`)
and the note goes through `voice_alloc` with no forced voice, so the
stock allocator picks, and rotates, exactly as with MPE off. Unchanged:
unison (each stack voice follows the note's channel; a live stack is taken
over voice by voice, an idle one rotates), mono/legato (the allocator's one
voice, bound to the sounding note's channel), release by channel, the
expression modules.

**Live, as the stock allocator reads it** (findings: [idle or
releasing](findings/summit-2.2-build2121.md#the-fpga-bus-spi1)):

| Field | Address | Live when |
|---|---|---|
| gate | `voice_state+0x334+v` (`0x20005B0C+v`) | nonzero (held, or sustained by the pedal) |
| envelope state | `voice_env_state` `0x20013354`, index v (Single) or `part×16 + v−part×8` (Multi) | not 3 (3 = release or idle) |
| envelope level | `voice_env_level` `0x200148F0`, same index | above `0x200`, the level `voice_candidates` counts as still sounding (`0x08015694`) |

The FPGA values come from `voice_env_read` `0x08014E3C`, which only
`voice_candidates` calls (`0x0801562A`), at the start of each allocator
pick. The patch hooks that call (`mpe_env_read`): when the reuse rule has
just read the FPGA itself, the allocator uses that read instead of waiting
for another, so a rotating note-on waits exactly as long as on stock.
The rule reads only when it has to: not if every bound voice is certain
without it, because its gate is held, or because the last read saw it
idle and it hasn't been allocated since (only an allocation wakes an
idle voice; `mpe_alloc_glide` notes each one). A voice the last read saw
releasing may have ended since, so it is read again.

**Cost (emulated).** A take-over of a held voice costs what it did in v1;
one of a releasing voice pays one read, as stock. A note that rotates pays
the allocator's read, as stock does on every note-on: up to 2 EXTI15
edges per engine (`voice_env_poll` `0x08014D54`; the simulator's edge
period, 100 µs, is a guess). So dense chords delay ticks as on stock.
Replaying the user's Live capture over USB, stock with the same messages
on channel 1 takes the FPGA queue to 126 of 128; v1 stayed at 98 (it never
read on a reused channel). v1.1 first reached 127: a tick delayed by 0.85
ms still sent its 4 Slide writes, and the next tick followed 0.25 ms
later. **Fix in `mpe_slide.c`:** a tick that runs half a ms or more after
its request (`timer_state+0x4A8` ≥ 5, 100 µs steps; 5 of about 2,560
ticks in that replay, normal ticks run at 0–4) sends no Slide; the voices
stay dirty and go next tick. v1.1 now peaks at **122** there, under the
conformance limit of 124 that every play keeps. **On the synth this guard
held back every Slide write** (v1.1's run: Slide dead); v1.2 replaces it,
[Slide, v1.2](#slide-v12).

**Tests** (`tests/test_mpe_rotation.py`, emulated, with the simulator's
release model `SimulatedSummit.release_ms`: the FPGA level falls to 0
over that many ms after the release command, 0 by default):
- note/release/note on one member channel, the release over: the same
  voice sequence as MPE off on the global channel (Single, and Multi with
  one MPE part in its 8 voices); during the release: the same voice each
  time; held (no note-off): the same voice, nothing doubled; mixed gaps;
  unison stacks; mono and MonoLG unchanged against MPE off;
- after rotating onto a voice another channel left bent, pressed and slid,
  the voice plays its new channel's bend, pressure and Slide, not the old
  ones; that other channel then gets a voice of its own with its own values
  (Single, and Multi with Part B MPE off playing in between);
- the rotation tests fail with v1's rule, and the "during the release"
  ones without the level check (both tried).

`tests/test_mpe_core.py`'s "takes over its voice" test runs with a
100 ms release now (with every level 0 a released voice is idle at once).

**Version:** boot screen `MPE2 Ver 126.778`, Settings `MPE2Ver` (`MPE1` =
v1, `hw/2026-11-02-mpe-v1`). The identity stays 2126.

### Image

`tools/patch.py patches/mpe/patch.py --verify`: 40 hooks (35 `bl`, 5
pointers) plus the startup hook, and the blob's branches, verified;
`arm-none-eabi-gcc` 16.2.0: 5,292 of 65,088 bytes of flash, 1,632 bytes of
CCM.

| Image | Image bytes | SHA-256 |
|---|---|---|
| `summit-firmware-2.2-build2121+mpe.syx` (v1.1, `MPE2`) | 284,288 | `5f6c5e57e21acb85111e7d7b2a05626a2f7486a9302c69b660ca98a6c941081b` |

## Slide, v1.2

Built 2026-11-08 on `patch/mpe-v1.2`, emulated
(`tests/test_mpe_slide_timing.py` and the existing suites). On hardware
2026-11-08: every rig check passes over USB and DIN, Slide works and idle
voices rotate ([hardware-log.md](hardware-log.md)).

**The bug** (observed on the v1.1 hardware run):
on v1.1 CC 74 moved nothing, solo or in a chord (`slide_right_note`
+0.00 c; v1 +199.51 c). The only change in the Slide path since v1 is the
tick-phase guard: no Slide when `timer_state+0x4A8` reads 5 or more at the
end of `mod_update(1)`.

**What the field is** (observed in code): 100 µs steps since the last tick
request, stepped by `tim6_isr` on every second 20 kHz interrupt and reset
with the request at 10 ([findings](findings/summit-2.2-build2121.md#cpu-rate-flash-and-spi-busy-waits)).
Inside `mod_tick` it therefore measures how long the CPU took since the
request. TIM6 and the CPU share SYSCLK, so a step is 12,000 cycles on any
unit.

**Why it read 5 or more** (inferred): v1.1's tick runs 11,500 instructions
to that point (stock 7,000; emulated). The simulator's default model, one
instruction per cycle, free SPI, 300 instructions per interrupt, puts that
at phase 1, where the threshold came from. The synth is far slower:
`clock_init` leaves the flash accelerator off (`FLASH_ACR` = 3: 3 wait
states, no prefetch or caches), and the TIM6 interrupt busy-waits about
3.2 µs per queued write on SPI1 (15 MHz), some 30 % of the CPU at 75–80
writes per ms (both observed in code; the effect on the rate inferred).
Every tick at phase ≥ 5, while ticks still don't merge, puts the main
thread at 11–19 % of the default model's rate. In the simulator,
`set_timing(0.3, spi_cost=True)` reproduces the synth's result exactly:
the Slide point at phase 5–8, v1.1's `0x60` never moves (emulated). The
value 0.3 rests on that one observation.

**Fix.** `mpe_slide.c` writes each voice's `0x60` with `fpga_voice_write`
(one SPI1 transaction under `cpsid f`) instead of queuing it, and the
queue-depth and phase checks are gone. Still only on change, at most 4 per
tick, round-robin (each moving voice every 4–6 ms), the new voice's value
at note-on.
- **Why direct:** queue safety then doesn't depend on timing at all. The
  queue holds stock's writes minus the dropped broadcasts (73 per tick with
  MPE on, stock 75), so no tick, late or not, adds to it. A check on the
  queue's depth can't see the case v1.1's guard was for: a tick 0.85 ms
  late finds 23 entries queued, sends its 4, and the next tick follows
  0.25 ms later (emulated, Live capture: without the guard 127 of 128). The
  phase is real time, but any threshold on it is a guess at the CPU rate,
  which is what failed.
- **Proven route:** stock `voice_alloc` writes every note-on's pitch,
  velocity and envelope commands with the same call, and the patch's
  note-on writes of pressure (`0x61`) and Slide have used it since v1: all
  on the synth since 2026-11-02.
- **Cost:** the same SPI time v1 spent in the TIM6 interrupt, now in the
  main loop: 4 writes × 3.2 µs plus code per tick at most. Interrupts are
  masked for one write at a time, a few µs, under TIM6's 50 µs period.
- **A broadcast still queued:** when an engine turns MPE (the flag, Multi,
  a zone change), a broadcast `0x60` that `mod_update` queued just before
  could land after a direct write. `mpe_wheel_write` notes the drain count
  (`voice_state+0x148`) by which each broadcast it lets through is sent;
  until the drain has got there, the engine's voices count as unknown and
  are written again.

**Queue** (emulated, peak of 128; the queue wraps at 128):

| Play | Timing | Stock (same messages on ch 1) | v1.1 | v1.2 |
|---|---|---|---|---|
| Live capture (L4), USB | default | 126 | 122 (127 without its guard) | **122** |
| Live capture | `set_timing(0.35, spi_cost=True)` | 120 | 100 | 84 |
| Live capture | `set_timing(0.3, spi_cost=True)`, as the synth | 115 | 67 (Slide dead) | 60 |
| Dense worst case (`test_worst_case_queue`) | default | 118 | | 114 |
| CC 120 / program change at 4 USB phases | default | 122 / 121 | 118 (step 4) | 114 / 102 |
| 16 voices moving (`test_mpe_expr_queue.py`), Single / Multi | default | 82 / 86 | 98 / 98 | 82 / 90 |

So the margin to the wrap is 6 entries at the worst play (stock there: 2),
and under the synth-like timing over 60. Multi's 90 against stock's 86 is
tick timing (the patch's own CPU work at the switch to Multi), not Slide
writes, as v1.1's 98.

**Simulator:** `SimulatedSummit.set_timing(cpu_scale, spi_cost)` (opt-in,
`reset()` restores the default, [SIMULATOR.md](SIMULATOR.md)).
`tests/test_mpe_slide_timing.py` plays the rig's `slide_right_note` at the
default rate, with SPI cost, and at 0.5, 0.35 and 0.3, each case checking
first that it reaches the phase it is for (0.3: 5 or more), plus a chord at
the slow rates and the Live capture's queue at three rates. Against v1.1's
`mpe_slide.c` the two Slide tests fail at 0.3 (`0x60` stays 0), as on the
synth.

**Version:** boot screen `MPE3 Ver 126.778`, Settings `MPE3Ver`. The
identity stays 2126.

`tools/patch.py patches/mpe/patch.py --verify`: 40 hooks (35 `bl`, 5
pointers) plus the startup hook, as v1.1, and the blob's branches,
verified; `arm-none-eabi-gcc` 16.2.0: 5,372 of 65,088 bytes of flash, 1,640
bytes of CCM.

| Image | Image bytes | SHA-256 |
|---|---|---|
| `summit-firmware-2.2-build2121+mpe.syx` (v1.2, `MPE3`), Homebrew GCC 16.2.0: flashed, `hw/2026-11-08-mpe-v1.2` | 284,352 | `199f190379852939b2903b155e1644249a80e6e2056be4f220c07047f4a74942` |
| `summit-firmware-2.2-build2121+mpe.syx` (v1.2, `MPE3`), dev image, Arm GNU Toolchain 15.3.rel2 (GCC 15.3.1): 5,416 bytes of flash, 1,640 of CCM; not yet flashed | 284,416 | `28916b05a90e56f8091644031af03b01d1f7e10b0160ac2e6e1017ad8c08ac96` |

## Open questions

- Whether `Zone Off` should show what an MPE patch plays then (Lower 15),
  for example as `Off (L15)`; step 3 shows the setting.
- Components: whether it reads or writes globals `+0x30`–`+0x34`, or
  expects 33 Settings pages.
- Whether a member-channel CC other than 74 (sustain, mod wheel) should do
  anything; step 1 drops them.
- ~~The FPGA's accepted range for `0x000`–`0x002` at ±48.~~ Answered
  (observed 2026-11-07, `hwrig run` `bend_range_48`): C5 bent from −48 to
  +48 semitones plays every step within 0.02 c, no clamp or wrap. Step 2's
  clamp (±43,690) is beyond what a ±48 range reaches.
- Whether a 4 ms per-voice `0x60` refresh is smooth enough when the wheel
  sweeps with 16 voices sounding (stock sends the broadcast every 1 ms;
  `0x61` gets 8 ms). On hardware, Slide and Live's wheel over a chord
  sounded smooth (L1, L6, a few voices); 16 voices sweeping wasn't tried.
- B1: after an MCM zone change the first chord sometimes played one note
  fewer (Hapax, twice; not reproduced on the synth or in the simulator).
- ~~Channel reuse takes over idle voices too (L5, F1).~~ v1.1 takes over
  only sounding or releasing voices ([above](#channel-reuse-v11));
  on the synth not yet.
- Whether the FPGA's real envelope level reaches `0x200` and below at the
  end of a release as `voice_candidates` assumes (the rig's stage 4 shows
  rotation, and so that it does).
- The FPGA queue under Live's densest chords: 122 of 128 in the
  simulator with v1.2 (stock 126); with the synth-like timing 60 (stock
  115). Slide no longer adds to it ([Slide, v1.2](#slide-v12)).
- The synth's real CPU rate: `set_timing(0.3, spi_cost=True)` is
  calibrated on one observation (v1.1's dead Slide). A measurement on the
  unit (for example a debug build that shows `timer_state+0x4A8` at the
  end of `mod_update(1)`) would pin it, and with it the simulator's tick
  timing (envelope reads, the queue, B1).
- Slide + wheel as a sum: whether players prefer the larger of the two.
- Whether the master range should also apply to unbound voices in Single
  mode (they bend by `BendRange`, as stock).
- ~~The boot label still reads `MPE1`.~~ v1.1 reads `MPE2`, v1.2 `MPE3`.
- ~~Slide dead on v1.1.~~ The tick-phase guard; v1.2 writes Slide
  directly ([Slide, v1.2](#slide-v12)); on the synth not yet.
- Single mode with two zones: give each zone its own master bend, pressure
  and wheel (step 4, above), if a Hapax setup needs it.
- Whether Peak firmware writes `0x1A2`.
- Whether Live and the Hapax send RPN 6 for both zones (decides how often
  the two-zone split above applies).
