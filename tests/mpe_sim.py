"""Shared set-up for the MPE core tests (tests/test_mpe_*.py).

Builds patches/mpe once per test session, boots it in SimulatedSummit with
the stock image's cached DataFlash, and wraps it with views of the patch's
state (voice_channel, mpe_live, mpe_zones, mpe_clash) and a player that
remembers which note each channel holds, so every step can check the
binding invariants (:meth:`Mpe.check`).
"""

import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import patch  # noqa: E402
import patch_build  # noqa: E402

from emu.firmware import SUMMIT_2_2, load_image  # noqa: E402

MPE = ROOT / "patches" / "mpe" / "patch.py"
NONE = 0xFF
FLAG = 0x1A2
MODE, UNISON = 0x22, 0x23  # patch: voice mode (0 Mono, 1 MonoLG, 2 Mono2, 3 Poly, 4 Poly2), unison
G_ZONE, G_MEMBERS, G_NOTE_RANGE, G_MASTER_RANGE = 0x30, 0x31, 0x32, 0x33
LOWER, UPPER = 0, 1
RELEASE_MS = 300  # Init Patch amp release is short; enough for every voice to go idle

_cache = {}


def stock_image():
    image = load_image(SUMMIT_2_2)
    if image is None:
        pytest.skip(f"firmware/{SUMMIT_2_2} not present")
    return image


def built(tmp_path_factory):
    """The MPE patch build, once per session."""
    if "built" not in _cache:
        stock_image()
        if not patch_build.available():
            pytest.skip("arm-none-eabi-gcc not installed")
        _cache["built"] = patch.build_image(MPE, build_dir=tmp_path_factory.mktemp("mpe-build"))
    return _cache["built"]


def summit(image, flash_from=None):
    from emu.synth import SimulatedSummit

    return SimulatedSummit(image, flash_from=flash_from)


def mpe_summit(tmp_path_factory):
    """A SimulatedSummit running the MPE patch, once per session (reset() it)."""
    if "mpe" not in _cache:
        b = built(tmp_path_factory)
        _cache["mpe"] = Mpe(summit(b.patched, flash_from=stock_image()), b.blob)
    return _cache["mpe"]


def stock_summit():
    if "stock" not in _cache:
        _cache["stock"] = summit(None)
    return _cache["stock"]


class Mpe:
    """The simulator with the patch's state, and a player that tracks held notes."""

    def __init__(self, s, blob):
        self.s = s
        self.blob = blob
        self.held = {}  # channel (1-16) -> note, for notes sent on zone channels

    def reset(self):
        self.s.reset()
        self.held = {}
        return self

    def addr(self, name):
        return self.blob.address(name)

    # -- patch state -----------------------------------------------------------

    def voice_channel(self):
        """Channel (1-16) per voice, None for no binding."""
        return [None if c == NONE else c + 1 for c in self.s.board.read(self.addr("voice_channel"), 16)]

    def live(self):
        m = self.s.board.read(self.addr("mpe_live"), 6)
        return {"members": (m[0], m[1]), "note_range": (m[2], m[3]), "master_range": (m[4], m[5])}

    def zones(self):
        """{"lower"/"upper": (part, master, first, last) with channels 1-16} for zones in use."""
        out = {}
        raw = self.s.board.read(self.addr("mpe_zones"), 8)
        for k, name in ((0, "lower"), (1, "upper")):
            part, master, first, last = raw[4 * k:4 * k + 4]
            if part != NONE:
                out[name] = (part, master + 1, first + 1, last + 1)
        return out

    def clash(self):
        return self.s.board.u8(self.addr("mpe_clash"))

    def part_of_voice(self, v):
        return 1 if self.s.multi_mode and v >= 8 else 0

    def zone_part(self, ch):
        """The part a zone channel (1-16) plays, or None."""
        for part, master, first, last in self.zones().values():
            if ch == master or first <= ch <= last:
                return part
        return None

    # -- settings ----------------------------------------------------------------

    def flag(self, on=True, part=0):
        self.s.set_patch_byte(FLAG, 1 if on else 0, part)
        self.s.tick(2)  # the main loop refreshes the routing

    def rpn(self, ch, msb, lsb, value, port="din"):
        c = 0xB0 | (ch - 1)
        self.s.midi_in([c, 101, msb, c, 100, lsb, c, 6, value], port=port)
        self.s.tick(5)

    def mcm(self, ch, members):
        """MPE Configuration Message (RPN 6) on channel 1 (Lower) or 16 (Upper)."""
        self.rpn(ch, 0, 6, members)

    def zone_setting(self, zone, members=0):
        """The Settings layout, as a Settings edit writes it (globals +0x30/+0x31)."""
        self.s.set_global(G_MEMBERS, members, run_ms=0)
        self.s.set_global(G_ZONE, zone)

    # -- playing -----------------------------------------------------------------

    def on(self, note, ch, velocity=100, ms=4, port="din"):
        self.s.note_on(note, velocity, channel=ch, port=port)
        self.s.tick(ms)
        if self.zone_part(ch) is not None:
            self.held[ch] = note
        self.check()

    def off(self, note, ch, ms=4, port="din"):
        self.s.note_off(note, channel=ch, port=port)
        self.s.tick(ms)
        if self.held.get(ch) == note:
            del self.held[ch]
        self.check()

    def all_off(self):
        for ch, note in list(self.held.items()):
            self.off(note, ch)
        self.s.tick(RELEASE_MS)
        assert self.s.active_voices() == [], "voices still gated after every note-off"
        self.check()

    def bound(self, ch):
        """Active voices bound to channel ch (1-16)."""
        vc = self.voice_channel()
        return [v for v in self.s.active_voices() if vc[v] == ch]

    # -- invariants --------------------------------------------------------------

    def check(self):
        """The binding invariants, after every event:

        * an active voice bound to a channel plays the note that channel holds
          (no orphan: stealing and reuse move the binding with the voice);
        * it belongs to an MPE part, and the channel is a channel of a zone of
          that part;
        * the active voices of one channel play one note, at most a unison
          stack of them;
        * an active voice of a part with MPE off has no binding.
        """
        s = self.s
        vc = self.voice_channel()
        per_channel = {}
        for v in s.active_voices():
            part = self.part_of_voice(v)
            ch = vc[v]
            on = s.patch_byte(FLAG, part) == 1
            if ch is None:
                continue
            assert on, f"voice {v} of part {part} (MPE off) is bound to channel {ch}"
            assert self.held.get(ch) == s.voice_note(v), \
                f"voice {v} bound to channel {ch} plays {s.voice_note(v)}, the channel holds {self.held.get(ch)}"
            assert self.zone_part(ch) == part, f"voice {v}: channel {ch} isn't a zone channel of part {part}"
            per_channel.setdefault(ch, []).append(v)
        for ch, voices in per_channel.items():
            part = self.part_of_voice(voices[0])
            unison = s.patch_byte(UNISON, part)
            stack = 8 if unison == 4 else unison + 1
            assert len(voices) <= stack, f"channel {ch} holds {voices}, more than a stack of {stack}"
            assert len({s.voice_note(v) for v in voices}) == 1


def u16(s, addr):
    return struct.unpack("<H", s.board.read(addr, 2))[0]
