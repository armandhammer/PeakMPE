#!/usr/bin/env python3
"""Export a patch definition as a descriptor for the web patcher (web/).

  web_descriptor.py export patches/mpe/patch.py web/patches/mpe.json
  web_descriptor.py check  web/patches/mpe.json   no Novation bytes; up to date
  web_descriptor.py compare web/patches/mpe.json  rebuild and compare (scripts/check-repro.sh)

The browser can't compile C, so the web app applies a precomputed list of
writes to the user's own copy of the official file. The descriptor holds only
our own work:

  writes    (address, bytes) runs: the replacement bytes of every byte patch
            and hook, and the compiled patch blob. A run never contains a byte
            equal to the official byte at that address: bytes a patch leaves
            unchanged are dropped, so they are not copied either.
  header    null (keep the official 0x71 header) or our replacement body.
  hashes    SHA-256 of the official .syx and of its decoded image, and of
            the expected output image and .syx, so the web side refuses any
            other input and any output that differs from tools/patch.py's.

Original firmware bytes appear only as those hashes. `check` proves it for
a descriptor file (docs/web.md#the-descriptor-holds-no-novation-bytes):

  1. the JSON has exactly the known keys, so no field can carry extra data;
  2. every write byte inside the official image differs from the official
     byte at that address, and the rest lie past the official image end;
  3. no run of MIN_SHARED (16) or more consecutive write bytes occurs
     anywhere in the official image or in the official .syx file. Aligned
     32-bit words that point into the firmware's memory map (flash, SRAM,
     peripherals: the blob's literal pools hold the addresses of firmware
     variables and functions it uses) split the runs, since an address is an
     interface fact the firmware's own literal pools hold too. The longest
     shared run is reported with and without that split;
  4. rebuilding from the descriptor gives tools/patch.py's output exactly.

`compare` rebuilds the patch from source and requires the descriptor's bytes:
the compiled blob always (it needs only the ARM toolchain, no firmware), and
the whole descriptor when the official file is in firmware/. It prints the
blob's SHA-256, so builds on two machines or architectures can be compared.

Needs the official file in firmware/ and, for export, the ARM toolchain.
Run with `scripts/dev python -I tools/web_descriptor.py ...`.
"""
import argparse
import base64
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import patch  # noqa: E402
import syx  # noqa: E402

FORMAT = "summit-mpe-patch-descriptor"
FORMAT_VERSION = 1
FILL = 0xFF
MIN_SHARED = 16

