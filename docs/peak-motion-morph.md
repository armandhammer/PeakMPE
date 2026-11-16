# Peak: motion recording and patch morph (design note)

Plan steps 21 and 22 of [peak-features.md](peak-features.md). Nothing here
is built. Written 2026-11-15 from the decompile and one simulator probe
(`work/_d_param_cost.py`, stock image); the usual labels apply (observed /
emulated / inferred).

## What was found

### How a parameter change reaches the sound chip

- **The setter.** `param_set_by_id` `0x0800F6AC` `(value, id)` checks the
  range against the descriptor, and `FUN_0800F658` writes the patch byte and
  ORs the parameter's **update-group mask** into a dirty word at
  `0x200043E8` (observed). The masks are a table of one u16 per patch
  offset at flash `0x08020484` (observed).
- **The apply.** `FUN_08013014`, called on every main-loop pass, does
  nothing until the millisecond counter has advanced by 16 since its last
  run; then, if the dirty word is nonzero, `FUN_08012F68` clears it and
  calls one handler per set bit (observed). So **a changed parameter
  reaches the chip within 16 ms, and changes faster than that are merged**:
  about 62 updates per second at most, for any parameter, from the panel
  or MIDI. (Emulated: a change waits 2 to 14 ms; 100 Filter Frequency
  steps 2 ms apart are sent as about 13 group updates and no modulation
  tick is lost.)
- **The groups** (bit, handler, members; observed in the table):

  | Bit | Handler | Parameters | Writes per update (emulated) |
  |---|---|---|---|
  | `0x0001` | `0x08016AC8` | oscillator `Wave`, a few unnamed switches | 2 idle; **about 1,290 with 8 voices sounding** (a wavetable load, target `0x1D`) |
  | `0x0002` | `0x08010348` | mod matrix slots (16 × source A, B, depth, destination) | 21 |
  | `0x0004` | `0x080103EC` | the fixed mod amounts (ME2/LFO2 to pitch, ME1/LFO1 to shape, LFO1/AmpEnv/ME1 to filter, FM amounts) | 16–25 |
  | `0x0008` | `0x0800FE88` | all three envelopes (A D S R, Hold, Repeats, Delay) | 21–29 |
  | `0x0010` | `voice_params_changed` `0x08012D80` | Glide Time, Diverge, Drift, noise filters, oscillator Coarse/Fine/Shape/Vsync/SawDense/FixedNote/BendRange | 8–18 |
  | `0x0020` | `0x08012104` | mixer: oscillator, ring, noise, patch, dry and wet levels | 9–20 |
  | `0x0040` | `0x08012A58` | all FX (distortion, delay, reverb, chorus), arp Mode and ClockRate | 30–39 |
  | `0x0080` | `0x080112D0` | LFO 1–4 | 9–11 |
  | `0x0100` | `0x0800FFD8` | filter: drive, resonance, frequency, Osc 3 amount, FltDiverge | 15–41 |
  | `0x0200` | `0x080100AC` | DenseDet ×3 | 25–27 |
  | `0x0400` | `0x08012A20` | Spread, VCA Gain, Pan, SpreadMode | 25 |
  | `0x0800` | `0x0801203C` | FX matrix (4 slots) | 5–6 |
  | `0x1000` | `0x08012F60` | tuning table | not run |

  Some parameters carry two bits (`FiltSlope`/`FiltShape` `0x0101`,
  `FiltKeyTrack` `0x0104`, `O1Range` and the Glide switch `0x0011`,
  `RevType`/`ChorType` `0x0041`). 110 patch bytes have no group (names,
  voice Mode, Unison, PreGlide, velocity amounts): they are read when a
  note starts.
- **Cost in context (emulated).** The idle firmware sends about 115 chip
  writes per millisecond with or without notes (the modulation tick's
  per-voice pitch and mod values). One group update is 5 to 40 more, once
  per 16 ms. Updating every continuous group in one 16 ms slot would be
  about 250 writes, 14 % on top. The simulator does not charge time for
  the bus by default, so this is a count, not a duration: how long 250
  writes take on the synth, and whether a modulation tick is delayed, is
  **not measured** (plan step 6 left the write duration open).
