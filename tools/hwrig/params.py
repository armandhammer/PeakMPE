"""The Summit's patch parameters, read from the local firmware image.

Nothing from the image is stored in the repository: the table is built at
run time from `firmware/summit-firmware-2.2-build2121.syx` (checked against
`firmware/SHA256SUMS` by `emu.firmware.load_image`). Addresses are for that
build (docs/findings/summit-2.2-build2121.md, "Patch layout" and "CC, NRPN
and RPN"):

- `patch_param_desc` flash `0x0804E7CC`: 420 records of 12 bytes,
  `{u8 min; u8 max; u8 nrpn_msb; u8 nrpn_lsb; u32 display; char* name}`,
  indexed by patch byte offset (observed).
- How a record is reached over MIDI (observed in the descriptor values,
  emulated through `cc` `0x080102C0` in tests/test_hwrig_setup.py):
  MSB 0-25 is NRPN `msb:lsb` (CC 99, 98, then CC 6); MSB 252 is CC `lsb`;
  254 is CC `lsb` (the coarse byte of a pair) and 253 is CC `lsb` (its fine
  byte); 255 can't be set over MIDI. Min = max = 0 is a reserved byte.
  NRPN MSB 21-24 (FX-matrix slots 5-8) are in the table but `cc` rejects
  them (emulated), so they count as unsettable too.
- Coupled (emulated): setting RevSize (0x0DE, NRPN 0:104) also sets
  RevType (0x0DA) from the size, and RevType loads a preset size. The Init
  Patch's pair (type 1, size 90) can't be rebuilt over MIDI; with the
  reverb level at 0 (Init) it isn't heard. RevType is sent first, then
  RevSize, and RevType is left to follow.
- The Init Patch at flash `0x080492F4` (0x200 bytes, observed).
- Mod-matrix source and destination names: pointer tables at `0x0804D698`
  (24) and `0x0804D6F8` (49); oscillator waves at `0x0804D860`, voice modes
  at `0x0804D9F0` (observed: the pointers, the strings and the ranges
  0-23/0-48/0-4/0-4 in the descriptors agree).
"""
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

IMAGE_BASE = 0x0800C000
PATCH_PARAM_DESC = 0x0804E7CC
N_PARAMS = 420
INIT_PATCH = 0x080492F4
MATRIX_SOURCES = (0x0804D698, 24)
MATRIX_DESTS = (0x0804D6F8, 49)
OSC_WAVES = (0x0804D860, 5)
VOICE_MODES = (0x0804D9F0, 5)

# The sound: everything from the voice mode (0x22) to the end of the patch
# proper (0x18C). Not the name, category, bank/patch fields (0x00-0x21), nor
# the Multi part fields (0x18D-0x1A1), nor the UI's selected matrix slots.
SOUND_FIRST, SOUND_LAST = 0x022, 0x18C
UI_ONLY = {0x0FB, 0x164}  # 'Slot': which matrix slot the panel shows

# CCs the firmware handles itself (cc 0x080102C0 switch, bank select, NRPN
# select, data entry); a parameter must never be sent on one of these.
RESERVED_CCS = {0, 1, 2, 6, 7, 11, 32, 64, 66, 98, 99, 114, 115} | set(range(120, 128))
REJECTED_NRPN_MSB = range(21, 25)
# Parameters the firmware derives from another one set after it.
DERIVED = {0x0DA: "RevType follows RevSize (0x0de)"}


