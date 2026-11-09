"""Rig configuration: work/hwrig.toml, overridden by CLI flags.

Nothing about the user's audio interface or DIN MIDI interface is assumed;
`hwrig list` shows the names to put here. See tools/hwrig/hwrig.example.toml
and docs/hw-test-rig.md#configuration.
"""
from dataclasses import dataclass, field, fields
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover - the venv's 3.9
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = REPO_ROOT / "work" / "hwrig.toml"
RUNS_DIR = REPO_ROOT / "work" / "hw-runs"


@dataclass
class Config:
    # MIDI
    usb_port: str = "Summit"   # output port name, exact or a unique substring
    din_port: str = ""         # the USB-MIDI interface's output wired to the Summit's DIN in
    channel: int = 1           # 1-16; the probe's channel
    # Audio
    audio_device: str = ""     # input device name (substring) or index; "" = system default
    inputs: list = field(default_factory=lambda: [1, 2])  # 1-based input channels with Summit L/R
    samplerate: int = 48000
    # Probe
    notes: list = field(default_factory=lambda: [57, 45, 69, 81])  # A3, A2, A4, A5
    velocity: int = 100
    hold_s: float = 1.0
    preroll_s: float = 0.5
    tail_s: float = 1.0
    a4_hz: float = 440.0
    slot: str = ""             # e.g. "D002": select it before the notes; "" = don't
    # Test sounds (hwrig setup): base slots that carry the MPE flag
    mpe_base: str = "D002"     # a patch with VOICE MPE On
    plain_base: str = "D003"   # a patch with VOICE MPE Off
    # The MPE layout the run leaves behind (and assumes at the start): "off" (the
    # Summit's Settings Zone Off: an MPE patch plays Lower 15), "lower N" or "upper N"
    zone: str = "off"
    part_a_channel: int = 2    # Settings MIDI CHANNEL PartA Chan (M1 only; can't be set over MIDI)
    part_b_channel: int = 3    # Settings MIDI CHANNEL PartB Chan

    def validate(self):
        if not 1 <= self.channel <= 16:
            raise ValueError(f"channel {self.channel}: must be 1-16")
        if not self.inputs or any(int(c) < 1 for c in self.inputs):
            raise ValueError(f"inputs {self.inputs}: 1-based channel numbers")
        for n in self.notes:
            if not 0 <= n <= 127:
                raise ValueError(f"note {n}: must be 0-127")
        if not 1 <= self.velocity <= 127:
            raise ValueError(f"velocity {self.velocity}: must be 1-127")
        for name in ("slot", "mpe_base", "plain_base"):
            v = getattr(self, name)
            if v or name != "slot":
                parse_slot(v)
        parse_zone(self.zone)
        for name in ("part_a_channel", "part_b_channel"):
            if not 1 <= getattr(self, name) <= 16:
                raise ValueError(f"{name}: must be 1-16")
        if min(self.hold_s, self.preroll_s, self.tail_s) < 0.1:
            raise ValueError("hold_s, preroll_s and tail_s must be at least 0.1 s")
        return self


SECTIONS = {
    "midi": ("usb_port", "din_port", "channel"),
    "audio": ("audio_device", "inputs", "samplerate"),
    "probe": ("notes", "velocity", "hold_s", "preroll_s", "tail_s", "a4_hz",
              "slot"),
    "patches": ("mpe_base", "plain_base", "part_a_channel", "part_b_channel"),
    "mpe": ("zone",),
}

BANKS = "ABCD"


def parse_slot(text):
    """'D002' -> (bank 4, program 2): bank A-D is CC 32 = 1-4, the number is
    the program change value, as the Summit's display shows it (emulated:
    CC 32 4 then program change 2 shows '4-002'; tests/test_hwrig_setup.py)."""
    t = str(text).strip().upper()
    if len(t) < 2 or t[0] not in BANKS or not t[1:].isdigit() or not 0 <= int(t[1:]) <= 127:
        raise ValueError(f"slot {text!r}: a bank letter A-D and a number 0-127, e.g. D002")
    return BANKS.index(t[0]) + 1, int(t[1:])


def parse_zone(text):
    """'off' -> ('off', 0); 'lower 15' -> ('lower', 15); 'upper 7' -> ('upper', 7)."""
    parts = str(text).strip().lower().split()
    if parts == ["off"]:
        return "off", 0
    if len(parts) == 2 and parts[0] in ("lower", "upper") and parts[1].isdigit() and 1 <= int(parts[1]) <= 15:
        return parts[0], int(parts[1])
    raise ValueError(f"zone {text!r}: 'off', 'lower N' or 'upper N' (N 1-15)")


def load(path=None):
    """Config from `path` (default work/hwrig.toml if it exists)."""
    cfg = Config()
    path = Path(path) if path else DEFAULT_PATH
    if path.exists():
        data = tomllib.loads(path.read_text())
        known = {f.name for f in fields(Config)}
        for section, values in data.items():
            if section not in SECTIONS or not isinstance(values, dict):
                raise ValueError(f"{path}: unknown section [{section}]")
            for key, value in values.items():
                if key not in SECTIONS[section] or key not in known:
                    raise ValueError(f"{path}: unknown key {section}.{key}")
                setattr(cfg, key, value)
    elif path != DEFAULT_PATH:
        raise FileNotFoundError(path)
    return cfg
