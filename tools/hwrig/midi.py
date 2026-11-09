"""MIDI out for the rig: message builders and a python-rtmidi port.

Nothing here sends on import or on listing. `RtMidiOut` is only opened by
`probe` after the user typed `play` (see cli.confirm).
"""
from dataclasses import dataclass

from .analysis import note_name


@dataclass
class Msg:
    at_s: float      # seconds after the start of the take (the note's pre-roll)
    data: bytes
    what: str

    def hex(self):
        return " ".join(f"{b:02X}" for b in self.data)


def note_on(ch, note, vel):
    return bytes([0x90 | (ch - 1), note, vel])


def note_off(ch, note):
    return bytes([0x80 | (ch - 1), note, 0])


def cc(ch, num, value):
    return bytes([0xB0 | (ch - 1), num, value])


def program_change(ch, program):
    return bytes([0xC0 | (ch - 1), program])


def slot_msgs(channel, slot):
    """Select a patch slot like 'D002': CC 32 (bank) then program change.
    No CC 0: this firmware passes CC 0 to the patch parameters (cc
    0x080102C0's default path), it isn't a bank select here."""
    from .config import parse_slot
    bank, program = parse_slot(slot)
    return [Msg(0.0, cc(channel, 32, bank), f"bank select CC 32 = {bank} (bank {slot[0].upper()})"),
            Msg(0.0, program_change(channel, program), f"program change {program} ({slot.upper()})")]


def program_msgs(cfg):
    """The probe's slot select, if configured (sent once, first)."""
    return slot_msgs(cfg.channel, cfg.slot) if cfg.slot else []


def note_msgs(cfg, note):
    on = cfg.preroll_s
    return [
        Msg(on, note_on(cfg.channel, note, cfg.velocity), f"note on  {note_name(note)} ({note}) vel {cfg.velocity}"),
        Msg(on + cfg.hold_s, note_off(cfg.channel, note), f"note off {note_name(note)} ({note})"),
    ]


def find_port(names, want):
    """The one port name matching `want`: exact, else a unique substring."""
    if want in names:
        return want
    hits = [n for n in names if want.lower() in n.lower()]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise LookupError(f"no MIDI output port matches {want!r}; ports: {names}")
    raise LookupError(f"several MIDI output ports match {want!r}: {hits}; give the full name")


def output_ports():
    import rtmidi
    return rtmidi.MidiOut().get_ports()


def input_ports():
    import rtmidi
    return rtmidi.MidiIn().get_ports()


# Channel voice messages only: note off/on, poly pressure, CC (RPN/NRPN and
# MCM are CCs), program change, channel pressure, pitch bend. Never SysEx or
# other system messages: the rig can't reach the updater or the bootloader.
ALLOWED_STATUS = {0x80, 0x90, 0xA0, 0xB0, 0xC0, 0xD0, 0xE0}
LENGTH = {0x80: 3, 0x90: 3, 0xA0: 3, 0xB0: 3, 0xC0: 2, 0xD0: 2, 0xE0: 3}


def check_message(data):
    """Raise ValueError unless `data` is one complete channel voice message."""
    data = bytes(data)
    if not data or data[0] & 0xF0 not in ALLOWED_STATUS:
        raise ValueError(f"refused: {data.hex(' ')} is not a channel voice message")
    if len(data) != LENGTH[data[0] & 0xF0] or any(b > 0x7F for b in data[1:]):
        raise ValueError(f"refused: malformed message {data.hex(' ')}")
    return data


def check_port_name(name):
    if "bootloader" in name.lower():
        raise ValueError(f"refused: {name!r} is a bootloader port")
    return name


class RtMidiOut:
    def __init__(self, name):
        import rtmidi
        self.out = rtmidi.MidiOut()
        names = self.out.get_ports()
        self.name = check_port_name(find_port(names, name))
        self.out.open_port(names.index(self.name))

    def send(self, data):
        self.out.send_message(list(check_message(data)))

    def close(self):
        self.out.close_port()
