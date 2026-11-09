"""The second patch, patches/version_word.py, and tools/patch.py's HEADER option.

The header tests use synthetic bodies. The rest build the real patched file
into a temporary directory and skip without the official firmware: only the
version word and the header digits may differ, flash.py must dry-run it byte
for byte and confirm 2127 afterwards, and the emulator must report 2127 in the
identity reply and show 127.778.
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
from patch import PatchError  # noqa: E402

from emu.machine import Machine  # noqa: E402
from test_patch import (BOOT_SCREEN, EXT_FLASH_READ, FORMAT_VALUE, FPGA_LOAD_FLAGS,  # noqa: E402
                        IDENTITY_REPLY, LCD_CURSOR, LCD_PUTC, SYSEX_PUT, SYSEX_SEND,
                        VERSION_WORD)

DEFINITION = ROOT / "patches" / "version_word.py"
BASE = patch.IMAGE_BASE
STOCK_HEADER = bytes.fromhex("0133000002010206")
NEW_HEADER = bytes.fromhex("0133000002010207")


# ------------------------------------------------------------ header option

def test_header_is_kept_without_a_spec():
    assert patch.replace_header(STOCK_HEADER, None) == STOCK_HEADER


def test_header_is_replaced_after_checking_the_original():
    assert patch.replace_header(STOCK_HEADER, (STOCK_HEADER, NEW_HEADER, "t")) == NEW_HEADER


@pytest.mark.parametrize("spec, message", [
    ((NEW_HEADER, NEW_HEADER, "t"), "expected 01 33 00 00 02 01 02 07"),
    ((STOCK_HEADER, NEW_HEADER[:7], "t"), "differs in length"),
    ((STOCK_HEADER, NEW_HEADER[:7] + b"\x80", "t"), "above 0x7F"),
])
def test_header_replacement_refuses(spec, message):
    with pytest.raises(PatchError, match=message):
        patch.replace_header(STOCK_HEADER, spec)


# ------------------------------------------------------- the real patched file

@pytest.fixture(scope="module")
def built(tmp_path_factory):
    definition = patch.load_definition(DEFINITION)
    if not (patch.FIRMWARE_DIR / definition.SOURCE).exists():
        pytest.skip(f"firmware/{definition.SOURCE} not present (run scripts/fetch-firmware.sh)")
    lines = []
    path, digest = patch.build(DEFINITION, out_dir=tmp_path_factory.mktemp("patched"), out=lines.append)
    official = (patch.FIRMWARE_DIR / definition.SOURCE).read_bytes()
    return definition, official, path.read_bytes(), digest, lines


def test_only_the_version_word_and_header_digits_differ(built):
    _, official, data, digest, lines = built
    header0, stock = syx.decode(official)
    header1, patched = syx.decode(data)
    assert header0 == STOCK_HEADER and header1 == NEW_HEADER
    assert len(patched) == len(stock) and len(data) == len(official)
    assert patch.diff(stock, patched) == [(VERSION_WORD, b"\x26", b"\x27")]
    assert patched[0x1AC:0x1B4] == b"MAIN\x27\x21\x00\x00"
    assert hashlib.sha256(data).hexdigest() == digest
    assert "header  01 33 00 00 02 01 02 06 -> 01 33 00 00 02 01 02 07" in lines


def test_container_differs_from_stock_only_in_two_messages(built):
    # The header (0x71) and the block holding 0x0800C1B0. syx.encode sends the
    # image from byte 32 on, then bytes 0-31 last, so that is data block 13.
    _, official, data, _, _ = built
    stock, new = flash.Plan(official).messages, flash.Plan(data).messages
    assert len(stock) == len(new)
    changed = [i for i, (a, b) in enumerate(zip(stock, new)) if a != b]
    assert changed == [0, (0x1B0 - 32) // syx.BLOCK + 1]


def test_flash_dry_run_is_byte_for_byte_and_confirms_2127(built):
    _, _, data, _, _ = built
    plan = flash.Plan(data)
    assert plan.product == "Summit" and plan.version == "2127"
    synth = flash.SimulatedSynth("Summit", version="2126")
    lines = []
    result = flash.flash(plan, synth, flash.Log(out=lines.append), confirm=lambda q: True,
                         sleep=lambda s: None)
    assert b"".join(synth.received) == data
    assert result == "2127"
    assert "device: Summit on 'Summit', firmware 2126" in lines
    assert lines[-1] == "application back: Summit firmware 2127, as in the file header"


def test_stock_reflash_from_2127_is_not_refused_by_flash_py(built):
    # The recovery step: flash.py itself has no downgrade check.
    _, official, _, _, _ = built
    plan = flash.Plan(official)
    synth = flash.SimulatedSynth("Summit", version="2127")
    result = flash.flash(plan, synth, flash.Log(out=lambda s: None), confirm=lambda q: True,
                         sleep=lambda s: None)
    assert b"".join(synth.received) == official
    assert result == "2126"


@pytest.fixture(scope="module")
def patched_machine(built):
    _, _, data, _, _ = built
    m = Machine(syx.decode(data)[1])
    m.boot()
    return m


@pytest.fixture
def screen(patched_machine):
    """As in test_patch.py: display captured as text, external flash reads 0x0778."""
    m = patched_machine
    m.restore()
    m.unstub_all()
    text = []
    m.stub(LCD_PUTC, lambda m: text.append(chr(m.arg(0))))
    m.stub(LCD_CURSOR, lambda m: text.append(f"<{m.arg(0)},{m.arg(1)}>"))
    m.stub(EXT_FLASH_READ, lambda m: m.write(m.arg(1), b"\x78\x07"))
    yield m, text
    m.unstub_all()


def test_identity_reply_reports_2127(screen):
    m, _ = screen
    assert m.read(VERSION_WORD, 2) == b"\x27\x21"
    sent = []
    m.stub(SYSEX_PUT, lambda m: sent.append(m.arg(0) & 0xFF))
    m.stub(SYSEX_SEND, lambda m: None)
    m.call(IDENTITY_REPLY, 0, budget=100_000)
    reply = bytes(sent)
    assert reply == bytes.fromhex("f07e7f06020020293301000002010207f7")
    assert flash.parse_identity(reply) == ("Summit", "2127")


def test_boot_screen_shows_127(screen):
    m, text = screen
    m.write(FPGA_LOAD_FLAGS + 2, bytes([m.u8(FPGA_LOAD_FLAGS + 2) | 0xC0]))
    m.call(BOOT_SCREEN, budget=200_000)
    assert "".join(text) == "<0,0><5,0> Novation<6,1> SUMMIT<1,3> Version 127.778"


def test_settings_version_value_shows_127(screen):
    m, text = screen
    m.call(FORMAT_VALUE, 0x59, 0, budget=100_000)
    assert "".join(text) == "127.778"
