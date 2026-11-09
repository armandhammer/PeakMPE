"""How stock firmware 2.2 sends pitch bend and the mod wheel to the FPGA.

These pin the stock behaviour the MPE design builds on
(docs/findings/summit-2.2-build2121.md, "Oscillator pitch" and "Part mod
sources"):

* the part bend goes out as the broadcast 0x68/0x69 and, audibly, through
  every voice's oscillator pitch 0x000-0x002 (osc_pitch 0x08013A2C), which
  stock recomputes for every held voice;
* the smoothed part mod wheel goes out only as 0x60 to the broadcast target
  0x1A and 0x860 to the part-level target 0x19, and nothing the MCU computes
  per voice depends on it, even with a mod-matrix slot set.

The bend sequence is tests/bend_play.py's (DIN, a held chord, a new note,
bend up and down, a note that moves the selection, centre, release); the
wheel sequence is the same with CC 1 instead of the bend. Emulated.
"""

import pytest

from bend_play import BEND, CHORD, MOVE_VOICE, NEW_VOICE, OSC_PITCH, Run, changes, played

pytestmark = [pytest.mark.slow, pytest.mark.xdist_group("bend_play")]

CHORD_VOICES = tuple(range(len(CHORD)))
FULL_BEND = 3800  # BendRange 12 (the simulated Init sound): close to 4,096 = one octave

MODWHEEL, MODWHEEL_PART = 0x060, 0x860
BROADCAST, PART_LEVEL = 0x1A, 0x19
NEW_NOTE, MOVE_NOTE = 72, 76
HALF = 0x4000  # CC1 64 << 8, where the smoother settles


# -- bend ------------------------------------------------------------------------


@pytest.fixture(scope="module")
def bend():
    return played()


def test_bend_sequence_selects_the_new_note_then_the_moved_one(bend):
    def at(t):
        return [v for ts, v in bend.selected if ts <= t][-1]

    assert at(bend.t["up"]) == NEW_VOICE
    assert at(bend.t["centre"]) == MOVE_VOICE
    assert bend.voices == []


def test_stock_bends_all_voices_through_the_broadcast(bend):
    assert max(e.value for e in bend.writes(0x1A, 0x68)) > 30000
    assert max(e.value for e in bend.writes(0x1A, 0x69)) > 30000
    assert not [e for e in bend.events if e.target < 0x10 and e.param in BEND]


def follows_bend(run, voice, param, start, stop):
    values = [e.value for e in run.writes(voice, param) if start < e.time_ms < stop]
    return len(set(values)) > 10 and max(values) - min(values) > FULL_BEND


@pytest.mark.parametrize("param", OSC_PITCH)
def test_stock_bends_every_held_voice_through_its_oscillator_pitch(bend, param):
    for v in (*CHORD_VOICES, NEW_VOICE):
        assert follows_bend(bend, v, param, bend.t["up"], bend.t["move"]), v
    assert follows_bend(bend, MOVE_VOICE, param, bend.t["move"], bend.t["release"])


# -- mod wheel -------------------------------------------------------------------


def play_wheel(s):
    """Chord, a new note, the wheel up and to half, a note that moves the
    selection, the wheel down, release. Returns the times (ms) of its steps."""
    s.set_soft_thru(True)
    t = {}
    for n in CHORD:
        s.note_on(n)
    s.tick(20)
    t["new"] = s.time_ms
    s.note_on(NEW_NOTE)
    s.tick(20)
    t["up"] = s.time_ms
    s.cc(1, 127)
    s.tick(60)
    t["half"] = s.time_ms
    s.cc(1, 64)
    s.tick(60)
    t["move"] = s.time_ms
    s.note_on(MOVE_NOTE)
    s.tick(40)
    t["down"] = s.time_ms
    s.cc(1, 0)
    s.tick(150)
    t["release"] = s.time_ms
    for n in (*CHORD, NEW_NOTE, MOVE_NOTE):
        s.note_off(n)
    s.tick(300)
    t["end"] = s.time_ms
    return t


@pytest.fixture(scope="module")
def wheel():
    from emu.firmware import SUMMIT_2_2, load_image
    from emu.synth import SimulatedSummit

    if load_image(SUMMIT_2_2) is None:
        pytest.skip(f"firmware/{SUMMIT_2_2} not present")
    return Run(SimulatedSummit(), play=play_wheel)


def test_stock_sends_the_wheel_per_part_only(wheel):
    for target, param in ((BROADCAST, MODWHEEL), (PART_LEVEL, MODWHEEL_PART)):
        assert max(e.value for e in wheel.writes(target, param)) > 32000
        settled = [e.value for e in wheel.writes(target, param) if wheel.t["move"] - 5 < e.time_ms < wheel.t["move"]]
        assert settled and all(abs(v - HALF) <= 0x80 for v in settled)
    assert not [e for e in wheel.events if e.target < 0x10 and e.param == MODWHEEL]


def _stock_wheel_reaches(sound):
    """(target, param) of every stock FPGA register whose values change when
    only CC1 moves, for a sound set up by *sound*."""
    from emu.synth import SimulatedSummit

    def one(move):
        s = SimulatedSummit()
        s.reset()
        sound(s)
        for n in CHORD:
            s.note_on(n)
        s.tick(20)
        if move:
            s.cc(1, 127)
        s.tick(40)
        if move:
            s.cc(1, 0)
        s.tick(80)
        return changes(s.fpga_events())

    plain, moved = one(False), one(True)
    return {k[1:] for k in set(plain) | set(moved) if plain.get(k) != moved.get(k)}


def _matrix_slot(s):
    """Mod-matrix slot 1 (NRPN 1:0 source, 1:2 depth, 1:3 destination; the
    MCU sends the slot to 0x1A param 0x80). Source 1 follows the source list
    at 0x0804A8E4 (Direct, ModWheel, AftTouch, ...); the destination is
    arbitrary: none of them changes what the MCU sends."""
    s.set_cc_nrpn_receive(True)
    for lsb, value in ((0, 1), (2, 127), (3, 11)):
        s.nrpn(1, lsb, value)
    s.tick(10)


@pytest.mark.parametrize("sound", [lambda s: None, _matrix_slot], ids=["init", "matrix-slot"])
def test_stock_wheel_reaches_only_0x60_and_0x860(wheel, sound):
    """Nothing the MCU computes per voice depends on the mod wheel, so a
    per-voice 0x60 is the only path for a per-note wheel (MPE Slide)."""
    assert _stock_wheel_reaches(sound) == {(BROADCAST, MODWHEEL), (PART_LEVEL, MODWHEEL_PART)}
