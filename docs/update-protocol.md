# Firmware update protocol (Novation Components → Summit)

How Novation Components flashes a Summit. Worked out first by **static
analysis of the shipped web app**. Then **confirmed by a live MIDI Monitor
capture** of a stock Summit 2.2 update (2026-10-31, see
[Live capture](#live-capture-2026-10-31)). The capture is git-ignored because
it contains the firmware bytes.

**Source analysed** (fetched 2026-10-31 into the git-ignored `work/components/`):

| File | SHA-256 (prefix) | Contents |
|---|---|---|
| `https://components.novationmusic.com/assets/main-D3lNZfPT.js` | `2322dc9fd409e591` | the app (Ember), all device classes and the updater |
| `/assets/decode-worker-cLhwFYVI.js` | `9fe51cd33169ed50` | Web Worker that splits the `.syx` into messages |
| `index.html` `<meta>` config | | `FIRMWARE_UPDATE_TIMEOUT: 10000`, `MAX_WAIT_FOR_RESET_TIMEOUT: 8000` |

The bundle is minified, so the names below are the minified ones. They change
with every Components release. The string constants (log messages, error
keys, enum names) are stable and are the way to find the same code again.

| Minified name | What it is | Anchor string to grep for |
|---|---|---|
| `H1` | base MIDI device class | `rebootToBootloader`, `" Bootloader"` |
| `Kae` | Summit device class | `productName="Summit"` |
| `Hae` | Peak device class | `productName="Peak"` |
| `s1` | firmware transfer state machine | `"Starting firmware transfer. State=%s"` |
| `o1` | per-device `firmwareUpdateConfig` defaults | `listenForDeviceStatusReport=!1` |
| `QEe` | firmware-updater UI component | `"Waiting for firmware version to be reported..."` |
| `hre` | FPGA updater | `"fpga-transmission-error"` |
| `EP` / `AP` | device status-report codes / log text | `"uploadFailedCompositionNotViable"` |
| worker `chunkFirmware` | `.syx` splitter | `"chunk-firmware"`, `"firmware-buffers"` |

---

## 1. Device identification

### Ports

The device's state comes **from the MIDI port names**, not from SysEx
(`H1.isBootloader` / `H1.isConnected`, `H1.status`):

- a port whose name contains `"Summit Bootloader"` → bootloader input/output;
- a port whose name contains `"Summit"` (and not `"… Bootloader"`) → main
  application input/output.

`status` is `"bootloader"` when a bootloader input+output pair is open,
`"present"` when a main pair is open, otherwise `"offline"`. All the waiting
in the updater ("wait until the device is in the bootloader", "wait until it
has rebooted") is waiting for these port names to appear or vanish.

### Identity request / reply

When an output port connects, the Summit class sends the Universal Device
Inquiry (`Kae.updateVersion`), to the main port or to the bootloader port,
whichever is open:

```
→ F0 7E 7F 06 01 F7
```

`Kae.handleVersionMessage` accepts a reply only if bytes 1–11 equal one of:

```
← F0 7E 7F 06 02 00 20 29 33 01 00 00 d0 d1 d2 d3 …   (device ID 7F, family 33 01)
← F0 7E 00 06 02 00 20 29 33 11 00 00 d0 d1 d2 d3 …   (device ID 00, family 33 11)
```

Peak (`Hae`) uses the same two templates with `7E 00` / `7E 10` in place of
`33 01` / `33 11`.

- Family code `33 01` is the 14-bit product ID LSB-first, i.e. `0x0133`. That
  is the same ID as the `.syx` header's `01 33` (MSB-first). Peak is `0x007E`
  (`7E 00` here, `00 7E` in its header). `Kae.productId` returns `[1, 51]` and
  `Hae.productId` returns `[0, 126]`, and every Novation SysEx the app builds
  for these synths uses them in that MSB-first order.
- The second template (member `33 11`, device ID `00`) is presumably the
  bootloader's reply. The app doesn't tell the two apart: the port name
  decides the mode.
- **Firmware version** = bytes 12–15, one decimal digit per byte, most
  significant first (`H1.versionFromBytes`): `02 01 02 01` → 2121. This
  number is compared with the catalogue `build` (`needsFirmwareUpdate =
  firmwareVersion < latestFirmwareVersion`).
- The Summit gets no bootloader version: only the legacy `F0 00 20 29 00 70
  F7` path reads one, and the Summit class overrides it.

### FPGA version

Sent to the main port after the firmware version has arrived
(`Kae.updateFPGAVersion`):

```
→ F0 00 20 29 00 7C 01 33 44 00 00 00 00 00 00 F7
← F0 00 20 29 00 7C 01 33 40 x x f0 f1 f2 f3 … F7
```

The reply is matched on bytes 1–8. The FPGA version is in bytes 11–14, one
digit per byte, **least** significant first (`fPGAVersionFromBytes`). The FPGA
file's own header carries the same `08 07 07 00` for build 778.

## 2. Entering the bootloader

**The app reboots the synth into the bootloader itself, by SysEx.** The user
only has to do it by hand in two cases (see §7).

For the Summit, `firmwareUpdateConfig = { sendToMainApplication: false,
waitForDeviceConfirmation: false, maxWaitForResetTimeout: 12000 }` and
`rebootTimeout = 15000`. In `s1.tryFirmwareUpdate`:

1. If `status === "bootloader"` already (the user booted it by hand), skip to
   the transfer.
2. If `status === "present"`, send **the first message of the firmware file**,
   the `0x71` header, to the *main* output (`s1.#Vi`):
   ```
   → F0 00 20 29 00 71 01 33 00 00 02 01 02 06 F7     (Summit 2.2 file header)
   ```
   Then wait, for up to `maxWaitForResetTimeout` = **12 s**, for `status` to
   become `"bootloader"`, which means the `Summit Bootloader` ports appear.
   If that doesn't happen, the error is `errors.firmware-process.timeout`.
3. Wait **100 ms**, then start the transfer on the bootloader ports.
4. Anything else (offline) → `errors.firmware-process.device-not-present`.

There is also a standalone `H1.rebootToBootloader()` with the short form
`F0 00 20 29 00 71 <pid hi> <pid lo> 00 00 F7` (`… 71 01 33 00 00 F7` for
the Summit), followed by a 5 s wait. The Summit update path doesn't use it;
it sends the full header from the file instead. So `0x71` addressed to the
running application means "reboot into the bootloader".

Before the transfer, `beforeFirmwareUpdate()` would send `F0 00 20 29 00 42
00 00 F7` to disable mass-storage mode, but only on devices with
`hasMsdMode`, which the Summit doesn't have.

## 3. Transfer: message sequence and flow control

### Splitting

The worker's `chunkFirmware` cuts the file at every `F0 … F7` pair, keeping
file order and leaving the bytes unchanged. Nothing is reordered, rewritten
or added: the device receives the file's own messages. The worker returns
them in batches of 10,000, which are concatenated. The Summit file is 8,719
messages: `0x71` ×1, `0x72` ×8717, `0x73` ×1.

### Sequence (bootloader ports)

```
App                                        Summit (bootloader)
 │── F0 00 20 29 00 71 01 33 00 00 02 01 02 06 F7 ─▶  header (message #0, again)
 │◀─ F0 00 20 29 00 72 c0 c1 c2 F7 ──────────────────  "send next" (10 bytes)
 │── F0 00 20 29 00 72 <37 septets> F7 ───────────▶  data block #1
 │◀─ F0 00 20 29 00 72 c0 c1 c2 F7 ──────────────────
 │   … one block per request, 8717 times …
 │── F0 00 20 29 00 73 <37 septets> F7 ───────────▶  final block (vectors 0x00–0x1F)
 │   (app stops listening: transfer complete)
 │                                       … device writes the vectors, reboots into the application …
 │── F0 7E 7F 06 01 F7 (on new main port) ────────▶
 │◀─ F0 7E 7F 06 02 00 20 29 33 01 00 00 v v v v … F7
```

So the transfer is **strictly stop-and-wait: one message in flight**. The app
has no fixed inter-message delay. It sends the next message only when the
device asks for it (`s1.#ji`, `s1.#Hi`, `s1.#$i`):

- After sending any message other than `0x73` (and other than the last
  message), the app restarts its timeout and waits.
- Device → app `0x72`, **10 bytes**: counter `t = c0 + (c1 << 7) + (c2 << 14)`.
  If `t > lastCounter` or `t == 0`, the app stores `t` and sends the next
  message. Otherwise (a repeated or older counter) it ignores the request.
  **The counter is only used as a monotonic gate. It never selects which
  block to send, and there is no resend or rewind.**
- Device → app `0x72`, **15 bytes** (an alternative format for other
  products): counter from nibbles, `e[7] + (e[6] << 4) + (e[5] << 8)` of
  bytes 6–13. Same gating.
- After the `0x73` (final) message the Summit transfer is complete
  immediately (`s1.#Wi`). `listenForDeviceStatusReport` is false for the
  Summit, so the app doesn't wait for an acknowledgement of the last block.

Messages are sent with WebMIDI `MIDIOutput.send(bytes)` with no timestamp,
which means "now". The only fixed delays in the Summit path are the 100 ms
after the bootloader appears and the polling intervals in §5.

### Device status reports (`0x73` from the device)

`s1.#Gi` handles device → app messages `F0 00 20 29 00 73 <code> x x F7`
(exactly 10 bytes) for every product, whether or not
`listenForDeviceStatusReport` is set:

| code | `EP` name | app log text (`AP`) | app action |
|---|---|---|---|
| `0x00` | initiateUpgrade | Entering "Initiate Upgrade" animation | log |
| `0x01` | waitingForUserConfirmation | Waiting for user confirmation | UI event |
| `0x10` | userCancelled | User cancelled the FW upgrade … | fail: `errors.firmware-process.user-cancelled` |
| `0x11` | waitingForUserConfirmationTimeout | … timed out … | UI event |
| `0x7C` | uploadFailedCompositionNotViable | **Device reported a CRC error**: Upload failed, composition is NOT viable | fail: `FirmwareUpdateFailedCRCError` |
| `0x7E` | uploadFailedCompositionViable | **Device reported a CRC error**: Upload failed, composition is viable | fail: same |
| `0x7D` | uploadSuccessfulCompositionNotViable | Upload so far successful but composition is NOT viable | log only |
| `0x7F` | uploadSuccessful | Upload so far successful and composition is viable | send next message, or finish |

This protocol is used by newer devices (Launch Control XL 3, FLkey 2 …,
configured with `listenForDeviceStatusReport: true`). The Summit config
doesn't enable it, which suggests **the Summit bootloader doesn't send these
reports**. But if it did send `7C`/`7E`, the app would abort with "Update
could not be completed".

## 4. Timing parameters

| Parameter | Value | Where it applies |
|---|---|---|
| Wait for bootloader ports after the reboot request | **12,000 ms** | `Kae.firmwareUpdateConfig.maxWaitForResetTimeout` (global default 8,000 ms) |
| Delay after bootloader ports appear | **100 ms** | `tryFirmwareUpdate` |
| Per-message request timeout | **10,000 ms** | `FIRMWARE_UPDATE_TIMEOUT` (`GQ`), restarted after every message sent |
| Pacing between blocks | none: the next block is sent on the device's `0x72` request | `s1.#$i` |
| Retries | **none** at the protocol level. On timeout the whole update fails; the user restarts it from block 0 | `s1`, `QEe.#Uh` (try-again prompt only for `waitForDeviceConfirmation` devices) |
| Wait for new firmware version after the transfer | poll every 500 ms, `rebootTimeout × 2 / 500` = **60 polls ≈ 30 s** | `QEe.waitFor` |
| Wait for `status === "present"` | another ≤ 30 s, same loop | `QEe.waitFor` |
| Wait before the FPGA check | 19 × 500 ms ≈ **9.5 s** for `ready && fPGAVersion` | `tryUpdateFPGA` |
| FPGA per-packet timeout | **10,000 ms** | `hre.updateTimeout` |
| `firmwareConfirmationTimeout` | 23,000 ms default, used only with `waitForDeviceConfirmation` (not the Summit) | `s1.#e` |

A port disconnect during `WAITING_FOR_PACKET_REQUEST` or
`FIRMWARE_TRANSFER_IN_PROGRESS` fails immediately with
`errors.firmware-process.device-disconnected`.

## 5. Success, failure and version checks

After the last block (`QEe.sendFirmwareToDevice`):

1. `waitForUpdatedFirmwareVersion` (default true): poll until
   `connected && firmwareVersion != null && !needsFirmwareUpdate`, i.e. the
   rebooted application answered the identity request with a version ≥ the
   catalogue's latest `build` (2121 for Summit 2.2).
2. `waitForReboot` (default true): poll until `status === "present"`.
3. Otherwise → error `iIe` → UI "**Unable to confirm update**: We couldn't
   reconnect to your Summit after the update…" (`errorState: rebootFailed`).

So **success is decided only by the identity reply after the reboot**.
Nothing during the transfer confirms the write. Failure states the UI tells
apart (`ZEe`): `timeout` ("No response from Summit"), `crc` ("Update could
not be completed"), `userCancelled`, `rebootFailed`.

**Version mismatch / wrong product:** the app does **not** compare the file
header's product ID (`01 33`) with the connected device. For the normal path,
the file is simply the catalogue entry for `product: "summit"`. Whether the
bootloader rejects a header with the wrong product ID is unknown. The only
content check anywhere is in the hidden drag-and-drop path (feature flag
`firmware-drag-and-drop`, enabled per user from the server's
`user.feature_flags`). It accepts a dropped local file only if `byte0 = F0`,
bytes 1–3 = `00 20 29`, `byte4 = 00` and `byte5 = 71`. The same flag also
exposes `window.installFirmware(buildOrVersion)`.

If the application never reports a version ("connected but no version
info"), the UI shows "It looks like your firmware is currently broken, this
could be due to an interrupted update process. Please try to update again."
with an Update button (`hasInvalidFirmware`).

## 6. Checksums and validation: what would reject a modified image

**The app computes and checks nothing over the firmware image.**

- `chunkFirmware` only splits at `F0`/`F7`. The worker's CRC-32 table and
  `checksum` code belong to the content-transfer paths (patches, samples,
  sessions: `upload-checksum-*`, `download-checksum-*`), not to the firmware.
- `rie()` downloads the file with a plain XHR and checks only for HTTP 200.
  There is no hash and no signature.
- The firmware messages themselves carry no checksum (see
  [firmware-format.md](firmware-format.md)).

So any rejection of a modified image would happen **on the device**.
**Answered for a small change (observed, 2026-10-31):** the Summit bootloader
accepts and boots an image with 15 changed bytes in the string data, with the
header and version word unchanged
([runs](#what-flashpy-runs-on-hardware-showed-2026-10-31-to-2026-11-08)). So it enforces no CRC or
signature over the whole image. **The version word and header digits
(observed, 2026-10-31):** it also accepts a changed version word at
`0x0800C1B0` with matching header digits (2127), and a downgrade back to
2126 ([runs](#what-flashpy-runs-on-hardware-showed-2026-10-31-to-2026-11-08)). Still not
ruled out: a check of only the vector table or the `MAIN` tag string, which
neither patch changed. The rest of this
section is the analysis from before that test. The
`EP` codes show that Novation bootloaders *can* report "CRC error,
composition (not) viable", but the Summit config doesn't listen for it. The
open questions are whether the Summit bootloader verifies a CRC (over what
data, and stored where), and whether it refuses to boot a bad image or
reports it. A modified image with **unchanged identity-reply digits** (2121)
would make Components report success. A lower number would make it report
"Unable to confirm update", even though the flash may have succeeded.

## 7. Firmware vs FPGA, and recovery instructions

**Order: firmware first, then FPGA.** The Summit firmware page wraps the
firmware updater in an FPGA wrapper whose `@afterCompleted` is
`tryUpdateFPGA`. After a successful firmware update, that waits ≈ 9.5 s for
the device to report `fPGAVersion`, then runs the FPGA update only if
`fPGAVersion < latest FPGA build` (778 for 2.1). If the firmware is current
but the FPGA isn't, the page shows a separate "Update FPGA" button.

The **FPGA update goes to the main application ports**, not the bootloader
(`hre.startUpdate`):

```
→ F0 00 20 29 00 7C 01 33 44 00 00 00 00 00 00 F7     start (= FPGA version request)
← … 7C 01 33 40 …   or   … 7C 01 33 42 …                → send next packet
← … 7C 01 33 41 p0 p1 …                                  page ack: if p0+(p1<<7) > last, send next
   (file: 7C 01 33 00 <count lo,hi> <ver digits>  start,
          7C 01 33 01 <page lo,hi> <ver> <data>   ×2373 (656 bytes each),
          7C 01 33 02 7F 7F <ver>                 end)
← … 7C 01 33 04 7F 7F v0 v1 v2 v3 …                      done: ok if bytes 9–10 = 7F 7F and version > 0,
                                                          else "fpga-transmission-error"
```

On success it shows "Please wait for your Summit to reboot". Our MPE work
doesn't touch the FPGA, and `tools/flash.py` should refuse `0x7C` files at
first.

**Manual bootloader entry, as shown by the app:** "Hold the three buttons to
the left of the screen while powering on your Summit to enter bootloader mode
and update your device" (with `summit-reboot-to-bootloader.*.png`). It's
shown when the running firmware is build **232** (Summit 2.0,
`R8e = {peak: 440, summit: 232}`), which presumably can't reboot itself on
`0x71`. Because `tryFirmwareUpdate` goes straight to the transfer when
`status` is already `"bootloader"`, this manual entry is also the **recovery
path** for a Summit whose application doesn't start: the bootloader at
`< 0x0800C000` isn't touched by the update and enumerates as `Summit
Bootloader`.

Other recovery text: the "No response" dialog says "Disconnect and reconnect
or restart the device, then try again", and links to Novation's support
article "I am unable to update my firmware using Novation Components".

---

## Live capture (2026-10-31)

A stock Summit 2.2 update by Components, recorded with Snoize MIDI Monitor:
- **Source:** `work/capture/fw_update_log_from_components.mmon`, which is
  git-ignored. `tools/mmon.py log` exports it.
  - **Overwritten (2026-10-31 19:05):** the `.mmon` was later replaced by
    other recordings. This run survives only as its text export,
    `work/capture/components-update.log` (17,659 lines).
    `tests/test_flash_capture.py` uses that export as its reference.
  - **Two later Components re-recordings (19:38, 19:41) are incomplete:**
    - MIDI Monitor attached to the newly appeared `Summit Bootloader` ports
      only after the erase pause had started;
    - so the bootloader identity exchange, the resent header, request 1 and
      block 1 are missing (19:41: 8,717 of 8,719 messages; 19:38 also lacks
      the reboot header);
    - what they do contain matches this run: erase pause 3.45 s, blocks
      ~9.9 s, application back 5.8 s after `0x73`, 2126, FPGA 778.

    Catching the bootloader's first messages depends on timing. A complete
    recording of the bootloader's start isn't guaranteed by re-recording.
- **Monitored:** the spy on the `Summit` destination, the `Summit` source and
  `Summit Bootloader` (both directions).
- **Size and length:** 17,659 messages over 32.7 s.

`tests/test_flash_capture.py` replays the bootloader's side into
`flash.Transfer`. It produces **exactly the 8,719 messages Components sent**.

| t (s) | Port | Direction | Message |
|---|---|---|---|
| 0.04 | Summit | ← | identity reply `… 33 01 00 00 02 01 02 06` → version **2126** |
| 0.05 | Summit | → ← | FPGA version query `7C … 44`, reply `… 40 45 12 08 07 07 00` (FPGA 778) |
| 12.36 | Summit | → | the file's `0x71` header (the user clicked Update). The application doesn't reply |
| 13.25 | Summit Bootloader | → | identity request, then the `0x71` header again. The ports appeared within ~0.9 s |
| 13.52 | Summit Bootloader | ← | identity reply `7E 00 06 02 … 33 11 00 00 02 01 02 06` → template 2, **2126** |
| 13.53 | Summit Bootloader | ← → | first request (counter **1**), block 1 |
| 16.94 | Summit Bootloader | ← | counter 2 after a **3.4 s pause** (presumably the flash erase) |
| 16.9–26.8 | Summit Bootloader | ← → | blocks at ~1 ms each (send → request: median 0.9 ms, p99 5 ms) |
| 26.83 | Summit Bootloader | → | final `0x73` block. **Nothing comes back** |
| 32.62 | Summit | ← | application restarts (CC resets, then identity reply 2126, FPGA 778). Components didn't re-flash the FPGA |

### Answers to the former open questions

1. **Port names:** `Summit` and `Summit Bootloader`, as MIDI Monitor
   reports them. python-rtmidi's names still need checking on first use;
   `flash.py ports` lists them.
2. **Identity replies:**
   - application: `F0 7E 7F 06 02 00 20 29 33 01 00 00 02 01 02 06 F7`;
   - bootloader: `F0 7E 00 06 02 00 20 29 33 11 00 00 02 01 02 06 F7`.

   So the `33 11` / device-ID-`00` template **is** the bootloader's. Nothing
   follows the version digits. Its digits are the installed application's
   version word, not the bootloader's own: it reported 2127 with the
   version-word patch installed
   ([run](#what-flashpy-runs-on-hardware-showed-2026-10-31-to-2026-11-08)).
3. **Request counter:**
   - It's the **number of messages received so far**: 1 after the header,
     8,718 after the last data block. It never decreases or skips.
   - The first request comes **after** the header, not unprompted.
   - The bootloader **repeated a request 197 times**, roughly every 45 blocks
     (counters 36, 82, 128, …). The `t > last` gate is what keeps Components
     from sending a block twice. Without it, the stream would be corrupted.
   - Longest wait: 3.4 s, after block 1. The 10 s timeout leaves enough
     headroom.
4. **After `0x73`:** nothing from the bootloader. The application answered
   ~5.8 s later. Its port name is back earlier, see
   [the `flash.py` run](#what-flashpy-runs-on-hardware-showed-2026-10-31-to-2026-11-08).
5. **Status reports:** none at all. The Summit bootloader doesn't report CRC
   results over MIDI, so a rejected modified image would only show as an
   application that doesn't come back. The recovery path covers that.
6. **Header digits `02 01 02 06`:** the application and the bootloader both
   report **2126**, the same digits as the file header. The catalogue's 2121
   is only a label. Components accepts 2126 ≥ 2121.
7. **Reboot on the full header:** yes. The application doesn't answer before
   rebooting.
8. **Bootloader product check:** still unknown. Not testable without risk,
   and the capture can't show it.
9. **Message integrity:** all 44-byte messages arrived intact (MIDI Monitor
   reassembles them). rtmidi preserves them too: in the `flash.py` run,
   MIDI Monitor saw the file byte for byte.

## What `flash.py` runs on hardware showed (2026-10-31 to 2026-11-08)

Stock, modified and longer images, flashed with `tools/flash.py` and, for
the first run, recorded with MIDI Monitor as well (the recordings are
git-ignored: they contain the firmware). **Observed** unless marked
otherwise.

- **Same exchange as Components:** the same 8,719 messages, byte for byte,
  for the stock file; requests 1 … 8,718, never decreasing; an erase pause
  of about 3.4 s after block 1; header to final `0x73` in about 15.6 s
  (Components 13.6 s: `flash.py` turns a block round about 0.3 ms slower,
  harmless). No status reports in any run.
- **Repeated requests** come about every 50 ms in every run (every 35 to 45
  blocks, depending on the host's speed), so the bootloader presumably
  re-sends a pending request on a timer (inferred). The counter gate handles
  every repeat.
- **After `0x73`, the port comes back before the application answers.**
  python-rtmidi lists `Summit` again about 2.1 s after `0x73`; on some days
  the application answered only at +5.8 s, on others the first request at
  +2.2 s, stock included (unexplained). At boot it sends CC resets
  (`B0 40/42/0B/02 00`, `B0 78 00` ×3, `DF 00 00`) and then an identity
  reply. `flash.py` therefore re-finds the port, reopens it and retries the
  identity request, for up to 15 × 2 s.
- **The synth's "100% received" runs ahead:** it shows when about 60% of the
  blocks have been sent, with Components as with `flash.py`. Every block
  carries data, so the bootloader's percentage uses another denominator
  (inferred). Wait for the tool, not the display.
- **Modified images boot:** 15 changed label bytes, a changed version word
  with matching header digits (2127), and images up to 8,887 messages long
  (the bootloader simply asks for more blocks). See
  [section 6](#6-checksums-and-validation-what-would-reject-a-modified-image).
- **No downgrade check:** the official 2126 file installs over 2127.
- **The bootloader's identity reply carries the installed application's
  version word**, not a version of its own (`33 11 00 00 02 01 02 07` with
  2127 installed).
- **zsh:** `read -p "…"` fails there; `read "?done, press enter"` keeps a
  terminal tab open after a run.

## Requirements for `tools/flash.py`

Behave exactly like Components, and stricter where Components trusts the file:

1. **Input validation before any MIDI is opened:** decode with `tools/syx.py`.
   Require exactly one `0x71` first, `0x72` blocks, and exactly one `0x73`
   last, with all bodies the expected length. Refuse `0x7C` (FPGA) files
   unless an explicit `--fpga` mode exists later.
2. **Product check:** header bytes `01 33` must match the connected device's
   identity reply (family `33 01`). Refuse otherwise. Never send a Peak
   (`00 7E`) image to a Summit.
3. **Port selection:** find the ports by name, `Summit` vs `Summit Bootloader`,
   the same substring rule as the app. `--port` overrides it; with several
   matches, list them and stop.
4. **Identify:** send `F0 7E 7F 06 01 F7` and accept the reply only if it
   matches one of the two Summit templates. Print the firmware version
   (bytes 12–15 as decimal digits) and, from the main port, the FPGA version
   (`7C 01 33 44 …`).
5. **Enter the bootloader** like Components: if only the main ports exist,
   send the file's own `0x71` header to the main output, wait ≤ 12 s for the
   bootloader ports, then wait 100 ms. If the bootloader ports are already
   there, skip this step (the manual-entry/recovery path).
6. **Transfer:** ask the bootloader for its identity (as Components does)
   and refuse if it isn't the file's product. Then send the messages in file
   order, starting with the header again, **one message per device `0x72`
   request**. Gate on the counter
   exactly as `s1.#$i` does (`t > last || t == 0`). Use a 10 s timeout per
   request. Parse the 15-byte request variant too. Treat a device `0x73`
   `7C`/`7E` as fatal, and `10` as cancelled. Abort on port disconnect.
7. **No retries in the middle of the transfer:** on timeout, stop. The
   vectors are only written by the final `0x73`, so the safe recovery is to
   restart the whole update from the header, in bootloader mode. Report the
   last counter and block index so a stall can be diagnosed.
8. **After `0x73`:** stop sending. Wait ≤ 30 s for the main ports, then
   re-identify, retrying for up to another 30 s: the port is back ~4 s before
   the application answers. Report the new version. Success = the
   application answers. If it reports a lower version than the file, say so,
   but don't call it a flash failure. (Implemented as a comparison with the
   header digits: `flash.py` says whether the reported version matches.)
9. **`--dry-run`:** do everything except open an output port. Print the
   planned sequence and counts, and simulate the request loop.
10. **Logging:** optionally record every byte sent and received
    (timestamped) to `work/`, so a run can be compared with a Components
    capture.
11. **Never send** the standalone `0x71 … 00 00` reboot, `0x42` (MSD) or any
    `0x7C` message in firmware mode. Never write anything that targets the
    bootloader region.
