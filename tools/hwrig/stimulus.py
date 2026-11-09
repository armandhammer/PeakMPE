"""Timed MIDI for one take: what a check plays, with named marks.

A Timeline is a list of (seconds into the take, message, label). The
recorder sends each at its time and stamps it on the audio clock; the check
then cuts its analysis windows from the stamped times of its marks
(`Take.time(label)`), so the analysis follows what was actually sent.

Builders for the MPE messages a check needs live here too. Everything is a
channel voice message, so it passes the port's allow-list.
"""
from dataclasses import dataclass, field

from .midi import check_message

BEND_CENTRE = 8192


def note_on(ch, note, vel=100):
    return bytes([0x90 | (ch - 1), note, vel])


def note_off(ch, note):
    return bytes([0x80 | (ch - 1), note, 0])


def bend(ch, value):
    """Pitch bend, `value` -8192..8191 (0 = centre)."""
    v = max(0, min(16383, value + BEND_CENTRE))
    return bytes([0xE0 | (ch - 1), v & 0x7F, v >> 7])


def pressure(ch, value):
    return bytes([0xD0 | (ch - 1), value])


def cc(ch, num, value):
    return bytes([0xB0 | (ch - 1), num, value])


def rpn(ch, msb, lsb, value):
    """RPN select, data entry MSB, then RPN null (so a later CC 6 goes nowhere)."""
    return [cc(ch, 101, msb), cc(ch, 100, lsb), cc(ch, 6, value), cc(ch, 101, 127), cc(ch, 100, 127)]


def bend_cents(value, range_semitones):
    """What a per-note bend `value` (-8192..8191) should do, in cents."""
    return value / 8192.0 * range_semitones * 100.0


@dataclass
class Event:
    t: float
    data: bytes
    label: str = ""


@dataclass
class Timeline:
    events: list = field(default_factory=list)
    duration: float = 0.0

    def at(self, t, data, label=""):
        check_message(data)
        self.events.append(Event(t, bytes(data), label))
        self.duration = max(self.duration, t)
        return t

    def mark(self, t, label):
        """A mark with no message: a zero-length marker the analysis can use.
        Stored as an event with no data (not sent)."""
        self.events.append(Event(t, b"", label))
        self.duration = max(self.duration, t)
        return t

    def sorted(self):
        return sorted(self.events, key=lambda e: e.t)

    def messages(self):
        return [e for e in self.sorted() if e.data]

    def held_at_end(self):
        """(channel, note) still on after the last event: should be empty."""
        held = set()
        for e in self.messages():
            st, kind = e.data[0] & 0x0F, e.data[0] & 0xF0
            if kind == 0x90 and e.data[2]:
                held.add((st + 1, e.data[1]))
            elif kind == 0x80 or (kind == 0x90 and not e.data[2]):
                held.discard((st + 1, e.data[1]))
        return held


@dataclass
class Take:
    """A recorded take: audio [n, inputs], samplerate, and the stamped time
    of every labelled event (seconds after the first sample)."""
    audio: object
    sr: int
    times: dict

    def time(self, label):
        return self.times[label]

    def window(self, t0, t1, ch=None):
        """Samples t0..t1 of input `ch` (an index into the recorded inputs),
        or by default the mean of all of them: with Multi's Part B on its
        own output pair (the user's rig: Part A on 9/10, Part B on 11/12),
        both parts are in the mix, and with identical L/R the level is that
        of one input."""
        a, b = int(round(t0 * self.sr)), int(round(t1 * self.sr))
        a, b = max(0, a), min(self.audio.shape[0], b)
        x = self.audio[a:b].astype("float64")
        return x[:, ch] if ch is not None else x.mean(axis=1)
