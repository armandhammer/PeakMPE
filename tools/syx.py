#!/usr/bin/env python3
"""Novation Peak/Summit firmware update (.syx) codec.

Container format (see docs/firmware-format.md):

  F0 00 20 29 00 71 <header> F7        product id, version fields
  F0 00 20 29 00 72 <37 septets> F7    32 image bytes each, sequential from
                                       image offset 0x20
  F0 00 20 29 00 73 <37 septets> F7    image bytes 0x00-0x1F (vector table
                                       entries 0-7), sent last

37 septets are a big-endian 7-bit bitstream carrying 256 bits plus 3 zero
padding bits. The image produced by `decode` is the flat flash contents,
starting at the vector table.

  syx.py info   FILE.syx
  syx.py decode FILE.syx IMAGE.bin
  syx.py encode TEMPLATE.syx IMAGE.bin OUT.syx    header copied from TEMPLATE
  syx.py roundtrip FILE.syx                       decode + encode, compare

Run with `python3 -I` when pointing it at downloaded files.
"""
import argparse
import collections
import hashlib
import sys

NOVATION = b"\x00\x20\x29"
CMD_HEADER, CMD_DATA, CMD_FINAL = 0x71, 0x72, 0x73
BLOCK = 32
SEPTETS = 37


def messages(data):
    """Yield (command, body) for each Novation SysEx message, body after the command byte."""
    pos = 0
    while pos < len(data):
        if data[pos] != 0xF0:
            raise ValueError(f"expected F0 at offset {pos:#x}, got {data[pos]:#04x}")
        end = data.index(0xF7, pos)
        msg = data[pos + 1:end]
        if msg[:3] != NOVATION or msg[3] != 0x00:
            raise ValueError(f"non-Novation message at offset {pos:#x}: {msg[:5].hex()}")
        yield msg[4], msg[5:]
        pos = end + 1


def unpack(septets):
    bits = n = 0
    out = bytearray()
    for b in septets:
        if b & 0x80:
            raise ValueError("data byte with bit 7 set")
        bits = (bits << 7) | b
        n += 7
        while n >= 8 and len(out) < BLOCK:
            n -= 8
            out.append((bits >> n) & 0xFF)
    if len(out) != BLOCK or bits & ((1 << n) - 1):
        raise ValueError("block does not carry exactly 32 bytes with zero padding")
    return bytes(out)


def pack(block):
    if len(block) != BLOCK:
        raise ValueError("block must be 32 bytes")
    bits = int.from_bytes(block, "big") << (SEPTETS * 7 - BLOCK * 8)
    return bytes((bits >> (7 * i)) & 0x7F for i in reversed(range(SEPTETS)))


def frame(cmd, body):
    return b"\xf0" + NOVATION + b"\x00" + bytes([cmd]) + body + b"\xf7"


def decode(data):
    """Return (header body, flat image)."""
    header, stream, final = None, bytearray(), None
    for cmd, body in messages(data):
        if cmd == CMD_HEADER:
            header = body
        elif cmd == CMD_DATA:
            stream += unpack(body)
        elif cmd == CMD_FINAL:
            final = unpack(body)
        else:
            raise ValueError(f"command {cmd:#04x} is not a firmware image (FPGA file?)")
    if header is None or final is None:
        raise ValueError("missing header (0x71) or final block (0x73)")
    return header, final + bytes(stream)


def encode(header, image):
    if len(image) % BLOCK:
        raise ValueError(f"image length {len(image)} is not a multiple of {BLOCK}")
    out = bytearray(frame(CMD_HEADER, header))
    for off in range(BLOCK, len(image), BLOCK):
        out += frame(CMD_DATA, pack(image[off:off + BLOCK]))
    out += frame(CMD_FINAL, pack(image[:BLOCK]))
    return bytes(out)


def cmd_info(args):
    data = open(args.syx, "rb").read()
    counts = collections.Counter()
    sizes = collections.Counter()
    header = None
    for cmd, body in messages(data):
        counts[cmd] += 1
        sizes[(cmd, len(body))] += 1
        if cmd == CMD_HEADER:
            header = body
    print(f"file    {args.syx}")
    print(f"sha256  {hashlib.sha256(data).hexdigest()}")
    print(f"bytes   {len(data)}")
    for cmd, n in sorted(counts.items()):
        lens = sorted(l for (c, l) in sizes if c == cmd)
        print(f"cmd {cmd:#04x}: {n} messages, body lengths {lens}")
    if header is not None:
        print(f"header  {header.hex(' ')}")
    if set(counts) <= {CMD_HEADER, CMD_DATA, CMD_FINAL}:
        _, image = decode(data)
        sp, reset = int.from_bytes(image[0:4], "little"), int.from_bytes(image[4:8], "little")
        print(f"image   {len(image)} bytes, initial SP {sp:#010x}, reset {reset:#010x}")


def cmd_decode(args):
    _, image = decode(open(args.syx, "rb").read())
    open(args.image, "wb").write(image)
    print(f"wrote {args.image}: {len(image)} bytes")


def cmd_encode(args):
    header, _ = decode(open(args.template, "rb").read())
    out = encode(header, open(args.image, "rb").read())
    open(args.out, "wb").write(out)
    print(f"wrote {args.out}: {len(out)} bytes, sha256 {hashlib.sha256(out).hexdigest()}")


def cmd_roundtrip(args):
    data = open(args.syx, "rb").read()
    header, image = decode(data)
    again = encode(header, image)
    if again != data:
        first = next(i for i, (a, b) in enumerate(zip(data, again)) if a != b)
        print(f"MISMATCH at offset {first:#x} (lengths {len(data)} / {len(again)})")
        return 1
    print(f"ok  {args.syx}: byte-identical after decode + encode")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("info"); s.add_argument("syx"); s.set_defaults(fn=cmd_info)
    s = sub.add_parser("decode"); s.add_argument("syx"); s.add_argument("image"); s.set_defaults(fn=cmd_decode)
    s = sub.add_parser("encode"); s.add_argument("template"); s.add_argument("image"); s.add_argument("out")
    s.set_defaults(fn=cmd_encode)
    s = sub.add_parser("roundtrip"); s.add_argument("syx"); s.set_defaults(fn=cmd_roundtrip)
    args = p.parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