- **Already known from the rig** ([peak-units.md](peak-units.md),
  observed): envelope times are read continuously (a change reaches a
  sounding note), and level and cutoff changes show no zipper noise at 5–10
  ms per step. The 16 ms gate explains the second: the chip never sees the
  steps faster than that, and what it does see is smooth.

### Knob moves, for recording

- Every knob or slider move comes through `knob_poll` `0x08016DF4` to
  `knob_overlay` `0x08016B14` `(id, prev, cur, saved, hires)`, which the
  patch already hooks (`disp_knob_overlay`, `disp.c`). `id` is the patch
  offset; `cur` is 0–127, or 0–255 for the 9-bit controls. That hook is
  where undo already captures a gesture (`undo_knob`), so a recorder gets
  its events there with no new hook (observed in our own code).
- Encoder and value-button edits do not pass there (they go through
  `ui_value_change`); they would not be recorded.
- Pickup: a played-back value written through the setter arms pickup for
  that control (`pickup_arm`, called by the setter), as a received CC does.
  With `Pickup` on, the knob then has to cross the played value before it
  takes over again; with it off the knob takes over at once and the value
  jumps.

### Musical time

- The tempo clock is `tempo_clock_step` `0x0800FB80`, in the 1 kHz
  interrupt: a 32-bit accumulator at `0x2000461C+0x2C` gets the tempo word
  (`0x20000264`, 1,717,984 per BPM) added each millisecond, and each
  overflow is one MIDI clock, 24 per quarter note; the overflow count is
  the u16 at `+0x30` (observed). Internal and external tempo both end up
  in the tempo word (EnvSync already reads it).
- So position in the bar, in 1/65536 of a clock, is the u32 at
  `0x20012268` that the same function writes (`count << 16 | accumulator
  >> 16`) (observed). A recorder can read it from the main loop or from
  `mpe_mod_update`; nothing has to be hooked.
- **Not traced:** what resets that count (MIDI Start `0xFA`, the arp's
  `arp_reset` `0x08014FA8` on the first held key, or nothing). A loop that
  should start "on the one" depends on it (below).

## Step 21: motion recording

**Proposal: one lane, 32 steps, one control.**

- **Record.** Hold **Mod** and press **Animate 1** (free while Mod is
  held; to be confirmed against the panel table as quick-assign's Mod
  button was): the next control moved becomes the recorded control. From
  its first move the recorder samples its value at each step boundary into
  32 bytes (9-bit controls keep their top 8 bits), for one pass of the
  loop, then plays.
- **Loop length:** 1 bar by default (32 steps of a 1/32 note: 3 clocks
  each, 96 clocks), 2 or 4 bars from a Settings item. A step at 120 BPM is
  62.5 ms, four of the firmware's 16 ms update slots, so finer steps would
  not be heard as finer.
- **Play.** At each step boundary write the step's value through
  `param_set_by_id`, only if it differs from the last value written.
  Between steps, optionally slide (a Settings item, "Smooth"): one
  intermediate value per 16 ms slot, linear. Smooth is what makes a
  recorded filter sweep sound like the gesture rather than a staircase.
- **Phase.** The loop position is the clock count modulo the loop length,
  so the lane follows the internal tempo and an external clock without a
  transport of its own. Whether it also lines up with the arp's step one
  and a DAW's bar depends on what resets the count (not traced, above); if
  nothing does, the recorder takes the moment recording starts as its
  "one" and keeps an offset.
- **Overdub or replace:** replace only in the first version: moving the
  recorded control during playback writes the moved value into the steps
  passed while it moves. Stop: Mod + Animate 1 again; the control gets its
  pre-recording value back.
- **State:** 32 bytes of steps, the control id, the loop length, a few
  flags: under 48 bytes of RAM. Not stored in the patch in the first
  version (a patch change stops it and clears it, as undo is cleared).
- **Interaction with other features.** Undo: a recording counts as one
  gesture (the value before it is what undo restores). Parameter lock: no
  conflict (locks act on patch load). Quick-assign: uses Mod + control, so
  the recorder needs the second button to tell them apart.
