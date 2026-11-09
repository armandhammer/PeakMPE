# Setup

Everything needed to reproduce this work from a clean machine.
`scripts/check-env.sh` reports what is present.

**Builds and tests run in one Docker image** (`docker/Dockerfile`), on the
Mac and in CI (GitHub Actions), through `scripts/dev`. The host needs only:

- **Docker** (OrbStack, Docker Desktop or Colima);
- **git**;
- **a browser**, for the web patcher.

Two things stay native on macOS, because a container there can't reach
CoreMIDI or CoreAudio. Neither is needed to build or test:

- **the hardware tools**, in a small `.venv` (`requirements-hw.txt`):
  `tools/flash.py`, `tools/midirec.py`, `tools/hwrig` and the `--hw`
  pytest runs;
- **reverse engineering**: Ghidra, its JDK, and Node for the REA MCP
  server.

Git stays on the host.

## Reference environment

**Host**

| Tool | Version | Used for | Install |
|---|---|---|---|
| macOS (Apple Silicon) | 26 (Darwin 25.6), arm64 | host | |
| OrbStack | 2.2.5 (Docker Engine 29.8.2, buildx 0.37.2) | runs the dev image; Rosetta for linux/amd64 | <https://orbstack.dev> (or Docker Desktop, or Colima with `--vz-rosetta`) |
| git, curl | system | version control, `scripts/fetch-firmware.sh` | ships with macOS |
| Python | 3.9.6 (system) | `scripts/fetch-firmware.sh`, the git hooks' syntax check, the hardware venv | ships with macOS |

**Dev image** (`docker/Dockerfile`, linux/arm64 and linux/amd64). Every
input is pinned:

| Component | Version | Pinned by | Used for |
|---|---|---|---|
| Base | `python:3.12.15-slim-trixie` (Debian 13.7) | image digest | |
| Debian packages | git, `llvm-19` (19.1.7), perl, curl, xz | `snapshot.debian.org` 20261101T000000Z | `llvm-objcopy`, `llvm-objdump` (`scripts/disasm.sh`, `tools/patch.py --verify`); `shasum` |
| Arm GNU Toolchain | 15.3.rel2: `arm-none-eabi-gcc` 15.3.1, binutils 2.45.1 | version and Arm's SHA-256, per architecture | compiling C patches (`tools/patch_build.py`, [patch-howto.md](patch-howto.md)) |
| Python | 3.12.15, with unicorn 2.1.4, pytest 8.4.2, pytest-xdist 3.8.0, numpy 2.0.2 | `requirements-dev.txt` | emulation harness `emu/`, tests `tests/`, `tools/*.py` |
| Node.js | 26.13.0, npm 11.20.0 | `node:26.13.0-trixie-slim` digest | the web patcher `web/` (`npm ci` from `web/package-lock.json`; [web.md](web.md)) |

**Native, optional**

| Tool | Version | Used for | Install |
|---|---|---|---|
| Hardware venv (`.venv/`) | python-rtmidi 1.5.8, numpy 2.0.2, sounddevice 0.5.1, unicorn 2.1.4, pytest 8.4.2 | `tools/flash.py`, `tools/midirec.py`, `tools/hwrig` ([hw-test-rig.md](hw-test-rig.md)), `pytest --hw` | `requirements-hw.txt`, step 7 |
| Homebrew | 7.0 | the reverse-engineering packages | <https://brew.sh> |
| OpenJDK | 21.0.13 | Ghidra runtime | `brew bundle` |
| Node.js | 26.13 | optional: `npx` for the REA MCP server | `brew bundle` |
| Xcode Command Line Tools | Apple clang 21 | building Ghidra's natives | `xcode-select --install` |
| Ghidra | 12.1.4 (natives built locally) | decompiler, headless analysis | `scripts/install-ghidra.sh` |
| REA (`rea-agents`) | 6.8.0 | optional: agent reverse-engineering tools (MCP); not needed to build, test or contribute | via `npx`, see below |
| Claude Code | desktop app | optional: the agent this project was developed with; not needed to build, test or contribute | <https://claude.com/claude-code> |

## Steps

1. **Docker.** Install and start one of OrbStack, Docker Desktop or Colima
   (`brew install colima docker docker-buildx`, then
   `colima start --vm-type vz --vz-rosetta`). Check that it runs:

   ```bash
   docker info
   ```

2. **Firmware:**

   ```bash
   scripts/fetch-firmware.sh --all
   ```

3. **Git hooks** (optional): they refuse to commit or push firmware and
   generated files, and shell or Python files that don't parse. CI checks
   the files on every pull request anyway:

   ```bash
   scripts/install-hooks.sh
   ```

4. **The dev image.** `scripts/dev` builds it by itself the first time it
   needs it (about 3 minutes; the toolchain download is 150 MB). To build it
   explicitly:

   ```bash
   scripts/dev --build
   ```

