"""The simulated Summit (emu/synth.py): MIDI in → stock firmware → FPGA bus and MIDI out.

Everything here runs the firmware's own main loop and interrupts; the
assertions read the decoded SPI1 traffic (emu/fpga.py) and RAM. Confidence:
the MCU behaviour is *emulated*. What the FPGA does with the writes is not
modelled, and two inputs to the firmware are inferred models, not
observations: the FPGA's per-voice envelope states (``VoiceStateModel``, which
voice_alloc reads back) and the EXTI15 edge rate. Tests that depend on them
say so.

Timing: a note-on over DIN takes about 1 ms for its three bytes and reaches
the FPGA in the next main-loop pass; the 1 kHz tick sends the part sources and
two voices' aftertouch per tick.
"""

import pytest

from emu.firmware import SUMMIT_2_2, load_image
from emu.fpga import ENV_COMMANDS, ENV_RELEASE, ENV_START, GATES

VEL_SHIFT = 8  # velocity param 0x66 = velocity << 8 (observed: 100 → 25600)


@pytest.fixture(scope="module")
def summit():
    if load_image(SUMMIT_2_2) is None:
        pytest.skip(f"firmware/{SUMMIT_2_2} not present (run scripts/fetch-firmware.sh)")
    from emu.synth import SimulatedSummit

    return SimulatedSummit()


@pytest.fixture
def s(summit):
    summit.reset()
    return summit


def starts(s, voice=None):
    """Voices that got an amp-envelope start command, in order."""
    return [e.voice for e in s.fpga_events(voice=voice, param=ENV_COMMANDS[0]) if e.value & 3 == ENV_START]


def releases(s, voice=None):
    return [e.voice for e in s.fpga_events(voice=voice, param=ENV_COMMANDS[0]) if e.value & 3 == ENV_RELEASE]


# -- notes ---------------------------------------------------------------------


def test_boot_reaches_the_main_loop_idle(s):
    assert s.active_voices() == []
    assert not s.multi_mode
    assert s.channels[0] == 1  # global channel after the factory initialise


def test_note_on_allocates_a_voice_with_gates_velocity_and_pitch(s):
    s.note_on(72, 100)
    s.tick(10)
    assert s.active_voices() == [0]
    assert s.voice_note(0) == 72
    assert s.voice_pitch(0) == 72 << 8  # 8.8 semitones, equal-tempered table
    names = {e.param for e in s.fpga_events(voice=0)}
    assert set(GATES) <= names and set(ENV_COMMANDS) <= names
    assert s.last_value(voice=0, param="velocity") == 100 << VEL_SHIFT
    assert s.last_value(voice=0, param="pitch") == (72 - 60) << 8  # voice_pitch - 0x3C00
    assert starts(s) == [0]
    assert all(e.engines == "A" for e in s.fpga_events(voice=0))


def test_note_on_over_usb_takes_the_same_path(s):
    s.note_on(60, 90, port="usb")
    s.tick(10)
    assert s.active_voices() == [0]
    assert s.last_value(voice=0, param="velocity") == 90 << VEL_SHIFT


def test_note_off_releases_the_voice(s):
    s.note_on(60)
    s.tick(5)
    s.clear()
    s.note_off(60)
    s.tick(5)
    assert s.active_voices() == []
    for param in ENV_COMMANDS:
        (cmd,) = [e.value for e in s.fpga_events(voice=0, param=param)]
        assert cmd & 3 == ENV_RELEASE
    assert s.voice_aftertouch(0) == 0  # voice_clear_at


def test_chord_takes_consecutive_voices(s):
    """Rotation over idle voices. Inferred input: idle voices report state 3."""
    for n in (60, 64, 67):
        s.note_on(n)
    s.tick(10)
    assert [(v.index, v.note) for v in s.voices(active_only=True)] == [(0, 60), (1, 64), (2, 67)]
    assert s.last_value(voice=1, param="pitch") == 4 << 8
    assert s.last_value(voice=2, param="pitch") == 7 << 8


def test_unison_4_stacks_eight_voices(s):
    s.nrpn(0, 3, 4)  # patch Unison (offset 0x23), NRPN 0:3
    s.tick(5)
    assert s.patch_byte(0x23) == 4
    s.note_on(60)
    s.tick(10)
    assert [(v.index, v.note) for v in s.voices(active_only=True)] == [(v, 60) for v in range(8)]
    assert sorted(starts(s)) == list(range(8))


def test_seventeenth_note_steals_a_voice(s):
    """All 16 voices held, so voice_alloc steals. Which voice it takes depends
    on the FPGA's reported states and levels (inferred model: held voices
    report sustain at level 0, so the rotation start, voice 0, is taken)."""
    for n in range(48, 64):
        s.note_on(n)
    s.tick(30)
    assert len(s.active_voices()) == 16
    s.clear()
    s.note_on(70)
    s.tick(10)
    assert len(s.active_voices()) == 16
    assert starts(s) == [0]
    assert s.voice_note(0) == 70
    notes = sorted(v.note for v in s.voices(active_only=True))
    assert 48 not in notes and 70 in notes


# -- bend, pressure, mod wheel -------------------------------------------------


def test_pitch_bend_reaches_the_fpga_as_68_after_ticks(s):
    s.note_on(60)
    s.tick(5)
    s.clear()
    s.bend(4096)
    s.tick(1)  # the three DIN bytes take about 1 ms
    assert s.part_bend(0) == 4096 * 2
    s.tick(30)
    up = [e.value for e in s.fpga_events(target=0x1A, param="bend_up", part=0)]
    assert len(up) >= 25  # one per tick
    assert up == sorted(up) and up[-1] > up[0] > 0  # smoothed towards the target
    assert set(e.value for e in s.fpga_events(target=0x1A, param="bend_down")) == {0}


