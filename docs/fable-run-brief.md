# Fable run brief (written 2026-11-15)

You are the session running on Fable 5.2 for a window of at most 24 hours.
Usage may stop without warning, and access may end for good, so work so that
a fresh session on any model can resume from the files alone.

## First, every time you start or resume

1. Read `docs/fable-run.md` if it exists (the running log) and continue at its
   "Next step". If it doesn't exist, create it (format below).
2. Read, once: `CLAUDE.md`, `docs/peak-features.md` (roadmap, steps 17 to 22),
   `docs/findings/peak-2.2-build2108.md`, `docs/hardware-log.md` (last three
   rows), `docs/symbols/peak-2.2-2108.csv`. Your auto-memory also holds the
   user's standing rules (exact test steps, no vague instructions, slider
   wording, no flash without confirmation, local commits allowed).
3. `git status`. Another session may have been building v0.13; do not touch
   `work/build*`, `work/flash/` or flash anything. If `patches/peak_mpe/`
   has uncommitted changes you did not make, ask the user before building on
   them.

## Goal

Highest-value results with the least waste: findings that are certain (labelled
observed / emulated / inferred, with addresses) and features that work in the
simulator, ready for one hardware flash per batch. Do not redo anything that
`docs/fable-run.md` marks verified.

## Work, in this order

Each item ends in a commit when its sub-step passes (see Saving).

**A. Step 18, tail-aware voice stealing (experiment).**
   The Peak has 8 voices; on a 9th note the stock firmware drops the first held
   note (user observed this on hardware, test A6).
   1. Trace the stock voice allocator in the simulator (`emu/`, the Peak image
      is `firmware/peak-firmware-2.2-build2108.syx`): which function allocates
      and steals, how it picks the victim, what per-voice state exists on the
      MCU (gate, age, note, release start) and what is only in the FPGA.
   2. Write the findings (addresses, confidence) before changing anything.
   3. Decide feasibility: can the MCU know which voice is in its release tail
      or quietest (estimate from release time and the patch's release stage if
      the FPGA level is not readable)? If not feasible, say so with the
      evidence and stop A there.
   4. If feasible: implement behind a Settings option (Off = stock), simulator
      tests, a rig-checkable experiment (exact steps, no vague wording).

**B. Step 19, per-note glide in MPE.** Same files, same method: how stock
   glide/portamento picks its start pitch, how MPE member channels interact,
   findings first, then a minimal implementation behind a Settings option if
   sound design allows it, tests.

**C. Clear the open inferences** (each a short trace or one measurement):
   1. Real `mpe_mod_update` tick rate on the synth (simulator says 2000 per
      second, docs say 1 kHz; matters for EnvSync's 1 s hold and the undo
      2 s gesture window). Propose one rig measurement and ask the user before
      sending any MIDI.
   2. Quick-assign control-to-destination table (`qassign.c` `dest_of[]`):
      verify every entry against the firmware's own table if one exists.
   3. DIN overflow counter size at `0x20003EAC + 0x204` (read as one byte).
   4. Message countdown rate: the `Msg Time + 5` count lasted about 0.3 s on
      the synth (60 ms per count) but the simulator counts about 18x faster;
      find out why (clock model in the simulator vs the firmware's tick).

**D. Steps 21 and 22 (motion recording, patch morph)** only if A to C are
   finished or blocked. Findings and a design note first.

Steps 17 and 20 (arp) are not yours; leave them for a cheaper model.

## Saving (the point of this brief)

After every sub-step that passes its tests:
1. Update `docs/fable-run.md`: what you found or changed, the confidence
   label, verified or not, and the exact next step (one sentence).
2. Put durable findings in `docs/findings/peak-2.2-build2108.md` and symbols
   in `docs/symbols/peak-2.2-2108.csv` immediately.
3. Commit locally on the current branch: code, tests, docs and the log
   together, ending with the `Co-Authored-By` trailer from your system
   reminder. Never push, never open a PR, never force anything.
Firmware images and `work/` never go into git.

`docs/fable-run.md` format: a "Next step" line at the top; then a table or list
of items A1, A2, ... with status (not started / in progress / done / blocked),
commit hash, one-line result, confidence.

## Hardware

Never flash, and never send MIDI or SysEx to the synth without the user's
explicit confirmation. Stage all features in the simulator first; ask the user
to flash once per batch (A and B together if both work), give the flash
command only (no recovery steps), and write the hands-on steps into `TEST.md`
as series F, exact as the user requires: control, row, value, click count,
expected screen text; check edit-buffer changes with the Pickup arrow or audio,
never the overlay's "saved val". After the flash, run `tools/hwrig run --stage
all --yes` (user keeps Ableton closed and hands off), log it in
`docs/hardware-log.md`.

## Efficiency

- Simulator and tests run through `MSYS_NO_PATHCONV=1 scripts/dev ...`.
  Quick check while working: the specific tests with `-k`; the full suite only
  before an image build. A cold simulator boot is about 80 s: batch your probes
  in one script (see `work/_dump_pages.py`, `work/_dump_params.py` for the
  pattern).
- Keep scratch scripts in `work/` (git-ignored).
- Don't narrate; the log file is the record. The user reads summaries.
- If blocked on something only the user can answer, ask one interactive
  question with a recommended option and keep working on an unblocked item.
