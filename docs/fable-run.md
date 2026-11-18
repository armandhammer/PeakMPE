# Fable run log (from 2026-11-15)

The running record of the work in [fable-run-brief.md](fable-run-brief.md).
A fresh session reads this first and continues at "Next step".

**Next step:** v0.24 is on the synth and series P passed; no series open
(the next is Q). My remaining proposal from 2026-11-17: the
blank-settings guard (step 3). Also open: step 4 looks done in practice
(strike it?); chord memory and scale quantise may be controller jobs (ask).

**v0.24 on the synth** (label `MPEO`, `99c71886…`, source `1688724`):
flashed 2026-11-18; series P passed (P5 by ear: per-note tails). Release velocity as a per-voice mod source.
The guide's matrix has no such source and `note_off` never reads the
velocity (findings, "Pedal sources and the note-off velocity"). Settings
`RELEASE VEL` > `Source` lends `ExprPED1` or `BrthPED2`: its broadcast is
dropped and each note-off writes its velocity into that source of the
voices it releases, before their release command. Emulated
(`tests/test_peak_relvel.py`, 7 tests). On the synth: the chip applies the
source to the release that follows microseconds later, no deferral needed;
t20 0.118 s at note-off velocity 1 to 3.7–4.0 s at 127, no carry-over
(run `relvel-2026-11-18_083855`); rig run `2026-11-18_083318` 136 pass,
0 fail, 5 info; the LinnStrument sends release velocity (P3).

**v0.23 on the synth** (label `MPEN`, `988f7a59…`, source `c09c231`):
flashed 2026-11-17, series O passed. The LCD cache (`lcdcache.c`: only
changed characters are sent; the bar's characters load one per main-loop
pass). O4 repeated M7: 17 modulation ticks lost over a knob turn against
2,645 on v0.21, longest gap 4 ms against 9 (observed); rig run
`2026-11-17_184027` 136 pass, 0 fail, 5 info.

**v0.22 on the synth** (label `MPEM`, `e7b5ec86…`, source `2d6f240`):
flashed 2026-11-17, series N passed. N1 and N2 by the user; N3 on the rig:
`work/fine_check.py` (run `fine-2026-11-17_160400`) put CC 15 = 14 at
−100.2 cents and CC 28 at −72.1 (28.1 apart), CC 0 the same as 14, CC 127
the same as 114, CC 20 at −87.9; `hwrig run --stage all` (run
`2026-11-17_160436`) 136 pass, 0 fail, 5 info. v0.22 is v0.21 plus Osc
1/2/3 Fine over MIDI reaching −100 (`ccpair.c`; the bug of upstream PR 3;
findings, "The parameter setter and 9-bit controls").

**v0.21 on the synth:** flashed, series M passed and the rig rerun gave
136 pass, 0 fail, 5 info (run `2026-11-17_100041`, 2026-11-17), after the
rig's clean start learned to reset the mod wheel (the first run's Slide
failure was a wheel left at 127 by the LinnStrument's Low Row; hardware
log).

**What v0.20 and v0.21 hold (all emulated, nothing on the synth):** Compare leaves
the undo step and a motion lane alone (`tests/test_peak_compare.py`);
Euclidean arp rhythms, Settings > ARP EUCLID (`euclid.c`,
`tests/test_peak_euclid.py`); the arp echo filter drops a note off only
while a loop is known (`tests/test_peak_arp_echo.py`); v0.21: arp ratchets,
Settings > ARP RATCHET, the tenth page of the patch, so Settings has 36
(`euclid.c`, `tests/test_peak_ratchet.py`).

**Series L is closed:** L1 and L2 passed on v0.19 (2026-11-16; the first
L2.5 was my mistake: stock ends all notes at any patch load, so a pad is
pressed again while Compare is held). L3 and L4 were not done on v0.19 and
are M2 and M8.

