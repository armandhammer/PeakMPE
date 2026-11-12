#!/usr/bin/env python3
"""Build a patched Summit firmware .syx from the official file.

  patch.py patches/version_string.py              build into work/patched/
  patch.py patches/version_string.py --out DIR    build into DIR
  patch.py patches/demo_note_hook/patch.py --verify
                                                  build a C patch and check every hook

A patch definition is a Python file (sources only, never images) with:

  SOURCE   official file name in firmware/, e.g. "summit-firmware-2.2-build2121.syx"
  NAME     short name used for the output file
  PATCHES  list of (address, original bytes, new bytes, why) tuples, addresses
           in flash (image base 0x0800C000). A 5th element True lets a patch
           extend the image (gap filled with 0xFF, the erased-flash value).
  HEADER   optional (original body, new body, why): replaces the 8-byte 0x71
           header body, e.g. its version digits. Without it the official
           header is kept.
  SOURCES  optional: C files, relative to the definition, compiled by
           tools/patch_build.py into a blob that is appended to the image
           (docs/patch-howto.md).
  HOOKS    optional, with SOURCES: (kind, site, expected, symbol, why) tuples
           that redirect firmware code into the blob:
             "bl"       the BL instruction at site, which must call expected,
                        is rewritten to call the patch function symbol;
             "pointer"  the 32-bit word at site, which must equal expected
                        (e.g. a handler table entry or its .data
                        initialiser), is replaced by symbol's address (with
                        the Thumb bit for functions).
           Every C patch also gets STARTUP_HOOKS[SOURCE]: Reset_Handler's call
           of main_loop goes to __patch_start, which zeroes patch RAM first.

The tool:
  1. checks the official file against firmware/SHA256SUMS (refuses if absent
     or different: addresses are specific to one build);
  2. decodes it with tools/syx.py; for C patches builds the blob at the image
     end and turns hooks into byte patches, checking each site's original
     instruction or word;
  3. applies every patch, refusing if the original bytes don't match or
     patches overlap, and keeps the image length unless a patch says
     otherwise (padded to 32 bytes, never past FLASH_LIMIT);
  4. re-encodes with the official header (or HEADER's, checked against the
     original), decodes the result again to check it,
     writes work/patched/<source>+<name>.syx and prints a byte diff summary;
  5. with --verify, disassembles every hook site and blob entry point of the
     patched image with llvm-objdump and checks where branches and pointers
     land (see verify()).

Run with `scripts/dev python -I tools/patch.py ...`.
"""
import argparse
import hashlib
import importlib.util
import os
import re
import struct
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import patch_build  # noqa: E402
import syx  # noqa: E402

IMAGE_BASE = 0x0800C000
FLASH_LIMIT = patch_build.FLASH_LIMIT
FIRMWARE_DIR = ROOT / "firmware"
OUT_DIR = ROOT / "work" / "patched"
LLVM_BIN = Path(os.environ.get("LLVM_BIN", "/opt/homebrew/opt/llvm/bin"))

# Added to every C patch: Reset_Handler 0x0801D9BC calls main_loop at
# 0x0801D9F2, after its .data copy and before main's init enables the FPU.
STARTUP_HOOKS = {
    "summit-firmware-2.2-build2121.syx":
        ("bl", 0x0801D9F2, 0x0801C564, "__patch_start",
         "Reset_Handler -> main_loop: zero patch RAM and run patch_init first"),
    # Peak: Reset_Handler 0x0801D6C4 calls main_loop 0x0800D11C at 0x0801D6FA
    # (docs/symbols/peak-2.2-2108.csv).
    "peak-firmware-2.2-build2108.syx":
        ("bl", 0x0801D6FA, 0x0800D11C, "__patch_start",
         "Reset_Handler -> main_loop: zero patch RAM and run patch_init first"),
}


class PatchError(Exception):
    pass


@dataclass
class Hook:
    kind: str       # "bl" or "pointer"
    site: int
    expected: int   # stock call target (bl) or stock word (pointer)
    symbol: str
    target: int     # new call target (bl, no Thumb bit) or new word (pointer)
    why: str


