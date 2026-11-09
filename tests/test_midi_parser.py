"""USB-MIDI output packetizer at 0x080212D8 (Summit 2.2 build 2121).

``usb_tx_byte`` in docs/symbols: ``midi_route`` 0x0801D610 calls it to forward
a MIDI byte stream to USB. It is the output path, not the input parser; MIDI
input goes through ``midi_parse_byte`` 0x080107B0.

The function takes one MIDI byte (r0) and keeps its state in a RAM struct
(pointer literal at 0x080213BC). When a message is complete it calls
0x08021294 with a pointer to a 4-byte USB-MIDI event packet
``[CIN, b0, b1, b2]``. Here 0x08021294 is stubbed to record that packet.
What 0x08021294 does with it on the hardware (it checks 0x08021284, then
pushes the bytes through 0x08021000) is not established yet.

The expected packets below are what the stock firmware produces in this
harness, checked against the USB-MIDI 1.0 class spec (CIN = status high nibble
for channel messages; 0x4/0x5/0x6/0x7 for SysEx start/continue and end).
"""

import pytest

PARSE_BYTE = 0x080212D8
EMIT_PACKET = 0x08021294


@pytest.fixture
def feed(machine):
    packets = []
    machine.stub(EMIT_PACKET, lambda m: packets.append(m.read(m.arg(0), 4)))

    def run(*data):
        for byte in data:
            machine.call(PARSE_BYTE, byte, budget=10_000)
        out = list(packets)
        packets.clear()
        return out

    return run


def p(*b):
    return bytes(b)


def test_note_on(feed):
    assert feed(0x90, 0x3C, 0x64) == [p(0x09, 0x90, 0x3C, 0x64)]


def test_note_on_needs_both_data_bytes(feed):
    assert feed(0x91, 0x3C) == []
    assert feed(0x64) == [p(0x09, 0x91, 0x3C, 0x64)]


def test_running_status(feed):
    assert feed(0x90, 0x3C, 0x64, 0x3E, 0x40, 0x3C, 0x00) == [
        p(0x09, 0x90, 0x3C, 0x64),
        p(0x09, 0x90, 0x3E, 0x40),
        p(0x09, 0x90, 0x3C, 0x00),
    ]


def test_note_off_and_cc(feed):
    assert feed(0x83, 0x3C, 0x40, 0xB0, 0x4A, 0x7F) == [
        p(0x08, 0x83, 0x3C, 0x40),
        p(0x0B, 0xB0, 0x4A, 0x7F),
    ]


def test_pitch_bend(feed):
    assert feed(0xE0, 0x00, 0x40, 0xE5, 0x7F, 0x7F) == [
        p(0x0E, 0xE0, 0x00, 0x40),
        p(0x0E, 0xE5, 0x7F, 0x7F),
    ]


def test_two_byte_messages_with_running_status(feed):
    # Program change and channel pressure carry one data byte; the parser
    # zeroes the unused third byte when the status arrives.
    assert feed(0xC0, 0x05, 0x07, 0xD1, 0x30, 0x31) == [
        p(0x0C, 0xC0, 0x05, 0x00),
        p(0x0C, 0xC0, 0x07, 0x00),
        p(0x0D, 0xD1, 0x30, 0x00),
        p(0x0D, 0xD1, 0x31, 0x00),
    ]


def test_data_without_status_is_ignored(feed):
    assert feed(0x3C, 0x64) == []


def test_realtime_byte_inside_message_is_ignored(feed):
    # 0xF8 (clock) neither produces a packet nor disturbs the pending note-on.
    assert feed(0x90, 0x3C, 0xF8, 0x64) == [p(0x09, 0x90, 0x3C, 0x64)]


def test_short_sysex_three_bytes(feed):
    assert feed(0xF0, 0x7E, 0xF7) == [p(0x07, 0xF0, 0x7E, 0xF7)]


def test_sysex_split_across_packets(feed):
    assert feed(0xF0, 0x7E, 0x01, 0x02, 0x03, 0xF7) == [
        p(0x04, 0xF0, 0x7E, 0x01),
        p(0x07, 0x02, 0x03, 0xF7),
    ]


def test_sysex_ending_with_two_bytes(feed):
    assert feed(0xF0, 0x7E, 0x01, 0x02, 0xF7) == [
        p(0x04, 0xF0, 0x7E, 0x01),
        p(0x06, 0x02, 0xF7, 0x01),  # third byte is stale buffer content
    ]


def test_sysex_ending_with_one_byte(feed):
    # CIN 5 says only the first byte is valid; the other two are left over
    # from the previous packet, not cleared.
    assert feed(0xF0, 0x01, 0x02, 0xF7) == [
        p(0x04, 0xF0, 0x01, 0x02),
        p(0x05, 0xF7, 0x01, 0x02),
    ]


def test_data_after_sysex_end_is_ignored(feed):
    feed(0xF0, 0x7E, 0xF7)
    assert feed(0x3C, 0x64) == []
    assert feed(0x90, 0x3C, 0x64) == [p(0x09, 0x90, 0x3C, 0x64)]


def test_parser_touches_no_peripherals(machine, feed):
    feed(0x90, 0x3C, 0x64, 0xF0, 0x7E, 0xF7)
    assert machine.periph_log == []
