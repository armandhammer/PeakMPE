# Web patcher (`web/`)

A static page that lets a Summit owner apply the MPE patch to their own copy
of the official firmware and flash it, all in the browser. TypeScript, Vite
and Tailwind CSS; no server, so it can be hosted on GitHub Pages.

**Status:** first version. Flashed a real Summit once, on 2026-11-08
(Vivaldi 8.3 on macOS, [run below](#first-hardware-flash-2026-11-08));
otherwise tested against a simulated bootloader. The page's concept is settled in
[Decisions](#decisions-2026-11-08).

## The Peak page (2026-11-12)

The same page patches the Peak when opened with `?synth=peak` (the default
stays the Summit). [`src/product.ts`](../web/src/product.ts) holds what
differs per synth: the descriptor (`patches/mpe.json` for the Summit,
`patches/peak-mpe.json` for the Peak, exported from `patches/peak_mpe/`),
Novation's download (catalogue id 155 for Peak 2.2), the build, the version
the stock application reports, the FPGA build that goes with 2.2 (Peak 469)
and what a Components backup covers (no Multis on the Peak). The page text
in `src/content.ts` names the synth through `{synth}`-style placeholders,
filled by `contentFor()`; a line under the subtitle links to the other
synth's page. The flash protocol already knew the Peak (identity templates,
product id `00 7E`).

**Status:** the parity test builds the Peak descriptor's output byte for byte
from the official file. The output (`bc3bf703…`) carries the per-zone master
bend fix found with the rig on 2026-11-12; the image before the fix
(`c961f3a1…`) was flashed and tested, and so was the fixed one on
2026-11-13 (136 rig rows pass, [hardware log](hardware-log.md)). The page itself has not flashed a Peak yet: the
flashes so far used `tools/flash.py`. The name the Peak download arrives
with (`peak-firmware-2108.syx`) is inferred from the Summit's pattern; the
page checks the file's hash, not its name.

## How it works

1. **Download.** Novation's API sends no CORS headers, so the page can't
   fetch the firmware. It links to
   `https://components.novationmusic.com/api/v2/firmwares/154/file`, which
   redirects to the `.syx` as a download (`summit-firmware-2121.syx`). The
   user then drops that file on the page. The site never hosts or proxies
   Novation's firmware.
2. **Verify.** The file's SHA-256 must be the official 2.2 build 2121's
   (`83b28931…d249396f`). Any other file is refused, with its hash shown.
3. **Patch.** `src/core/patcher.ts` decodes the SysEx container
   (`src/core/syx.ts`, a port of `tools/syx.py`). It checks the decoded
   image's hash, applies the descriptor's writes, and fills the extension
   with `0xFF`. Then it re-encodes and checks the output image and `.syx`
   hashes against the descriptor (`28916b05…` for MPE v1.2 as the dev image
   builds it; [SETUP.md](SETUP.md#reproducible-patch-bytes)). On any mismatch
   it throws, and the page offers neither a download nor a flash.
4. **Flash** over Web MIDI (`src/flash/`), or download the modded `.syx` for
   another tool.
5. **Restore.** The same flasher sends the verified official file unchanged.

Every action that touches firmware stays disabled until the user ticks the
disclaimer (unticked by default) and clicks *Accept and continue*. Flashing
and restoring also need the **backup confirmation**: the user backs up their
patches and Multis with Novation Components, ticks the backup checkbox
(unticked by default) and clicks *Confirm backup*. Building or downloading
the modded file doesn't touch the synth, so it doesn't need the backup. Both
confirmations are kept in memory only, so a reload asks again. The flasher asks
once more, in a dialog, after it has identified the synth and before it sends
anything that reboots or writes it.

## The descriptor

The browser can't run `arm-none-eabi-gcc`, so `tools/web_descriptor.py`
exports what `tools/patch.py` builds:

```bash
scripts/dev python -I tools/web_descriptor.py export patches/mpe/patch.py web/patches/mpe.json
```

`web/patches/mpe.json` (committed, about 16 KB) holds:
- the version metadata;
- the SHA-256 and length of the official `.syx` and of its decoded image;
- the same for the expected output;
- `header`: `null` keeps the official `0x71` header;
- `writes`: the address and base64 bytes of every run our patch writes, from
  byte patches, hook instructions and the compiled blob.

Re-run the export after any change to `patches/mpe/`;
`tests/test_web_descriptor.py` fails while the committed file is stale.

### The descriptor holds no Novation bytes

`tools/web_descriptor.py check` proves it for a descriptor file, and the
export runs the same check before writing:

```bash
scripts/dev python -I tools/web_descriptor.py check web/patches/mpe.json --definition patches/mpe/patch.py
```

1. **Fixed keys.** The JSON has exactly the known keys, so no field can carry
   extra data. Original bytes appear only as SHA-256 hashes of the whole file
   and image, never per patch site. A hash of a few bytes could be
   brute-forced back into them.
2. **Every in-image byte differs from stock.** A run never contains a byte
   equal to the official byte at its address: bytes a patch leaves unchanged
   are dropped from the export. Bytes past the official image end (the blob)
   have no original.
3. **No shared runs.** No run of 16 or more write bytes occurs anywhere in
   the official image or the official `.syx`. Aligned 32-bit words that point
   into the firmware's memory map (flash `0x0800…`, SRAM `0x2000…`,
   peripherals) split the runs. The blob's literal pools hold the addresses
   of firmware functions and variables it calls or reads, and the firmware's
   own literal pools hold the same addresses. Those are interface facts, not
   copied content.
4. **Same output.** Rebuilding from the descriptor gives `tools/patch.py`'s
   output exactly.

Result for MPE v1.2 as the dev image builds it (Arm GNU Toolchain
15.3.rel2, 2026-11-08):

```
writes  64 runs, 5580 bytes (164 inside the official image, all differing from it; 5416 past its end)
shared  longest run of write bytes also in the official image or .syx: 7 bytes (limit 15) with 307 firmware-address words as separators; 16 bytes without separating them
output  rebuilt 391087 bytes, sha256 28916b05a90e56f8091644031af03b01d1f7e10b0160ac2e6e1017ad8c08ac96 as declared
check   ok: no Novation bytes in the descriptor
```

(The image flashed and verified as v1.2, `199f1903…`, was built with
Homebrew's GCC 16.2.0; its blob is 5,372 bytes. The source is the same.)

The 16-byte run without separators is four consecutive RAM addresses in the
blob's literal pool (`0x200161A4`, `0x20004B20`, `0x20004B28`, `0x200138A0`),
which the stock code at `0x0800FFD0` also loads.

**Limit of check 3:** the separator test looks only at a word's value, so a
pair of Thumb instructions that happens to read as such a word (for example
`movs r0, #…` = `0x20xx`) also splits a run. That makes the check
conservative in what it reports, not stricter. Using the ELF's `$d` mapping
symbols to split at literal pools only would tighten it.

`tests/test_web_descriptor.py` also checks that the check rejects a copied
stock byte, a 32-byte stock run pasted into the blob, and an extra field.

## Flashing

`src/flash/protocol.ts` ports `tools/flash.py` and
[update-protocol.md](update-protocol.md):

1. **Identify.** Send the identity request to the `Summit` port and refuse
   any device other than a Summit.
2. **Confirm, then reboot.** After the dialog, send the file's `0x71` header
   to the app port, then wait up to 12 s for `Summit Bootloader` and 100 ms
   more.
3. **Transfer.** Identify the bootloader, then send stop-and-wait: one
   message per device `0x72` request. The counter is the number of messages
   received. A request is answered only if `t > last || t == 0`, so repeats
   are ignored. 10 s per request covers the ~3.4 s erase pause after block 1.
   On a timeout it stops, with no retries, and says to restart from the
   beginning in bootloader mode.
4. **Restart.** After the final `0x73`, wait for the app port and retry the
   identity request (2 s each, up to 30 s). The page reports the version and
   whether it matches the file header.

If `Summit Bootloader` is already there (manual entry), it skips steps 1–2:
that is the recovery path.

`src/flash/fake.ts` is a simulated Summit, modelled on `flash.py`'s
`SimulatedSynth` and the hardware captures: the bootloader appears after a
delay, the counter counts messages received, some requests repeat, there is
an erase pause after block 1, and the restarted app ignores its first
identity requests. It can also stall or send a CRC report. The tests use it,
and so does the page's *Practice with a simulated Summit* mode, which sends
no MIDI.

`src/flash/webmidi.ts` asks for `requestMIDIAccess({ sysex: true })` only
when the user starts a real flash. Browser support:
- Chrome and Edge work.
- Firefox works after a site-permission prompt.
- Safari has no Web MIDI; the page says so and offers only practice mode.
- Vivaldi 8.3 (Chromium 152) on macOS flashed the Summit on 2026-11-08, but
  only after a browser restart. Before it, the page stopped with "no
  identity reply on "Summit"" (observed): the browser's identity request
  reached the synth, and the synth answered (`tools/midirec.py` recorded
  the reply), but the browser's Web MIDI passed nothing on, on any input,
  for several tries and a USB replug. SysEx through the IAC loopback bus
  still arrived. Quitting and reopening the browser fixed it. Cause
  unknown; a stale MIDI service in the browser is a guess (inferred). The
  page now shows its own panel for this case (FlashError code
  `no-identity`, raised only before anything that changes the synth is
  sent): nothing was changed, restart the browser and try again.
- On Windows, a MIDI port can be open in one app only, so close Components
  and the DAW first.

## Run it locally

Node runs in the dev image ([SETUP.md](SETUP.md)); the first `npm` command
runs `npm ci` there. The dev server listens inside the container, so
publish its port and bind it to all of the container's interfaces:

```bash
DEV_PORTS=5173 scripts/dev npm --prefix web run dev -- --host 0.0.0.0 --port 5173 --strictPort
```

Open <http://localhost:5173/> in the browser on the Mac (Web MIDI needs
https or localhost; the port is published on 127.0.0.1 only).

`scripts/dev npm --prefix web run build` type-checks and writes the static
site to `web/dist/`; `npm run preview` serves that build (same flags as
`dev`).

For a browser test with the real file without picking it by hand, set
`SUMMIT_DEV_FIRMWARE_DIR` (for example `SUMMIT_DEV_FIRMWARE_DIR=firmware`)
in front of the dev server command. `scripts/dev` mounts that folder
read-only, and the dev server serves it under `/@fs/`. This is dev only;
the build never contains it.

## Tests

The web package's tests run with vitest, under Node, in the dev image:

```bash
scripts/dev npm --prefix web test
```

- `test/syx.test.ts`: the codec, with vectors from `tools/syx.py`.
- `test/patcher.test.ts`: the hash gates, on a synthetic image.
- `test/flash.test.ts`: the protocol against the fake bootloader. It covers
  the reboot path and the recovery path, repeated requests, the erase pause,
  a decline, a Peak, a stall, a CRC report, an app that doesn't come back,
  and a version mismatch.
- `test/parity.test.ts` (local only): runs the TS patcher on
  `firmware/summit-firmware-2.2-build2121.syx`. It compares the result byte
  for byte with `tools/patch.py`'s `.syx` (run from `$SUMMIT_PYTHON`, which
  the dev image sets to its Python, else `.venv/bin/python`, else
  `python3`). It also flashes the patched and the
  official file into the fake bootloader. Without the firmware it is skipped
  and prints the reason. `npm run test:parity` runs it alone.

The parity test sits in the web package's `npm test`, **not** in pytest, so
the Python suite needs no Node. `tests/test_web_descriptor.py` (pytest)
covers the Python side.

## Deploying to GitHub Pages

The page is deployed by the **Release** workflow
(`.github/workflows/release.yml`), never on a push. The maintainer runs it
by hand (Actions → Release → Run workflow; only people with write access
can) with two inputs:

- `version`, for example `v1.2`. It must match the descriptor's `version`
  and not exist yet as a tag or a release.
- `dry_run` (on by default): everything up to the page build, then stop.

The run:

1. **Checks the version,** and that a real release runs from `main`.
2. **Runs the CI checks** (`ci.yml`) with the firmware required: a failed
   download from Novation fails the release instead of falling back.
3. **Builds the page** in the dev image:
   - the footer's source link comes from `VITE_SOURCE_URL`, set to
     `$GITHUB_SERVER_URL/$GITHUB_REPOSITORY`, so a fork's page links to the
     fork. A local build has no URL and says "Local build";
   - `built.commit` in the bundled descriptor is stamped with the released
     commit (12 hex digits). The committed `web/patches/mpe.json` keeps
     `null` there; `tests/test_web_descriptor.py` ignores `built`;
   - the job fails if `web/dist/` holds a `.syx`, `.bin` or `.elf` file, or
     lacks the link or the commit. Then `web/dist/` is uploaded as the Pages
     artifact.
4. **Unless it is a dry run:** creates the tag `version` on the commit and
   the GitHub Release (notes with the image SHA-256; no firmware or `.syx`
   attached), then deploys the artifact with `actions/deploy-pages`.

One-time setup: *Settings → Pages → Source: GitHub Actions*. `base: "./"`
in `vite.config.ts` makes the build work under any path, such as
`https://<user>.github.io/<repo>/`.

The published site distributes the patch (our code), never firmware.

## First hardware flash (2026-11-08)

The MPE v1.2 image built in the dev image (GCC 15.3, SHA-256 `28916b05…`,
tag `hw/2026-11-08-web-flash-v1.2`), flashed from the page on a local dev
server (`npm run dev` in the dev image, port 5173) in Vivaldi 8.3 on macOS.
Row in [hardware-log.md](hardware-log.md). All observed, from the page's
log and the user's report:

- **First tries failed** with "no identity reply on "Summit"": Web MIDI
  passed nothing on until the browser was restarted (see the Vivaldi bullet
  under [Flashing](#flashing)). Nothing was sent past the identity request.
  The page now shows its own panel for this.
- **After the restart, 19.2 s end to end:** identity and FPGA (778) at
  0.01 s; reboot request at 1.2 s; bootloader port and identity at 2.3 s;
  the erase pause after block 1, 3.35 s; the last block and the final
  message at 16.5 s; the application answered at 19.2 s ("synth back:
  Summit firmware 2126, as in the file header; FPGA 778").
- **Requests:** 9,105 for 8,887 blocks. The 218 repeats (about one every 41
  blocks) were ignored as designed; no block went twice.
- **After:** boot screen `MPE3 Ver 126.778`. The test rig passed every
  stage over USB and DIN with the same values as the GCC 16.2 build, and
  the by-ear checks were fine.

UX ideas from the run, not built:

- The browser-support text names Chrome and Edge, but only Vivaldi has
  flashed a Summit. Say which browsers were tried on hardware.
- The erase pause after block 1 (3.4 s) shows as a frozen progress bar.
  A line such as "the synth is erasing its flash" would explain it.
- Show the elapsed time or an estimate during the transfer (about 15 s).
- In the `no-identity` case, the page could offer to retry without a
  reload once the browser is back.

## Decisions (2026-11-08)

The owner's answers to the first version's open questions:

| Question | Decision |
|---|---|
| When to publish | GitHub Pages, deployed by the release workflow (decided 2026-11-09) |
| Versions offered | Only the latest MPE firmware: re-export the descriptor when a new version lands on `main` |
| License | MIT (`LICENSE`), as added |
| Disclaimer wording | Kept as it is: no legal review, English only |
| Persisting the confirmations | No: they reset on every reload; no cookies or storage |
| A dropped modded file | Refused: the page always builds the mod from the official file |
| MPE user guide on the page | Not needed |
| Success and failure | A large result panel after every flash (done, version mismatch, no answer, stopped, cancelled), with next steps and a link to Recovery |
| Detailed Components backup steps | Not needed |
| FPGA | Checked: see below |

### FPGA check

The flasher asks the application for its FPGA build twice: when it first
identifies the synth, and after the restart. It uses the query Components
sends on every connect (`F0 00 20 29 00 7C 01 33 44 00 … F7`,
[update-protocol.md §1](update-protocol.md#fpga-version)). The reply's bytes
11–14 are the digits, least significant first; the Components capture shows
`08 07 07 00` = 778. The query is ported from the documented protocol and
tested on the captured reply only; `tools/flash.py` doesn't send it.

If the restarted synth reports a build older than 778, which goes with
firmware 2.2, the result panel says so and points to Novation Components for
the FPGA update. If it doesn't answer, the panel says the version is unknown.
The page never sends or modifies FPGA data, and the check never blocks a
flash.