def load_definition(path):
    """Import a patch definition file and return the module."""
    path = Path(path)
    spec = importlib.util.spec_from_file_location(f"patchdef_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for attr in ("SOURCE", "NAME", "PATCHES"):
        if not hasattr(module, attr):
            raise PatchError(f"{path}: missing {attr}")
    if getattr(module, "HOOKS", None) and not getattr(module, "SOURCES", None):
        raise PatchError(f"{path}: HOOKS need SOURCES")
    return module


def sources(definition):
    """The definition's C files as paths, relative to the definition file."""
    base = Path(definition.__file__).parent
    return [base / s for s in getattr(definition, "SOURCES", [])]


# ------------------------------------------------------------------ hooks

def encode_bl(site, target):
    """The 4 bytes of a Thumb-2 BL (T1) at *site* calling *target*."""
    offset = target - (site + 4)
    if offset % 2 or not -(1 << 24) <= offset < (1 << 24):
        raise PatchError(f"BL from {site:#010x} cannot reach {target:#010x}")
    s = (offset >> 24) & 1
    i1, i2 = (offset >> 23) & 1, (offset >> 22) & 1
    j1, j2 = (1 - i1) ^ s, (1 - i2) ^ s
    hw1 = 0xF000 | (s << 10) | ((offset >> 12) & 0x3FF)
    hw2 = 0xD000 | (j1 << 13) | (j2 << 11) | ((offset >> 1) & 0x7FF)
    return struct.pack("<HH", hw1, hw2)


def decode_bl(site, data):
    """The call target of the Thumb-2 BL in *data* at *site*, or None if it isn't one."""
    hw1, hw2 = struct.unpack("<HH", bytes(data[:4]))
    if hw1 & 0xF800 != 0xF000 or hw2 & 0xD000 != 0xD000:
        return None
    s = (hw1 >> 10) & 1
    j1, j2 = (hw2 >> 13) & 1, (hw2 >> 11) & 1
    i1, i2 = 1 - (j1 ^ s), 1 - (j2 ^ s)
    offset = (s << 24) | (i1 << 23) | (i2 << 22) | ((hw1 & 0x3FF) << 12) | ((hw2 & 0x7FF) << 1)
    if s:
        offset -= 1 << 25
    return site + 4 + offset


def resolve_hooks(specs, blob):
    """Turn (kind, site, expected, symbol, why) tuples into :class:`Hook`s against *blob*."""
    hooks = []
    text = (blob.origin, blob.origin + len(blob.data))
    for kind, site, expected, symbol, why in specs:
        if symbol not in blob.symbols:
            raise PatchError(f"hook {site:#010x}: patch symbol {symbol!r} is not defined ({why})")
        value = blob.address(symbol)
        in_text = text[0] <= value & ~1 < text[1]
        in_ram = blob.bss[0] <= value < blob.bss[1]
        if kind == "bl":
            if not (blob.is_function(symbol) and in_text):
                raise PatchError(f"hook {site:#010x}: {symbol} is not a patch function ({why})")
            target = value & ~1
        elif kind == "pointer":
            if not (in_text or in_ram):
                raise PatchError(f"hook {site:#010x}: {symbol} is not in the patch blob or patch RAM ({why})")
            if blob.is_function(symbol) and not value & 1:
                raise PatchError(f"hook {site:#010x}: {symbol} has no Thumb bit ({why})")
            target = value
        else:
            raise PatchError(f"hook {site:#010x}: unknown kind {kind!r} ({why})")
        hooks.append(Hook(kind, site, expected, symbol, target, why))
    return hooks


def hook_patches(image, hooks, base=IMAGE_BASE):
    """Byte patches for *hooks*, after checking each site holds the expected BL or word."""
    patches = []
    for h in hooks:
        off = h.site - base
        if off < 0 or off + 4 > len(image):
            raise PatchError(f"hook {h.site:#010x} is outside the image ({h.why})")
        old = bytes(image[off:off + 4])
        if h.kind == "bl":
            found = decode_bl(h.site, old)
            if found != h.expected:
                what = f"a BL to {found:#010x}" if found is not None else f"not a BL ({old.hex(' ')})"
                raise PatchError(f"hook {h.site:#010x}: expected a BL to {h.expected:#010x}, found {what} ({h.why})")
            new = encode_bl(h.site, h.target)
        else:
            if h.site % 4:
                raise PatchError(f"hook {h.site:#010x}: a pointer site must be 4-byte aligned ({h.why})")
            found = struct.unpack("<I", old)[0]
            if found != h.expected:
                raise PatchError(f"hook {h.site:#010x}: expected the word {h.expected:#010x}, "
                                 f"found {found:#010x} ({h.why})")
            new = struct.pack("<I", h.target)
        patches.append((h.site, old, new, f"{h.kind} hook -> {h.symbol}: {h.why}"))
    return patches


def expected_sha256(firmware_dir, name):
    sums = Path(firmware_dir) / "SHA256SUMS"
    if sums.exists():
        for line in sums.read_text().splitlines():
            digest, _, file = line.partition("  ")
            if file.strip() == name:
                return digest
    return None


def read_official(firmware_dir, name):
    """Return the official .syx bytes after checking them against SHA256SUMS."""
    path = Path(firmware_dir) / name
    if not path.exists():
        raise PatchError(f"{path} not found (run scripts/fetch-firmware.sh)")
    expected = expected_sha256(firmware_dir, name)
    if expected is None:
        raise PatchError(f"{name} has no entry in {Path(firmware_dir) / 'SHA256SUMS'}")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise PatchError(f"{path} does not match its SHA-256 in SHA256SUMS")
    return data


def apply(image, patches, base=IMAGE_BASE):
    """Return a patched copy of *image*. Every patch is checked before any is applied."""
    out = bytearray(image)
    taken = []
    for entry in patches:
        addr, old, new, why = entry[:4]
        extend = len(entry) > 4 and entry[4]
        off = addr - base
        if not extend and len(new) != len(old):
            raise PatchError(f"{addr:#010x}: new bytes ({len(new)}) differ in length from the "
                             f"original ({len(old)}) ({why})")
        end = off + max(len(old), len(new))
        if off < 0:
            raise PatchError(f"{addr:#010x} is below the image base {base:#010x}")
        if end > len(image) and not extend:
            raise PatchError(f"{addr:#010x}: patch runs past the image end "
                             f"{base + len(image):#010x} and does not allow extending")
        for lo, hi, other in taken:
            if off < hi and lo < end:
                raise PatchError(f"{addr:#010x} overlaps the patch at {base + lo:#010x}")
        taken.append((off, end, addr))
        have = bytes(image[off:off + len(old)])
        if have != old:
            raise PatchError(f"{addr:#010x}: expected {old.hex(' ')}, found {have.hex(' ')} ({why})")
    for entry in patches:
        addr, old, new = entry[:3]
        off = addr - base
        if off + len(new) > len(out):
            out += b"\xff" * (off + len(new) - len(out))
        out[off:off + len(new)] = new
    if len(out) % syx.BLOCK:
        out += b"\xff" * (-len(out) % syx.BLOCK)
    return bytes(out)


def replace_header(header, spec):
    """Return the header body to encode: *header* itself, or *spec*'s new body after checking."""
    if spec is None:
        return bytes(header)
    old, new, why = spec
    if len(new) != len(header):
        raise PatchError(f"new header ({len(new)} bytes) differs in length from the original "
                         f"({len(header)}) ({why})")
    if bytes(header) != old:
        raise PatchError(f"header: expected {old.hex(' ')}, found {bytes(header).hex(' ')} ({why})")
    if any(b > 0x7F for b in new):
        raise PatchError(f"header: {new.hex(' ')} has bytes above 0x7F, not valid in SysEx ({why})")
    return bytes(new)


def diff(a, b, base=IMAGE_BASE):
    """List (address, old bytes, new bytes) runs where *a* and *b* differ."""
    runs, start = [], None
    n = max(len(a), len(b))
    for i in range(n + 1):
        differs = i < n and (i >= len(a) or i >= len(b) or a[i] != b[i])
        if differs and start is None:
            start = i
        elif not differs and start is not None:
            runs.append((base + start, bytes(a[start:i]), bytes(b[start:i])))
            start = None
    return runs


def _show(data):
    return "".join(chr(c) if 32 <= c < 127 else "." for c in data)


@dataclass
class Built:
    """Everything build_image() produced, before encoding."""
    definition: object
    header: bytes        # official 0x71 body
    new_header: bytes
    image: bytes         # official flat image
    patched: bytes
    blob: object = None  # patch_build.Blob for C patches
    hooks: tuple = ()


def build_image(definition_path, firmware_dir=FIRMWARE_DIR, build_dir=None):
    """Build the patched flat image of a definition (no file written except C build output)."""
    definition = load_definition(definition_path)
    official = read_official(firmware_dir, definition.SOURCE)
    header, image = syx.decode(official)
    patches = list(definition.PATCHES)
    blob, hooks = None, []
    if getattr(definition, "SOURCES", None):
        if definition.SOURCE not in STARTUP_HOOKS:
            raise PatchError(f"no startup hook known for {definition.SOURCE}")
        origin = IMAGE_BASE + len(image) + (-len(image) % 4)
        try:
            blob = patch_build.build(definition.NAME, sources(definition), origin, build_dir,
                                     csv_path=patch_build.symbols_for(definition.SOURCE))
        except patch_build.BuildError as e:
            raise PatchError(str(e)) from None
        hooks = resolve_hooks([STARTUP_HOOKS[definition.SOURCE], *getattr(definition, "HOOKS", [])], blob)
        patches += hook_patches(image, hooks)
        patches.append((origin, b"", blob.data, f"patch blob {definition.NAME}", True))
    patched = apply(image, patches)
    if IMAGE_BASE + len(patched) > FLASH_LIMIT:
        raise PatchError(f"patched image ends at {IMAGE_BASE + len(patched):#010x}, past {FLASH_LIMIT:#010x}")
    new_header = replace_header(header, getattr(definition, "HEADER", None))
    return Built(definition, bytes(header), new_header, image, patched, blob, tuple(hooks))


def build(definition_path, firmware_dir=FIRMWARE_DIR, out_dir=OUT_DIR, out=print, verify_hooks=False,
          build_dir=None):
    """Build the patched .syx; return (output path, sha256 hex)."""
    b = build_image(definition_path, firmware_dir, build_dir)
    definition, header, image, patched, new_header = b.definition, b.header, b.image, b.patched, b.new_header
    data = syx.encode(new_header, patched)

    header2, image2 = syx.decode(data)
    if header2 != new_header or image2 != patched or syx.encode(header2, image2) != data:
        raise PatchError("re-encoded file does not decode back to the patched image")

    if verify_hooks:
        if b.blob is not None:
            verify(patched, b.hooks, b.blob, out=out)
        else:
            out("verify  nothing to check: byte patches only, no hooks")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{Path(definition.SOURCE).stem}+{definition.NAME}.syx"
    path.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()

    runs = diff(image, patched)
    out(f"source  {definition.SOURCE}  ({len(image)} bytes, header {header.hex(' ')})")
    out(f"patch   {definition.NAME}: {len(definition.PATCHES)} patch(es), {len(b.hooks)} hook(s), "
        f"{sum(len(o) for _, o, _ in runs)} byte(s) differ in {len(runs)} run(s)")
    for addr, old, new in runs:
        if len(new) > 32 and not old:
            out(f"  {addr:#010x}  {len(new)} bytes appended (blob and padding)")
            continue
        out(f"  {addr:#010x}  {old.hex(' ')}  '{_show(old)}'")
        out(f"  {'':10}  {new.hex(' ')}  '{_show(new)}'")
    for h in b.hooks:
        out(f"hook    {h.kind:7} {h.site:#010x}: {h.expected:#010x} -> {h.target:#010x} {h.symbol}")
    if b.blob is not None:
        for line in patch_build.budget(b.blob):
            out(line)
    if new_header != header:
        out(f"header  {header.hex(' ')} -> {new_header.hex(' ')}")
    if len(patched) != len(image):
        out(f"length  {len(image)} -> {len(patched)} bytes")
    out(f"wrote   {path}")
    out(f"sha256  {digest}")
    return path, digest


# ----------------------------------------------------------------- verify

_INSN = re.compile(r"^\s*([0-9a-f]+):\s+(.*?)\s*$")
_BRANCH = re.compile(r"^(blx?|b(?:eq|ne|cs|hs|cc|lo|mi|pl|vs|vc|hi|ls|ge|lt|gt|le|al)?(?:\.[nw])?"
                     r"|cbn?z\s+r\d+,)\s+0x([0-9a-f]+)")


def _objdump(elf, start, stop, adjust=0):
    """[(address, instruction text)] disassembled by llvm-objdump from *start* to *stop*."""
    tool = LLVM_BIN / "llvm-objdump"
    if not tool.exists():
        raise PatchError(f"{tool} not found (run it in the dev image: scripts/dev; or set LLVM_BIN)")
    cmd = [str(tool), "-d", "--triple=thumbv7em-none-eabi", "--mcpu=cortex-m4", "--no-show-raw-insn",
           f"--start-address={start - adjust:#x}", f"--stop-address={stop - adjust:#x}"]
    if adjust:
        cmd.append(f"--adjust-vma={adjust:#x}")
    r = subprocess.run(cmd + [str(elf)], capture_output=True, text=True)
    if r.returncode:
        raise PatchError(f"llvm-objdump failed: {r.stderr.strip()}")
    out = []
    for line in r.stdout.splitlines():
        m = _INSN.match(line)
        if m:
            insn = re.sub(r"<[^>]*>", "", m.group(2).split("@")[0])
            out.append((int(m.group(1), 16), " ".join(insn.split())))
    return out


def _target(text):
    m = _BRANCH.match(text)
    return (m.group(1).split()[0], int(m.group(2), 16)) if m else (None, None)


def verify(patched, hooks, blob, base=IMAGE_BASE, out=print):
    """Disassemble the patched image and check every hook and the blob's branches.

    Checks, with llvm-objdump on the patched image itself:
      * each BL hook site decodes to `bl <target>` with target the patch
        function, inside the blob;
      * each pointer hook site holds the patch symbol's address (Thumb bit
        set for functions) and, for functions, the entry disassembles;
      * the blob bytes in the image equal the linked ELF's .text;
      * every direct branch in the blob (disassembled from the ELF, whose
        mapping symbols keep literal pools out) lands inside the blob or on
        a firmware function entry from the symbols CSV, and none is a BLX
        (which would switch to ARM state).
    Raises PatchError listing every failure.
    """
    problems = []
    text = (blob.origin, blob.origin + len(blob.data))
    off = blob.origin - base
    if patched[off:off + len(blob.data)] != blob.data:
        problems.append("blob bytes in the image differ from the ELF .text")

    with tempfile.TemporaryDirectory() as tmp:
        raw, elf = Path(tmp) / "image.bin", Path(tmp) / "image.elf"
        raw.write_bytes(patched)
        r = subprocess.run([str(LLVM_BIN / "llvm-objcopy"), "-I", "binary", "-O", "elf32-littlearm",
                            "--rename-section", ".data=.text,alloc,load,readonly,code,contents",
                            "--strip-all", "image.bin", "image.elf"], cwd=tmp, capture_output=True, text=True)
        if r.returncode:
            raise PatchError(f"llvm-objcopy failed: {r.stderr.strip()}")

        entries = {"__patch_start"}
        for h in hooks:
            if h.kind == "bl":
                insn = _objdump(elf, h.site, h.site + 4, base)
                shown = insn[0][1] if insn else "?"
                mnemonic, target = _target(shown)
                ok = mnemonic == "bl" and target == h.target and text[0] <= target < text[1]
                out(f"verify  {h.site:#010x}  {shown:24} -> {h.symbol} {'ok' if ok else 'FAIL'}")
                if not ok:
                    problems.append(f"{h.site:#010x}: {shown!r} is not 'bl {h.target:#x}' ({h.symbol})")
                entries.add(h.symbol)
            else:
                word = struct.unpack_from("<I", patched, h.site - base)[0]
                ok = word == h.target
                out(f"verify  {h.site:#010x}  .word {word:#010x}       -> {h.symbol} {'ok' if ok else 'FAIL'}")
                if not ok:
                    problems.append(f"{h.site:#010x}: word {word:#010x}, expected {h.target:#010x} ({h.symbol})")
                if blob.is_function(h.symbol):
                    entries.add(h.symbol)

        for name in sorted(entries):
            addr = blob.address(name)
            entry = addr & ~1
            first = _objdump(elf, entry, entry + 4, base)
            shown = first[0][1] if first else "?"
            ok = addr & 1 and text[0] <= entry < text[1] and first and first[0][0] == entry \
                and "unknown" not in shown
            out(f"entry   {entry:#010x}  {shown:24}    {name} {'ok' if ok else 'FAIL'}")
            if not ok:
                problems.append(f"entry {name} at {addr:#010x}: {shown!r}")

    external = set()
    for addr, insn in _objdump(blob.elf, text[0], text[1]):
        mnemonic, target = _target(insn)
        if mnemonic is None:
            continue
        if mnemonic == "blx":
            problems.append(f"{addr:#010x}: {insn!r} switches to ARM state")
        elif not text[0] <= target < text[1]:
            if target in blob.fw_functions:
                external.add(target)
            else:
                problems.append(f"{addr:#010x}: {insn!r} branches to {target:#010x}, "
                                "neither in the blob nor a known firmware function")
    names = {a & ~1: n for n, a in blob.firmware.items() if a & ~1 in blob.fw_functions}
    out(f"verify  blob branches: internal or to {len(external)} firmware function(s): "
        + ", ".join(names[t] for t in sorted(external)))
    if problems:
        raise PatchError("verify failed:\n  " + "\n  ".join(problems))
    out("verify  ok")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("definition", help="patch definition file, e.g. patches/version_string.py")
    p.add_argument("--firmware", default=str(FIRMWARE_DIR), help="directory with the official file and SHA256SUMS")
    p.add_argument("--out", default=str(OUT_DIR), help="output directory (default work/patched)")
    p.add_argument("--verify", action="store_true",
                   help="disassemble hook sites and blob entry points after patching (C patches)")
    args = p.parse_args(argv)
    try:
        build(args.definition, args.firmware, args.out, verify_hooks=args.verify)
    except PatchError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