# Shown on the web page; the synth (the SOURCE file's first word) and the
# definition's NAME select the entry.
META = {
    ("summit", "mpe"): {
        "title": "MPE for Summit",
        "version": "1.3",
        "label": "MPE4 Ver 126.778",
        "summary": "Per-note pitch bend, pressure and slide (MPE), a per-patch MPE switch "
                   "(VOICE page), Settings MPE pages, Single and Multi mode; v1.1 rotates idle voices; v1.2 fixes Slide on hardware; "
                   "v1.3 lets a chord on a zone's master channel play in full (checked in the simulator only).",
    },
    ("peak", "mpe"): {
        "title": "MPE for Peak",
        "version": "0.43",
        "label": "MPEh Ver 108.469",
        "summary": "Per-note pitch bend, pressure (channel or poly aftertouch) and slide (MPE) on the Peak's "
                   "8 voices, a per-patch MPE switch (VOICE page) and Settings MPE pages; one or two zones. "
                   "v0.2: the arpeggiator ignores its own notes when a DAW sends them back (MIDI loop). "
                   "v0.3: turning a knob shows envelope times in ms and the filter cutoff in Hz, with a value bar, "
                   "and Pickup shows an arrow and a distance bar. "
                   "v0.4: Settings > MPE > PressCurve chooses stock's squared pressure or a linear curve. "
                   "v0.5: CC 11 on a member channel works as pressure. "
                   "v0.6: Settings > MPE EXTRAS > EnvSync sets the amp Decay and Release to a note length (1/2 to 1/16) at the current tempo (v0.7: a changed setting applies after 1 s). "
                   "v0.8: hold Mod and move a slider or knob to put its modulation destination in the first free matrix slot; the encoder chooses the source. "
                   "v0.11: Settings > PARAM LOCK keeps the FX, Arp or Voice settings through a patch change. "
                   "v0.12: Settings > COPY SECTION copies an oscillator, envelope or LFO to another; Mod + Page left/right undoes and redoes the last change; Settings > MIDI MONITOR shows the last message and the DIN overflow count. "
                   "v0.13: the copy and undo messages stay on screen about 2 s. "
                   "v0.14: Settings > MPE EXTRAS > Glide starts a poly glide from the previous note (LastNote), or only while another note is held (Legato), instead of from the voice's own last pitch; EnvSync and undo timings corrected. "
                   "v0.15: the patch's messages always clear and stay 3 s; Msg Time 127 now lasts about 3 s (stock: 1.5 s). "
                   "v0.16: motion recording: hold Mod and press Animate 1, move a slider or knob, and its movement over one bar loops in time with the tempo (Settings > MOTION sets 1, 2 or 4 bars). "
                   "v0.17: the recorded movement plays back as a ramp from step to step instead of jumps, also where the loop starts again. "
                   "v0.18: patch morph: with Settings > MORPH > Morph set to ModWheel, the mod wheel blends the patch as you have edited it (wheel down) towards the patch as it is stored (wheel up); levels, amounts, times, the filter, FX amounts and mod matrix depths move, switches stay. "
                   "v0.19: morph: holding Compare with the mod wheel up no longer loses the edit when the button is let go; after Save the saved sound is the patch, so the wheel has nothing left to blend until the next edit. "
                   "v0.20: holding Compare no longer clears the undo step or stops a motion lane: both wait while the button is held and go on when it is let go. Euclidean arp rhythms: Settings > ARP EUCLID sets Pulses, Steps and Rotate, and the arpeggiator plays that many notes spread evenly over the steps in place of the patch's Rhythm. With Arp>MIDI on and no MIDI loop, a key let go just after the arpeggiator's own note off is no longer ignored (before, the arpeggiator could go on playing a released key). "
                   "v0.21: arp ratchets: Settings > ARP RATCHET makes every note, or every second to eighth one, sound two or three times within its step. "
                   "v0.22: Osc 1/2/3 Fine sent over MIDI (CC 15, 18, 21) now reaches -100; stock ignored -100 to -73. "
                   "v0.23: the screen only sends the characters that change, about a tenth of stock's display traffic while a knob turns, which leaves more time for the per-note modulation (pitch bend, pressure, slide). "
                   "v0.24: release velocity: Settings > RELEASE VEL > Source puts each note-off's velocity into the ExprPED1 or BrthPED2 mod source of the notes it releases; route that source to AmpEnv R in the mod matrix and how fast a note is let go sets its release. "
                   "v0.25: MIDI Tuning Standard: the single-note tuning change is also taken with device ID 7F (all devices) and with several notes in one message, and the bulk tuning dump with device ID 7F, so tuning software reaches the tuning tables. "
                   "v0.26: Settings > RANDOMISE rolls new values for one section of the patch (an oscillator, the mixer, the filter, an envelope, an LFO, the FX, or all of them) inside ranges that keep it sounding, by an Amount from a nudge to a fresh roll; nothing is saved, and Mod + Page left takes a roll back. PARAM LOCK now keeps the chorus Mode with the FX instead of the arp. "
                   "v0.27: band-pass and high-pass rolls keep the cutoff where the note still comes through, and band-pass rolls bring some resonance, so they are no longer much quieter than the rest. "
                   "v0.28: hold Mod and press Audition for a panic: every note stops at once, and held or latched arp notes, stuck keys and per-note bend, pressure and slide are cleared. "
                   "v0.29: the patch's checks of the screen, the settings and the arp rhythm run once a millisecond instead of on every pass of the main loop, which gives the synth's own work more time. "
                   "v0.30: Settings > PATCH DUMP > Send = USB sends each newly loaded patch (by program change or the patch buttons) over USB in the editor's own format, so an editor or DAW can follow along. A rare full RANDOMISE roll could leave every oscillator quieter than the mixer rule allows; fixed. "
                   "v0.31: Settings > PATCH TIMING > Change at = Beat, Bar, 2 Bars or 4 Bars: while a DAW's MIDI clock plays, a patch change by program change or the patch buttons waits for the next beat or bar line and lands on it. "
                   "v0.32: a program change that arrives right on the bar line (just after its clock) now loads at once instead of a bar later; Continue without a song position goes on from where Stop left off. "
                   "v0.33: the PATCH TIMING message shows the right patch number (it showed D 55 for D003 after a program change). "
                   "v0.34: Settings > USB IN and DIN IN turn Notes, CC and Patch (program change and bank select) on or off for each input, for example notes only from a controller on DIN and patch changes only from a DAW on USB. Patch timing counts the clock only from the port the Clock Source setting follows, so a clock on both inputs no longer counts twice. "
                   "v0.35: Settings > JUST TUNE tunes chords in just intonation: Mode Fixed tunes every note to the Root you choose; Mode Adapt follows the chord you play, keeps held notes where they are and plays a note alone at its normal pitch. It works with or without MPE and with the arp. "
                   "v0.36: with MPE on, a chord on a zone's master channel plays in full (before, its notes took each other's voice). "
                   "v0.37: after the Peak is switched on, PATCH TIMING waits for a Start or a song position before it times changes, instead of guessing the bar from a bare Continue; a patch dump is no longer lost when an editor asks for something at the same moment. "
                   "v0.38: a key held down while you let go of the sostenuto pedal keeps sounding (the Peak's own firmware stopped it); with Glide on, the first notes after the Peak is switched on no longer glide up or down from middle C. "
                   "v0.39: when every voice is still in its attack (a slow pad), a new note takes the oldest note, not the one played just before it. "
                   "v0.40: when every voice is held, a new note takes a note the sustain or sostenuto pedal is holding before a key you are still holding down, and otherwise the oldest note. "
                   "v0.41: Settings VOICE STEAL > Keep Low: when voices run out, a new note never takes the lowest note that sounds, so a bass note under a chord keeps playing. "
                   "v0.42: Settings ARP RATCHET > Chance (10-100 %): each ratcheted note plays its repeats by chance, as ArpChance does for steps. "
                   "v0.43: fixes from a code audit: the arpeggiator echo filter no longer drops a real note about once a minute after the arp has played; "
                   "the MIDI monitor counts can no longer overrun their field; stock's display characters go back without a 3 ms pause in the per-note modulation; "
                   "editing a Settings item outside the MPE page no longer clears the MPE page's unsaved mark. "
                   "Tested on one Peak with the automated hardware test rig and played from a LinnStrument.",
    },
}

