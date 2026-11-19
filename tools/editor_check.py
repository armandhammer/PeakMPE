#!/usr/bin/env python3
r"""Editor baseline on the synth: the Peak's answers to the editor's read requests.

The editor protocol (findings, "The editor protocol"; read from stock's SysEx
parsers): header F0 00 20 29 01 10 00 7E, a command, five bytes, then data for
a write. This tool sends only the read requests below, plus one write to the
edit buffer (the current patch sent back unchanged, as Components does when it
sends a sound), and records what comes back:

  identity       F0 7E 7F 06 01 F7
  current        40           the edit buffer (changes with every rig setup:
                              compared within the run, by the round trip)
  D002           41 bank 4 (D) patch 2 (the rig's test patch; banks 1-4 = A-D)
  settings       44
  wave b.p       46 block b (0-10), part p (0-4)   55 requests (block 10 not compared)
  wave name n    47 n (0-73)
  tuning t       F0 7E 00 08 00 t F7, t 0-16 (stock's tuning-table dump)
  bank D         4A bank 4: 128 patches
  round trip     the current patch's answer sent back as write 00, then 40 again

Every message passes allowed() before it is sent: nothing that stores to the
synth's memory (writes 01, 04, 06, 07), nothing for the updater or the factory
test, no other SysEx. The answers stay in work/ (they hold the user's patches).

Each run's summary (count, lengths and SHA-256 of the answer per request) is
compared with the newest earlier run, or --against DIR. The first run is the
baseline.

  .venv\Scripts\python.exe -I tools\editor_check.py --dry-run
  .venv\Scripts\python.exe -I tools\editor_check.py --yes      (only with the user's OK)

Output: work/hw-runs/editor-<timestamp>/ (replies.log, summary.json).
"""
import argparse
import hashlib
import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "work" / "hw-runs"
HDR = bytes([0x00, 0x20, 0x29, 0x01, 0x10, 0x00, 0x7E])
IDENTITY = bytes([0xF0, 0x7E, 0x7F, 0x06, 0x01, 0xF7])
READS = {0x40, 0x41, 0x44, 0x46, 0x47, 0x4A}
WRITE_CURRENT = 0x00
PATCH_LEN = 527                     # F0, header, command, 5 bytes, 512 data, F7
# Not compared between runs: the edit buffer (every rig setup changes it) and
# wavetable block 10 (blocks 0-9 are the user slots; block 10 changed between
# two runs a minute apart on 2026-11-19: inferred a working buffer).
VOLATILE = {"current"} | {f"wave 10.{q}" for q in range(5)}


def req(cmd, b10=0, b11=0, b12=0):
    return bytes([0xF0, *HDR, cmd, 0, 0, b10, b11, b12, 0xF7])


def tuning_dump(table):
    return bytes([0xF0, 0x7E, 0x00, 0x08, 0x00, table, 0xF7])


def allowed(msg):
    """Raise ValueError unless msg is one of the messages this tool may send."""
    m = bytes(msg)
    if m == IDENTITY:
        return m
    if len(m) < 7 or m[0] != 0xF0 or m[-1] != 0xF7 or any(b > 0x7F for b in m[1:-1]):
        raise ValueError(f"refused: not one SysEx message: {m[:10].hex(' ')}")
    if m[1:5] == bytes([0x7E, 0x00, 0x08, 0x00]) and len(m) == 7 and m[5] <= 16:
        return m
    if m[1:8] == HDR:
        cmd = m[8]
        if cmd in READS and len(m) == 15 and m[9] == m[10] == 0:
            return m
        if cmd == WRITE_CURRENT and len(m) == PATCH_LEN:
            return m
    raise ValueError(f"refused: {m[:10].hex(' ')} is not a read request or a write to the edit buffer")


def plan():
    """(label, message, expected answers, seconds to wait)."""
    p = [("identity", IDENTITY, 1, 1.0), ("current", req(0x40), 1, 1.0),
         ("D002", req(0x41, 0, 4, 2), 1, 1.0), ("settings", req(0x44), 1, 1.0)]
    p += [(f"wave {b}.{q}", req(0x46, b, q), 1, 1.0) for b in range(11) for q in range(5)]
    p += [(f"wave name {n}", req(0x47, n), 1, 1.0) for n in range(74)]
    p += [(f"tuning {t}", tuning_dump(t), 1, 1.0) for t in range(17)]
    p += [("bank D", req(0x4A, 0, 4), 128, 40.0)]
    return p


def split(data):
    msgs, cur = [], None
    for x in data:
        if x == 0xF0:
            cur = [x]
        elif cur is not None:
            cur.append(x)
            if x == 0xF7:
                msgs.append(bytes(cur))
                cur = None
    return msgs


