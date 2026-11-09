"""Shared helpers for the MPE expression tests (tests/test_mpe_expr_*.py).

The patch is mpe_sim's build (patches/mpe, step 1 and step 2). These read
what each voice gets from the FPGA writes the simulator decodes: the
oscillator pitch 0x000-0x002, aftertouch 0x61 and ModWheel 0x60 per voice.
"""

import struct

OSC = (0x000, 0x001, 0x002)
AFTERTOUCH, MODWHEEL, MODWHEEL_PART = 0x61, 0x60, 0x860
BROADCAST, PART_LEVEL = 0x1A, 0x19
PART_BEND_SMOOTHED = 0x2001389C
OSC_MIN, OSC_MAX = -43691, 43689
FULL_SLIDE = 0x7FFF


def osc(s, v):
    """The voice's last oscillator pitches (Osc 1-3)."""
    return tuple(s.last_value(voice=v, param=p) for p in OSC)


def shifted(values, by):
    return tuple(x + by for x in values)


def member_offset(bend, note_range=48):
    """Offset of a member bend (-8192..8191) at note_range semitones."""
    return int(bend * note_range / 24)


def master_offset(s, master_range=2, part=0):
    """Offset of the settled master bend: part_bend_smoothed x range / 48."""
    pbs = struct.unpack("<h", s.board.read(PART_BEND_SMOOTHED + 2 * part, 2))[0]
    return int(pbs * master_range / 48)


def slide(cc):
    return FULL_SLIDE if cc == 127 else cc << 8


def wheel(s, v):
    return s.last_value(voice=v, param=MODWHEEL)


def at_sent(slot):
    """0x61 that mod_update sends for a settled slot (0x080143A0-0x080143F4)."""
    x = slot & 0xFFF0
    return (x * x >> 15) & 0xFFFF


def moved(s, since, params):
    """Voices with any write of params since the time given whose value changed."""
    out = set()
    last = {}
    for e in s.fpga_events(param=params):
        if e.target >= 0x10:
            continue
        key = (e.target, e.param)
        if e.time_ms >= since and key in last and last[key] != e.value:
            out.add(e.target)
        last[key] = e.value
    return out


def broadcasts(s, since, param=MODWHEEL, target=BROADCAST):
    return [e for e in s.fpga_events(param=param, target=target) if e.time_ms >= since]