TOP_KEYS = {"format", "formatVersion", "name", "title", "version", "label", "summary", "built",
            "input", "output", "header", "fill", "writes"}
FILE_KEYS = {"fileName", "sha256", "bytes", "imageSha256", "imageLength"}
OUT_KEYS = FILE_KEYS | {"messages"}
WRITE_KEYS = {"address", "data", "why"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def changed_runs(image, address, new):
    """(address, bytes) runs of *new* at *address* that differ from *image* or lie past its end."""
    runs, start = [], None
    off = address - patch.IMAGE_BASE
    for i in range(len(new) + 1):
        differs = i < len(new) and (off + i >= len(image) or image[off + i] != new[i])
        if differs and start is None:
            start = i
        elif not differs and start is not None:
            runs.append((address + start, bytes(new[start:i])))
            start = None
    return runs


def git_commit():
    r = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def export(definition_path, firmware_dir=patch.FIRMWARE_DIR, build_dir=None):
    """The descriptor dict for a definition, built and checked against tools/patch.py."""
    b = patch.build_image(definition_path, firmware_dir, build_dir)
    d = b.definition
    official = patch.read_official(firmware_dir, d.SOURCE)
    entries = list(d.PATCHES) + patch.hook_patches(b.image, b.hooks)
    if b.blob is not None:
        entries.append((b.blob.origin, b"", b.blob.data, f"patch blob {d.NAME} (compiled C)", True))
    writes = []
    for entry in sorted(entries, key=lambda e: e[0]):
        addr, _old, new, why = entry[:4]
        for a, data in changed_runs(b.image, addr, new):
            writes.append({"address": f"0x{a:08X}", "data": base64.b64encode(data).decode(), "why": why})
    out = syx.encode(b.new_header, b.patched)
    meta = META.get((d.SOURCE.split("-")[0], d.NAME), {"title": d.NAME, "version": "0", "label": "", "summary": ""})
    desc = {
        "format": FORMAT,
        "formatVersion": FORMAT_VERSION,
        "name": d.NAME,
        **meta,
        "built": {"commit": git_commit(), "definition": str(Path(definition_path).as_posix())},
        "input": {"fileName": d.SOURCE, "sha256": sha(official), "bytes": len(official),
                  "imageSha256": sha(b.image), "imageLength": len(b.image)},
        "output": {"fileName": f"{Path(d.SOURCE).stem}+{d.NAME}.syx", "sha256": sha(out), "bytes": len(out),
                   "imageSha256": sha(b.patched), "imageLength": len(b.patched),
                   "messages": 2 + len(b.patched) // syx.BLOCK - 1},
        "header": None if b.new_header == b.header else b.new_header.hex(),
        "fill": FILL,
        "writes": writes,
    }
    rebuilt_header, rebuilt = apply_descriptor(desc, official)
    if rebuilt != b.patched or syx.encode(rebuilt_header, rebuilt) != out:
        raise patch.PatchError("descriptor does not reproduce tools/patch.py's output")
    return desc


def apply_descriptor(desc, official):
    """(header, image) from the official .syx and a descriptor: what the web patcher does."""
    if sha(official) != desc["input"]["sha256"]:
        raise patch.PatchError("input is not the official file this descriptor is for")
    header, image = syx.decode(official)
    out = bytearray(image) + bytes([desc["fill"]]) * (desc["output"]["imageLength"] - len(image))
    for w in desc["writes"]:
        off = int(w["address"], 16) - patch.IMAGE_BASE
        data = base64.b64decode(w["data"])
        out[off:off + len(data)] = data
    new_header = bytes.fromhex(desc["header"]) if desc["header"] else header
    return new_header, bytes(out)


def longest_shared(pieces, haystacks, floor=4):
    """Length of the longest run of any of *pieces* that occurs in any of *haystacks* (0 if under *floor*)."""
    pieces = [bytes(p) for p in pieces]

    def found(n):
        grams = set()
        for h in haystacks:
            grams.update(h[i:i + n] for i in range(len(h) - n + 1))
        return any(p[i:i + n] in grams for p in pieces for i in range(len(p) - n + 1))

    best, lo, hi = 0, floor, max((len(p) for p in pieces), default=0)
    while lo <= hi:  # a run of length n implies one of every shorter length: binary search
        n = (lo + hi) // 2
        if found(n):
            best, lo = n, n + 1
        else:
            hi = n - 1
    return best


# Aligned words with these values are firmware addresses (literal pools).
POINTER_RANGES = [(0x08000000, 0x08060000), (0x20000000, 0x20030000), (0x40000000, 0x60000000)]


def split_at_pointers(addr, data):
    """Pieces of *data* (at *addr*) between aligned words that point into the firmware's memory map."""
    pieces, start, i = [], 0, (-addr) % 4
    while i + 4 <= len(data):
        word = int.from_bytes(data[i:i + 4], "little")
        if any(lo <= word < hi for lo, hi in POINTER_RANGES):
            pieces.append(data[start:i])
            start = i + 4
        i += 4
    pieces.append(data[start:])
    return [p for p in pieces if p]


def check(desc, firmware_dir=patch.FIRMWARE_DIR):
    """Run the no-Novation-bytes checks on a descriptor dict; return report lines, raise on failure."""
    problems, report = [], []
    if set(desc) != TOP_KEYS:
        problems.append(f"top-level keys {sorted(set(desc) ^ TOP_KEYS)} unexpected or missing")
    if set(desc["input"]) != FILE_KEYS or set(desc["output"]) != OUT_KEYS:
        problems.append("input/output keys unexpected")
    if any(set(w) != WRITE_KEYS for w in desc["writes"]):
        problems.append("a write has unexpected keys")
    official = patch.read_official(firmware_dir, desc["input"]["fileName"])
    header, image = syx.decode(official)
    payload = []
    past_end = 0
    for w in desc["writes"]:
        addr = int(w["address"], 16)
        data = base64.b64decode(w["data"])
        off = addr - patch.IMAGE_BASE
        for i, byte in enumerate(data):
            if off + i < len(image):
                if image[off + i] == byte:
                    problems.append(f"{addr + i:#010x}: write byte equals the official byte")
            else:
                past_end += 1
        payload.append((addr, data))
    if desc["header"] is not None and bytes.fromhex(desc["header"]) == header:
        problems.append("header replacement equals the official header")
    total = sum(len(d) for _, d in payload)
    report.append(f"writes  {len(payload)} runs, {total} bytes ({total - past_end} inside the official "
                  f"image, all differing from it; {past_end} past its end)")
    haystacks = (image, official)
    raw = longest_shared([d for _, d in payload], haystacks)
    pieces = [piece for addr, data in payload for piece in split_at_pointers(addr, data)]
    pointers = (total - sum(len(p) for p in pieces)) // 4
    worst = longest_shared(pieces, haystacks)
    report.append(f"shared  longest run of write bytes also in the official image or .syx: {worst} bytes "
                  f"(limit {MIN_SHARED - 1}) with {pointers} firmware-address words as separators; "
                  f"{raw} bytes without separating them")
    if worst >= MIN_SHARED:
        problems.append(f"a run of {worst} write bytes occurs in the official firmware")
    new_header, rebuilt = apply_descriptor(desc, official)
    out = syx.encode(new_header, rebuilt)
    if sha(rebuilt) != desc["output"]["imageSha256"] or sha(out) != desc["output"]["sha256"]:
        problems.append("rebuilding from the descriptor does not give the expected output hashes")
    else:
        report.append(f"output  rebuilt {len(out)} bytes, sha256 {sha(out)} as declared")
    if problems:
        raise patch.PatchError("descriptor check failed:\n  " + "\n  ".join(problems))
    report.append("check   ok: no Novation bytes in the descriptor")
    return report


def compare(desc, definition_path=None, firmware_dir=patch.FIRMWARE_DIR, blob_only=False):
    """Rebuild a descriptor's patch from source and compare; return report lines, raise on a difference.

    The blob is compiled at the origin the descriptor implies (the official
    image end, 4-byte aligned) and must equal the descriptor's blob write.
    That needs no firmware. With the official file present (and not
    *blob_only*), a fresh export must equal the whole descriptor too.
    """
    definition_path = definition_path or ROOT / desc["built"]["definition"]
    d = patch.load_definition(definition_path)
    if d.NAME != desc["name"]:
        raise patch.PatchError(f"{definition_path} defines {d.NAME!r}, the descriptor is for {desc['name']!r}")
    lines = [f"tools   {patch.patch_build.tool('gcc')}: {_first_line([patch.patch_build.tool('gcc'), '--version'])}"]
    with tempfile.TemporaryDirectory(prefix="summit-mpe-compare-") as tmp:
        srcs = patch.sources(d)
        if srcs:
            n = desc["input"]["imageLength"]
            origin = patch.IMAGE_BASE + n + (-n % 4)
            try:
                blob = patch.patch_build.build(d.NAME, srcs, origin, Path(tmp) / "blob",
                                               csv_path=patch.patch_build.symbols_for(d.SOURCE))
            except patch.patch_build.BuildError as e:
                raise patch.PatchError(str(e)) from None
            runs = [w for w in desc["writes"] if w["why"].startswith(f"patch blob {d.NAME}")]
            if len(runs) != 1 or int(runs[0]["address"], 16) != origin:
                raise patch.PatchError(f"descriptor has no single blob write at {origin:#010x}")
            committed = base64.b64decode(runs[0]["data"])
            if committed != blob.data:
                first = next((i for i, (a, b) in enumerate(zip(committed, blob.data)) if a != b),
                             min(len(committed), len(blob.data)))
                raise patch.PatchError(
                    f"compiled blob differs from the descriptor's: {len(blob.data)} bytes, sha256 "
                    f"{sha(blob.data)}; descriptor {len(committed)} bytes, sha256 {sha(committed)}; "
                    f"first difference at {origin + first:#010x}")
            lines.append(f"blob    {len(blob.data)} bytes at {origin:#010x}, sha256 {sha(blob.data)}: "
                         f"equal to the descriptor")
        official = Path(firmware_dir) / desc["input"]["fileName"]
        if blob_only:
            lines.append("full    skipped (--blob-only)")
        elif not official.exists():
            lines.append(f"full    skipped: no {official} (only the blob was compared)")
        else:
            fresh = export(definition_path, firmware_dir, build_dir=Path(tmp) / "full")
            fresh["built"] = desc["built"]
            if fresh != desc:
                keys = sorted(k for k in desc if fresh.get(k) != desc.get(k))
                raise patch.PatchError(f"a fresh export differs from the descriptor in {keys}; output sha256 "
                                       f"{fresh['output']['sha256']}, descriptor {desc['output']['sha256']}")
            lines.append(f"full    fresh export equal to the descriptor, output sha256 {desc['output']['sha256']}")
    lines.append("compare ok")
    return lines


def _first_line(cmd):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    return r.stdout.splitlines()[0] if r.stdout else "?"


def dumps(desc):
    return json.dumps(desc, indent=1) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("export")
    s.add_argument("definition")
    s.add_argument("out")
    s.add_argument("--firmware", default=str(patch.FIRMWARE_DIR))
    s = sub.add_parser("check")
    s.add_argument("descriptor")
    s.add_argument("--firmware", default=str(patch.FIRMWARE_DIR))
    s.add_argument("--definition", help="also require the descriptor to equal a fresh export of this definition")
    s = sub.add_parser("compare", help="rebuild from source and require the descriptor's bytes")
    s.add_argument("descriptor")
    s.add_argument("--definition", help="default: the descriptor's built.definition")
    s.add_argument("--firmware", default=str(patch.FIRMWARE_DIR))
    s.add_argument("--blob-only", action="store_true", help="compare only the compiled blob (no firmware needed)")
    args = p.parse_args(argv)
    try:
        if args.command == "compare":
            desc = json.loads(Path(args.descriptor).read_text())
            lines = compare(desc, args.definition, args.firmware, args.blob_only)
        elif args.command == "export":
            desc = export(args.definition, args.firmware)
            lines = check(desc, args.firmware)
            Path(args.out).write_text(dumps(desc))
            lines.append(f"wrote   {args.out}")
        else:
            desc = json.loads(Path(args.descriptor).read_text())
            lines = check(desc, args.firmware)
            if args.definition:
                fresh = export(args.definition, args.firmware)
                fresh["built"] = desc["built"]
                if fresh != desc:
                    raise patch.PatchError(f"{args.descriptor} is out of date: re-run export")
                lines.append("fresh   equal to a new export of the definition")
    except patch.PatchError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
