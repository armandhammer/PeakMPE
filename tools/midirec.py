#!/usr/bin/env python3
"""Record every MIDI input to a log file, with no history limit.

Replaces Snoize MIDI Monitor for hardware sessions. It only listens: it opens
MIDI inputs and never sends anything.

  midirec.py list                         the MIDI input ports
  midirec.py record [options]             record until Ctrl-C (or --duration)

  --port SUB       record only inputs whose name contains SUB (case-insensitive,
                   repeatable); default: every input
  --out PATH       log file; default work/capture/rec-YYYYmmdd-HHMMSS.log.
                   An existing file is never overwritten: "-2", "-3", ... is
                   added to the name instead
  --keep-clock     keep MIDI clock (F8) and active sensing (FE); dropped by
                   default. SysEx is always recorded
  --marker         Enter writes "# marker N <seconds>" into the log
  --duration S     stop after S seconds

Each message is written as it arrives (line-buffered), in the format of
`tools/mmon.py log` and `tools/flash.py --log`, so `mmon.read_log` and
`tools/sim.py --mmon` read it:

  "<seconds:10.4f> < <port_with_underscores> <hex bytes>"

Seconds count from the start of the recording; "<" means received. On stop
it prints the path, the message count per port and the file's SHA-256, and
writes the hash to "<file>.sha256" (`shasum -a 256 -c` format).

Needs python-rtmidi: run with `.venv/bin/python -I tools/midirec.py`.
"""
import argparse
import hashlib
import re
import sys
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAPTURE_DIR = ROOT / "work" / "capture"
CLOCK, ACTIVE_SENSING = 0xF8, 0xFE


def port_label(name):
    """A port name as one log field: spaces (any whitespace) become underscores,
    as in `mmon.py log`."""
    return re.sub(r"\s", "_", name)


def format_line(seconds, port, data, direction="<"):
    return f"{seconds:10.4f} {direction} {port_label(port)} {bytes(data).hex(' ')}\n"


def is_filtered(data, keep_clock=False):
    """True for messages dropped by default: MIDI clock and active sensing."""
    return not keep_clock and len(data) == 1 and data[0] in (CLOCK, ACTIVE_SENSING)


def default_path(directory=CAPTURE_DIR, now=None):
    now = now or datetime.now()
    return Path(directory) / f"rec-{now:%Y%m%d-%H%M%S}.log"


def candidates(path):
    """*path*, then path-2, path-3, ... (the suffix goes before the extension)."""
    path = Path(path)
    yield path
    n = 2
    while True:
        yield path.with_name(f"{path.stem}-{n}{path.suffix}")
        n += 1


def create_unique(path):
    """Create and open a new log at *path*, or the first free suffixed name.
    Never truncates an existing file (exclusive create, so two recorders
    started in the same second don't collide). Returns (path, file)."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    for p in candidates(path):
        if Path(f"{p}.sha256").exists():
            continue
        try:
            return p, open(p, "x", buffering=1)  # line-buffered
        except FileExistsError:
            continue


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def write_sidecar(path):
    """Write "<file>.sha256" next to *path*; return the hash."""
    digest = sha256_file(path)
    Path(f"{path}.sha256").write_text(f"{digest}  {Path(path).name}\n")
    return digest


class Recorder:
    """Writes messages from any thread to one log, timed from its creation."""

    def __init__(self, path, keep_clock=False, clock=time.monotonic):
        self.path, self.file = create_unique(path)
        self.keep_clock, self.clock = keep_clock, clock
        self.t0 = clock()
        self.lock = threading.Lock()
        self.counts = Counter()
        self.filtered = Counter()
        self.markers = 0
        self.digest = None

    def elapsed(self):
        return self.clock() - self.t0

    def message(self, port, data):
        data = bytes(data)
        if not data:
            return
        with self.lock:
            if self.file is None:
                return
            if is_filtered(data, self.keep_clock):
                self.filtered[data[0]] += 1
                return
            self.file.write(format_line(self.elapsed(), port, data))
            self.counts[port_label(port)] += 1

    def marker(self):
        with self.lock:
            if self.file is None:
                return None
            self.markers += 1
            t = self.elapsed()
            self.file.write(f"# marker {self.markers} {t:.4f}\n")
            return self.markers, t

    def close(self):
        with self.lock:
            if self.file is None:
                return self.digest
            self.file.close()
            self.file = None
        self.digest = write_sidecar(self.path)
        return self.digest

    def summary(self):
        lines = [f"recorded {sum(self.counts.values())} messages to {self.path}"]
        for port, n in sorted(self.counts.items()):
            lines.append(f"  {port:32s} {n}")
        if self.filtered:
            lines.append(f"  filtered: {self.filtered[CLOCK]} clock (F8), "
                         f"{self.filtered[ACTIVE_SENSING]} active sensing (FE)")
        if self.markers:
            lines.append(f"  markers: {self.markers}")
        lines.append(f"sha256 {self.digest}  (written to {self.path.name}.sha256)")
        return "\n".join(lines)


# ---------------------------------------------------------------- port source

class RtMidiSource:
    """MIDI inputs through python-rtmidi. Input only: no output is opened."""

    def __init__(self):
        import rtmidi
        self.rtmidi = rtmidi

    def names(self):
        midi_in = self.rtmidi.MidiIn()
        try:
            return midi_in.get_ports()
        finally:
            midi_in.delete()

    def open(self, index, name, callback):
        """Open input *index* and call callback(data) for every message.
        Clock and active sensing are filtered by the Recorder, not here:
        rtmidi's `timing` flag would also drop MTC quarter frames (F1)."""
        midi_in = self.rtmidi.MidiIn()
        midi_in.ignore_types(sysex=False, timing=False, active_sense=False)
        midi_in.set_callback(lambda event, _data: callback(event[0]))
        midi_in.open_port(index)
        return midi_in

    @staticmethod
    def close(handle):
        handle.close_port()
        handle.delete()


