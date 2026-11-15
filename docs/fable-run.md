# Fable run log (from 2026-11-15)

The running record of the work in [fable-run-brief.md](fable-run-brief.md).
A fresh session reads this first and continues at "Next step".

**Next step:** read the result of the Peak regression rerun on the corrected
simulator clock (`scripts/dev python -m pytest -q -n auto tests/test_peak_*.py
tests/test_mod_tick.py`; it must be all green before an image is built), then
build v0.14 with `scripts/build-image.sh patches/peak_mpe` (bump the boot label
to `MPEE` in `patches/peak_mpe/patch.py` first), dump the MPE EXTRAS screen
from the simulator and write `TEST.md` series F.

**Waiting for the user (nothing was sent to the synth):**
- OK to run `work/steal_check.py` (A4) and `work/glide_check.py` (B): notes and
  CCs over USB to the edit buffer, about 1 minute each, Ableton closed.
- The Msg Time value on their Peak and how long a knob message lasts (C4).
- Whether to build any of the steal refinements (A4).

## Items

| Item | Status | Commit | Result | Confidence |
|---|---|---|---|---|
| A1 Trace the stock voice allocator | done | `7d7ee6f` | `voice_alloc` `0x080122B0` asks `voice_candidates` `0x08011B70`, which reads each voice's envelope state and level from the sound chip and ranks: quietest in release, then quietest held, then newest in attack | code observed; chip replies inferred |
| A2 Findings and symbols | done | `7d7ee6f` | [findings, "Voice allocation and stealing"](findings/peak-2.2-build2108.md#voice-allocation-and-stealing-2026-11-15); 12 symbols; `tests/test_peak_voice_steal.py` (4 pass) | emulated |
| A3 Feasibility | done | `7d7ee6f` | **Step 18 as written is what stock does**: a 9th note takes the quietest releasing voice and cuts no held note. Nothing to build for "tail-aware". The MCU itself holds no level or release time, only the gate, pedal-held flags and a start stamp per voice | code observed |
| A4 Rig experiment | ready, needs the user's OK | (work/, not in git) | `work/steal_check.py`: three takes (8 held + one released + a 9th and 10th; 8 held + 9th + 10th; slow attack + 9th), reports which pitch stops. Dry run clean (869 messages). Turns "chip replies inferred" into observed. No new steal policy built; possible refinements are listed in the findings | not run |
| B1 Trace stock glide | done | (this commit) | A poly note glides from the pitch its own voice last had (`voice_state+0x74+4v` is never reset); after power-on from note 60; MonoLG glides only legato; PreGlide overrides | code observed, emulated (`work/_b1_glide.py`) |
| B2 Glide findings | done | (this commit) | [findings, "Glide"](findings/peak-2.2-build2108.md#glide-2026-11-15) | |
| B3 Glide option | done in the simulator | (this commit) | Settings > MPE EXTRAS > Glide: Stock / LastNote / Legato (globals `+0x3E`), in `mpe_voice.c` `glide_start`; `tests/test_peak_glide.py` 6 pass. Rig check `work/glide_check.py` ready (dry run clean) | emulated; not on the synth |
| C1 Tick rate of `mpe_mod_update` | done without a measurement | (this commit) | **1 kHz.** TIM6 PSC 59 ARR 99 = 10 kHz, a tick every 10th interrupt; the tempo constant 1,717,984 per BPM is 24 clocks per quarter at 1 kHz, and the arp step measured 125 ms on the synth. The simulator's 2000 per second was its own error (TIM6 raised every 50 us slot); fixed in `emu/board.py` | code observed + one hardware time; no new rig measurement needed |
| C2 Quick-assign `dest_of[]` | done | (this commit) | All 47 entries: the control's name (`patch_param_desc`) and the destination's name (matrix list `0x080464E0`) agree. The firmware has no control-to-destination table (searched in destination order at record sizes 1, 2, 4, 8, 12) | names observed; pairing by name |
| C3 DIN overflow counter size | done | (this commit) | One byte: `ldrb.w`/`strb.w [r3, #0x204]` at `0x0800EE2C`/`0x0800EE32` in the USART6 interrupt; wraps after 255 | observed |
| C4 Message countdown rate | cause found; one reading open | (this commit) | The simulator counted 2x fast (same TIM6 error). A count is at least 11 ms by the code; the guide's "Msg Time 127 is approx. 3 seconds" would be 23 ms. The old "60 ms per count" assumed Msg Time 0. The 2 s message hold now uses the patch's own 1 kHz tick (`ui_hold_poll`) | code observed; synth time not measured (TEST.md F3) |
| C5 Patch timing constants (found through C1) | done in the simulator | (this commit) | EnvSync check interval 128 -> 64 ticks, undo gesture 4000 -> 2000 ticks, message hold by ticks. On the synth v0.13 has the first two twice too long and the hold too short | emulated |
| D Steps 21, 22 | not started | | only after A to C | |

## Verified so far

- `tests/test_peak_glide.py`: 6 pass. `tests/test_peak_voice_steal.py`: 4 pass
  (before the clock fix; in the rerun).
- First regression run on the corrected clock (before the constants and the
  Glide option went in): 72 pass, 5 fail, all five settle times that were
  too short at the true tick rate (pressure and Slide smoothing); their
  waits are doubled in `tests/test_peak_sim.py`. **The rerun with everything
  in was not finished when this was committed.**
- Not run yet: the full suite (`scripts/check`), the web tests, the image
  build. The Summit tests should be unaffected (TIM6 period 50 us as
  before) but have not been rerun.

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
