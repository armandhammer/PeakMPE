#!/usr/bin/env python3
"""Estimate the flash load address of a flat Cortex-M image.

Counts how many 32-bit little-endian words in the image point exactly at the
start of a NUL-terminated ASCII string, for each candidate base. The correct
base produces a sharp peak. Also checks that the reset vector lands inside the
image at that base.

  find_base.py IMAGE.bin [--lo 0x08000000] [--hi 0x08100000] [--step 0x20]
"""
import argparse
import re
import struct


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("image")
    p.add_argument("--lo", type=lambda s: int(s, 0), default=0x08000000)
    p.add_argument("--hi", type=lambda s: int(s, 0), default=0x08100000)
    p.add_argument("--step", type=lambda s: int(s, 0), default=0x20)
    args = p.parse_args()

    data = open(args.image, "rb").read()
    strings = {m.start() for m in re.finditer(rb"[\x20-\x7e]{4,}\x00", data)}
    words = [struct.unpack_from("<I", data, i)[0] for i in range(0, len(data) - 3, 4)]
    flash = [w for w in words if args.lo <= w < args.hi + len(data)]

    scores = []
    for base in range(args.lo, args.hi, args.step):
        scores.append((sum(1 for w in flash if (w - base) in strings), base))
    scores.sort(reverse=True)

    reset = struct.unpack_from("<I", data, 4)[0] & ~1
    print(f"{len(strings)} strings, {len(flash)} flash-range words")
    for score, base in scores[:5]:
        inside = 0 <= reset - base < len(data)
        print(f"  base {base:#010x}: {score:5d} string pointers, reset {'inside' if inside else 'OUTSIDE'} image")


if __name__ == "__main__":
    main()
