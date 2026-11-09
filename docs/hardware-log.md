# Hardware log

Every release flashed to a Summit, newest first, with what was checked on
it. See [hardware.md](hardware.md) for how a build gets to the synth and
how its row is recorded. The log is a record, not a merge gate.

- **One row per flash** from now on, naming the commit and the image
  SHA-256 that `scripts/build-image.sh` printed.
- **Builds before publication** (the rows below): the public repository
  starts from one squashed snapshot, so their `hw/` names are build names
  only, with no tag or commit behind them. The image SHA-256 identifies
  each build.
- **Before MPE v1**, stock firmware, a version-string patch, a version-word
  patch and five expression experiments were flashed and played on the same
  Summit (2026-10-31 and 11-01). What they showed is in
  [the findings](findings/summit-2.2-build2121.md) and
  [update-protocol.md](update-protocol.md#what-flashpy-runs-on-hardware-showed-2026-10-31-to-2026-11-08).
  Every image, stock and modified, booted, and the official file always
  restored stock.

All images below are firmware 2.2 (build 2121, FPGA 778) with the patch
applied, flashed with `tools/flash.py` or the web page (the Tool column). Each image's hash matched the build
before the flash, and the application came back reporting 2126.

| Date | Tag | Image SHA-256 | Tool | Result | Notes |
|---|---|---|---|---|---|
| 2026-11-08 | `hw/2026-11-08-web-flash-v1.2` | `28916b05a90e56f8091644031af03b01d1f7e10b0160ac2e6e1017ad8c08ac96` (MPE v1.2 built in the dev image with Arm GNU Toolchain 15.3.rel2; 8,889 messages with header and final) | web page (`web/`, local dev server), Vivaldi 8.3 on macOS | ok: "synth back: Summit firmware 2126, as in the file header; FPGA 778", 19.2 s end to end. Boot screen `MPE3 Ver 126.778` (user check). Kept on the synth | First flash through the web page. It worked only after a browser restart: before it, Web MIDI passed no input on and the page stopped with "no identity reply" before sending anything ([web.md](web.md#first-hardware-flash-2026-11-08)). 9,105 requests for 8,887 blocks (218 repeats, handled). **Rig (2026-11-09), all pass, same values as `199f1903…`:** `slide_right_note` +199.51 c, USB and DIN; stage 2 57/57; stage 3 68/68, B1 0 of 300; stage 4 USB and DIN 6/6. By ear R1–R4 fine (user, 2026-11-09). CH CLASH (stage 3 info row) not looked at. Log: `work/flash-web-v1.2-2026-11-08.log` |
| 2026-11-08 | `hw/2026-11-08-mpe-v1.2` | `199f190379852939b2903b155e1644249a80e6e2056be4f220c07047f4a74942` (MPE v1.2, 8,887 messages) | `tools/flash.py` | ok. Boot screen `MPE3 Ver 126.778`. **Slide works again and idle voices still rotate.** Kept on the synth | Test rig, USB and DIN, all pass: stage 2 57/57, stage 3 68/68 (B1 0 of 300), stage 4 6/6. By-ear checks fine |
| 2026-11-08 | `hw/2026-11-08-mpe-v1.1` | `5f6c5e57e21acb85111e7d7b2a05626a2f7486a9302c69b660ca98a6c941081b` (MPE v1.1, 8,885 messages) | `tools/flash.py` | partly: boot screen `MPE2 Ver 126.778`; **idle voices rotate, but Slide does nothing** | Rig: stage 2 56/57 (`slide_right_note` +0.00 c), stage 3 68/68, stage 4 5/6. Cause: v1.1's late-tick guard on Slide (inferred); fixed in v1.2 |
| 2026-11-02 | `hw/2026-11-02-mpe-v1` | `eacd0a220cd946f1acd8b5840c8aa9d7becfea3b085e35d1cf9fd5cc9f1741bd` (MPE v1, 8,873 messages) | `tools/flash.py` | ok. Boot screen `MPE1 Ver 126.778`. Played from Ableton Live/Push 3 and a Squarp Hapax, Single and Multi mode | Every step of the run plan ok. One stuck note with Live over DIN (DIN overrun; none over USB, so use USB for Live, [mpe-design.md](mpe-design.md#connecting-senders)). B1: twice, the first chord after a Hapax zone change played one note fewer; not reproduced since. MPE off sounds as stock |