**Decided by me in that night** (the user, going to bed: "If any decision
needs to be made, I authorize you to make the most logical, best choice"):
Compare leaves undo and motion alone, as the morph since v0.19; the Euclid
setting is global, not per patch (a Rhythm byte above 32 would index past
stock's table on an unpatched Peak); the arp echo fix; no sostenuto fix (a
rare gesture, and the feature list dropped pedal changes); nothing built
for MIDI Tuning (stock has single-note retuning: findings); ratchets as
`Ratchet` x2/x3 with `Every` 1 to 8, over one note per step when `Pulses`
is Off.

**Still open, the user's choice:** MIDI Tuning for device ID `7F` and
several notes per message; a chance for the ratchet; the stepwise closing of the filter
seen in J2; the two decisions below. (The README describes 0.21 since
2026-11-17; Strum was dropped by the user the same day.)

**Model:** the Fable brief (items A to D) is worked through; what is left is
hands-on testing, small fixes and then the morph from the written design
note. Opus 5.5 (high effort for the morph, medium for test rounds) can take
it from these files.

**State on the synth:** v0.21 (`e702ad11…`, boot `MPEL`, commit `7d0224e`), flashed by the user 2026-11-17; series M passed; rig 136 pass, 0 fail, 5 info (run `2026-11-17_100041`; the first run, `2026-11-17_093307`, 126/3/5 with a mod wheel left at 127: hardware log). Before it: v0.19 (`fb36f0fb…`, boot `MPEJ`, commit `709b87f`), flashed by the user 2026-11-16 17:54; no rig run on it; L2 of series L passed. Before it: v0.18 (`9df89b4d…`, boot `MPEI`, commit `c19c0f8`), flashed by
the user 2026-11-16 (flash log ok, identity `02 01 00 08`; rig 136 pass, 0 fail, 5 info, run
`2026-11-16_143231`; series J and K done). After series K `Morph` and the LinnStrument's Low Row are as the user left them (not reported). Before it: v0.17 (`e5e9e652…`, boot
`MPEH`, commit `163e5c7`, rig 136/0/5, run `2026-11-16_105659`). Before it: v0.16 (`0f262ad9…`, boot `MPEG`, commit
`11f5b71`, rig 136/0/5, run `2026-11-16_091401`). Before it: v0.15 (`dee61e50…`, boot `MPEF`, commit `ed02aa9`),
flashed 2026-11-15 21:22. Rig 136 pass, 0 fail, 5 info (run
`2026-11-15_212605`). Series F and G done (hardware log): stock stealing
observed, all three Glide settings work, undo window ok, messages clear after
3 s, Msg Time 127 = about 3 s accepted by the user. No hands-on test pending.

**Open with the user (no hurry):** whether to build a steal refinement (oldest
on a tie, pedal-held first, keep the lowest note, or protect the newest note
in a slow attack) and whether to fix the sostenuto quirk.

## Items

