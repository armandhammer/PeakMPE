# Fable run log (from 2026-11-15)

The running record of the work in [fable-run-brief.md](fable-run-brief.md).
A fresh session reads this first and continues at "Next step".

**Next step:** B1: run `work/_b1_glide.py` in the simulator (stock glide: the
start pitch of a new note, the first note after power-on, MonoLG, PreGlide) and
write the glide findings; then B3 (the `Glide` option in `mpe_alloc_glide`).

**Waiting for the user:** OK to send MIDI for the A4 rig check (see A4).

## Items

| Item | Status | Commit | Result | Confidence |
|---|---|---|---|---|
| A1 Trace the stock voice allocator | done | (this commit) | `voice_alloc` `0x080122B0` asks `voice_candidates` `0x08011B70`, which reads each voice's envelope state and level from the sound chip and ranks: quietest in release, then quietest held, then newest in attack | code observed; chip replies inferred |
| A2 Findings and symbols | done | (this commit) | [findings, "Voice allocation and stealing"](findings/peak-2.2-build2108.md#voice-allocation-and-stealing-2026-11-15); 12 symbols; `tests/test_peak_voice_steal.py` (4 tests pass) | emulated |
| A3 Feasibility | done | (this commit) | **Step 18 as written is what stock does**: a 9th note takes the quietest releasing voice and cuts no held note. Nothing to build for "tail-aware". The MCU itself holds no level or release time; it has the gate, the pedal-held flags and a start stamp per voice | code observed |
| A4 Implementation | not started, needs the user | | Proposed instead of a new steal policy: (1) one rig check on the current image, MIDI only, no flash: 8 notes held, one released, a 9th played, which pitch stops (turns "inferred" into "observed"); (2) a read-only row on the MIDI MONITOR page with the chip's states and levels at the last allocation, in the next flash. Optional refinements if the user wants them: ties among held voices to the oldest, pedal-held notes before key-held, keep the lowest note | |
| B1 Trace stock glide | in progress | | From the code: each voice keeps its own glide pitch (`voice_state+0x74+4v`), so a new note glides from **that voice's** last pitch; `voice_glide` `0x08010A9C`; rate from `GlideTime` patch `+0x27` when `+0x29` is on; PreGlide `+0x28` | code observed, not yet emulated |
| B2 Glide findings | not started | | | |
| B3 Glide option, tests | not started | | Plan: Settings option `Glide` = Stock / LastNote / Legato, seeding the chosen voice's glide pitch in the existing `mpe_alloc_glide` hook | |
| C1 Tick rate of `mpe_mod_update` on the synth | not started | | needs one rig measurement (ask before sending MIDI) | |
| C2 Quick-assign `dest_of[]` against the firmware's table | not started | | | |
| C3 DIN overflow counter size | not started | | | |
| C4 Message countdown rate, simulator vs synth | not started | | | |
| D Steps 21, 22 | not started | | only after A to C | |

## Notes for whoever resumes

- Tree was clean at `275d14f` (v0.13 committed) when this run started; the
  untracked `scripts/ghidra-import.ps1` is older work, left alone.
- Probe scripts are in `work/` (`_a1_alloc.py`); one simulator boot is about
  80 s of wall time, a probe with seven scenarios about 3 minutes.
- Docker Desktop has to be running for `scripts/dev`.
- Nothing was sent to the synth and nothing was flashed in this run.
