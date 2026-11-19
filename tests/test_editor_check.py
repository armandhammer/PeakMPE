"""tools/editor_check.py: what it may send, and how runs compare (no hardware)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import editor_check as ec  # noqa: E402


def test_every_planned_message_is_allowed():
    steps = ec.plan()
    assert len(steps) == 4 + 55 + 74 + 17 + 1
    for _, msg, _, _ in steps:
        assert ec.allowed(msg) == msg


@pytest.mark.parametrize("cmd", [0x01, 0x04, 0x06, 0x07, 0x49, 0x42])
def test_stores_and_unknown_commands_are_refused(cmd):
    with pytest.raises(ValueError):
        ec.allowed(ec.req(cmd))
    with pytest.raises(ValueError):
        ec.allowed(bytes([0xF0, *ec.HDR, cmd, 0, 0, 0, 0, 0]) + bytes(512) + b"\xf7")


@pytest.mark.parametrize("msg", [
    bytes([0xF0, 0x00, 0x20, 0x29, 0x00, 0x71, 0x00, 0x7E, 0xF7]),        # the updater
    bytes([0xF0, 0x00, 0x20, 0x29, 0x30, 0x01, 0x00, 0x00, 0x7F, 0xF7]),  # the factory test
    bytes([0xF0, 0x7E, 0x00, 0x08, 0x01, 0x10]) + bytes(401) + b"\xf7",  # a tuning-table write
    bytes([0xF0, 0x7E, 0x00, 0x08, 0x00, 17, 0xF7]),                     # no table 17
    bytes([0x90, 60, 100]),
    ec.req(0x40)[:-1] + bytes([0x00, 0xF7]),                              # a request one byte long
])
def test_other_messages_are_refused(msg):
    with pytest.raises(ValueError):
        ec.allowed(msg)


def test_the_edit_buffer_write_is_allowed():
    msg = bytes([0xF0, *ec.HDR, 0x00, 0, 0, 0, 0, 0]) + bytes(512) + b"\xf7"
    assert len(msg) == ec.PATCH_LEN and ec.allowed(msg) == msg


def test_split_and_compare():
    a, b = ec.req(0x40), ec.req(0x44)
    assert ec.split(list(a + b"\x90\x3c" + b)) == [a, b]
    now = {"current": ec.summarize([a]), "settings": ec.summarize([b]), "D002": ec.summarize([a])}
    before = {"current": ec.summarize([b]), "settings": ec.summarize([b]), "D002": ec.summarize([b])}
    assert ec.compare(now, before) == ["D002"]           # "current" changes with every setup


def test_pdump_sends_only_the_rig_slot_select():
    msgs = ec.pdump_messages(1)
    assert msgs == [bytes([0xB0, 32, 4]), bytes([0xC0, 2])]
    for m in msgs:
        assert ec.allowed(m) == m
    for m in (bytes([0xB0, 0, 3]), bytes([0xB0, 32, 5]), bytes([0xB0, 32, 0]), bytes([0xB0, 7, 100]), bytes([0x90, 60, 100])):
        with pytest.raises(ValueError):
            ec.allowed(m)
