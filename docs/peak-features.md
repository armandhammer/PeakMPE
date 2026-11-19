# Peak features beyond MPE: plan

Firmware features for the Peak 2.2 (build 2108) beyond the MPE patch, in the
order we intend to build them. Nothing here is implemented yet.

The ideas came from three places: the stock-bug and improvement list in
[peak-port-plan.md](peak-port-plan.md) section 2b, a short public description
of another person's private Peak firmware (MIDI loop prevention, better
pickup with OLED feedback, plug-in communication, envelope times in ms,
filter in Hz), and two rounds of outside review. Every idea was then checked
against the stock firmware's documentation:

- Novation's current Peak user guide (v5.0, "applicable to Peak synthesisers
  with the latest firmware"):
  [Novation Peak in detail](https://userguides.novationmusic.com/hc/en-gb/articles/25494693870354-Novation-Peak-in-detail),
  [Peak hardware overview](https://userguides.novationmusic.com/hc/en-gb/articles/25494651161362-Peak-hardware-overview),
  [Peak appendix](https://userguides.novationmusic.com/hc/en-gb/articles/25494651392146-Peak-appendix)
  (mod sources and destinations, MIDI parameter list).
- The [2.2 release notes](https://keyboardchronicles.com/2023/08/13/novation-peak-and-summit-2-2-firmware-release-notes/).

"Guide" below means that user guide; "2.2 notes" means the release notes.
Build 2108 is what Components installed on 2026-11-12, so the guide most
likely describes it, but the guide is a feature reference, not proof of any
internal detail: anything a feature depends on is confirmed in the image or
on the synth first. Firmware findings carry the usual labels (observed /
emulated / inferred).

## What the stock 2.2 firmware already does

Checked so that we don't rebuild it. Source in brackets.

| Area | Stock behaviour |
|---|---|
| Screen | 4 rows × 20 characters OLED (guide). Turning a knob shows the parameter value and the patch's saved value for `Msg Time`, up to about 3 s (guide) |
| Pickup | `Pickup` On/Off: a knob changes nothing until it passes the saved value (guide). The screen text is `pickup` / `current` / `saved val` on row 3 (strings at `0x08045DA0`, observed) |
| Compare | **Compare** button: hold to hear the unmodified patch (hardware overview) |
| Value entry | Value +/- buttons step one value at a time (hardware overview). No Shift button on the panel |
| MIDI CC | `CC/NRPN`: Disabled, Receive, Transmit, Rec+Tran (guide; strings observed). `Local` Off still transmits the knobs (guide); since 2.2 Local is saved and settable by CC 122 (2.2 notes). CC pairs honour the LSB since 2.2 (2.2 notes). Whether received CCs are sent back out is **not documented** |
| Panic | Responds to CC 120 (all sound off) and CC 123 (all notes off) since 2.2 (2.2 notes) |
| Voices | Poly, Poly2 (a repeated note reuses its voice), Mono, MonoLG, Mono2 (voice rotation) (guide). Poly glide starts from the new voice's last pitch, which the guide calls unpredictable with chords |
| Pressure | `AftTouch` source takes channel or polyphonic aftertouch, poly per note (guide) |
| Detune | `Diverge` (fixed per-oscillator offsets), `Drift` (slow wander), `FltDiverge` (guide) |
| Envelopes | DAHDSR with `Repeats` looping (guide). The time destinations are in the mod matrix (appendix) |
| Mod matrix | 16 slots, two sources multiplied, plus 4 FX slots (guide). Sources include ModWheel, AftTouch, both pedals, Velocity, Keyboard (note number), LFO 1–4, three envelopes, Animate 1/2, CV, bend wheel, noise (appendix). Animate 1/2 as sources give macro and "FX throw" behaviour without firmware changes |
| Arp | 7 types incl. Chord, 33 rhythms, Key Latch, swing, `ArpChance` (one global probability) (guide) |
| Patches | `PatchCue` (choose, then confirm, the patch change), `Initialise` = Live (guide) |
| Tuning | 16 tuning tables at 1/256 semitone, Scala via Components, "MIDI Tuning Standard (MTS) Messages are also supported" (guide). Which MTS messages is not stated |
| Pedals | Sustain, Sostenuto, Animate 1/2 (guide; strings observed) |

The guide also gives time and rate references that the unit display must
agree with: attack maximum over 18 s, decay about 22 s, release over 24 s;
envelope Delay 85 ≈ 1 s and 127 = 10 s (exponential); Hold 127 = 500 ms;
Glide 90 ≈ 1 s; LFO rate 0–200 Hz (Low) and 0–1.6 kHz (High).

## How features combine into one image

Only one image is on the synth at a time, so the features can't be separate
patch definitions flashed side by side. They go into **one combined
definition**, built from `patches/peak_mpe/` plus one module per feature:

- Each feature is a set of C files with a build-time switch, so it can be
  built alone (on top of MPE) or with everything.
- Where several features need the same function (MIDI dispatch, the screen,
  voice allocation, parameter changes, patch load), there is **one hook**
  that calls each enabled feature's handler in a fixed order. Features never
  hook the same site on their own.
- The builder already refuses two byte patches that overlap and checks every
  hook site's original instruction (`tools/patch.py`, observed), so a clash
  fails the build instead of the last patch winning.
- Each module declares its hooks, RAM and flash, and the build reports the
  totals against the free space.

**Every feature passes before it's kept:** its own rig or simulator test;
the full MPE rig run (136 rows on 2026-11-13) with the feature on, so MPE
doesn't regress; flash and RAM added; note behaviour under the soak load; and
the editor/MIDI baseline (step 5) unchanged unless the feature means to
change it; and the timing budget below within its limits. Each passing image is recorded in the
[hardware log](hardware-log.md), built by `scripts/build-image.sh` as usual.

## Engineering rules

These apply to every module in the combined definition.

- **Only the infrastructure the next two or three features need.** A few
  compact functions (read, change, save and restore a parameter), not an
  event bus or dynamic registration. Refactor when a real need appears.
- **Every parameter change carries its origin:** panel, USB, DIN, internal
  (our features) or editor. The origin is set where the change enters and
  travels with it through the dispatch path, never guessed later by
  comparing values. The MIDI path already knows the source:
  `midi_channel_filter` `0x0800EED0` takes `(src handler msg)` (observed).
  Echo suppression, undo, parameter lock and morph all use it.
- **Delayed events name an allocation, not just a voice.** Each voice
  allocation gets a generation counter. A scheduled event (ratchet, strum,
  delayed retrigger) stores voice and generation and is discarded if the
  voice has since been stolen or released. Panic, patch change, MPE channel
  reuse and sustain release clear the queue. In place before strum and
  ratchets.
- **Times in the patch are counted in modulation ticks, 1000 per second**
  (`mpe_ticks()`). The Peak's TIM6 runs at 10 kHz and requests a tick every
  10th interrupt ([findings](findings/peak-2.2-build2108.md#timers-and-the-1-khz-tick-2026-11-15)).
  Until 2026-11-15 the simulator ran the Peak's timers twice too fast, and
  v0.6 to v0.13 carried tick counts twice too large (EnvSync's holds, the
  undo gesture window). Stock's message countdown is not used for timing.
  From v0.15 one count of it is 22 ms (stock: 11 ms), so `Msg Time` 127
  lasts about 3 s as the guide says, and a message of the patch always sets
  stock's changed flag, without which the page is never redrawn after it.
- **Timing budget, checked for every combined image:**
  - note latency (MIDI in to sound) under combined load: dense MPE
    expression while changing patches, paging the screen and receiving
    external clock. Measured on the rig against the stock image
  - main-loop and modulation-tick time, and sound-chip write rate and
    duration (simulator cycle counts, step 6 on hardware)
  - DIN receive ring and any queue of ours: peak occupancy
  - stack high-water mark (painted stack in the simulator)
  - screen update time. Display and diagnostic work stays out of
    interrupt and timing-critical paths
- **Recovery and persistent settings.** Before a feature image is flashed:
  the stock 2.2/2108 image and the bootloader route in
  [recovery.md](recovery.md) are confirmed; the image is built from the
  official file whose hash is in `firmware/SHA256SUMS` (the builder refuses
  any other file and any hook site whose original bytes differ: fail
  closed); and once, before the first feature image, the patches and
  settings are backed up with the Peak's own Backup page (`ABCD+Set` over
  USB, recorded with `tools/midirec.py`). New preferences start as
  volatile defaults; the stored settings layout changes only when a feature
  is stable, with a version number, and never from automation or a held
  control (no frequent flash writes).
- **Musical acceptance as well as technical.** Each playing or
  sound-design feature states one musical success condition, checked by
  playing and listening, next to its rig test. A feature that passes every
  test and still disappoints in use is not kept. The first ones:

  | Feature | Musical success |
  |---|---|
  | Pressure curve | Light pressure is controllable on the LinnStrument and full pressure still reaches the full range |
  | Pickup feedback | The pickup point is found without jumps or confusing readouts |
  | Quick-assign | A common routing (say Osc 3 → filter) is clearly faster than through the stock matrix |
  | Tempo-synced envelopes | Repeating envelope gestures stay with the music when the tempo changes |
  | Tail-aware stealing | Playing past eight notes interrupts less than stock, by ear |
  | Morph | A slow sweep sounds smooth and intended, not like parameters switching |

## Shared pieces

Built once and used by several features:

- **Temporary-display system.** One owner for the knob-turn overlay on the
  OLED, so value bars, units (ms, Hz), note names and pickup feedback don't
  fight over the 4×20 screen. It sits on `format_value` `0x08017604` and
  `ui_draw_values` `0x08018070` (observed) and the 8 custom-character slots
  (Summit `lcd_load_cgram`; the Peak's pair not yet mapped).
- **Parameter snapshot.** One way to save and restore the patch's
  parameters, used by undo, parameter lock and morph. It covers **patch
  parameters only**. Global settings (MIDI, pickup, tuning) and runtime state
  (pressure, active voices, arp position) are never in a snapshot; locks,
  morph position and motion playback keep their own state. Stock Compare is
  left exactly as it is, and the snapshot code must not touch whatever
  Compare uses until that has been mapped.
- **Measured unit tables.** Value → ms and value → Hz, measured with the
  [test rig](hw-test-rig.md) and stored in flash. They feed the display and
  the tempo-synced envelopes.

## Build order

Effort: **S** a single hook; **M** new state or several subsystems;
**L** timing or patch-management work. Each item names its first check.

The order isn't strictly serial. After step 1 the work splits into two
tracks that can run side by side: **expression** (steps 7–8 and 17–20),
which makes the Peak more expressive than stock, and **workflow** (steps
9–16), which makes it faster to program from the panel or a plain keyboard.
Measurements (step 6) can run on the rig while code is written for others.

### 1. Reliability and groundwork

1. **MIDI echo / loop fix** (S). Rig results, 2026-11-13, on the MPE image
   over USB (observed; `work/echo_test.py`, `note_echo_test.py`,
   `loopback_test.py`): received CC 5 and NRPN 0:4 are **not** sent back
   out, and received notes are not passed through with the arp off. With the
   arp on and `Arp>Midi` On, the Peak sends its arp notes out. Returning
   those notes to the Peak (a DAW routing loop) did not run away: the arp
   went silent within about a second, while the chord was still held, after
   six note messages. The likely cause is that the returned note-offs
   release the held notes (inferred). So the loop to fix is arp notes
   coming back into the arp, not a CC echo. Fix: ignore incoming notes that
   match the arp's own recent output (see the origin rule), then repeat the
   loopback test. Still untested: DIN, and the stock image.
   **Built (v0.2, `patches/peak_mpe/arp_echo.c`):** two bl hooks on the
   arp's MIDI sends (`0x08015202`, `0x08014EE2`) remember each note for
   100 ms (`mod_tick`, 1 kHz); `mpe_channel_filter` drops a matching
   incoming note once. Emulated (`tests/test_peak_arp_echo.py`, DIN looped
   back): stock stops while the chord is held; patched keeps playing C E G
   and stops after release. **On hardware (2026-11-13, image `a7015456…`, observed):** the USB loopback kept the arp playing 16 note messages/s while held and stopped after release; the 13-check MPE rig run gave 136 pass, 0 fail, as v0.1. Not yet tried with a real DAW.
2. ~~**Oscillator pitch clamp**~~ **Dropped (2026-11-13).** The overflow
   is real (`osc_pitch` `0x08010B60` sums in 16 bits, observed), but it
   wraps only beyond ±128 semitones from note 60, about 400 kHz and
   0.16 Hz: an inaudible pitch becomes another inaudible one. The most the
   simulator reached with Range, Coarse, Fine and bend at their maximum was
   +31,318 of 32,767 (emulated). Details in the
   [findings](findings/peak-2.2-build2108.md). MPE voices already clamp
   their own bend.
3. ~~**Blank-settings-chip guard**~~ **Closed without a firmware change
   (2026-11-18).** On the Peak, `settings_load` reads no index from a blank
   chip (the patch loader skips `0xFFFF`), and the patch's stored settings
   already fall back to their defaults at 0xFF; `tests/test_peak_blank.py`
   checks both (emulated). Stock itself doesn't run on an unformatted chip
   (the 0xFF edit buffer turns on the arp, which reads through a null
   pointer); that needs a factory format, which isn't worth carrying in
   the patch. Details in the [findings](findings/peak-2.2-build2108.md).
4. **Combined definition, shared hooks and the golden baseline** (M).
   Restructure into the one definition described above, MPE first, with
   the dispatch hooks and the resource report. Done when the MPE image built
   this way passes the full rig run, as today's does. That image and its
   recorded MIDI/audio results become the known-good baseline every later
   feature is compared against, including the first timing-budget numbers.
   **Struck (the user, 2026-11-18): done in practice.** Every release is
   built from the one definition (`patches/peak_mpe/patch.py`) and passes
   the same `hwrig run --stage all` (136 measured rows) before its
   hands-on series; the hardware log is the baseline.
5. **Front-panel panic and editor/MIDI baseline** (S). A button combination
   that runs stock's CC 120 handling and also clears our MPE note ownership
   and anything our features have queued (arp, strum). Plus a recorded
   baseline of the Novation editor's traffic (Components) and of MIDI out
   for a fixed set of actions, kept as a regression check.
   **Panic built (v0.28, `panic.c`; on the synth 2026-11-19, series T passed):**
   hold **Mod** and press **Audition**. Stock's CC 120, then the held keys,
   the arp's keys and play map (a latched or stuck chord stops), the MPE
   voice bindings and every channel's bend, pressure and slide. Delay and
   reverb tails ring out. Message `PANIC` / `All notes off`. Tests
   `tests/test_peak_panic.py` (with control cases that fail without the
   panic); findings, "All sound off, all notes off and the panic".
   **Editor/MIDI baseline built (2026-11-19; on the synth the same day,
   series U: Components reads the Peak; `editor-2026-11-19_085344` is the first hardware baseline):** the editor protocol read from stock's SysEx parsers
   (findings, "The editor protocol"). `tests/test_peak_editor.py` plays
   fixed sessions into stock and the patch and requires the same bytes
   out: every editor request, a bank dump's start, each write read back,
   and MIDI out for arp notes, CCs, a program change and All Notes Off;
   plus the patch's settings surviving a settings dump and write-back
   (step 7's open question about Components, as far as the protocol
   goes). `tools/editor_check.py` sends the read requests (and one write
   to the edit buffer) to the synth and compares the answers with its
   previous run. Not covered: what Components itself sends (not
   recorded), the Backup page's dump from the panel.

### 2. Expression, first part

6. **Measurements: envelopes, filter, sound-chip writes** (M; rig work).
   - Envelope times: start with about 32 settings per parameter and add
     points where the curve bends fast. Write down the timing definition
     used (thresholds, sustain level). Cross-check against the guide's
     references above.
   - Filter cutoff: self-oscillation at full resonance (if the filter
     self-oscillates; unconfirmed) or noise and a spectrum. The result is a
     calibrated estimate for stated conditions (mode, slope, resonance,
     tracking), not an exact frequency.
   - Sound-chip writes: how long one parameter write takes, whether
     changing an envelope time mid-note changes the sounding note or only the
     next one, and whether fast changes step audibly (zipper noise). This
     sets the budget for tempo sync, motion recording and morph.
   - **Done 2026-11-13 (observed): [peak-units.md](peak-units.md)** has the
     tables and the method. Attack is a linear ramp (127 = 17.9 s); decay and
     release are the same curve, linear in dB (127: 20.6 s to −40 dB); the
     filter self-oscillates and its frequency is the cutoff (CC 29 → Hz table;
     key track 127 = 100 %). Envelope times are read continuously, so a
     change reaches a sounding note (attack and decay; release at note-off).
     Level and cutoff changes show no zipper at 5–10 ms per step. Hold 127
     measures 0.68 s against the guide's 500 ms; env Delay can't be set over
     MIDI and wasn't measured. Sound-chip write *duration* was not measured.
7. **Pressure curve and controller shaping** (M). A linear option next to
   stock's squared aftertouch, plus CC 11 as pressure on member channels.
   Smoothing for CC 74 and bend. Check that poly aftertouch on member
   channels reaches the right voice under MPE.
   **Mapped (2026-11-13, observed in the disassembly, image base
   `0x0800C000`):** the squaring is `mod_update`'s last block. `ubfx r4, r4,
   #12, #16` (`0x08010A6C`) takes x from the smoother (`voice_state+0x54+4v`),
   `mul.w r4, r4, r4` (`0x08010A70`) and `ubfx r4, r4, #15, #16`
   (`0x08010A74`) give x²>>15, then `bl voice_mod_write` (`0x08010A7C`, r0 =
   voice, r1 = 1, r2 = value) and a `part_mod_write` call just after. x tops
   out at `0x7F00` for pressure 127, so squared gives `0x7E00`, linear
   `0x7F00`. Plan: hook both `bl`s to C wrappers that send x instead of x²>>15
   when the setting is Linear (no asm needed, x is recomputed from the
   smoother); `mpe_pressure_voice`'s note-on write uses the same helper. The
   setting is a third item on the Settings MPE page (a new record, display
   type and `edit_setting` case in `mpe_ui.c`, one globals byte). Open
   before building: which globals byte is free on the Peak (`+0x34` is read
   on the Summit), and that Save and Components leave it alone.
   **Built (v0.4, `mpe_pressure.c`, `mpe_ui.c`; rig unchanged, 136/0):** the
   Squared/Linear option. **v0.5 (emulated, `test_peak_sim.py`):** CC 11 on a
   member channel is pressure; poly aftertouch on a member channel reaches
   only its own voice (checked, no change needed). CC 74 and bend are already
   smoothed per voice (1/8 and 1/4 of the step per tick, `mpe_slide.c`,
   `mpe_bend.c`); an adjustable amount is not built. Checked on the synth 2026-11-14: Linear works and persists through Save and a power cycle.
8. **New per-voice mod values, proof first** (M). Feeding values into the
   matrix is proven: the MPE patch writes each voice's pressure into the
   slots the matrix reads (`voice_state` +0x44, observed on hardware). First
   prove the sound: put a random-per-note value through an existing source
   and hear it on a per-voice destination. Only then work out how source IDs
   are stored and listed, to add release velocity, random per note and voice
   index as real choices in the matrix.
   **Release velocity done (v0.24, `relvel.c`; on the synth 2026-11-18):** no new source ID. Settings `RELEASE VEL` > `Source` lends one
   of the two pedal sources (`ExprPED1`, `BrthPED2`, parameters 0x62/0x63):
   its per-tick broadcast is dropped and each note-off writes its velocity
   into that source of the voices it releases, just before their release
   command. Route the source to `AmpEnv R`; the chip reads the release time
   at note-off (step 6), so each note gets its own. Rig (observed): t20
   grows from 0.12 s at note-off velocity 1 to about 3.8 s at 127, with no
   carry-over; the LinnStrument sends release velocity. Random per
   note and voice index could lend a source the same way; not built.
   **The rest is optional, for later (the user, 2026-11-18):** random
   per note and voice index stay possible (no controller can send them
   per voice) but are not planned.

### 3. Screen

9. **Display system: value bars, units, note names** (M). Bipolar parameters
   are drawn from the centre. Note names go on the split point, transpose and
   fixed note. Units appear once step 6 has measured them.
   **Built (v0.3, `patches/peak_mpe/disp.c`, emulated; not yet on the synth):**
   the knob-turn overlay (`knob_overlay` `0x08016B14`, mapped in the
   [findings](findings/peak-2.2-build2108.md)) now shows attack, decay, release
   and Hold in ms/s (Amp, Mod Env 1 and 2; the mod envelopes use the amp
   curves, inferred) and the filter cutoff in Hz, from the measured tables in
   [peak-units.md](peak-units.md) (generated into `disp_tables.h` by
   `gen_disp_tables.py`), with a 20-cell value bar on row 3 (5 pixels per
   cell, bipolar types drawn from the centre). Settings below the measuring
   chain's resolution read `<35ms` (attack), `<61ms` (decay), `<10ms`
   (release) and `<33Hz` (cutoff below CC 12). The bars use custom characters 1-7, loaded when
   an overlay first draws and put back (`lcd_load_cgram`) when its message
   time ends. **Not done:** envelope Delay (not measured; its parameter is
   not nameable), values on the menu pages (only the knob overlay changed),
   and note names: stock already prints `FixedNote` and `SplitPoint` as note
   names (display types 0x40/0x41) and Transpose is a Settings page number,
   not a knob, so there was nothing to add to the overlay.
   **Cost, v0.23 (`lcdcache.c`, emulated):** series M7 measured about half
   the 1 kHz modulation ticks lost while a knob turned (observed). Stock
   rewrites the whole overlay on every knob event (37 writes, about 1.9 ms
   of busy-waited bus time) and v0.22's bar doubled it; with the LCD cache
   only changed characters are sent (about 4 per event, 0.2 ms), and the
   bar's characters load one per main-loop pass. On the synth (series O4,
   2026-11-17): 17 ticks lost over a knob turn against 2,645 on v0.21.
   Findings, "The patch's LCD cache".
10. **Pickup feedback** (M). Show which way to turn and how far, as an arrow
    and a bar closing on the saved value, in place of stock's numbers.
    **Built (v0.3, `disp.c`; checked on the synth by the user, 2026-11-13):**
    while Pickup holds a knob back, the bottom line is the value bar of the
    knob's position with an arrow (`>` or `<`) at the end of the filled part,
    pointing the way to the patch's value. The arrow moves with the knob and
    is gone once the value is reached, when the line becomes the plain bar.
    The "current" line follows the knob while it is held back (stock showed
    the patch's value there); stock's `pickup` label is dropped. The target
    is the patch's value, not the compare buffer's `saved val`. Musical
    success (the pickup point is found without jumps or confusing readouts)
    was judged "much better" after the arrow moved onto the bar.
11. **Tempo-synced envelope times** (M). With the ms tables, choose the value
    nearest to a note length at the current tempo (1/8 at 120 BPM = 250 ms).
    Whether "from the next note" is even possible depends on step 6: if the
    sound chip reads envelope times continuously rather than latching them
    at note-on, a new value also reaches sounding notes. In that case the
    first version recalculates only on deliberate tempo changes (no
    per-voice workaround). External tempo is smoothed so clock jitter
    doesn't cause constant updates; if the clock stops, the last tempo holds
    (as stock's flywheel does). With `Repeats` this gives rhythmic looping
    envelopes. It syncs durations, not phase, and a matching duration won't
    always feel on the beat.
    **Built (v0.6, `patches/peak_mpe/envsync.c`; emulated, not yet on the synth):**
    Settings > MPE EXTRAS > EnvSync (Off, 1/2, 1/4, 1/8, 1/16; v0.7: a changed choice applies only after it has held about 1 s, because v0.6 applied the choices you scrolled past; **measured on the synth 2026-11-14:** 1/8 gives Decay 264 ms and Release 272 ms at 120 BPM, about 514/533 ms at 60). While on, the amp
    Decay and Release go to the value whose measured time to -40 dB is nearest the
    note length at the current tempo, when the tempo or the setting changes (a
    tempo must hold 4 checks of 128 ms and move by 1 BPM). Amp envelope only; the
    mod envelopes, Attack and Hold are not synced. Tempo is stock's own word at
    `0x20000264` (1,717,984 per BPM; internal and external clock both), values go
    in through the setter behind a received CC (`0x0800F6AC`), so the patch, the
    FPGA update and pickup follow as for a CC. Tests: `test_peak_sim.py`
    (`test_envsync_*`: 1/8 at 120 BPM picks about 250 ms, at 240 BPM about
    125 ms; Off changes nothing).

### 4. Editing

12. **Quick-assign modulation** (M). Hold **Mod**, move a knob, pick the
    source with the encoder: the routing goes into the first free slot. Each
    knob needs mapping to its mod destination (only some have one). Also:
    skip empty slots when paging. First check: whether the panel scan
    reports a held menu button while a knob moves (`panel_button_event`
    `0x08016FF0`, button table `0x20000AB8`, observed).
    **Built (v0.8, `patches/peak_mpe/qassign.c`; emulated, not yet on the
    synth):** hold **Mod** (panel button 7, `button_table` entry 7: type 3,
    mode 5, observed in the table; the event read at `0x08016FF4` is hooked and
    gives press/release), turn the value encoder or press the value buttons to
    choose the source (default Lfo1+, shown on the OLED for the message time),
    then move a slider or knob: its destination goes into the first free slot
    (both sources Direct, depth 0) at depth +32. The same control again does
    nothing; a control with no destination says so. Control-to-destination
    table: names matched to the matrix's destination list (checked
    2026-11-15: for all 47 entries the control's own name in
    `patch_param_desc` and the destination's name in the matrix list
    `0x080464E0` agree, e.g. `O1Shape` → `Osc1Shpe`; the firmware has no
    table of its own from control to destination, searched for in
    destination order at five record sizes; mod
    destinations without a control are left out). Values go in through the CC
    setter with the slot's NRPN number (emulated: slots updated). **On the synth
    (v0.9, 2026-11-14, user):** assign, slot choice, the Mod menu entry and the
    filter following LFO 1 all worked; stock's knob overlay flickered behind the
    message and the moved control still changed, so from v0.10 (`MPEA`) a control
    moved with Mod held draws nothing of stock's and is not applied. Not built:
    skipping empty slots when paging.

13. **Snapshot system, then undo** (M). One level of undo. One knob gesture
    (a continuous turn) is one undo step, and a section paste is one step.
    **Built (v0.12, `patches/peak_mpe/section.c`; emulated, not yet on the
    synth):** one level, no separate snapshot system. The parameters (0x1A2
    bytes) are saved before a section paste, a quick-assign and the first move
    of a control after about 2 s of stillness (one gesture is one step; a
    different control starts a new one); **Mod + Page left** undoes, **Mod + Page
    right** redoes, written back through the CC setter for the parameters that
    differ. Not recorded: value-button and encoder edits, and parameters
    without a CC/NRPN number. A patch load clears it.

14. **Parameter lock** (M). Keep chosen parameters (FX, arp, performance
    settings) across patch changes.
    **Built (v0.11, `patches/peak_mpe/paramlock.c`; emulated, not yet on the
    synth):** Settings > PARAM LOCK has Lock FX, Lock Arp and Lock Voice (Off/On,
    saved with the Settings). A locked group keeps its current values when a
    patch loads: the load is one function (`0x0801AEB8`, traced in the
    simulator), and its copy into the patch (`0x0801AECC`, the byte loop at
    `0x0801D736`) is hooked to save the locked ranges and write them back
    before the push to the sound chip. Ranges (mine, from the parameter table):
    FX `0xC7-0xEC`, Arp `0xED-0xFA` (includes the tempo), Voice `0x22-0x2F`
    (v0.11-v0.25 had `0xEC`, the chorus Mode, in Arp; fixed in v0.26)
    (mode, unison, glide, diverge, drift, noise filters). Initialise and
    Compare loads are covered too (any load into the current patch); the first
    load after power-up is not. The mod matrix and per-patch MPE flag are not in
    a group.

15. **Section copy and paste** (M). LFO 1 → LFO 2, Env 2 → Env 3, and so on.
    **Built (v0.12, `section.c`; emulated, not yet on the synth):** Settings >
    COPY SECTION: "Section" picks one of 14 copies (Osc 1>2, 1>3, 2>1, 2>3, 3>1,
    3>2; Amp>E1, E1>Amp, Amp>E2, E2>Amp, E1>E2, E2>E1; LFO 1>2, 2>1), "Do it" set to
    Yes performs it. Blocks (patch offsets): oscillators `0x30/0x45/0x5A` (19
    bytes), envelopes `0x92/0x9B/0xA3` (8 bytes), LFOs `0xAC/0xBA` (12 bytes).
    Parameters without a CC or NRPN number are skipped. Setter ids come from
    the descriptors (msb 252-254 CC, 255 none, else NRPN).

16. **Diagnostics and MIDI monitor page** (S–M). DIN overflow count, the MPE
    zone in effect, the last incoming messages.
    **Built (v0.12, `patches/peak_mpe/diag.c`; emulated, not yet on the synth):**
    Settings > MIDI MONITOR (read-only): the last channel message in hex, the
    message count since power-up, and the DIN overflow counter (a byte at
    `0x20003EAC+0x204`, address from the earlier DIN tests; **one byte,
    observed 2026-11-15** in the USART6 interrupt's `ldrb`/`strb`, so it
    wraps after 255). The MPE zone in effect is on the Settings MPE page already.

### 5. Playing

17. **Euclidean arp rhythms and ratchets** (M). Pulses in steps (5 in 8)
    alongside the 33 stock rhythms. First check for ratchets: whether a
    retriggered note reuses or takes a new voice under Poly, Poly2 and MPE,
    which changes how a ratchet sounds. Needs the allocation generation
    counter (engineering rules).
    **Euclidean rhythms built 2026-11-16 (v0.20, emulated, not on the
    synth):** Settings > ARP EUCLID with `Pulses` (Off, 1-32), `Steps`
    (1-32) and `Rotate`. With Pulses on, the arp plays that many notes
    spread evenly over the steps in place of the patch's Rhythm; SyncRate,
    Type, Octaves, Gate, Swing and Latch stay stock's. Stock's rhythms are
    lists of note and rest lengths
    ([findings, "Arp rhythm patterns"](findings/peak-2.2-build2108.md#arp-rhythm-patterns-2026-11-16)),
    so the patch builds such a list in RAM and points the arp at it
    (`euclid.c`, one hook on the call of `arp_tick`; tests
    `tests/test_peak_euclid.py`). The setting is global, like Lock Arp,
    not per patch: a patch's Rhythm byte above 32 would index past stock's
    table on a Peak without the patch.
    **Ratchets built 2026-11-16 (v0.21, emulated, not on the synth):**
    Settings > ARP RATCHET with `Ratchet` (Off, x2, x3: a note sounds two
    or three times within its step) and `Every` (1 to 8: every note, every
    second one, and so on). The voice check came first: in the poly modes
    each repeat takes the next voice, in Mono and MonoLG it retriggers the
    one voice (emulated). A repeat is an extra note event in the generated
    pattern, marked so that a second hook (on the arp's choice of the next
    note) makes stock choose the same note again; it works with all eight
    Types. With `Pulses` Off the ratchet plays over one note per step, not
    over the patch's Rhythm (stock's own patterns are not rewritten). Not
    built: a chance for the ratchet, and x4 (a step is six arp clocks, so
    four equal parts do not fit).
18. **Tail-aware voice stealing** (M, an experiment). Prefer an idle voice,
    then one in release, then the least disruptive. First check: what stock
    does (the search at `0x08011B70` keeps the largest age counter, inferred
    oldest-voice), measured on the rig. Kept only if it measurably helps.
    **Traced 2026-11-15: stock already does this.** The allocator reads each
    voice's envelope state and level from the sound chip on every note-on and
    takes the quietest voice in its release first, then the quietest held
    voice, then the newest still in its attack (code observed; the chip's
    replies inferred; emulated in `tests/test_peak_voice_steal.py`). The search
    is not by age. Details and what a patch could still add (oldest on a tie,
    pedal-held notes before key-held, keep the lowest note) are in the
    [findings](findings/peak-2.2-build2108.md#voice-allocation-and-stealing-2026-11-15).
    **Confirmed on the synth 2026-11-15 (observed, `work/steal_check.py`):**
    with eight notes held and one let go, a 9th takes the releasing voice
    and no held note is cut; with all held, the voice after the last pick
    goes (rotation, not age); with all eight still in a slow attack, the
    newest goes. Step closed: nothing to build for "tail-aware".
19. **Per-note glide in MPE** (M). Scope still open. With channel rotation
    (the LinnStrument's default) a member channel's previous note is
    unrelated to its next one, so seeding glide per channel would glide from
    a random earlier note, and the LinnStrument already slides by per-note
    bend. The useful case is likely a mono or legato lead played in MPE.
    First check: decide the musical use with the LinnStrument before
    building.
    **Traced and built 2026-11-15 (emulated, not yet on the synth):** stock
    keeps one glide pitch per voice and never resets it, so in Poly (and in
    MPE, where each note gets its own voice) a note glides from whatever its
    voice played last, the guide's "unpredictable"; after power-on from
    middle C ([findings, "Glide"](findings/peak-2.2-build2108.md#glide-2026-11-15)).
    Settings > MPE EXTRAS > **Glide** chooses where a poly glide starts:
    `Stock`; `LastNote`, from where the previous note's pitch is now,
    whichever voice or member channel played it; `Legato`, the same but only
    while another note is held, a detached note starting on pitch (what
    MonoLG does with its one voice, here with a voice per note, so per-note
    bend, Slide and pressure keep working). It only moves the start: the
    patch's Glide On and Glide Time decide whether and how fast, PreGlide
    still wins when it is not 0, and the mono modes are untouched. The
    start is the previous note's unbent pitch (a per-note bend is added
    after the glide). Code: `mpe_voice.c` (`glide_start`, in the existing
    hook on `voice_alloc`'s `voice_glide` call); tests
    `tests/test_peak_glide.py`. **On the synth, v0.14, 2026-11-15
    (observed, `work/glide_check.py`):** all three settings start a glide
    where designed (table in the findings), and by ear on the LinnStrument both Legato and
    LastNote "work as expected" (user): they are two different functions, not
    alternatives, and both stay. Musical success as stated before the build: a legato
    line on the LinnStrument glides note to note as a mono lead would, and
    chords no longer swoop in from unrelated pitches.
20. ~~**Strum**~~ **Dropped (2026-11-17, the user):** strumming is the MIDI
    controller's job, not the synth's. The plan as it stood:
    (S–M as an arp/Chord mode; M–L for incoming MIDI). MIDI sends
    a chord as separate notes, so strumming live input needs a short
    chord-detection window and care with note-offs, sustain and expression
    arriving during the delay. Prototype it as an arp Chord-mode option
    first. Needs the allocation generation counter.

### 6. Large features

Only after step 6 has measured the sound-chip write budget, and kept out of
the earlier modules so their needs don't shape them.

**Design note, 2026-11-15:** [peak-motion-morph.md](peak-motion-morph.md)
has the findings both need (parameters are applied in 13 update groups, at
most once per 16 ms; what each group costs) and a proposal for each. Nothing
built.

21. **Motion recording** (L). Record one knob's movement for 1–4 bars at a
    clock subdivision and loop it, with overdub or replace. Prototype in RAM
    with one lane of 16 steps.
    **Built (`patches/peak_mpe/motion.c`; on the synth as v0.17,
    2026-11-16: recording, looping, replacing and stopping work by hand and
    ear, hardware log):** one lane of 32 steps. Hold **Mod** and press **Animate 1**
    (the screen says `Move a control`), then move a slider or knob: from that
    move its values are recorded for one loop and then played back, as a
    ramp from each step's value to the next, until Mod + Animate 1 is pressed
    again, which puts the control back
    to its value from before. Moving the control while it plays replaces the
    steps that pass meanwhile. Settings > MOTION has `Length` (1, 2 or 4
    bars: a step is a 1/32, 1/16 or 1/8 note), the recorder's state, and
    `LateTicks`, a count of modulation ticks the main loop lost and the
    longest stall in ms, read when the page is drawn (the measure
    of how much parameter traffic the synth has room for, needed before the
    morph). Time is stock's own tempo clock, internal or external; the loop's
    "one" is the move that started the recording. Not stored with the patch;
    a patch load clears it. Controls without a CC or NRPN number are not
    taken. Not built: more than one lane. Tests:
    `tests/test_peak_motion.py`.
22. **Patch morph** (L). Blend selected parameter groups (cutoff,
    resonance, mix, wavetable position, FX levels) between two snapshots,
    from the mod wheel or pressure; discrete settings switch at an
    endpoint. Interpolate times and frequencies in a perceptual scale.
    **Built (v0.18, `patches/peak_mpe/morph.c`; on the synth 2026-11-16:
    the blend measured equal to the directly set value, a 10 s sweep of 24
    controls cost about 3 modulation ticks; hardware log):** Settings > MORPH > `Morph` = `ModWheel`. The mod wheel (CC 1
    on the zone's master channel with MPE on, on the synth's channel
    without) blends the patch as you have edited it (wheel at 0) towards
    the patch as it is stored (wheel at 127): load a patch, turn some
    knobs, and the wheel takes the changes out and brings them back. No
    second snapshot and nothing new to store. 126 continuous controls
    move (levels, amounts, times, rates, the filter, FX amounts, the
    depths of the mod matrix); switches, waves, ranges, sync settings and
    the arp stay as edited, so nothing switches halfway. A matrix slot
    routed by hand fades to zero depth. A knob turned with the wheel up
    still sets the edited value, and what sounds and shows is its blend.
    Values are written through stock's setter, 16 per 16 ms at most; a
    wheel jump becomes a ramp of about 130 ms. The page also shows the
    `Position` in effect and `Differ`, the number of controls that differ.
    Save stores what sounds. Not built: pressure or a pedal as the source,
    a second snapshot. Tests: `tests/test_peak_morph.py`.

### Later

Adaptive just intonation (per-voice pitch path, fixed root first), random
per note and voice index as lent sources (step 8), patch change timed to
the bar, per-port MIDI filters, a stuck-note watchdog that looks for inconsistent state rather than
note age (2.2 fixed the hanging-note bug, and our 400-run soak found none).

**Patch dump on patch change:** **built (v0.30, `pdump.c`; emulated, not
yet on the synth).** Settings PATCH DUMP > Send (Off, USB): after a
stored patch loads (program change, the patch buttons, a cued patch) the
Peak sends it over USB as the editor's current-patch answer (00).
Compare, Initialise and patches received by SysEx send nothing, nor
does the power-up load. Tests `tests/test_peak_pdump.py`; rig check
`tools/editor_check.py --pdump`; findings, "Patch selection and the
patch dump".

**Plug-in communication:** too vague to plan. The baseline in step 5 is the
first look; enhancements only if it shows gaps.

**MTS real-time retuning:** check the SysEx handler (`0x0800D040`) for
real-time single-note tuning before planning anything; stock may already
have it. **Checked 2026-11-16: it does** (code observed, emulated on the
stock image; [findings](findings/peak-2.2-build2108.md#midi-tuning-standard-in-stock-2026-11-16)).
`F0 7F 00 08 02 tt 01 kk xx yy zz F7` retunes one note of tuning table
`tt` (0 to 16), sounding voices included, and the bulk dump (`7E 00 08
00/01`) is there too. `0x0800D040` itself is a factory-test handler. Two
limits a patch could lift: the device ID has to be `00` (not `7F`), and a
message carries one note.
**Both lifted (v0.25, `mts.c`; on the synth 2026-11-18, every rig row
within 0.2 cents of its target):** a second
parser runs after stock's on every SysEx byte (hook on `sysex_rx_byte`'s
call of the single-note parser, `0x0801AE42`) and takes the single-note
change with device ID `7F` or `00` and any number of notes, and the bulk
dump with device ID `7F`; the one case stock handles (device `00`, one
note) stays stock's. As stock, a message is applied at its `F7` at its
exact length, through stock's `tuning_note_set`, so sounding notes on the
patch's table move at once. Tests `tests/test_peak_mts.py`; rig check
`work/mts_check.py`. Not taken: the bank forms (sub-ID `07`), the
scale/octave forms (`08 08`, `08 09`), the dump request to `7F`.

**Patch randomiser by section:** the guide has no randomise function.
**Built (v0.26, `rand.c`; on the synth 2026-11-18, series R; v0.27 band-pass and high-pass ranges on the synth 2026-11-18, series S):** Settings >
RANDOMISE has Section (Osc 1-3, Mixer, Filter, Amp Env, Mod Env1/2, LFO
1/2, FX, All), Amount (10-100 %, 50 % until changed) and Roll. A roll gives
each continuous control of the section a fresh value inside a safe range
and moves it there by Amount; a switch is picked afresh with a chance of
Amount. Then the section's checks (mixer level and headroom, filter open
for its shape, an amp envelope that sounds, FX headroom) are enforced: at
100 % always, below only when the patch passed them before the roll.
Values go in through stock's setter, as section copy; the roll is one
undo step. Ranges and checks are in `rand.c`'s header; tests
`tests/test_peak_rand.py`; rig check of the rules `work/rand_check.py`.
Not touched: pitch modulation depths, the mod matrix, the arp, the voice
settings, VCA Gain and Patch Level. On the rig, 150 rolls of the rules:
none silent or clipped; band-pass rolls about 12 dB quieter than the
other shapes (hardware log, v0.26). A sweep on the rig showed why: the
band-pass range sat above the note and resonance lifts band-pass most
(findings, "Value scales for the randomiser"). v0.27 rolls band-pass
at cutoff 64-150 with resonance 40-96, and high-pass at most 110:
band-pass rolls came out about 6 dB louder on the rig (median -31.1 dB
against low-pass -24.9; hardware log, v0.27).

## Dropped

| Idea | Why |
|---|---|
| Voice monitor | The front panel has 8 Active Voice LEDs |
| Analog drift | Stock `Drift` and `Diverge` |
| Separate CC send/receive | Stock `CC/NRPN` setting |
| Global arp probability | Stock `ArpChance` |
| A/B compare | Stock Compare button |
| Note number as a mod source | Stock `Keyboard` source |
| Performance macros, FX throws | Mod matrix and FX matrix with Animate 1/2 or ModWheel as sources |
| Fine-edit modifier | Value +/- step by one |
| Slew for incoming MIDI automation | 2.2 honours CC-pair LSBs; low value |
| Sustain and sostenuto changes | Stock pedal modes |
| Strum (step 20) | The MIDI controller's job, not the synth's (the user, 2026-11-17) |
| Chord memory | The MIDI controller's job, as strum (the user, 2026-11-18) |
| Scale quantise | The MIDI controller's job, as strum (the user, 2026-11-18) |
| Event prioritisation | Not until measured: the soak handled 900 messages/s with no stuck note; measure note latency under load first |
