# Using the simulator

`emu/synth.py` is a simulated Summit: MIDI goes in, the real firmware (stock
or patched) processes it, and out come the writes to the FPGA and the MIDI
the Summit sends. It's the test bed for the MPE patch: every patch is played
here before anything is flashed.

It needs the venv and the official image ([SETUP.md](SETUP.md)). Tests that use
it skip when `firmware/` is absent.

## What runs

The firmware's own `main`: the reset path, main's initialisation, then the
endless main loop. TIM6 (20 kHz: the 1 kHz modulation tick and the FPGA
queue drain), USART6 (DIN MIDI) and EXTI15 interrupt it, on a virtual clock:
50 µs slots of 6000 instructions, so 120 MHz at one instruction per cycle.

| Part | Level | Notes |
|---|---|---|
| FPGA writes | **peripheral**: SPI1 frames + GPIOB chip selects | decoded into `(time_ms, engine, target, param, value)`; any route a patch takes to SPI1 shows up the same way |
| DIN MIDI in/out | **peripheral**: USART6 data register and interrupt | 320 µs per byte |
| DataFlash (settings, patches) | **peripheral**: SPI4 + GPIOE, AT45-style model | blank at first; the firmware's own factory initialise formats it once, cached in `work/cache/dataflash/` (`emu/cache.py`) |
| USB MIDI in/out | **endpoint buffers** in RAM (fallback; no OTG core) | in: packets into the OUT buffer once per 1 ms frame, at `usb_phase_us` into each ms (default 0, on the tick's boundary; a real host's frames aren't locked to the Summit's timer, so tests sweep it), one 50 µs slot later if the main thread is inside `usb_out_poll` then (it loads the received count and the read index separately; a buffer written between the loads replayed the old buffer's packets, found 2026-11-08); out: taken when the firmware starts an IN transfer |
| FPGA replies | **model, inferred** | envelope state per voice for `voice_alloc` (idle/released = 3, attack 0 for 5 ms, then sustain 2); levels read 0, unless `s.release_ms` is set: then a voice reads `0x4000` from its start until its release command and falls to 0 over `release_ms` (a release that ends, which MPE v1.1's channel reuse tells from idle; `reset()` sets it back to None); everything else reads 0 |
| EXTI15 edge | **model, guess** | every 100 µs; `voice_env_poll` waits for 2–3 edges per note-on |
| CPU speed | **model**; default: 1 instruction per cycle, SPI free, each interrupt 300 instructions | `s.set_timing(cpu_scale, spi_cost=True)` (opt-in; `reset()` restores the default): each SPI1 frame costs its wire time (128 cycles: 15 MHz, from the firmware's SPI1 set-up, observed in code), in an interrupt out of the next slot, in the main thread carried on; `cpu_scale` is the main thread's instructions per cycle. The synth runs from flash with the ART accelerator off (`FLASH_ACR` = 3, observed in code), so it is slower than the default: `set_timing(0.3, spi_cost=True)` reproduces MPE v1.1's dead Slide (inferred from that one observation; [mpe-design.md](mpe-design.md#slide-v12)). The interrupts' real cost (TIM6 about 11,300 instructions per ms, EXTI15 246 per edge, emulated) is not charged as such |
| Display | **peripheral**: SPI2 + GPIOB PB11 (US2066-style OLED, 20×4) | text, boot screen, PNG screenshots |
| Buttons and encoder | **peripheral**: the shift-register chain on GPIO (PB2 load, PC10 clock, PC11 in) | `press`, `turn`; the LED bits shifted out are kept too |
| Skipped | | FPGA bitstream upload (only that part of `boot_screen`), keybed (USART3), pots/pedals (ADC + DMA), OTG |

Other peripherals are a register file (reads return the last write). GPIO
inputs read 1 (the panel chain's data input follows the held buttons). A wait-for-flag loop on a
register nobody models is broken after 32 identical reads by returning the
complement; every break is counted in `board.poll_breaks`. See the module
docstrings of `emu/board.py`, `emu/fpga.py` and `emu/synth.py` for details,
and [the findings](findings/summit-2.2-build2121.md#the-fpga-bus-spi1) for
the firmware side.

## In Python and tests

```python
from emu.synth import SimulatedSummit

s = SimulatedSummit()                 # stock 2.2; or SimulatedSummit("work/patched/x.syx")
s.note_on(60, 100)                    # DIN; port="usb" for USB; channels are 1-16
s.tick(10)                            # run 10 ms (10 modulation ticks)
s.active_voices()                     # [0]
s.fpga_events(voice=0, param="velocity")
s.last_value(target=0x1A, param="bend_up")
s.midi_out()                          # DIN and USB messages the Summit sent
s.reset()                             # back to the booted, idle state (fast)
```

- **Input:** `midi_in(bytes | "90 3C 64", port=)`, plus `note_on`,
  `note_off`, `cc`, `nrpn`, `bend` (-8192…8191), `channel_pressure`,
  `poly_pressure`.
- **FPGA:** `fpga_events(voice=, part=, param=, target=, since_ms=)`; `param`
  takes a number, a name (`emu.fpga.PARAM_NAMES`: `env1_gate`, `env1_cmd`,
  `velocity`, `pitch`, `bend_up`, `bend_down`, `modwheel`, `aftertouch`, …)
  or a list. `fpga_state()` is the last value per `(engine, target, param)`.
  `clear()` forgets recorded events and MIDI out, and keeps the state.
- **State views:** `voices()` (index, active, note, pitch, aftertouch),
  `voice_note(v)`, `voice_pitch(v)` (8.8 semitones), `voice_aftertouch(v)`,
  `part_bend(p)`, `part_modwheel(p)`, `patch_byte(offset)`.
- **Power:** `power_cycle()` boots a new board from the DataFlash (saved
  settings, patches, multis); RAM starts afresh. `reset()` afterwards
  returns to that boot. `power_cycle(before_boot=fn)` calls `fn(board)` on
  the new board before it starts: fill RAM as a real power-up may leave it,
  or queue MIDI that arrives during the startup (`board.din.rx_queue`), as
  `tests/test_mpe_ui_powerup.py` does.
- **Between passes:** `to_pass_start()` runs until the main loop starts a
  pass. The firmware changes patch and settings bytes from its main loop,
  never in the middle of a pass, but `set_patch_byte`/`set_global` between
  two slots can land inside one (`mod_tick` runs in the main loop). Poke
  from here when a test measures single ticks
  (`tests/test_mpe_expr_queue.py`).
- **Settings:** `set_mode("single" | "multi")`, `set_channels(global_=,
  part_a=, part_b=)`, `set_global(offset, value)`, `set_soft_thru(on)`,
  `set_cc_nrpn_receive(on)`. Patch parameters: send their NRPN
  (`s.nrpn(0, 3, 4)` = Unison 4). Writing patch bytes in RAM doesn't apply
  them.

Building one `SimulatedSummit` takes about 3 s (25 s the first time per
image, for the DataFlash format; a patched image can reuse the stock
image's format with `SimulatedSummit(patched, flash_from=stock)` when the
patch doesn't change the factory initialise). C patches' startup hook
(`__patch_start`) runs, since the board continues Reset_Handler at its
`bl main_loop`; `tests/test_synth_patch.py` plays the demo note hook. Make it once per test module and `reset()`
per test, as `tests/test_synth_sim.py` does. One simulated second takes about
4–5 s.

Timing to expect: a DIN note-on needs 0.96 ms for its bytes and reaches the
FPGA about 0.9 ms after the first byte. Mod sources go out once per tick;
aftertouch two voices per tick, so 8 ticks for all 16.

## From the command line: `tools/sim.py`

```bash
scripts/dev python -I tools/sim.py -e "0 on 60" -e "20 bend 4096" -e "60 off 60"
```

```bash
scripts/dev python -I tools/sim.py --score chord.txt --image work/patched/x.syx
```

```bash
scripts/dev python -I tools/sim.py --mmon capture.mmon --to Summit
```

Input is hex (`--hex`), a text score (`--score FILE` or `-e LINE`), or a MIDI
Monitor capture (`--mmon`, the messages sent *to* the destination named by
`--to`). The score format is in `tools/sim.py --help`:

```
# time_ms  message   [ch=N] [port=din|usb]
0    on 60 100
0    on E4
+20  bend 4096
40   cp 100           # channel pressure; pp NOTE VAL = poly pressure
50   cc 1 64
60   nrpn 62 0 1
70   mode multi
80   hex 90 3C 00
```

The output is one timeline: `>` MIDI in, `fpga` writes, `<` MIDI out. FPGA
writes are printed when a value changes, and by default only the named
MIDI-facing parameters (`--any-param` for all, `--all` for every refresh,
`--voice`, `--param` to filter).

Example, a C major chord, bend up at 20 ms, channel pressure at 40 ms,
release at 80 ms (stock 2.2, Init Patch; lines cut where marked):

```
     0.00 ms  > din  in  90 3C 64
     0.00 ms  > din  in  90 40 64
     0.00 ms  > din  in  90 43 64
     0.90 ms    fpga A  v0   env1_gate   32767
     0.90 ms    fpga A  v0   env2_gate   32767
     0.90 ms    fpga A  v0   env3_gate   32767
     0.90 ms    fpga A  v0   velocity    25600
     0.90 ms    fpga A  v0   env1_cmd    48
     0.90 ms    fpga A  v0   env2_cmd    48
     0.90 ms    fpga A  v0   env3_cmd    48
     2.00 ms    fpga A  v1   env1_gate   32767
     …
     2.00 ms    fpga A  v1   pitch       1024
     2.00 ms    fpga A  v1   velocity    25600
     …
     3.00 ms    fpga A  v2   pitch       1792
     …
    20.00 ms  > din  in  E0 00 60
    21.00 ms    fpga A  0x1a bend_up     1024
    21.15 ms    fpga B  0x1a bend_up     1024
    22.00 ms    fpga A  0x1a bend_up     1984
    22.15 ms    fpga B  0x1a bend_up     1984
    23.00 ms    fpga A  0x1a bend_up     2884
     …
    40.00 ms  > din  in  D0 64
    40.00 ms    fpga A  0x1a bend_up     11879
    40.15 ms    fpga B  0x1a bend_up     11879
    41.00 ms    fpga A  0x1a bend_up     12161
    41.10 ms    fpga B  v13  aftertouch  1253
    41.15 ms    fpga B  0x1a bend_up     12161
    41.25 ms    fpga B  v14  aftertouch  1253
    42.00 ms    fpga A  0x1a bend_up     12425
    42.10 ms    fpga B  v15  aftertouch  1253
     …
    80.00 ms  > din  in  80 3C 00
    80.00 ms  > din  in  80 40 00
    80.00 ms  > din  in  80 43 00
    80.00 ms    fpga A  0x1a bend_up     16046
    80.10 ms    fpga B  v11  aftertouch  11666
     …
    80.75 ms    fpga A  v0   env1_cmd    55
    80.75 ms    fpga A  v0   env2_cmd    55
    80.75 ms    fpga A  v0   env3_cmd    55
     …
    81.80 ms    fpga A  v1   env1_cmd    55
     …
-- end at 120.00 ms; active voices (voice, note): none
```

Read it as: one voice per note (pitch relative to C4 in 1/256 semitones);
envelope commands `counter << 2 | state` (state 0 start, 3 release); bend as
one part-wide value to both engines, closing 1/16 of the gap per tick; and
pressure written to every voice's aftertouch, two voices per tick, smoothed
and squared. The full run is about 400 lines.

## Screen and front panel

The firmware draws on a modelled OLED and scans a modelled button chain and
encoder with its own code, so a patched menu shows up exactly as the patched
code draws it ([findings](findings/summit-2.2-build2121.md#display-and-front-panel)).

```python
s = SimulatedSummit()
s.boot_screen()                 # ['      Novation      ', …, '  Version 126.778   ']
s.press("settings")             # press and release (40 ms + 60 ms)
s.press("page_next")
print(s.screen_dump())          # the four rows in a frame
s.screen_text()[2]              # 'Version    126.778  '
s.press("item3"); s.turn(+2)    # select row 3, two encoder detents up
s.press("save")
s.screenshot("work/screens/x.png")
```

- **Buttons:** `press(name, hold_ms=40, after_ms=60)`, `hold(name)` /
  `release(name)` for combinations. Names are in `emu.panel.BUTTONS`
  (`tools/sim.py --buttons`); ids 0-69 work too. Menus: `patch`, `multi`,
  `osc`, `env`, `lfo`, `arp`, `voice`, `fx`, `mod_matrix`, `fx_matrix`,
  `settings`, `save`. Navigation: `page_next`, `page_prev`, `item1`-`item3`
  (move the ▶ cursor to display row 1-3), `value_inc`, `value_dec`,
  `patch_next`, `patch_prev`. `emu.panel.BUTTON_CONFIDENCE` says which names
  were checked in the simulator and which are inferred.
- **Encoder:** `turn(steps)`, positive = value up. Detents are 32 ms apart, so
  each is one step; the firmware accelerates faster turns.
- **Screen:** `screen_text()` (characters outside ASCII: `▶` `◀` and the frame
  pieces `┌┐└┘▔▁▏▕`; unknown codes as `·`), `screen_dump(title)`,
  `boot_screen()`, `display_on`, `screenshot(path, scale=4)`. The PNG is
  drawn dot by dot from the display RAM with a font made for this project
  (not the controller's ROM bitmaps); it needs no extra package.
- **Pots** aren't modelled (ADC + DMA). Selecting `Calibrate` (Settings 2/33,
  row 3) starts the pot calibration, as on the synth.

From the command line, panel actions and screen output are score lines:

```bash
scripts/dev python -I tools/sim.py -e "0 press settings" -e "+0 press page_next" -e "+0 screen" -e "+0 shot work/screens/system-2.png" --no-fpga --no-midi-out --tail 10
```

```
     0.00 ms    panel press settings
   100.00 ms    panel press page_next
   200.00 ms    screen
+- 200.00 ms --------+
|SYSTEM          2/33|
|Msg Time    64     ▶|
|Version    126.778  |
|▶ Calibrate         |
+--------------------+
   200.00 ms    screenshot work/screens/system-2.png
-- end at 210.00 ms; active voices (voice, note): none
```

Score lines: `press BUTTON [HOLD_MS]`, `hold BUTTON`, `release BUTTON`,
`turn STEPS`, `screen`, `shot PATH`. Options: `--screen` (at the end),
`--boot-screen`, `--screenshot PATH`, `--buttons`. Put screenshots in
`work/` (never committed).

**Golden screens:** `tests/test_screen_sim.py` compares pages with
`tests/golden/screens/*.txt` and prints a diff when one changes. After an
intended UI change, rewrite them with
`UPDATE_GOLDEN=1 scripts/dev python -m pytest tests/test_screen_sim.py` and
review the diff.

## Comparing a patch with stock

Run the same score on both images, for example a bend on stock and on the
MPE build with MPE off for the sound (it must match stock):

```bash
scripts/dev python -I tools/sim.py --score bend.txt --param bend_up --param bend_down --no-midi-out
```

```bash
scripts/dev python -I tools/sim.py --score bend.txt --image work/patched/summit-firmware-2.2-build2121+mpe.syx --param bend_up --param bend_down --no-midi-out
```

Both print the bend on the broadcast target (`0x1a`) for both engines. For
assertions, `tests/test_mpe_off.py` compares whole runs of stock and the MPE
build: value sequences per FPGA register, MIDI out and the FPGA queue.

## Replaying captures

`--mmon` replays what a MIDI Monitor capture sent to the Summit, with the
capture's timing. Use it for MPE captures from Live, the Hapax or any other sender: run the
stock image to see what the Summit does with MPE today, then the patched
image to check the MPE behaviour.