5. **Check:**

   ```bash
   scripts/check-env.sh
   ```

6. **Tests.** The harness decodes `firmware/summit-firmware-2.2-build2121.syx`
   in memory and checks it against `firmware/SHA256SUMS`. Without the firmware,
   every test that needs it is skipped. The full run, in parallel with
   pytest-xdist (what `scripts/check` and CI run):

   ```bash
   scripts/dev python -m pytest -q -n auto
   ```

   The long simulator plays (the bend experiments, the MPE queue and
   expression sequences, the demo patch, the CLI) are marked `slow`. For a
   quick run while working:

   ```bash
   scripts/dev python -m pytest -q -m "not slow" -n auto
   ```

   In one process (much longer; for debugging):

   ```bash
   scripts/dev python -m pytest -q
   ```

Measured on 2026-11-08, M5 Mac with 10 cores (OrbStack: 10 CPUs,
   15.7 GiB), warm simulator cache, 626 tests. The native run used the
   previous Homebrew toolchain and the main checkout's venv:

   | Run | Native (Python 3.9, GCC 16.2) | Dev image (`scripts/dev`, arm64) |
   |---|---|---|
   | full (`-n auto`) | 369 s | 380 s; 342 s in a later `scripts/check` |
   | quick (`-m "not slow"`, 395 tests) | 104 s | 147 s |
   | no firmware, as CI (`scripts/check --no-firmware`: pytest, web test and build, descriptor) | | 94 s (pytest 84 s: 223 passed, 403 skipped) |

   Other sessions' tests were loading the machine during most of these runs
   (load averages 8–32), so the numbers vary by tens of seconds; the full
   suite costs the same in the image within that noise. Starting a container takes about a second.
   The first run after a new image also rebuilds the venv's bytecode in the
   cache volume.

   The MPE stress plays (`tests/test_mpe_stress.py`) run one seed of two
   phrases per layout; more seeds (each its own xdist group) and phrases
   for a longer bug hunt (`scripts/dev` passes these variables through):

   ```bash
   MPE_STRESS_SEEDS=1-20 MPE_STRESS_PHRASES=4 scripts/dev python -m pytest -n auto tests/test_mpe_stress.py -k random_play
   ```

   CI runs the full suite on every pull request. Mark
   a new test `@pytest.mark.slow` if it takes more than a few seconds.

   **Parallel tests.** Each xdist worker is its own process: session caches
   (the MPE build and boot in `tests/mpe_sim.py`, `bend_play.played`) exist
   once per worker, and `tmp_path` is per worker. `tests/conftest.py` keeps
   the tests that share a module-scoped fixture on one worker (`--dist
   loadgroup` in `pytest.ini`), so a long play runs once. Write new tests the
   same way: output into `tmp_path` / `tmp_path_factory` (patch builds pass
   `build_dir=`, never the shared `work/build/`), and an
   `@pytest.mark.xdist_group` where a cache must be shared across modules.

   **Cache.** The simulated Summit (`tests/test_synth_*.py`, `tools/sim.py`,
   [SIMULATOR.md](SIMULATOR.md)) boots from a DataFlash formatted by the
   firmware's own factory initialise. That takes about 25 s per image, so
   it is cached in `work/cache/dataflash/` (`emu/cache.py`). The key is the
   SHA-256 of the image that formats it plus the SHA-256 of every
   `emu/*.py`, so a different image or a changed simulator never reads an old
   entry. Writes are atomic and locked: one worker formats an image while
   the others wait. `tests/test_cache.py` checks that a cold boot matches a
   cached one. List or clear it:

   ```bash
   scripts/dev python -I tools/cache.py
   ```

   ```bash
   scripts/dev python -I tools/cache.py clear
   ```

   `SUMMIT_MPE_NO_CACHE=1` bypasses it for one run. Patch builds (under
   0.5 s each) and the image decode (under 0.1 s) are not cached.

   **The web patcher's tests** (Vitest, [web.md](web.md)). The first `npm`
   command in a checkout runs `npm ci` into its own volume:

   ```bash
   scripts/dev npm --prefix web test
   ```

7. **Hardware venv** (optional; only for flashing, recording MIDI and the
   test rig, which need CoreMIDI and CoreAudio). Git-ignored `.venv/`, pinned
   in `requirements-hw.txt`. A worktree without one uses the main
   checkout's:

   ```bash
   python3 -m venv .venv
   ```

   ```bash
   .venv/bin/pip install -r requirements-hw.txt
   ```