| Item | Status | Commit | Result | Confidence |
|---|---|---|---|---|
| A1 Trace the stock voice allocator | done | `7d7ee6f` | `voice_alloc` `0x080122B0` asks `voice_candidates` `0x08011B70`, which reads each voice's envelope state and level from the sound chip and ranks: quietest in release, then quietest held, then newest in attack | code observed; chip replies inferred |
| A2 Findings and symbols | done | `7d7ee6f` | [findings, "Voice allocation and stealing"](findings/peak-2.2-build2108.md#voice-allocation-and-stealing-2026-11-15); 12 symbols; `tests/test_peak_voice_steal.py` (4 pass) | emulated |
| A3 Feasibility | done | `7d7ee6f` | **Step 18 as written is what stock does**: a 9th note takes the quietest releasing voice and cuts no held note. Nothing to build for "tail-aware". The MCU itself holds no level or release time, only the gate, pedal-held flags and a start stamp per voice | code observed |
| A4 Rig experiment | done | `c63f5d0` | `work/steal_check.py` on v0.14, 2026-11-15: the 9th note took the releasing voice (released note -56 dB, held notes +0 dB); the 10th cut the next voice in rotation (63), not the oldest; all held: 48 then 53 cut; slow attack: the newest (83) cut. All as the code reads. No steal policy built; refinements listed in the findings are the user's call | observed |
| B1 Trace stock glide | done | `aea1d4d` | A poly note glides from the pitch its own voice last had (`voice_state+0x74+4v` is never reset); after power-on from note 60; MonoLG glides only legato; PreGlide overrides | code observed, emulated (`work/_b1_glide.py`) |
| B2 Glide findings | done | `aea1d4d` | [findings, "Glide"](findings/peak-2.2-build2108.md#glide-2026-11-15) | |
| B3 Glide option | done, confirmed on the synth | `aea1d4d` | Settings > MPE EXTRAS > Glide: Stock / LastNote / Legato (globals `+0x3E`), in `mpe_voice.c` `glide_start`; `tests/test_peak_glide.py` 6 pass. Rig check `work/glide_check.py` run for all three settings on v0.14 | emulated and observed; by-ear check F7 open |
| C1 Tick rate of `mpe_mod_update` | done without a measurement | `aea1d4d` | **1 kHz.** TIM6 PSC 59 ARR 99 = 10 kHz, a tick every 10th interrupt; the tempo constant 1,717,984 per BPM is 24 clocks per quarter at 1 kHz, and the arp step measured 125 ms on the synth. The simulator's 2000 per second was its own error (TIM6 raised every 50 us slot); fixed in `emu/board.py` | code observed + one hardware time; no new rig measurement needed |
| C2 Quick-assign `dest_of[]` | done | `aea1d4d` | All 47 entries: the control's name (`patch_param_desc`) and the destination's name (matrix list `0x080464E0`) agree. The firmware has no control-to-destination table (searched in destination order at record sizes 1, 2, 4, 8, 12) | names observed; pairing by name |
| C3 DIN overflow counter size | done | `aea1d4d` | One byte: `ldrb.w`/`strb.w [r3, #0x204]` at `0x0800EE2C`/`0x0800EE32` in the USART6 interrupt; wraps after 255 | observed |
| C4 Message countdown rate | done | `aea1d4d` | The simulator counted 2x fast (same TIM6 error). A count is at least 11 ms by the code; the guide's "Msg Time 127 is approx. 3 seconds" would be 23 ms. The old "60 ms per count" assumed Msg Time 0. The 2 s message hold now uses the patch's own 1 kHz tick (`ui_hold_poll`) | code observed; on the synth Msg Time 127 lasted about 1.5 s (user's stopwatch), so a count is 11 ms and the guide's 3 s is not what build 2108 does |
| C5 Patch timing constants (found through C1) | done, on the synth in v0.14/v0.15 | `aea1d4d` | EnvSync check interval 128 -> 64 ticks, undo gesture 4000 -> 2000 ticks, message hold by ticks. On the synth v0.13 has the first two twice too long and the hold too short | emulated |
| D1 Findings for steps 21, 22 | done | `6d22ee9` | Parameter changes are applied by 13 update groups, at most once per 16 ms (`FUN_08013014`); a group costs 5-40 chip writes, a waveform change about 1,290 with voices sounding (`work/_d_param_cost.py`); knob events and the tempo clock position are reachable without new hooks | code observed, counts emulated; bus time on the synth not measured |
| D2 Design note | done | `6d22ee9` | [peak-motion-morph.md](peak-motion-morph.md): one-lane 32-step motion recorder; morph between the stored and the edited patch from the mod wheel; order and risks | proposal, nothing built |
| D3 Motion recorder | done in the simulator | `b1e4e9f` | `motion.c`: Mod + Animate 1 arms, the next control moved is recorded for 32 steps and loops; replace while playing; stop restores the value. Settings > MOTION: Length 1/2/4 bars, state, `LateTicks` (late-tick counter, `diag.c`). `tests/test_peak_motion.py` 10 pass; Peak regression 95 pass | emulated; not on the synth |
| D4 Smooth | done, on the synth in v0.17 (the user: rises smoothly) | | Lane playback is a ramp from step to step, written every 16 ms; the loop start no longer jumps. `tests/test_peak_motion.py` 13 pass | emulated and heard by the user |
| D5 Morph | done, confirmed on the synth in v0.18 (series J) | | `morph.c`: Settings > MORPH > Morph = ModWheel; CC 1 blends the edited patch (0) towards the stored one (127); 126 continuous controls, switches stay; 16 setter calls per 16 ms. `tests/test_peak_morph.py` 16 pass. Rig script `work/morph_check.py` | emulated; not on the synth |
| E1 Compare with undo and a motion lane | done in the simulator, v0.20 | `6f56a92` | v0.19 cleared the undo step and stopped a lane at a Compare press (emulated first). Now both stand still while Compare is held; undo, paste, quick-assign and Mod + Animate 1 say `Not during Compare` | emulated; not on the synth |
| E2 Euclidean arp rhythms (feature list step 17) | done in the simulator, v0.20 | `d1a25fd`, `daad110` | Settings > ARP EUCLID: Pulses, Steps, Rotate. Stock's 33 rhythms are lists of note and rest lengths in arp clocks; `euclid.c` builds one and points the arp at it (hook on the call of `arp_tick`). Ratchets not built | emulated; not on the synth |
| E3 Arp echo filter | done in the simulator, v0.20 | `c267544` | With Arp>MIDI on and no loop, v0.2 to v0.19 took a key let go within 100 ms of the arp's own note off for the echo, so the arp went on (emulated). A note off is now dropped only within a minute of an echoed note on | emulated; not on the synth |
| E4 MIDI Tuning Standard (feature list, "Later") | checked | `25c11f2` | Stock already takes `F0 7F 00 08 02 tt 01 kk xx yy zz F7` (one note, device 00) and the bulk dump; nothing built | code observed, emulated on stock |
| E5 Arp ratchets (the rest of step 17) | done in the simulator, v0.21 | `7d0224e` | Settings > ARP RATCHET: Ratchet Off/x2/x3, Every 1-8. A repeat is a marked note event; a hook on the arp's choice of the next note makes stock pick the same note again. All eight Types | emulated; not on the synth |

## Verified so far

- Peak simulator tests on the corrected clock, everything in: 83 passed
  (`tests/test_peak_*.py`, `tests/test_mod_tick.py`).
- Full `scripts/check` for the v0.14 build: pytest 650 passed, 9 skipped
  (Summit and Peak), web 34 passed, descriptors equal.
- On the synth (v0.14): rig regression 136 pass, 0 fail, 5 info; the steal
  check (A4). Not yet on the synth: Glide, the timing corrections, the 2 s
  message hold.

## Stock firmware quirks found (not fixed)

- Sostenuto pedal up releases a note whose key is still down (emulated:
  note 60 held, CC 66 127 then 0: the voice gets its release commands;
  `FUN_08011F90` checks only the pedal-held flag). A fix would be one hook.
- After power-on every voice's glide pitch is note 60, so with Glide on the
  first notes glide from middle C.
- With all eight voices still in their attack, a new note takes the newest
  one (the note just played).

## Notes for whoever resumes

- Tree was clean at `275d14f` (v0.13 committed) when this run started; the
  untracked `scripts/ghidra-import.ps1` is older work, left alone.
- Probe scripts are in `work/` (`_a1_alloc.py`, `_b1_glide.py`; rig scripts
  `steal_check.py`, `glide_check.py`, both with `--dry-run`); one simulator
  boot is about 80 s of wall time, `tests/test_peak_sim.py` about 12 minutes.
- The Peak guide's text is saved in `work/tmp/peak-guide-detail.txt` (read
  through the browser pane; scripted fetches get HTTP 403).
- Docker Desktop has to be running for `scripts/dev`.
- Nothing was sent to the synth and nothing was flashed in this run.