- **Cost:** one group update per step (5–40 writes per 62.5 ms at 120
  BPM), or per 16 ms with Smooth: within what a turning knob already costs.

**Built 2026-11-16 as v0.16 (emulated, `tests/test_peak_motion.py`; not on
the synth).** As proposed, with these points settled or changed:

- Animate 1 is panel button 14 (`button_table` `0x20000AB8`: type 4, action
  6, argument 0; Animate 2 is entry 15, the Hold button entry 12; action 6
  with argument 0 or 1 runs the Animate function and sends CC 114 or 115:
  observed). The press with Mod held and its release are hidden from stock.
- The loop's "one" is the move that starts the recording; the recorder
  keeps its own position by adding up the changes of stock's clock count,
  and restarts the loop if that count jumps (what resets it is still not
  traced).
- Stopping puts the control back to its value from before the recording.
- The recorded control's Pickup is cleared on each of its moves, so the
  hand takes over at once, also with `Pickup` on.
- Settings > MOTION: `Length` 1, 2 or 4 bars (a step of 3, 6 or 12 clocks),
  the state (`Off`, `Armed`, `Rec`, `Play`) and `LateTicks`.
- Not built: storing the lane, a second lane. (Smooth: built after series H, below.)

**First reading on the synth (v0.16, user, 2026-11-16):** with the MOTION
page open and nothing playing, `LateTicks` ran up by about 1,000 a second.
Most likely cause (inferred, not yet separated on the synth): the row showed
the live count, the patch redraws its page whenever a shown value changes,
and drawing the screen keeps the main loop from its modulation ticks, so
each redraw lost ticks, changed the number and caused the next redraw. The
simulator does not show it (it charges no time for the screen: 0 to 1 late
ticks in 2 s). Changed in the source after v0.16, not flashed: the row is a
latched reading, taken only when the page is drawn, and shows `count gap`
(the count and the longest gap between two ticks in ms since the last
reading); and lane playback no longer asks stock for a page redraw on every
step. **If the latched count still grows by hundreds a second between two
looks, the cause is something else and the main loop really is that
short of time**; that reading decides how the morph is built. Either way
it is a finding: screen redraws cost modulation ticks on this synth, so
anything that changes a shown value many times a second (the MIDI MONITOR
page's `Msg count` while playing, a received CC on the page that shows it)
takes time from pitch, pressure and Slide smoothing.

**Series H on the synth (v0.16, user, 2026-11-16):**

- H2: the recorded Frequency sweep (dull to bright in 2 s) loops, but "sounds
  weird, like it's clicking at one end of the animation", which it does not
  when the knob is turned by hand. Read as the loop's start (inferred): the
  recording ends bright and begins dull, and v0.16 wrote each step's value
  in one go, so the cutoff went from fully open to fully closed in a single
  write once per bar, a jump no hand can make. With the MOTION page open the
  count still ran up, by about 800 a second: the same self-made reading as
  H1 (the page was open both times), so it says nothing about the lane's
  own cost.
- H3 (replace part of the loop): "hard to evaluate, something is not right".
  Not enough to name a fault. The step was poorly designed: after the hand
  stops, the lane takes over again within 250 ms, so the replaced part is
  short and sits next to the click. Series I asks for a plainer gesture.
- H4 (stop, cancel): pass.

**Changed after series H (in the source for v0.17):** playback is a ramp. At
each step the value moves from where it is to the step's recorded value and
arrives 20 ms before the step ends, written every 16 ms (stock's own rate
for applying parameter changes). The loop's start is then a fall over about
40 ms (at 120 BPM and 1 bar; 230 ms at 4 bars) instead of a jump, and a sweep has 60 small
changes a second instead of 16 larger ones. This is the "Smooth" of the
proposal, always on (the MOTION page has no free row, and a hand movement
is continuous). `tests/test_peak_motion.py`
`test_the_loop_start_is_a_ramp_not_a_jump`.

**What a redraw costs (2026-11-16, from the code):** the screen is on SPI2
at PCLK1/64, about 469 kHz, busy-waited: about 4.5 ms of main-loop time for
the four rows (findings, "LCD bus speed"; bit rate observed, time inferred).
A page that redraws on every pass therefore leaves room for under 200 ticks
a second, which fits the 800 to 1,000 late ticks a second the user read, and
the 16 redraws a second that v0.16's playback asked for would cost about 70
of 1,000 ticks. Both are gone in the source.

**Series I on the synth (v0.17, user, 2026-11-16; observed):**

| Reading | `LateTicks` | Since the reading before |
|---|---|---|
| I1.1 MOTION page, nothing playing | `79 35` | since power-on |
| I1.2 after 10 s on the next page | `88 6` | **+9**, longest gap 6 ms |
| I3.1 a Frequency lane playing | `1245 10` | +1,157 over all of I2 (messages, the 2 s knob sweep with its overlay, opening Settings: not separated), longest gap 10 ms |
| I3.2 after 10 s on the next page, lane playing | `1254 6` | **+9**, longest gap 6 ms |

- **The row works:** the numbers stand still, and the count no longer feeds
  itself. v0.16's 800 to 1,000 a second were the row's own redraws.
- **Idle, the main loop loses about 9 of 10,000 ticks**, and those are the
  two page draws inside the interval: the longest gap, 6 ms, is one page
  draw, which agrees with the 4.5 ms of bus time read from the code plus
  the formatting.
- **A playing lane costs nothing that this measure can see:** the same +9
  with the lane writing Filter Frequency about 60 times a second (two
  setter calls each, one update group applied per 16 ms). So parameter
  traffic of that size is free, and **the morph's budget is the chip
  writes per group, not the main loop**: a morph that moves a handful of
  groups at stock's 16 ms rate is the same order of traffic. Groups that
  cost over a thousand writes (a waveform change) stay excluded as planned.
- **What does cost ticks is the screen.** The 1,157 lost during I2 were not
  separated; the knob overlay redrawing during the 2 s sweep is the likely
  bulk (inferred). Not a morph question (the wheel draws nothing), but a
  reading before and after a knob sweep would show what the overlay costs
  MPE smoothing while a knob is turned.
- **I2, I5 (by ear):** the sweep rises smoothly; where the loop starts again
  the user hears a thump (with the effects on, a "tap tap": the effects
  repeating it), which changes with other patch settings and which the user
  puts down to the patch. That is the cutoff falling from fully open to
  closed in 40 ms: a movement that ends where it began has none. Stop (I4)
  and the repeating dip (I5) pass.

**Risks and what to check first**

1. Which button events arrive while Mod is held (the panel table entry for
   Animate 1 and 2: type, mode). Simulator, then one hands-on check.
   *Settled in the table (above); the hands-on check is series H.*
2. Pickup and the overlay: playback must not draw the knob overlay on
   every step, and must not leave pickup armed in a way that makes the
   control feel dead after stopping. The setter arms pickup; playback
   should clear the arm it caused when it stops.
3. Whether the recorded control's own MIDI CC is sent on playback. The
   setter is the receive path, so nothing is transmitted (inferred from
   the code path; check in the simulator's DIN log). Probably right for a
   first version; a DAW would not record the motion.

**Musical success:** a one-bar filter or wavetable-position gesture
repeats in time with the arp and with an external clock, and sounds like
the hand movement, not like steps.

## Step 22: patch morph

**Proposal: morph between the stored patch and the edited patch.**

Stock already holds both: the current patch (`0x20012340`) and the compare
buffer the **Compare** button plays (the patch as stored, read by
`FUN_080190F8(id)`; the plan forbids touching what Compare uses until it
is mapped, and this only reads it, as the knob overlay does for "saved
val"). So "A" is the patch as saved, "B" is the patch as it stands after
editing, and the morph position 0–127 blends from A to B. No second
snapshot buffer, no new storage, and the workflow is the one a player
already uses: load a patch, turn some knobs, and the difference is the
morph.

- **Which parameters:** only continuous ones in the cheap groups, and
  only where A and B differ: mixer levels (`0x0020`), filter drive,
  resonance and frequency (`0x0100`), oscillator Shape, Fine, Vsync,
  SawDense (`0x0010`), DenseDet (`0x0200`), envelope times and sustain
  (`0x0008`), LFO rates and Slew (`0x0080`), FX levels, times and feedback
  (`0x0040`), the fixed mod amounts (`0x0004`), matrix depths (`0x0002`,
  `0x0800`), pan (`0x0400`). A table of patch offsets marks them, built
  from the descriptor table and reviewed by hand.
- **Never morphed, switched at the midpoint instead** (or left at B, a
  Settings choice): `Wave` (about 1,290 writes with voices sounding: a
  switch mid-note would also click), filter Slope and Shape, reverb and
  chorus Type, sync switches, voice Mode, Unison, matrix sources and
  destinations, arp settings.
- **Position source:** a Settings item `Morph` = Off / ModWheel in the
  first version (CC 1 on the global channel; in MPE mode the master
  channel's CC 1, since member-channel Slide is per note). Pressure and a
  pedal can follow. The wheel keeps working as a mod source; a patch that
  also routes ModWheel in the matrix gets both.
- **Scale:** linear in the parameter's own value for levels and amounts.
  Times and frequencies are already stored on the firmware's perceptual
  scales (decay and release times are exponential in the stored value,
  and the cutoff table runs from 33 Hz to 23.7 kHz over the control's
  range: [peak-units.md](peak-units.md), observed), so linear in the stored
  value is close to the perceptual blend the plan asks for. 9-bit parameters blend as 9-bit values.
- **Rate and cost.** Recompute when the position changes, at most once per
  16 ms slot (anything faster is merged by the firmware anyway). Write
  through `param_set_by_id` only the bytes whose blended value changed. A
  slow wheel sweep changes each parameter by a step every few slots; the
  worst case is every group dirty in one slot, about 250 writes (above). To
  keep the modulation tick safe before the bus time is measured, spread
  the groups: at most three groups' parameters per slot, the rest in the
  next, which costs up to 64 ms of lag at the fastest wheel flick.
- **What the edit buffer holds during a morph.** The setter writes the
  blended values into the current patch, so B would be lost at the first
  blend. The morph therefore keeps its own copy of B's morphable bytes
  (about 120), taken when the position first leaves 127 (127 = B = the
  patch as it stands). A knob moved during a morph changes B. Save stores
  what is sounding, which at any position but 127 is the blend; the screen
  has to say so (for example `MORPH 64` on the patch page while the
  position is not 127).
- **Interaction.** Undo: the snapshot before a morph starts is one undo
  step. Parameter lock: locked groups are skipped. EnvSync: if on, amp
  Decay and Release are EnvSync's, skipped by the morph. Pickup: the
  setter arms pickup on every morphed control; that is right (the knobs no
  longer show the sounding value).
- **Cost in the image:** the offset table (about 60 bytes as a bitmap of
  0x1A3 offsets), B's snapshot (about 120 bytes of RAM), the blend loop.
  Small next to the 83 kB of flash and 63 kB of patch RAM left.

**Risks and what to check first**

1. **Bus time.** Measure how long a group update takes on the synth
   before morphing more than one group per slot: a diagnostics counter of
   merged modulation ticks (the tick request byte `voice_state+0xAC`
   greater than 1 when `mod_tick` runs) shown on the MIDI MONITOR page,
   read while sweeping. This is the missing measurement from step 6.
2. **Compare buffer.** Map where the stored patch lives and when it is
   refreshed (patch load, Save, Initialise) before reading it for A:
   `FUN_080190F8` is the reader; the buffer at `0x200129C4` is what a patch
   load fills when `0x20011213` is nonzero (observed in `patch_load`), which
   may be the same thing. Not traced further.
3. **Zipper.** Mixer levels and cutoff were clean at 5–10 ms steps on the
   rig. Resonance, FX feedback and delay time were not measured; delay time
   steps will pitch-shift the repeats (stock `SlewRate` governs that).
4. **Musical success** (from the plan): a slow sweep sounds smooth and
   intended, not like parameters switching. The midpoint switches are the
   weak spot; "leave discrete settings at B" may be the better default.

## Order

1. The merged-tick counter on the diagnostics page (risk 1): small, and
   it also answers plan step 6's open measurement.
2. Motion recording, one lane, steps only; then Smooth.
3. Morph on the mixer and filter groups only; widen group by group with
   the counter watching.
