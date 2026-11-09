#!/usr/bin/env python3
"""Play MIDI into the simulated Summit and print what reaches the FPGA and MIDI out.

  sim.py --hex "90 3C 64"                      bytes, all sent at t = 0
  sim.py --score chord.txt                     a text score (format below)
  sim.py -e "0 on 60" -e "20 bend 4096"        score lines on the command line
  sim.py --mmon capture.mmon [--to Summit]     the messages a MIDI Monitor
                                               capture sent *to* the Summit
  sim.py ... --image work/patched/x.syx        a patched image (default: stock)

Output is one timeline: `>` MIDI into the Summit, `fpga` decoded SPI1 writes,
`<` MIDI out (DIN or USB). FPGA writes are printed only when a value changes
(per engine, target and parameter); `--all` prints every write, including the
per-tick refreshes. By default only the named MIDI-facing parameters are shown
(gates, envelope commands, velocity, pitch, bend, mod sources, aftertouch);
`--any-param` shows all, `--param NAME|0xNN` (repeatable) picks. Other filters:
`--voice N` (repeatable), `--no-fpga`, `--no-midi-out`. `--tail MS` runs on after the last input
(default 40 ms); `--port usb` sends over USB instead of DIN.

Score format: one message per line, `#` starts a comment.

  TIME  MESSAGE [ch=N] [port=din|usb]
  TIME is ms from the start, or +ms after the previous line.
  MESSAGE:
    on NOTE [VEL]      off NOTE [VEL]      cc NUM VAL      pc NUM
    bend VALUE         (-8192..8191)       cp VALUE        (channel pressure)
    pp NOTE VALUE      (poly pressure)     nrpn MSB LSB VAL
    hex BYTES...       (raw bytes)         mode single|multi
  Front panel and screen (emu.panel names, or a button id 0-69):
    press BUTTON [HOLD_MS]                 hold BUTTON     release BUTTON
    turn STEPS         (encoder detents, negative = down)
    screen             (print the display)  shot PATH      (PNG screenshot)
  NOTE may be a number or a name such as C4 (= 60) or F#3.
  `press` and `turn` take time (40 + 60 ms per press, 32 ms per detent);
  later lines whose time has passed run right after them.

Screen options: `--screen` prints the display at the end, `--boot-screen`
the boot screen, `--screenshot PATH` saves a PNG at the end (put them in
work/, which git ignores). `--buttons` lists the button names.

Example: open Settings, page to 2/33, print it and save a screenshot.

  sim.py -e "0 press settings" -e "+0 press page_next" -e "+0 screen" \
         -e "+0 shot work/screens/system-2.png" --no-fpga

Example: a chord with pitch bend and pressure.

  0    on 60 100
  0    on 64 100
  0    on 67 100
  20   bend 4096
  40   cp 100
  80   off 60
  80   off 64
  80   off 67

The first run for an image formats the simulated DataFlash (about 25 s) and
caches it in work/cache/ (emu/cache.py). Run with `scripts/dev python -I tools/sim.py ...`.
"""
from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from emu.fpga import param_number  # noqa: E402
from emu.screen import dump as screen_dump  # noqa: E402
from emu.synth import SimulatedSummit, to_bytes  # noqa: E402

DEFAULT_PARAMS = (0x3F, 0x40, 0x42, 0x43, 0x45, 0x46, 0x60, 0x61, 0x62, 0x63, 0x66, 0x67, 0x68, 0x69)
NOTE_NAMES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def note_number(text: str) -> int:
    m = re.fullmatch(r"([A-Ga-g])([#b]?)(-?\d+)", text)
    if not m:
        return int(text, 0)
    n = NOTE_NAMES[m.group(1).upper()] + {"#": 1, "b": -1, "": 0}[m.group(2)]
    return n + 12 * (int(m.group(3)) + 1)


