"""Unit tests for the simulator's pieces that need no firmware: the SPI1 bus
decoder, the voice-state reply, MIDI framing, and the tools/sim.py score
parser. Plus one CLI run, skipped without firmware."""

import importlib.util
from pathlib import Path

import pytest

from emu.firmware import SUMMIT_2_2, load_image
from emu.fpga import CS_ENGINE0, CS_ENGINE1, FpgaBus, filter_events
from emu.synth import split_messages, split_timed, usb_packets

ROOT = Path(__file__).resolve().parent.parent


def sim_tool():
    spec = importlib.util.spec_from_file_location("sim_tool", ROOT / "tools" / "sim.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def transaction(bus, cs, frames, read=False):
    bus.gpiob_bsrr(cs << 16)
    for f in frames:
        bus.spi_write(f)
        if read:
            bus.spi_read()
    bus.gpiob_bsrr(cs)


def test_bus_decodes_voice_targets_per_engine():
    bus = FpgaBus(lambda: 1.5)
    transaction(bus, CS_ENGINE0, [0x3067, 0x0000, 0x0400])  # voice 3, pitch, +4 semitones
    transaction(bus, CS_ENGINE1, [0x2061, 0x0000, 0x1234])  # engine B nibble 2 = voice 10
    a, b = bus.events
    assert (a.engines, a.target, a.voice, a.name, a.value, a.time_ms) == ("A", 3, 3, "pitch", 0x400, 1.5)
    assert (b.engines, b.target, b.voice, b.name, b.value) == ("B", 10, 10, "aftertouch", 0x1234)


def test_bus_decodes_broadcasts_and_signed_values():
    bus = FpgaBus(lambda: 0.0)
    transaction(bus, CS_ENGINE0 | CS_ENGINE1, [0xA068, 0xFFFF, 0xF000])
    (e,) = bus.events
    assert (e.engines, e.target, e.voice, e.part, e.name, e.value) == ("AB", 0x1A, None, None, "bend_up", -4096)


def test_bus_ignores_frames_without_chip_select_and_flags_odd_lengths():
    bus = FpgaBus(lambda: 0.0)
    bus.spi_write(0x1234)
    transaction(bus, CS_ENGINE0, [0x0001, 0x0002])
    assert bus.events == [] and len(bus.malformed) == 1


def test_voice_state_reply_packs_two_bits_per_voice():
    bus = FpgaBus(lambda: 0.0)
    assert bus.voices.packed(0, 0.0) == 0xFFFF  # never played: release/idle
    transaction(bus, CS_ENGINE0, [0x103F, 0, 0x30])  # voice 1 amp env start
    assert bus.voices.packed(0, 1.0) == 0xFFF3  # attack (0) for voice 1
    assert bus.voices.packed(0, 10.0) == 0xFFFB  # then sustain (2)
    replies = []
    bus.gpiob_bsrr(CS_ENGINE0 << 16)
    for f in (0x8010, 0, 1):
        bus.spi_write(f)
        replies.append(bus.spi_read())
    bus.gpiob_bsrr(CS_ENGINE0)
    assert replies == [0, 0, 0xFFFB]
    assert bus.events[-1].read


def test_filter_events_by_name_part_and_voice():
    bus = FpgaBus(lambda: 0.0)
    transaction(bus, CS_ENGINE0, [0x0066, 0, 100 << 8])
    transaction(bus, CS_ENGINE1, [0x0066, 0, 90 << 8])
    transaction(bus, CS_ENGINE0 | CS_ENGINE1, [0xA060, 0, 7])
    assert [e.voice for e in filter_events(bus.events, param="velocity")] == [0, 8]
    assert [e.target for e in filter_events(bus.events, part=1)] == [8, 0x1A]
    assert filter_events(bus.events, voice=8, param=("velocity", 0x60))[0].value == 90 << 8


def test_split_messages_expands_running_status_and_keeps_sysex():
    stream = bytes.fromhex("90 3C 64 40 64 F8 B0 01 7F F0 7E 7F 06 01 F7 C0 05")
    assert split_messages(stream) == [
        bytes.fromhex("903C64"),
        bytes.fromhex("904064"),
        b"\xf8",
        bytes.fromhex("B0017F"),
        bytes.fromhex("F07E7F0601F7"),
        bytes.fromhex("C005"),
    ]
    assert split_timed([(1.0, 0x90), (2.0, 0x3C), (3.0, 0x64)]) == [(3.0, bytes.fromhex("903C64"))]


def test_usb_packets_follow_the_usb_midi_code_index_numbers():
    assert usb_packets(bytes.fromhex("903C64 D040 F07E7F0601F7")) == [
        bytes.fromhex("09903C64"),
        bytes.fromhex("0DD04000"),
        bytes.fromhex("04F07E7F"),
        bytes.fromhex("070601F7"),
    ]


def test_score_parser():
    sim = sim_tool()
    lines = ["0 on C4 100  # comment", "+20 bend -8192 ch=2", "+5 nrpn 62 0 1 port=usb", "", "40 mode multi", "50 hex 90 3c 00"]
    assert list(sim.parse_score(lines)) == [
        (0.0, "midi", bytes.fromhex("903C64"), None),
        (20.0, "midi", bytes.fromhex("E10000"), None),
        (25.0, "midi", bytes.fromhex("B0633E B06200 B00601"), "usb"),
        (40.0, "mode", "multi", None),
        (50.0, "midi", bytes.fromhex("903C00"), None),
    ]
    assert sim.note_number("F#3") == 54 and sim.note_number("64") == 64


@pytest.mark.slow  # boots the simulator from scratch in tools/sim.py, about 6 s
def test_cli_prints_a_timeline(capsys):
    if load_image(SUMMIT_2_2) is None:
        pytest.skip(f"firmware/{SUMMIT_2_2} not present")
    sim_tool().main(["-e", "0 on 60", "-e", "10 off 60", "--tail", "10"])
    out = capsys.readouterr().out
    assert "> din  in  90 3C 64" in out
    assert "fpga A  v0   velocity    25600" in out
    assert out.strip().endswith("active voices (voice, note): none")
