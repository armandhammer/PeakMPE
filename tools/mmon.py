#!/usr/bin/env python3
"""Read Snoize MIDI Monitor documents (.mmon) without MIDI Monitor.

A .mmon file is a binary plist whose `messageData` is an NSKeyedArchiver
archive of SMMessage objects (SMSystemExclusiveMessage, SMVoiceMessage, ...).
Each message has an `originatingEndpoint` name ("To X" for what was sent to
destination X, "From X" for what source X sent), a host timestamp in ns, and
its bytes (SysEx without the F0/F7 framing).

  mmon.py summary CAPTURE.mmon          endpoints, message counts, time span
  mmon.py log CAPTURE.mmon [OUT.log]    one line per message, in the same
                                        format as `tools/flash.py --log`:
                                        "<seconds> <>|<> <port> <hex bytes>"

Run with `python3 -I`; uses only the standard library.
"""
import argparse
import collections
import plistlib
import sys


def messages(path):
    """Yield (seconds, direction, port, bytes) in capture order."""
    doc = plistlib.load(open(path, "rb"))
    if "messageData" not in doc:  # a document saved with no messages
        return
    archive = plistlib.loads(doc["messageData"])
    objs = archive["$objects"]

    def deref(v):
        return objs[v.data] if isinstance(v, plistlib.UID) else v

    root = deref(archive["$top"]["root"])
    t0 = None
    for uid in root["NS.objects"]:
        o = deref(uid)
        cls = deref(o["$class"])["$classname"]
        endpoint = deref(o.get("originatingEndpoint")) or "?"
        if endpoint.startswith("To "):
            direction, port = ">", endpoint[3:]
        elif endpoint.startswith("From "):
            direction, port = "<", endpoint[5:]
        else:
            direction, port = "?", endpoint
        ns = o.get("timeStampInNanos", 0)
        t0 = ns if t0 is None else t0
        status = o.get("statusByte", 0)
        if cls == "SMSystemExclusiveMessage":
            body = deref(o.get("data")) or b""
            data = bytes([0xF0]) + bytes(body) + (b"\xf7" if o.get("wasReceivedWithEOX", True) else b"")
        else:
            data = bytes([status]) + bytes(deref(o.get("dataBytes")) or b"")
        yield (ns - t0) / 1e9, direction, port.replace(" ", "_"), data


def read_log(path):
    """Yield (seconds, direction, port, bytes) from a `mmon.py log` export,
    a `flash.py --log` or a `midirec.py` recording. Blank lines and comment
    lines starting with "#" (midirec's markers) are skipped."""
    for line in open(path):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        t, d, port, *hexbytes = line.split()
        yield float(t), d, port, bytes.fromhex("".join(hexbytes))


def cmd_summary(args):
    count = collections.Counter()
    first = last = None
    for t, d, port, data in messages(args.mmon):
        kind = f"SysEx {data[5]:#04x}" if data[:5] == b"\xf0\x00\x20\x29\x00" and len(data) > 5 else (
            "SysEx" if data[0] == 0xF0 else f"{data[0] & 0xF0:#04x}")
        count[(d, port, kind)] += 1
        first = t if first is None else first
        last = t
    for (d, port, kind), n in sorted(count.items()):
        print(f"{d} {port:24s} {kind:12s} {n}")
    print(f"span {last - first:.3f} s" if first is not None else "no messages")


def cmd_log(args):
    out = open(args.out, "w") if args.out else sys.stdout
    for t, d, port, data in messages(args.mmon):
        out.write(f"{t:10.4f} {d} {port} {data.hex(' ')}\n")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("summary"); s.add_argument("mmon"); s.set_defaults(fn=cmd_summary)
    s = sub.add_parser("log"); s.add_argument("mmon"); s.add_argument("out", nargs="?"); s.set_defaults(fn=cmd_log)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
