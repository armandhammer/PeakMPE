# Recovery: getting back to stock firmware

Read this before flashing anything modified. Source: the instructions in the
Components app ([update-protocol.md §7](update-protocol.md#7-firmware-vs-fpga-and-recovery-instructions)).
**Manual bootloader entry confirmed on our unit on 2026-10-31** (see
[hardware-log.md](hardware-log.md)). Re-flashing from that state with our own
tool hasn't been tried yet.

## Why recovery should always be possible

- The bootloader lives in flash below `0x0800C000`. Updates never write there,
  and our tools refuse to.
- The update sends the vector table (the `0x73` block) **last**. An
  interrupted or stalled transfer leaves an application that never starts,
  but the bootloader still runs.

The open risk is a modified image that **does** start but then hangs or
misbehaves before USB comes up. The manual entry below should still work in
that case, presuming the bootloader checks the buttons before it starts the
application. It works on our unit with stock firmware installed; we haven't
tested it with a broken application.

The bootloader sends **no** CRC or status reports over MIDI (live capture).
So if it rejects an image, the only sign is that the application never comes
back. Then use the manual entry below. (It accepted every modified image so
far: the version-string and version-word patches and a downgrade from 2127
back to stock on 2026-10-31, and the two longer bend experiment images,
8,727 and 8,725 messages, on 2026-11-01.)

## Manual bootloader entry

1. Power the Summit off.
2. Hold the **three buttons to the left of the screen**, and power it on.
3. The synth enumerates as **`Summit Bootloader`** over USB.

## Re-flashing stock firmware

Either of these works:
- **Novation Components:** open the Summit page and run the update. When the
  bootloader is already active, Components goes straight to the transfer.
- **Our tool**, using the official, hash-checked file:

  ```bash
  scripts/fetch-firmware.sh
  ```

  ```bash
  .venv/bin/python -I tools/flash.py flash firmware/summit-firmware-2.2-build2121.syx
  ```

  It detects the `Summit Bootloader` ports and uses the recovery path.

After the reboot, check the version: the Settings menu, or
`tools/flash.py identify`. `flash.py` also compares it with the file header
itself. Coming back from a patch that raised the version (2127), stock is a
downgrade. The application can't refuse it (it reboots after the first 7
header bytes), and the bootloader doesn't either: it accepted stock over 2127
on 2026-10-31 (observed); see the
[version word patch](findings/summit-2.2-build2121.md#version-word-patch-on-hardware-2026-10-31). If the FPGA version is behind, Components offers a
separate FPGA update. Our tools never touch the FPGA.

## If the transfer stalls

`tools/flash.py` stops after 10 s without a request from the device. It
reports the last counter and block number. Power-cycle into the bootloader as
above, and start the whole update again from the beginning.

Record every recovery in [hardware-log.md](hardware-log.md).
