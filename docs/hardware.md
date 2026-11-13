# Flashing and hardware sessions

How a build gets onto the maintainer's Summit, and how a hardware session is
run and recorded. Contributors don't need this: pull requests are checked by
the tests and the simulator ([CONTRIBUTING.md](../CONTRIBUTING.md)).

**Peak (Windows):** the maintainer's Peak is flashed from PowerShell with
`scripts/flash.ps1 <image>` (file check, dry run and flash with a log in one
command; `flash.py` still asks for the confirmation), which
`scripts/build-image.sh` prints on Windows. The rig runs with
`tools\hwrig ... --yes` when the owner has approved test runs in advance;
its config for the Peak is `product = "Peak"` in `work/hwrig.toml`.

## Safety rules

- **Never flash, and never send MIDI or SysEx to a real synth, without the
  owner's explicit confirmation.** An agent working in this repository
  never runs `tools/flash.py flash` without `--dry-run`, never starts the
  test rig against real ports, and never types a confirmation.
- **The owner runs the flash** in their own terminal and types the
  confirmation (`flash`) there.
- **Recovery steps come first**, before the flash commands
  ([recovery.md](recovery.md)).
- **Only a checked, verified build is flashed:** the full suite with the
  firmware, an image built with `--verify`, its SHA-256 recorded.
- **Firmware and images never leave the machine:** not into git, a commit
  message, an issue, a CI artifact or any upload.

## Before a flash: `scripts/build-image.sh`

```bash
scripts/build-image.sh
```

The argument picks another patch definition (default
`patches/mpe/patch.py`), for example
`scripts/build-image.sh patches/version_string.py`. The script never
flashes. It stops at the first step that fails:

1. **`scripts/check`**, the full suite with the firmware. `--skip-checks`
   skips it, for a rebuild of a tree that just passed.
2. **Builds** with `tools/patch.py <definition> --verify` and checks the
   file's SHA-256 against the one the build printed.
3. **Copies the image** to `work/flash/<name>-<sha12>.syx`. The flash
   commands use this copy, which no later build overwrites.
4. **Prints** the commit (and whether the tree had uncommitted changes),
   the recovery steps, then `flash.py check`, `flash --dry-run` and the
   real `flash` with a `--log`.

Pass those commands on unchanged.

## After the flash

1. **Record it.** Every flash gets a row in
   [hardware-log.md](hardware-log.md): date, commit, image SHA-256, tool,
   result, recovery used if any, log file. Results of an experiment go into
   its write-up or the findings.
2. **If the hardware fails,** fix it, run the checks, build again, flash,
   and record that run as well.
3. **Release** a build only after its hardware run passed
   ([CONTRIBUTING.md](../CONTRIBUTING.md#releases)). The log is a record,
   not a merge gate: a change can land on `main` before it has been on a
   synth.

## Commands for a hardware session

The owner's shell is zsh. Every command in a run plan must work there as
well as in bash:

- **Run from the root of the checkout that built the image;**
  `build-image.sh` prints its `cd`. Paths may have a space, so quote them:
  `cd "$HOME/src/Summit MPE"`. The commands use relative paths (`work/…`)
  from there.
- **Dates in log names:** `--log work/flash-<what>-$(date +%F).log`. A
  bare `<date>` placeholder is a redirection in both shells.
- **Keeping a terminal tab open** after a run: `printf 'done, press enter '; read -r _`
  works in both shells. Bash's `read -p "…"` fails in zsh ("no
  coprocess"); zsh's own form is `read '?done, press enter'`.
- **Placeholders** such as `<what>` only go in prose; a command in a fenced
  block must run as pasted.

## Recording MIDI

A recording of what a sender really sent is what settles a "stuck note" or
"dropped note" report afterwards (L4 and B1 of the MPE v1 run, [hardware-log.md](hardware-log.md)). Recordings go in
`work/capture/` (git-ignored, never committed). Give each a new name: an
overwritten recording can't pin a test.

`tools/midirec.py` replaces MIDI Monitor for hardware sessions. It only
listens (it opens MIDI inputs, never an output) and writes each message to
disk as it arrives, so there is no history limit and Ctrl-C or a crash loses
nothing. MIDI clock (F8) and active sensing (FE) are dropped unless you pass
`--keep-clock`; SysEx is kept.

List the inputs, then record. Quote every `--port` substring (zsh):

```bash
.venv/bin/python -I tools/midirec.py list
```

```bash
.venv/bin/python -I tools/midirec.py record --marker --port "Push" --port "Hapax" --port "Summit"
```

- Without `--port` it records every input. `--duration 60` stops after a
  minute; otherwise Ctrl-C stops it.
- With `--marker`, press Enter at a moment worth finding again (for example
  right before the chord after a zone change). It writes
  `# marker N <seconds>` into the log.
- The log goes to `work/capture/rec-YYYYmmdd-HHMMSS.log` (git-ignored; an
  existing file is never overwritten). On stop the tool prints the path, the
  message count per port and the SHA-256, and writes `<file>.sha256`. A test
  can pin the capture by that hash, as `tests/test_mpe_conformance.py` does.
- Each line is `"<seconds> < <port> <hex bytes>"`, the format of
  `tools/mmon.py log` and `tools/flash.py --log`; `mmon.read_log` reads it
  and skips the `#` lines.
- It sees only what MIDI sources send to the Mac (`<`). Unlike MIDI Monitor's
  spy, it can't see what another app (Ableton Live) sends to the Summit
  port. To record Live's output, have Live also send the same MIDI to a port
  the recorder can open (for example an IAC bus), or record what reaches the
  Mac from Push and the Hapax.
- Note the log file and its hash in the session's row in
  [hardware-log.md](hardware-log.md).

For what Ableton Live sends to the Summit, MIDI Monitor's spy is still the
simplest recorder (or route Live's output to an IAC bus as well). In MIDI
Monitor:

- **Raise the history limit** ("Remember the most recent … events"; the
  default is 1,000). Both Hapax recordings of the v1 run hit 1,000 and lost
  their start.
- **Filter out clock** (and active sensing), so the limit holds notes and
  controllers, not 24 clock messages per beat.
- Record **every source and destination** involved (all of the Hapax's
  ports, the interface's DIN out), so the recording shows which path a
  sender used.
