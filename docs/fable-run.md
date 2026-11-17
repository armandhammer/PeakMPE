# Fable run log (from 2026-11-15)

The running record of the work in [fable-run-brief.md](fable-run-brief.md).
A fresh session reads this first and continues at "Next step".

**Next step:** image v0.19 (label `MPEJ`, `fb36f0fb…`,
`work/flash/peak-firmware-2.2-build2108+mpe-fb36f0fb37d1.syx`) is built with
all checks passed (687 simulator tests, 34 web tests, `work/build-v19.log`)
and **flashed by the user 2026-11-16** (flash log ok, identity `02 01 00 08`; hardware-log row added). It mends Compare
during a morph (v0.18 lost the edit at the release: emulated) and makes the
saved blend the patch after Save; see [peak-motion-morph.md](peak-motion-morph.md),
"Compare and Save, v0.19". Then series L in `TEST.md`: L2 Compare with the
row up, L3 Save with the row up (saves over D002, the user's Init sound with
`MPE` On; L3.12 restores it. Not D003: it holds the user's patch "Element
Song", MPE Off, found 2026-11-16 when it was silent from the LinnStrument), L4 the rig run on **GO rig** after asking what
is plugged in. Readings wanted: `Position` in L2.4 and L3.2, `current` in
L3.1, `saved val` in L3.11 (expected current × (127 − Position) / 127).
Then add the results to the v0.19 hardware-log row.
**Series L so far (2026-11-16):** L2.1 to L2.4 pass (`Position` 64). The
first L2.5 was wrong (it expected a held note to go on through Compare; stock
ends all notes at any patch load, emulated on the stock image, and the user
saw the note stop); the steps from L2.5 on were rewritten (press the pad again
while Compare is held) and **all of L2 passed**. Open: L3 (Save over D002) and
L4 (the rig run on GO rig).
Not asked yet: whether Compare should also leave the undo step and a motion
lane alone (today it clears both; inferred from the code). Still open, the
user's choice: the stepwise closing of the filter seen in J2, the knob
overlay's cost in `LateTicks`, and the two decisions below.

**Model:** the Fable brief (items A to D) is worked through; what is left is
hands-on testing, small fixes and then the morph from the written design
note. Opus 5.5 (high effort for the morph, medium for test rounds) can take
it from these files.

**State on the synth:** v0.19 (`fb36f0fb…`, boot `MPEJ`, commit `709b87f`), flashed by the user 2026-11-16 17:54; no rig run yet; series L under way (L2 passed; L3 and L4 open). Before it: v0.18 (`9df89b4d…`, boot `MPEI`, commit `c19c0f8`), flashed by
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
