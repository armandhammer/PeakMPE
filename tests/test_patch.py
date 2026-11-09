"""tools/patch.py and the first patch, patches/version_string.py.

The apply/diff tests use synthetic images. The rest build the real patched
file into a temporary directory and skip without the official firmware: only
the declared bytes may differ, the file must pass flash.py's checks and dry
run, and the emulator must show the new labels with the identity reply
unchanged.
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

DEFINITION = ROOT / "patches" / "version_string.py"
BASE = patch.IMAGE_BASE

# Firmware addresses (docs/findings/summit-2.2-build2121.md, "Version text and identity").
BOOT_SCREEN = 0x08012084
FORMAT_VALUE = 0x0801B18C        # (display type, value)
UI_DRAW_PAGE = 0x0801C830
IDENTITY_REPLY = 0x0801DE18      # (port)
LCD_PUTC, LCD_CURSOR = 0x08019DC8, 0x08019DB4
EXT_FLASH_READ = 0x0800DD04
SYSEX_PUT, SYSEX_SEND = 0x0801DD7C, 0x0801DDA4
FPGA_LOAD_FLAGS = 0x20013318     # +2 bits 0xC0 set: boot_screen skips the FPGA load
UI_STATE, SETTINGS_MENU = 0x20012534, 0x2000202C
VERSION_WORD = 0x0800C1B0


# -------------------------------------------------------------- apply / diff

def image(n=64):
    return bytes(range(n))


def test_apply_replaces_declared_bytes_only():
    out = patch.apply(image(), [(BASE + 4, bytes([4, 5]), b"AB", "t")])
    assert out[4:6] == b"AB"
    assert patch.diff(image(), out) == [(BASE + 4, bytes([4, 5]), b"AB")]


@pytest.mark.parametrize("patches, message", [
    ([(BASE + 4, b"xx", b"AB", "t")], "found 04 05"),
    ([(BASE + 4, bytes([4, 5]), b"ABC", "t")], "differ in length"),
    ([(BASE + 4, bytes([4, 5]), b"AB", "t"), (BASE + 5, bytes([5]), b"C", "t")], "overlaps"),
    ([(BASE + 63, b"xx", b"AB", "t")], "past the image end"),
    ([(BASE - 1, b"", b"", "t")], "below the image base"),
])
def test_apply_refuses(patches, message):
    with pytest.raises(PatchError, match=message):
        patch.apply(image(), patches)


def test_apply_refuses_before_changing_anything():
    patches = [(BASE + 1, bytes([1]), b"A", "t"), (BASE + 2, b"x", b"B", "t")]
    with pytest.raises(PatchError):
        patch.apply(image(), patches)


def test_extend_pads_with_erased_flash_to_a_block():
    out = patch.apply(image(), [(BASE + 66, b"", b"AB", "append", True)])
    assert len(out) == 96
    assert out[64:66] == b"\xff\xff" and out[66:68] == b"AB" and set(out[68:]) == {0xFF}


def test_official_file_must_match_sha256sums(tmp_path):
    (tmp_path / "x.syx").write_bytes(b"not firmware")
    with pytest.raises(PatchError, match="no entry"):
        patch.read_official(tmp_path, "x.syx")
    (tmp_path / "SHA256SUMS").write_text("0" * 64 + "  x.syx\n")
    with pytest.raises(PatchError, match="does not match"):
        patch.read_official(tmp_path, "x.syx")


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


def test_only_declared_bytes_differ(built):
    definition, official, data, _, _ = built
    header0, stock = syx.decode(official)
    header1, patched = syx.decode(data)
    assert header1 == header0
    assert len(patched) == len(stock)
    changed = {a + i for a, old, new in patch.diff(stock, patched) for i in range(len(old))}
    declared = {a + i for a, old, new, _ in definition.PATCHES for i in range(len(new)) if old[i] != new[i]}
    assert changed == declared
    for addr, old, new, _ in definition.PATCHES:
        assert patched[addr - BASE:addr - BASE + len(new)] == new


def test_patched_file_round_trips_and_keeps_the_container(built):
    _, official, data, digest, lines = built
    assert hashlib.sha256(data).hexdigest() == digest
    assert syx.encode(*syx.decode(data)) == data
    assert len(data) == len(official)
    assert any(digest in line for line in lines)


def test_patched_file_passes_flash_check_and_dry_run(built):
    _, _, data, _, _ = built
    plan = flash.Plan(data)
    assert plan.product == "Summit"
    synth = flash.SimulatedSynth("Summit")
    flash.flash(plan, synth, flash.Log(out=lambda s: None), confirm=lambda q: True, sleep=lambda s: None)
    assert b"".join(synth.received) == data


@pytest.fixture(scope="module")
def patched_machine(built):
    _, _, data, _, _ = built
    m = Machine(syx.decode(data)[1])
    m.boot()
    return m


@pytest.fixture
def screen(patched_machine):
    """The booted patched machine with the character display captured as text.

    Cursor moves appear as ``<col,row>``. External flash reads return 0x0778,
    standing in for the FPGA build the version formatter prints after the dot.
    """
    m = patched_machine
    m.restore()
    m.unstub_all()
    text = []
    m.stub(LCD_PUTC, lambda m: text.append(chr(m.arg(0))))
    m.stub(LCD_CURSOR, lambda m: text.append(f"<{m.arg(0)},{m.arg(1)}>"))
    m.stub(EXT_FLASH_READ, lambda m: m.write(m.arg(1), b"\x78\x07"))
    yield m, text
    m.unstub_all()


def test_boot_screen_shows_the_marker(screen):
    m, text = screen
    m.write(FPGA_LOAD_FLAGS + 2, bytes([m.u8(FPGA_LOAD_FLAGS + 2) | 0xC0]))
    m.call(BOOT_SCREEN, budget=200_000)
    assert "".join(text) == "<0,0><5,0> Novation<6,1> SUMMIT<1,3>MPE0 Ver 126.778"


def test_settings_system_page_shows_the_marker(screen):
    m, text = screen
    system = 0x0804E2BC - 0x0804BD80 + 0x20000000   # page record in RAM (.data)
    pages = [m.u32(SETTINGS_MENU + 4 + 4 * i) for i in range(m.u8(SETTINGS_MENU + 1))]
    m.write(UI_STATE + 2, bytes([10]))                # UI mode 10 = Settings
    m.write(SETTINGS_MENU, bytes([pages.index(system)]))
    m.call(UI_DRAW_PAGE, budget=500_000)
    # 0x10 before "Calibrate" is a glyph the stock firmware draws there too.
    assert "".join(text) == "<16,0>2/33<0,0>SYSTEM<0,1>Msg Time<0,2>MPE0Ver<0,3>\x10 Calibrate"


def test_version_value_and_identity_reply_are_unchanged(screen):
    m, text = screen
    assert m.read(VERSION_WORD, 2) == b"\x26\x21"
    m.call(FORMAT_VALUE, 0x59, 0, budget=100_000)
    assert "".join(text) == "126.778"
    sent = []
    m.stub(SYSEX_PUT, lambda m: sent.append(m.arg(0) & 0xFF))
    m.stub(SYSEX_SEND, lambda m: None)
    m.call(IDENTITY_REPLY, 0, budget=100_000)
    assert bytes(sent) == bytes.fromhex("f07e7f0602002029330100000201020" "6f7")