def select_ports(names, filters):
    """(index, name) of the inputs matching any of *filters* (all if none)."""
    wanted = [f.lower() for f in filters or []]
    return [(i, n) for i, n in enumerate(names)
            if not wanted or any(f in n.lower() for f in wanted)]


def record(source, out=None, filters=None, keep_clock=False, marker_input=None,
           duration=None, stop=None, clock=time.monotonic, say=print):
    """Record from *source* until *stop* is set, *duration* passes or Ctrl-C.
    *marker_input*: a text stream whose lines each write a marker (stdin
    with --marker). Returns the closed Recorder."""
    ports = select_ports(source.names(), filters)
    if not ports:
        raise SystemExit("no matching MIDI input" + (f" for --port {' '.join(filters)}" if filters else ""))
    rec = Recorder(out or default_path(), keep_clock=keep_clock, clock=clock)
    stop = stop or threading.Event()
    handles = []
    try:
        for index, name in ports:
            handles.append(source.open(index, name, lambda data, name=name: rec.message(name, data)))
            say(f"listening: {name}")
        say(f"recording to {rec.path}" + (f" for {duration:g} s" if duration else "")
            + "; Ctrl-C stops" + ("; Enter writes a marker" if marker_input else ""))
        if marker_input is not None:
            def markers():
                for _line in marker_input:
                    if stop.is_set():
                        break
                    m = rec.marker()
                    if m:
                        say(f"marker {m[0]} at {m[1]:.4f} s")
            threading.Thread(target=markers, daemon=True).start()
        deadline = None if duration is None else clock() + duration
        while not stop.is_set():
            if deadline is not None and clock() >= deadline:
                break
            stop.wait(0.05)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        for handle in handles:
            try:
                source.close(handle)
            except Exception as e:  # keep closing the others and the file
                say(f"warning: closing a port failed: {e}")
        rec.close()
        say(rec.summary())
    return rec


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="print the MIDI input ports")
    s = sub.add_parser("record", help="record MIDI inputs to a log")
    s.add_argument("--port", action="append", metavar="SUB", help="input name substring (repeatable)")
    s.add_argument("--out", help="log file (default: work/capture/rec-YYYYmmdd-HHMMSS.log)")
    s.add_argument("--keep-clock", action="store_true", help="keep MIDI clock (F8) and active sensing (FE)")
    s.add_argument("--marker", action="store_true", help="Enter writes a '# marker N <seconds>' line")
    s.add_argument("--duration", type=float, metavar="S", help="stop after S seconds")
    args = p.parse_args(argv)

    source = RtMidiSource()
    if args.command == "list":
        names = source.names()
        for i, name in enumerate(names):
            print(f"{i:3d}  {name}")
        if not names:
            print("no MIDI inputs")
        return 0
    record(source, out=args.out, filters=args.port, keep_clock=args.keep_clock,
           marker_input=sys.stdin if args.marker else None, duration=args.duration)
    return 0


if __name__ == "__main__":
    sys.exit(main())
