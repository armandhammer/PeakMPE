# Fable run log (from 2026-11-15)

The running record of the work in [fable-run-brief.md](fable-run-brief.md).
A fresh session reads this first and continues at "Next step".

**Next step:** the user's remaining steps of series F in `TEST.md`: F3 (Msg Time
number and stopwatch), F4 (2 s message), F5 (undo window), F7 (LinnStrument, by
ear); add each result to the v0.14 row of `docs/hardware-log.md` and settle the
"Message time" paragraph of the findings from F3. F0, F1, F2 and F6 are done.
The Peak's Glide item was left on Legato (F7 uses it). With nothing from the
user, the next unblocked work is D3: the merged-tick counter on the MIDI
MONITOR page ([peak-motion-morph.md](peak-motion-morph.md), "Order").

**F3.1 (user, 2026-11-15):** `Msg Time` on the Peak reads 64. The stopwatch reading at 127 (F3.3) is still open.

**F2 done (observed, v0.14):** Stock starts every note at about 72 (its voice's
last pitch); LastNote from the previous note's current pitch; Legato on pitch
when detached and from the held note when legato. Table in the findings,
"Glide".

**v0.14 was flashed by the user 2026-11-15 19:13** (log `work/flash-06be5529-2026-11-15.log`: full transfer, identity `02 01 00 08`; row in `docs/hardware-log.md`). Rig run on it: 136 pass, 0 fail, 5 info (run `2026-11-15_191511`). The image:
`work/flash/peak-firmware-2.2-build2108+mpe-06be5529753f.syx`, SHA-256
`06be5529753f67073d8be8d6fa2380f61d6ca2a03e793a367ceb95efa37e4925`, boot label
`MPEE`. `scripts/check` before it: pytest 650 passed, 9 skipped; web 34 passed;
both descriptors equal (log `work/build-v14.log`).

**Waiting for the user (nothing was sent to the synth):**
- GO for the rig runs (F0, F2, F6): notes and CCs over USB, Ableton closed.
- The flash, and the readings of series F (Msg Time value and message time).
- Whether to build any of the steal refinements (A4) or fix the sostenuto
  quirk.

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
| C4 Message countdown rate | cause found; one reading open | `aea1d4d` | The simulator counted 2x fast (same TIM6 error). A count is at least 11 ms by the code; the guide's "Msg Time 127 is approx. 3 seconds" would be 23 ms. The old "60 ms per count" assumed Msg Time 0. The 2 s message hold now uses the patch's own 1 kHz tick (`ui_hold_poll`) | code observed; synth time not measured (TEST.md F3) |
| C5 Patch timing constants (found through C1) | done in the simulator | `aea1d4d` | EnvSync check interval 128 -> 64 ticks, undo gesture 4000 -> 2000 ticks, message hold by ticks. On the synth v0.13 has the first two twice too long and the hold too short | emulated |
| D1 Findings for steps 21, 22 | done | `6d22ee9` | Parameter changes are applied by 13 update groups, at most once per 16 ms (`FUN_08013014`); a group costs 5-40 chip writes, a waveform change about 1,290 with voices sounding (`work/_d_param_cost.py`); knob events and the tempo clock position are reachable without new hooks | code observed, counts emulated; bus time on the synth not measured |
| D2 Design note | done | `6d22ee9` | [peak-motion-morph.md](peak-motion-morph.md): one-lane 32-step motion recorder; morph between the stored and the edited patch from the mod wheel; order and risks | proposal, nothing built |
| D3 Build | not started | | first the merged-tick counter on the diagnostics page (design note, "Order") | |

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