@dataclass(frozen=True)
class Param:
    offset: int
    name: str
    min: int
    max: int
    msb: int
    lsb: int

    @property
    def kind(self):
        if self.min == self.max == 0:
            return "reserved"
        if self.msb in REJECTED_NRPN_MSB:
            return "none"
        if self.msb <= 25:
            return "nrpn"
        if self.msb in (252, 253, 254):
            return "cc"
        return "none"

    @property
    def settable(self):
        return self.kind in ("nrpn", "cc")

    def messages(self, channel, value):
        """MIDI bytes that set this parameter to `value` on `channel`."""
        if not self.settable:
            raise ValueError(f"{self} can't be set over MIDI")
        if not self.min <= value <= min(self.max, 127):
            raise ValueError(f"{self.name} ({self.offset:#05x}): {value} outside "
                             f"{self.min}-{min(self.max, 127)}")
        st = 0xB0 | (channel - 1)
        if self.kind == "nrpn":
            return [bytes([st, 99, self.msb]), bytes([st, 98, self.lsb]), bytes([st, 6, value])]
        return [bytes([st, self.lsb, value])]

    def __str__(self):
        how = {"nrpn": f"NRPN {self.msb}:{self.lsb}", "cc": f"CC {self.lsb}"}.get(self.kind, self.kind)
        return f"{self.name} ({self.offset:#05x}, {how})"


class Table:
    """Parameters, Init Patch and value names of one firmware image."""

    def __init__(self, image):
        self.image = image
        self.params = {}
        for off in range(N_PARAMS):
            mn, mx, msb, lsb, _disp, name = struct.unpack_from(
                "<BBBBII", image, PATCH_PARAM_DESC + 12 * off - IMAGE_BASE)
            self.params[off] = Param(off, self._str(name) if mx else "", mn, mx, msb, lsb)
        self.init = image[INIT_PATCH - IMAGE_BASE:INIT_PATCH - IMAGE_BASE + 0x200]
        self.sources = self._names(*MATRIX_SOURCES)
        self.dests = self._names(*MATRIX_DESTS)
        self.waves = self._names(*OSC_WAVES)
        self.modes = self._names(*VOICE_MODES)
        for p in self.params.values():
            if p.kind == "cc" and p.lsb in RESERVED_CCS:
                raise ValueError(f"{p} would use a reserved CC")

    def _str(self, addr):
        o = addr - IMAGE_BASE
        if not 0 <= o < len(self.image):
            return "?"
        return self.image[o:self.image.index(b"\0", o)].decode("latin-1").strip()

    def _names(self, table, n):
        return [self._str(struct.unpack_from("<I", self.image, table + 4 * i - IMAGE_BASE)[0])
                for i in range(n)]

    def param(self, offset, name=None):
        """The parameter at `offset`; `name` guards against a wrong build."""
        p = self.params[offset]
        if name is not None and p.name != name:
            raise ValueError(f"offset {offset:#05x} is {p.name!r}, not {name!r}: another firmware build?")
        return p

    def sound_params(self):
        """Settable parameters of the sound, in offset order."""
        return [p for o, p in sorted(self.params.items())
                if SOUND_FIRST <= o <= SOUND_LAST and o not in UI_ONLY and p.settable]

    def unsettable_sound_params(self):
        return [p for o, p in sorted(self.params.items())
                if SOUND_FIRST <= o <= SOUND_LAST and o not in UI_ONLY and p.kind == "none"]

    def init_value(self, offset):
        """Init Patch value, clamped into what MIDI can send (7 bits). The
        fine byte of a pair is 0-64 and the coarse 0-255; the Init Patch
        uses 7-bit values everywhere the sound needs (observed)."""
        p = self.params[offset]
        return max(p.min, min(self.init[offset], p.max, 127))

    def index(self, names, name, what):
        try:
            return names.index(name)
        except ValueError:
            raise ValueError(f"no {what} {name!r}; known: {names}") from None


def load_table():
    """The table from firmware/<Summit 2.2>, or raise FileNotFoundError."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from emu.firmware import FIRMWARE_DIR, SUMMIT_2_2, load_image
    image = load_image(SUMMIT_2_2)
    if image is None:
        raise FileNotFoundError(f"{FIRMWARE_DIR / SUMMIT_2_2} (run scripts/fetch-firmware.sh)")
    return Table(image)
