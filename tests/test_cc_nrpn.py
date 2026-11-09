"""CC handler ``cc`` 0x080102C0: NRPN state machine and the missing RPN path.

``cc`` takes a pointer to the two data bytes ``[controller, value]``. The
current part comes from ``midi_current_part`` 0x20004D88. CC 99/98 store the
NRPN MSB/LSB at ``part+0x129``/``part+0x128``; CC 6 combines them into the
parameter number ``msb*128 + lsb + 0x80``, and ``param_set_from_midi``
0x08010038 receives ``(value, number)``. Any CC that the switch doesn't
handle goes to the same function as ``(value, cc)``. That includes CC 100/101
(RPN select) and CC 38, so CC 6 after an RPN select is applied to the last
NRPN.

This all runs only when the global setting ``CC/NRPN`` has its receive bit set
(``globals`` 0x200161A4 ``+0x14`` bit 0). After boot() the globals are zero
(``.bss``; ``settings_load`` hasn't run), so the tests set it.
"""

import pytest

CC = 0x080102C0
PARAM_SET_FROM_MIDI = 0x08010038
GLOBALS = 0x200161A4
CC_NRPN_RX = GLOBALS + 0x14
MIDI_CURRENT_PART = 0x20004D88
PARTS = 0x20013388
PART_SIZE = 0x288
NRPN_LSB, NRPN_MSB = 0x128, 0x129
MODE_REQUEST = 0x20004B38  # main loop: ui_select_mode(value & 0x7F) when bit 7 set

DATA = 0x08060000  # free flash, used for the [controller, value] bytes


@pytest.fixture
def send(machine):
    calls = []
    machine.stub(PARAM_SET_FROM_MIDI, lambda m: calls.append((m.arg(0), m.arg(1) & 0xFFFF)))
    machine.write(CC_NRPN_RX, b"\x01")

    def run(*pairs, part=0):
        machine.write(MIDI_CURRENT_PART, bytes([part]))
        for controller, value in pairs:
            machine.write(DATA, bytes([controller, value]))
            machine.call(CC, DATA, budget=20_000)
        out = list(calls)
        calls.clear()
        return out

    return run


def nrpn_state(machine, part=0):
    p = PARTS + part * PART_SIZE
    return machine.u8(p + NRPN_MSB), machine.u8(p + NRPN_LSB)


def test_nrpn_number_is_stored_per_part(machine, send):
    assert send((99, 3), (98, 17), part=1) == []
    assert nrpn_state(machine, part=1) == (3, 17)
    assert nrpn_state(machine, part=0) == (0, 0)


def test_nrpn_data_entry_maps_to_parameter_number(machine, send):
    # Osc 1 BendRange is NRPN 0:20 (patch descriptor 0x0804EAE4).
    assert send((99, 0), (98, 20), (6, 76)) == [(76, 0x80 + 20)]


def test_nrpn_62_0_requests_single_or_multi(machine, send):
    assert send((99, 62), (98, 0), (6, 1)) == []
    assert machine.u8(MODE_REQUEST) == 0x81
    send((6, 0))
    assert machine.u8(MODE_REQUEST) == 0x80


def test_nrpn_62_0_ignores_values_above_10(machine, send):
    send((99, 62), (98, 0), (6, 11))
    assert machine.u8(MODE_REQUEST) == 0


def test_rpn_select_is_not_tracked(machine, send):
    # RPN 0 (pitch-bend sensitivity) = 48 semitones: CC 101/100 are plain CCs,
    # and CC 6 is applied to the last NRPN (0:5 here), not to RPN 0.
    send((99, 0), (98, 5))
    assert send((101, 0), (100, 0), (6, 48), (38, 0)) == [
        (0, 101),
        (0, 100),
        (48, 0x80 + 5),
        (0, 38),
    ]
    assert nrpn_state(machine) == (0, 5)


def test_cc_nrpn_receive_off_drops_everything(machine, send):
    machine.write(CC_NRPN_RX, b"\x00")
    assert send((99, 62), (98, 0), (6, 1), (74, 100)) == []
    assert nrpn_state(machine) == (0, 0)
    assert machine.u8(MODE_REQUEST) == 0