def test_pitch_bend_down_uses_69(s):
    s.bend(-4096)
    s.tick(30)
    assert s.part_bend(0) < 0
    assert s.last_value(target=0x1A, param="bend_down") > 0
    assert s.last_value(target=0x1A, param="bend_up") == 0


def test_channel_pressure_reaches_every_active_voice_within_16_ticks(s):
    for n in (60, 64, 67):
        s.note_on(n)
    s.tick(10)
    s.clear()
    s.channel_pressure(100)
    s.tick(17)
    for v in s.active_voices():
        assert s.voice_aftertouch(v) > 0
        assert any(e.value > 0 for e in s.fpga_events(voice=v, param="aftertouch"))
    # chan_at_store writes every voice's slot, so idle voices get it too
    assert {e.voice for e in s.fpga_events(param="aftertouch") if e.value > 0} == set(range(16))


def test_aftertouch_is_sent_two_voices_per_tick(s):
    s.channel_pressure(100)
    s.tick(1)
    s.clear()
    s.tick(8)
    voices = [e.voice for e in s.fpga_events(param="aftertouch")]
    assert sorted(voices) == list(range(16))  # 8 ticks x 2 = every voice once


def test_poly_pressure_reaches_only_that_notes_voice(s):
    s.note_on(60)
    s.note_on(64)
    s.tick(10)
    s.clear()
    s.poly_pressure(64, 120)
    s.tick(17)
    assert s.voice_aftertouch(1) > 0 and s.voice_aftertouch(0) == 0
    pressed = {e.voice for e in s.fpga_events(param="aftertouch") if e.value > 0}
    assert pressed == {1}


def test_mod_wheel_reaches_the_fpga_as_60(s):
    s.cc(1, 100)
    s.tick(10)
    assert s.part_modwheel(0) == 100
    assert s.last_value(target=0x1A, param="modwheel") > 0


# -- channels and modes --------------------------------------------------------


def test_single_mode_drops_other_channels(s):
    s.note_on(60, channel=2)
    s.cc(1, 100, channel=5)
    s.tick(10)
    assert s.active_voices() == []
    assert s.part_modwheel(0) == 0
    s.note_on(60, channel=1)
    s.tick(5)
    assert s.active_voices() == [0]


def test_global_channel_setting_moves_single_mode(s):
    s.set_channels(global_=4)
    assert s.channels[0] == 4
    s.note_on(60, channel=1)
    s.tick(5)
    assert s.active_voices() == []
    s.note_on(60, channel=4)
    s.tick(5)
    assert s.active_voices() == [0]


def test_multi_mode_routes_part_a_to_voices_0_7_and_part_b_to_8_15(s):
    s.set_mode("multi")
    assert s.multi_mode
    _, part_a, part_b = s.channels
    s.clear()
    s.note_on(60, channel=part_a)
    s.note_on(62, channel=part_b)
    s.tick(10)
    active = {v.index: v.note for v in s.voices(active_only=True)}
    assert len(active) == 2
    (va,) = [v for v, n in active.items() if n == 60]
    (vb,) = [v for v, n in active.items() if n == 62]
    assert va < 8 <= vb
    assert {e.engines for e in s.fpga_events(voice=va)} == {"A"}
    assert {e.engines for e in s.fpga_events(voice=vb)} == {"B"}


def test_multi_mode_part_b_holds_eight_voices(s):
    s.set_mode("multi")
    part_b = s.channels[2]
    for n in range(60, 69):
        s.note_on(n, channel=part_b)
    s.tick(30)
    assert all(8 <= v < 16 for v in s.active_voices())
    assert len(s.active_voices()) == 8


def test_nrpn_62_0_switches_single_and_multi(s):
    s.nrpn(62, 0, 1)
    s.tick(10)
    assert s.multi_mode
    part_a = s.channels[1]
    s.nrpn(62, 0, 0, channel=part_a)
    s.tick(10)
    assert not s.multi_mode


def test_in_multi_mode_nrpn_62_0_on_the_global_channel_is_ignored(s):
    """Emulated quirk: in Multi, the global channel goes to
    multi_global_dispatch, which doesn't deliver the NRPN to cc."""
    s.set_mode("multi")
    s.nrpn(62, 0, 0, channel=s.channels[0])
    s.tick(10)
    assert s.multi_mode


# -- MIDI out ------------------------------------------------------------------


def test_soft_thru_echoes_din_input_on_din_out(s):
    s.set_soft_thru(True)
    s.note_on(60)
    s.tick(5)
    assert [m.data for m in s.midi_out("din")] == [bytes.fromhex("903c64")]


def test_identity_request_is_answered_on_the_port_it_came_from(s):
    reply = bytes.fromhex("F0 7E 7F 06 02 00 20 29 33 01 00 00 02 01 02 06 F7")
    s.midi_in("F0 7E 7F 06 01 F7", port="usb")
    s.tick(10)
    assert [m.data for m in s.midi_out()] == [reply]
    assert s.midi_out()[0].port == "usb"
    s.reset()
    s.midi_in("F0 7E 7F 06 01 F7", port="din")
    s.tick(20)
    assert [(m.port, m.data) for m in s.midi_out()] == [("din", reply)]


def test_reset_returns_to_the_ready_state(s):
    s.note_on(60)
    s.bend(2000)
    s.tick(10)
    t = s.time_ms
    s.reset()
    assert s.active_voices() == [] and s.part_bend(0) == 0 and s.time_ms < t
    assert s.fpga_events() == [] and s.midi_out() == []
