"""Peak version-word patch (patches/peak_version_word.py): 2108 -> 2109.

Only the version word and the header digits may differ from stock; flash.py
must dry-run it byte for byte and confirm 2109; in the simulator the Settings
SYSTEM page shows 109.469 and the identity reply reports 02 01 00 09.
"""
import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import flash  # noqa: E402
import patch  # noqa: E402
import syx  # noqa: E402

DEFINITION = ROOT / "patches" / "peak_version_word.py"
VERSION_WORD = 0x0800C1B0
STOCK_HEADER = bytes.fromhex("007e000002010008")
NEW_HEADER = bytes.fromhex("007e000002010009")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    definition = patch.load_definition(DEFINITION)
    if not (patch.FIRMWARE_DIR / definition.SOURCE).exists():
        pytest.skip(f"firmware/{definition.SOURCE} not present (run scripts/fetch-firmware.sh)")
    lines = []
    path, digest = patch.build(DEFINITION, out_dir=tmp_path_factory.mktemp("patched"), out=lines.append)
    official = (patch.FIRMWARE_DIR / definition.SOURCE).read_bytes()
    return official, path.read_bytes(), digest, lines


def test_only_the_version_word_and_header_digits_differ(built):
    official, data, digest, lines = built
    header0, stock = syx.decode(official)
    header1, patched = syx.decode(data)
    assert header0 == STOCK_HEADER and header1 == NEW_HEADER
    assert len(patched) == len(stock) and len(data) == len(official)
    assert patch.diff(stock, patched) == [(VERSION_WORD, b"\x08", b"\x09")]
    assert patched[0x1AC:0x1B4] == b"MAIN\x09\x21\x00\x00"
    assert hashlib.sha256(data).hexdigest() == digest
    assert "header  00 7e 00 00 02 01 00 08 -> 00 7e 00 00 02 01 00 09" in lines


def test_container_differs_from_stock_only_in_two_messages(built):
    official, data, _, _ = built
    stock, new = flash.Plan(official).messages, flash.Plan(data).messages
    assert len(stock) == len(new)
    changed = [i for i, (a, b) in enumerate(zip(stock, new)) if a != b]
    assert changed == [0, (0x1B0 - 32) // syx.BLOCK + 1]


def test_flash_dry_run_is_byte_for_byte_and_confirms_2109(built):
    official, data, _, _ = built
    plan = flash.Plan(data)
    assert plan.product == "Peak" and plan.version == "2109"
    synth = flash.SimulatedSynth("Peak", version="2108")
    result = flash.flash(plan, synth, flash.Log(out=lambda s: None), confirm=lambda q: True,
                         sleep=lambda s: None)
    assert b"".join(synth.received) == data
    assert result == "2109"
    # and back to stock (the recovery step): flash.py has no downgrade check
    synth = flash.SimulatedSynth("Peak", version="2109")
    result = flash.flash(flash.Plan(official), synth, flash.Log(out=lambda s: None),
                         confirm=lambda q: True, sleep=lambda s: None)
    assert result == "2108"


@pytest.fixture(scope="module")
def board(built):
    from emu.board import Board
    _, data, _, _ = built
    b = Board(syx.decode(data)[1])
    b.power_on(max_ms=20000)
    b.run_ms(50)
    return b


@pytest.mark.slow
def test_settings_system_page_shows_109(board):
    from test_peak_sim import _show
    rows = _show(board, 8, 1, 0)                 # Settings page 2: SYSTEM
    assert rows[0].startswith("SYSTEM"), rows
    assert "109.469" in "\n".join(rows), rows


@pytest.mark.slow
def test_identity_reply_reports_2109(board):
    board.din.tx_log.clear()
    for x in bytes.fromhex("f07e7f0601f7"):
        board.din.rx_queue.append((board.time_us, x))
    board.run_ms(80)
    reply = bytes(b for _, b in board.din.tx_log)
    start = reply.find(b"\xf0\x7e")
    assert start >= 0, reply.hex(" ")
    reply = reply[start:reply.index(b"\xf7", start) + 1]
    assert reply.endswith(bytes.fromhex("02010009f7")), reply.hex(" ")
    assert flash.parse_identity(reply) == ("Peak", "2109")