8. **Reverse-engineering tools** (optional). Homebrew packages (the JDK for
   Ghidra, Node for REA), then Ghidra. The script installs into `~/tools`,
   checks the release zip against GitHub's published SHA-256, and builds the
   macOS decompiler (about 1 minute):

   ```bash
   brew bundle
   ```

   ```bash
   scripts/install-ghidra.sh
   ```

   Then add this to your shell profile:

   ```bash
   export GHIDRA_INSTALL_DIR="$HOME/tools/ghidra_12.1.4_PUBLIC"
   ```

   Ghidra 12.2 exists, but REA 6.8.0 verifies against 12.1.x. Stay on 12.1.x
   until REA supports newer versions.

9. **First analysis.** `scripts/disasm.sh` runs in the dev image, Ghidra
   natively:

   ```bash
   scripts/disasm.sh firmware/summit-firmware-2.2-build2121.syx
   ```

   ```bash
   scripts/ghidra-import.sh firmware/summit-firmware-2.2-build2121.syx --decompile 0x0801d9bc
   ```

10. **Hardware test rig** (optional; [hw-test-rig.md](hw-test-rig.md)): the
    Summit's main outputs into an audio interface. Find the device, its input
    channels and the MIDI ports (sends nothing), then copy the example config
    and fill it in:

    ```bash
    .venv/bin/python -I tools/hwrig list
    ```

    ```bash
    mkdir -p work && cp tools/hwrig/hwrig.example.toml work/hwrig.toml
    ```

## `scripts/check`: what CI runs

One command runs every check CI runs (`.github/workflows/ci.yml`), in the
dev image. All steps run
even if one fails, and a summary lists each one:

1. **pytest**, `-n auto`. With the firmware this is the full suite; without
   it, the tests that need Novation's file skip.
2. **web test**: Vitest. The parity test skips without the firmware.
3. **web build**: `tsc` and `vite build`.
4. **descriptor compare** (`tools/web_descriptor.py compare`): the
   compiled blob always; the whole descriptor with the firmware.
5. **descriptor check** (no Novation bytes), only with the firmware.

```bash
scripts/check
```

CI downloads the official firmware from Novation for each run
(`scripts/fetch-firmware.sh`, checked against the pinned SHA-256) and never
keeps or uploads it. If that download fails, CI runs the no-firmware view
and says so in the job summary. `--no-firmware` hides `firmware/` behind an
empty tmpfs in the container (`DEV_NO_FIRMWARE=1` for `scripts/dev`), so
you can see exactly that view:

```bash
scripts/check --no-firmware
```

`--quick` adds `-m "not slow"` to pytest. `--shard I/N` runs only shard I
of N of pytest, as CI's six parallel jobs do (`tests/shard.py`; the web and
descriptor steps run in shard 1). Shards keep each xdist group whole and are
balanced by `tests/shard_weights.json`; refresh it after adding slow tests:

```bash
scripts/dev python -m pytest -q -n auto --shard-weights-out tests/shard_weights.json
```

 The cross-architecture byte
check is `scripts/check-repro.sh` (below), since the second architecture
is emulated here.

## The dev image and `scripts/dev`

`scripts/dev <command>` runs the command in the image, in the current
directory of the checkout. With no command it opens a shell there.

**What it mounts**, at the same absolute paths as on the host, so a
worktree's symlinks resolve:

| Host | In the container | Why |
|---|---|---|
| the checkout | read-write | sources, `.pytest_cache` |
| `work/` (its real directory; a worktree's is a symlink into the main checkout) | read-write | build output, simulator cache |
| `firmware/*` except the README (their real files) | **read-only** | Novation's files. They are never copied into the image, a layer or a build context: `.dockerignore` admits only `docker/Dockerfile`, `docker/entrypoint.sh` and `requirements-dev.txt` |
| a worktree's git directory | read-only | `git rev-parse` for the descriptor's commit; git itself runs on the host |
| volume `summit-mpe-cache` | `/cache` | home, npm cache, Python bytecode (`PYTHONPYCACHEPREFIX`) |
| volume `summit-mpe-web-<checkout>-<arch>` | `web/node_modules` | Linux binaries for Vite and Vitest, apart from any macOS `node_modules` |

The container starts as root only long enough to give the volumes to your
user, then runs the command as your uid, so files it writes belong to you.
It passes `UPDATE_GOLDEN`, `SUMMIT_MPE_NO_CACHE`, `SUMMIT_MPE_FIRMWARE_DIR`
(mounted read-only), `MPE_STRESS_SEEDS`, `MPE_STRESS_PHRASES` and
`PYTEST_ADDOPTS` through. Inside the image (`SUMMIT_MPE_IN_IMAGE=1`, as in
CI) `scripts/dev` runs the command directly.

**Options:**

| Command | Does |
|---|---|
| `scripts/dev --build` | build the image for this machine |
| `scripts/dev --image` | print the image tag in use |
| `scripts/dev --fingerprint` | the image's architecture, toolchain, Python packages, Node and Debian versions (`scripts/check-env.sh` reads it) |
| `DEV_PLATFORM=linux/amd64 scripts/dev …` | the other architecture, emulated (Rosetta in OrbStack) |
| `DEV_IMAGE=<ref> scripts/dev …` | a pulled image (for example from a registry) instead of the local build |
| `DEV_NO_FIRMWARE=1 scripts/dev …` | hide `firmware/` (an empty tmpfs), as CI does when the download fails |
| `DEV_PORTS=5173 scripts/dev …` | publish ports on 127.0.0.1, for the web dev server ([web.md](web.md#run-it-locally)) |

**The local tag** is `summit-mpe-dev:<hash>-<arch>`, where the hash covers
the Dockerfile, the entrypoint and `requirements-dev.txt`. A change to any
of them builds a new image on the next run instead of using a stale one.
Old tags can be removed with `docker image prune`. `docker volume rm
summit-mpe-cache` clears the cache volume.

**Both platforms in one image**, for a registry (publishing is set up
separately):

```bash
docker buildx build --platform linux/arm64,linux/amd64 -f docker/Dockerfile -t <registry>/summit-mpe-dev:<tag> --push .
```

**Updating a pin.** Change the `ARG` in `docker/Dockerfile`: a base image
tag with its digest, `DEBIAN_SNAPSHOT`, or `ARM_TOOLCHAIN` with both
SHA-256s. Arm publishes each as `<file>.sha256asc` next to the download on
<https://gitlab.arm.com/tooling/gnu-toolchains-for-arm>. A new compiler
changes the patch bytes. Then:

1. regenerate the descriptor;
2. run the check on both platforms;
3. update the hashes the web tests and docs pin;
4. the new image needs a hardware run before a release.

```bash
scripts/dev python -I tools/web_descriptor.py export patches/mpe/patch.py web/patches/mpe.json
```

```bash
scripts/check-repro.sh linux/arm64 linux/amd64
```

## Reproducible patch bytes

`scripts/check-repro.sh` rebuilds the patch in the image and requires the
committed `web/patches/mpe.json` (`tools/web_descriptor.py compare`):

- **the compiled blob, always.** It needs only the toolchain, not
  Novation's file, so CI can run it (`BLOB_ONLY=1`);
- **the whole descriptor** (hooks, header, output hashes) when the
  official file is in `firmware/`.

With several platforms it also requires them to compile the same blob:

```bash
scripts/check-repro.sh linux/arm64 linux/amd64
```

Result on 2026-11-08 (Arm GNU Toolchain 15.3.rel2):

| | linux/arm64 (native) | linux/amd64 (Rosetta) |
|---|---|---|
| blob | 5,416 bytes, `eac5114a…2388c8a9` | identical |
| output `.syx` | `28916b05…c08ac96`, equal to the descriptor | identical |

Before the image, the descriptor came from Homebrew's `arm-none-eabi-gcc`
16.2.0. Arm has no GCC 16 build, so no pinned Arm toolchain gives those
bytes: GCC 15.3 makes the blob 44 bytes longer. The source is the same.
The first image flashed and verified as v1.2 (`199f1903…`) is the GCC 16.2
build. The dev image's build `28916b05…` was flashed through the web page
on 2026-11-08 and passed every rig check ([hardware-log.md](hardware-log.md)).

## REA MCP server (for Claude Code, optional)

Only needed to reverse-engineer the firmware with an agent. Building, testing
and contributing work without REA, Ghidra or Claude Code.

REA gives the agent tools such as `open_binary`, decompilation and
cross-references. It is registered as a user-scope MCP server in
`~/.claude.json`, and needs the Ghidra and JDK locations in its environment:

```json
"rea": {
  "command": "npx",
  "args": ["-y", "rea-agents@6.8.0", "mcp"],
  "env": {
    "GHIDRA_INSTALL_DIR": "/Users/<you>/tools/ghidra_12.1.4_PUBLIC",
    "JAVA_HOME": "/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"
  }
}
```

Restart Claude Code after changing it. To verify the setup without the agent:

```bash
GHIDRA_INSTALL_DIR="$HOME/tools/ghidra_12.1.4_PUBLIC" npx -y rea-agents@6.8.0 doctor --client claude_code
```

All of REA's Ghidra checks should pass, including `native_decompiler`.

## Generated files

`work/` holds decoded images, disassembly, the Ghidra project
(`work/ghidra/`), decompiled functions (`work/decomp/`) and patched update
files (`work/patched/`, from `scripts/dev python -I tools/patch.py
patches/<name>.py`). All of it is git-ignored and can be regenerated with
the commands above.

## Planned additions

These are listed here so the setup stays complete as the work progresses
(see [PLAN.md](PLAN.md)).

| Tool | Phase | Purpose |
|---|---|---|
| Renode | 3b | optional full STM32 boot emulation |