def parse_score(lines):
    """Yield (time_ms, kind, payload, port) for each score line.

    kind is "midi" (payload: bytes) or "mode" (payload: "single"/"multi")."""
    t = 0.0
    for lineno, raw in enumerate(lines, 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        words = line.split()
        opts = dict(w.split("=", 1) for w in words if "=" in w)
        words = [w for w in words if "=" not in w]
        when, cmd, args = words[0], words[1].lower(), words[2:]
        t = t + float(when[1:]) if when.startswith("+") else float(when)
        ch = int(opts.get("ch", 1)) - 1
        port = opts.get("port")
        try:
            if cmd == "on":
                data = [0x90 | ch, note_number(args[0]), int(args[1]) if len(args) > 1 else 100]
            elif cmd == "off":
                data = [0x80 | ch, note_number(args[0]), int(args[1]) if len(args) > 1 else 0]
            elif cmd == "cc":
                data = [0xB0 | ch, int(args[0], 0), int(args[1], 0)]
            elif cmd == "pc":
                data = [0xC0 | ch, int(args[0], 0)]
            elif cmd == "bend":
                v = max(-8192, min(8191, int(args[0], 0))) + 8192
                data = [0xE0 | ch, v & 0x7F, v >> 7]
            elif cmd == "cp":
                data = [0xD0 | ch, int(args[0], 0)]
            elif cmd == "pp":
                data = [0xA0 | ch, note_number(args[0]), int(args[1], 0)]
            elif cmd == "nrpn":
                msb, lsb, val = (int(a, 0) for a in args[:3])
                data = [0xB0 | ch, 99, msb, 0xB0 | ch, 98, lsb, 0xB0 | ch, 6, val]
            elif cmd == "hex":
                data = list(to_bytes(" ".join(args)))
            elif cmd == "mode":
                yield t, "mode", args[0], port
                continue
            elif cmd in ("press", "hold", "release"):
                button = int(args[0]) if args[0].isdigit() else args[0]
                hold_ms = float(args[1]) if cmd == "press" and len(args) > 1 else 40.0
                yield t, cmd, (button, hold_ms), port
                continue
            elif cmd == "turn":
                yield t, "turn", int(args[0]), port
                continue
            elif cmd == "screen":
                yield t, "screen", None, port
                continue
            elif cmd == "shot":
                yield t, "shot", args[0], port
                continue
            else:
                raise ValueError(f"unknown message {cmd!r}")
        except (IndexError, ValueError) as e:
            raise SystemExit(f"score line {lineno}: {raw.strip()!r}: {e}")
        yield t, "midi", bytes(data), port


def mmon_inputs(path: str, to: str):
    spec = importlib.util.spec_from_file_location("mmon", ROOT / "tools" / "mmon.py")
    mmon = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mmon)
    reader = mmon.read_log if path.endswith(".log") else mmon.messages
    first = None
    for t, direction, port, data in reader(path):
        if direction != ">" or to.lower() not in port.lower():
            continue
        first = t if first is None else first
        yield (t - first) * 1000.0, "midi", bytes(data), None


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_argument_group("input")
    src.add_argument("--hex", help="bytes to send at t = 0")
    src.add_argument("--score", help="score file")
    src.add_argument("-e", dest="lines", action="append", default=[], help="a score line (repeatable)")
    src.add_argument("--mmon", help="MIDI Monitor capture (.mmon, or a `mmon.py log` .log)")
    src.add_argument("--to", default="Summit", help="with --mmon: destination name to replay (default Summit)")
    p.add_argument("--image", help="firmware image: .syx or flat .bin (default: stock 2.2)")
    p.add_argument("--port", choices=("din", "usb"), default="din", help="default input port")
    p.add_argument("--tail", type=float, default=40.0, help="ms to run after the last input")
    p.add_argument("--all", action="store_true", help="print every FPGA write, not only changes")
    p.add_argument("--voice", type=int, action="append", help="only FPGA writes for this voice (repeatable)")
    p.add_argument("--param", action="append", help="only this FPGA parameter (name or number, repeatable)")
    p.add_argument("--any-param", action="store_true", help="show every FPGA parameter")
    p.add_argument("--no-fpga", action="store_true")
    p.add_argument("--no-midi-out", action="store_true")
    p.add_argument("--no-cache", action="store_true", help="don't read or write the DataFlash cache")
    p.add_argument("--screen", action="store_true", help="print the display at the end")
    p.add_argument("--boot-screen", action="store_true", help="print the boot screen")
    p.add_argument("--screenshot", metavar="PATH", help="save a PNG of the display at the end")
    p.add_argument("--buttons", action="store_true", help="list the front-panel button names and exit")
    args = p.parse_args(argv)

    if args.buttons:
        from emu.panel import BUTTON_CONFIDENCE, BUTTONS

        for name, bid in sorted(BUTTONS.items(), key=lambda x: x[1]):
            print(f"{bid:3d}  {name:<12} {BUTTON_CONFIDENCE[name]}")
        return 0

    inputs = []
    if args.hex:
        inputs.append((0.0, "midi", to_bytes(args.hex), None))
    if args.score:
        inputs.extend(parse_score(Path(args.score).read_text().splitlines()))
    if args.lines:
        inputs.extend(parse_score(args.lines))
    if args.mmon:
        inputs.extend(mmon_inputs(args.mmon, args.to))
    if not inputs and not (args.screen or args.boot_screen or args.screenshot):
        p.error("no input: give --hex, --score, -e or --mmon (or a screen option)")
    inputs.sort(key=lambda i: i[0])

    params = None if args.any_param else set(DEFAULT_PARAMS)
    if args.param:
        try:
            params = {param_number(x) if not x[0].isdigit() else int(x, 0) for x in args.param}
        except KeyError as e:
            p.error(f"unknown parameter name {e}")

    print("booting the simulated Summit…", file=sys.stderr)
    s = SimulatedSummit(args.image, cache=not args.no_cache)
    t0 = s.time_ms
    state_at_start = s.fpga_state()
    timeline = []
    for t, kind, payload, port in inputs:
        now = s.time_ms - t0
        if t > now:
            s.tick(t - now)
        if kind == "mode":
            timeline.append((s.time_ms, 0, f"  mode {payload}"))
            s.set_mode(payload, run_ms=0)
        elif kind in ("press", "hold", "release"):
            button, hold_ms = payload
            timeline.append((s.time_ms, 0, f"  panel {kind} {button}"))
            try:
                if kind == "press":
                    s.press(button, hold_ms=hold_ms)
                else:
                    getattr(s, kind)(button)
            except (KeyError, ValueError) as e:
                p.error(str(e))
        elif kind == "turn":
            timeline.append((s.time_ms, 0, f"  panel turn {payload:+d}"))
            s.turn(payload)
        elif kind == "screen":
            timeline.append((s.time_ms, 0, "  screen\n" + s.screen_dump(f"{s.time_ms - t0:.2f} ms")))
        elif kind == "shot":
            timeline.append((s.time_ms, 0, f"  screenshot {s.screenshot(payload)}"))
        else:
            port = port or args.port
            timeline.append((s.time_ms, 0, f"> {port:<4} in  {payload.hex(' ').upper()}"))
            s.midi_in(payload, port=port)
    s.tick(args.tail)

    if not args.no_fpga:
        last = dict(state_at_start)
        for e in s.fpga_events():
            if args.voice is not None and e.voice not in args.voice:
                continue
            if params is not None and e.param not in params:
                continue
            key = (e.engines, e.target, e.param)
            if not args.all and last.get(key) == e.value:
                continue
            last[key] = e.value
            tgt = f"v{e.target}" if e.target < 0x10 else f"{e.target:#04x}"
            timeline.append((e.time_ms, 1, f"  fpga {e.engines:<2} {tgt:<4} {e.name:<11} {e.value}"))
    if not args.no_midi_out:
        for m in s.midi_out():
            timeline.append((m.time_ms, 2, f"< {m.port:<4} out {m.data.hex(' ').upper()}"))

    for t, _order, text in sorted(timeline, key=lambda x: (x[0], x[1])):
        print(f"{t - t0:9.2f} ms  {text}")
    if args.boot_screen:
        print(screen_dump(s.boot_screen(), "boot screen"))
    if args.screen:
        print(s.screen_dump(f"end, {s.time_ms - t0:.2f} ms"))
    if args.screenshot:
        print(f"screenshot: {s.screenshot(args.screenshot)}")
    active = [(v.index, v.note) for v in s.voices(active_only=True)]
    print(f"-- end at {s.time_ms - t0:.2f} ms; active voices (voice, note): {active or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