def summarize(msgs):
    return {"count": len(msgs), "lengths": sorted({len(m) for m in msgs}),
            "sha256": hashlib.sha256(b"".join(msgs)).hexdigest()}


def compare(now, before):
    """Labels whose answers differ from the earlier run (volatile ones left out)."""
    out = []
    for label, s in now.items():
        if label in VOLATILE or label not in before:
            continue
        if s != before[label]:
            out.append(label)
    return out


def previous_run(exclude=None):
    runs = sorted(d for d in RUNS.glob("editor-*") if (d / "summary.json").exists() and d != exclude)
    return runs[-1] if runs else None


class Port:
    """The Peak's USB MIDI in and out (python-rtmidi)."""

    def __init__(self, name):
        import rtmidi
        sys.path.insert(0, str(ROOT / "tools"))
        from hwrig.midi import check_port_name, find_port
        self.out, self.inp = rtmidi.MidiOut(), rtmidi.MidiIn()
        self.name = check_port_name(find_port(self.out.get_ports(), name))
        self.out.open_port(self.out.get_ports().index(self.name))
        names = self.inp.get_ports()
        self.inp.open_port(names.index(check_port_name(find_port(names, name))))
        self.inp.ignore_types(sysex=False, timing=True, active_sense=True)
        self.lock, self.got = threading.Lock(), []
        self.inp.set_callback(self._rx)

    def _rx(self, event, _data):
        with self.lock:
            self.got.extend(event[0])

    def take(self):
        with self.lock:
            g, self.got = self.got, []
        return g

    def send(self, msg):
        self.out.send_message(list(allowed(msg)))

    def close(self):
        self.inp.close_port()
        self.out.close_port()


def exchange(port, msg, expect, wait, log, t0):
    port.take()
    log.write(f"{time.monotonic() - t0:10.4f} > {bytes(msg).hex(' ')}\n")
    port.send(msg)
    end = time.monotonic() + wait
    data = []
    while time.monotonic() < end:
        time.sleep(0.02)
        data += port.take()
        if len(split(data)) >= expect:
            time.sleep(0.05)
            data += port.take()
            break
    msgs = split(data)
    for m in msgs:
        log.write(f"{time.monotonic() - t0:10.4f} < {m.hex(' ')}\n")
    return msgs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="print the plan, send nothing")
    ap.add_argument("--yes", action="store_true", help="send (only with the user's OK)")
    ap.add_argument("--port", help="MIDI port (default: [midi] usb_port of work/hwrig.toml)")
    ap.add_argument("--against", type=Path, help="earlier run directory to compare with")
    args = ap.parse_args(argv)

    steps = plan()
    for _, msg, _, _ in steps:
        allowed(msg)
    if args.dry_run or not args.yes:
        print(f"{len(steps) + 2} messages, all read requests but one write to the edit buffer:")
        for label, msg, n, _ in steps[:6] + steps[-1:]:
            print(f"  {label:12s} {msg.hex(' ')}  ({n} answer{'s' if n > 1 else ''})")
        print("  ... and 'round trip': the current patch sent back as write 00, then 40")
        if not args.yes:
            print("Nothing sent (give --yes, with the user's OK).")
        return 0

    sys.path.insert(0, str(ROOT / "tools"))
    from hwrig import config as config_mod
    port = Port(args.port or config_mod.load().usb_port)
    out = RUNS / f"editor-{datetime.now():%Y-%m-%d_%H%M%S}"
    out.mkdir(parents=True)
    summary, problems = {}, []
    t0 = time.monotonic()
    try:
        with open(out / "replies.log", "w", encoding="utf-8") as log:
            answers = {}
            for label, msg, n, wait in steps:
                msgs = exchange(port, msg, n, wait, log, t0)
                answers[label] = msgs
                summary[label] = summarize(msgs)
                if len(msgs) != n:
                    problems.append(f"{label}: {len(msgs)} answers, expected {n}")
            cur = answers["current"]
            if len(cur) == 1 and len(cur[0]) == PATCH_LEN:
                exchange(port, cur[0], 0, 0.5, log, t0)          # write 00: the edit buffer, unchanged
                back = exchange(port, req(0x40), 1, 1.0, log, t0)
                ok = len(back) == 1 and back[0] == cur[0]
                summary["round trip"] = {"same": ok}
                if not ok:
                    problems.append("round trip: the current patch came back changed")
            else:
                problems.append("round trip: no current patch to send back")
    finally:
        port.close()
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    before = args.against or previous_run(exclude=out)
    changed = compare(summary, json.loads((before / "summary.json").read_text())) if before else []
    print(f"{out.relative_to(ROOT)}: {len(summary)} requests")
    for p in problems:
        print("  PROBLEM", p)
    if before:
        print(f"  against {before.name}: {len(changed)} changed" + (": " + ", ".join(changed) if changed else ""))
    else:
        print("  first run: this is the baseline")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
