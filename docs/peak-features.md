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
3. **Blank-settings-chip guard** (S). `settings_load` trusts the stored
   indices (port plan 2b item 4). First check: the simulator with a blank
   DataFlash.
4. **Combined definition, shared hooks and the golden baseline** (M).
   Restructure into the one definition described above, MPE first, with
   the dispatch hooks and the resource report. Done when the MPE image built
   this way passes the full rig run, as today's does. That image and its
   recorded MIDI/audio results become the known-good baseline every later
   feature is compared against, including the first timing-budget numbers.
5. **Front-panel panic and editor/MIDI baseline** (S). A button combination
   that runs stock's CC 120 handling and also clears our MPE note ownership
   and anything our features have queued (arp, strum). Plus a recorded
   baseline of the Novation editor's traffic (Components) and of MIDI out
   for a fixed set of actions, kept as a regression check.

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
8. **New per-voice mod values, proof first** (M). Feeding values into the
   matrix is proven: the MPE patch writes each voice's pressure into the
   slots the matrix reads (`voice_state` +0x44, observed on hardware). First
   prove the sound: put a random-per-note value through an existing source
   and hear it on a per-voice destination. Only then work out how source IDs
   are stored and listed, to add release velocity, random per note and voice
   index as real choices in the matrix.

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

### 4. Editing

12. **Quick-assign modulation** (M). Hold **Mod**, move a knob, pick the
    source with the encoder: the routing goes into the first free slot. Each
    knob needs mapping to its mod destination (only some have one). Also:
    skip empty slots when paging. First check: whether the panel scan
    reports a held menu button while a knob moves (`panel_button_event`
    `0x08016FF0`, button table `0x20000AB8`, observed).
13. **Snapshot system, then undo** (M). One level of undo. One knob gesture
    (a continuous turn) is one undo step, and a section paste is one step.
14. **Parameter lock** (M). Keep chosen parameters (FX, arp, performance
    settings) across patch changes.
15. **Section copy and paste** (M). LFO 1 → LFO 2, Env 2 → Env 3, and so on.
16. **Diagnostics and MIDI monitor page** (S–M). DIN overflow count, the MPE
    zone in effect, the last incoming messages.

### 5. Playing

17. **Euclidean arp rhythms and ratchets** (M). Pulses in steps (5 in 8)
    alongside the 33 stock rhythms. First check for ratchets: whether a
    retriggered note reuses or takes a new voice under Poly, Poly2 and MPE,
    which changes how a ratchet sounds. Needs the allocation generation
    counter (engineering rules).
18. **Tail-aware voice stealing** (M, an experiment). Prefer an idle voice,
    then one in release, then the least disruptive. First check: what stock
    does (the search at `0x08011B70` keeps the largest age counter, inferred
    oldest-voice), measured on the rig. Kept only if it measurably helps.
19. **Per-note glide in MPE** (M). Scope still open. With channel rotation
    (the LinnStrument's default) a member channel's previous note is
    unrelated to its next one, so seeding glide per channel would glide from
    a random earlier note, and the LinnStrument already slides by per-note
    bend. The useful case is likely a mono or legato lead played in MPE.
    First check: decide the musical use with the LinnStrument before
    building.
20. **Strum** (S–M as an arp/Chord mode; M–L for incoming MIDI). MIDI sends
    a chord as separate notes, so strumming live input needs a short
    chord-detection window and care with note-offs, sustain and expression
    arriving during the delay. Prototype it as an arp Chord-mode option
    first. Needs the allocation generation counter.

### 6. Large features

Only after step 6 has measured the sound-chip write budget, and kept out of
the earlier modules so their needs don't shape them.

21. **Motion recording** (L). Record one knob's movement for 1–4 bars at a
    clock subdivision and loop it, with overdub or replace. Prototype in RAM
    with one lane of 16 steps.
22. **Patch morph** (L). Blend selected parameter groups (cutoff,
    resonance, mix, wavetable position, FX levels) between two snapshots,
    from the mod wheel or pressure; discrete settings switch at an
    endpoint. Interpolate times and frequencies in a perceptual scale.

### Later

Adaptive just intonation (per-voice pitch path, fixed root first), chord
memory, scale quantise, patch randomiser by section, patch change timed to
the bar, opt-in patch dump on program change (USB only), per-port MIDI
filters, a stuck-note watchdog that looks for inconsistent state rather than
note age (2.2 fixed the hanging-note bug, and our 400-run soak found none).

**Plug-in communication:** too vague to plan. The baseline in step 5 is the
first look; enhancements only if it shows gaps.

**MTS real-time retuning:** check the SysEx handler (`0x0800D040`) for
real-time single-note tuning before planning anything; stock may already
have it.

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
| Event prioritisation | Not until measured: the soak handled 900 messages/s with no stuck note; measure note latency under load first |
