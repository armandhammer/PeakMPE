"""The simulated display and front panel (emu.display, emu.panel, emu.screen).

The firmware draws on the modelled OLED and scans the modelled button chain
and encoder itself; these tests drive the panel and read the screen. Golden
screens are in tests/golden/screens/; rewrite them with
``UPDATE_GOLDEN=1 scripts/dev python -m pytest tests/test_screen_sim.py``.
"""

import difflib
import os
import struct
import sys
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from emu.display import Us2066  # noqa: E402
from emu.firmware import SUMMIT_2_2, load_image  # noqa: E402
from emu.panel import BUTTONS, PanelChain, detent_phases  # noqa: E402
from emu.screen import render, write_png  # noqa: E402

GOLDEN = ROOT / "tests" / "golden" / "screens"
GLOBALS = 0x200161A4
PICKUP, BRIGHTNESS = 0x0C, 0x0D  # globals offsets (emulated: changed through the panel)
SETTINGS_FLASH = 0x300000


# ------------------------------------------------------------ models alone

def lcd_with(*steps):
    lcd = Us2066()
    for kind, value in steps:
        getattr(lcd, kind)(value)
    return lcd


def test_us2066_addresses_rows_at_32_byte_steps():
    lcd = lcd_with(("command", 0x01), ("command", 0x80 | 0x40 + 3), *[("data", ord(c)) for c in "Hi"])
    assert lcd.text()[2] == "   Hi" + " " * 15


def test_us2066_oled_command_bytes_and_selection_args_do_not_touch_ram():
    lcd = lcd_with(("command", 0x01), ("command", 0x2A), ("command", 0x79), ("command", 0x81), ("command", 0x7F),
                   ("command", 0x78), ("command", 0x72), ("data", 0x00), ("command", 0x28))
    assert lcd.text() == [" " * 20] * 4 and not lcd.unknown


def test_us2066_cgram_glyphs():
    lcd = lcd_with(("command", 0x40 + 8), ("data", 0x1F), ("data", 0x11))
    assert lcd.glyph(1)[:2] == [0x1F, 0x11]


def test_panel_chain_clocks_out_held_buttons():
    panel = PanelChain()
    panel.set_button("save", True)  # id 35 = word 2 bit 5
    panel.gpiob_bsrr(1 << (2 + 16))  # load
    seen = []
    for _ in range(7 * 16):
        seen.append(not panel.idr(0x40020810, 4) >> 11 & 1)
        panel.gpioc_bsrr(1 << 10)
        panel.gpioc_bsrr(1 << 26)
    assert [i for i, s in enumerate(seen) if s] == [BUTTONS["save"] + 2]


def test_encoder_detents_rest_at_0_and_3():
    assert detent_phases(0, True)[-1] == 3 and detent_phases(3, True)[-1] == 0
    assert detent_phases(0, False)[-1] == 3
    with pytest.raises(ValueError):
        detent_phases(1, True)


def test_png_is_valid(tmp_path):
    lcd = lcd_with(("command", 0x80), *[("data", ord(c)) for c in "PNG"])
    w, h, rgb = render(lcd, scale=2)
    data = write_png(tmp_path / "x.png", w, h, rgb).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", data[16:24]) == (w, h)
    idat = data[data.index(b"IDAT") + 4 : data.index(b"IEND") - 8]
    assert len(zlib.decompress(idat)) == h * (3 * w + 1)


# --------------------------------------------------------- with the firmware

@pytest.fixture(scope="module")
def summit():
    from emu.synth import SimulatedSummit

    if load_image(SUMMIT_2_2) is None:
        pytest.skip(f"firmware/{SUMMIT_2_2} not present (run scripts/fetch-firmware.sh)")
    return SimulatedSummit()


@pytest.fixture
def s(summit):
    summit.reset()
    return summit


def check_golden(name, lines):
    path = GOLDEN / f"{name}.txt"
    text = "\n".join(lines) + "\n"
    if os.environ.get("UPDATE_GOLDEN") or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        if not os.environ.get("UPDATE_GOLDEN"):
            pytest.fail(f"wrote new golden screen {path.relative_to(ROOT)}; check it and run again")
        return
    expected = path.read_text()
    if text != expected:
        diff = "".join(difflib.unified_diff(
            [f"|{line}|\n" for line in expected.splitlines()], [f"|{line}|\n" for line in lines],
            f"golden/{name}", "screen"))
        pytest.fail(f"screen {name} differs from its golden copy:\n{diff}")


def test_boot_screen_stock(s):
    rows = s.boot_screen()
    assert rows[0].strip() == "Novation" and rows[1].strip() == "SUMMIT"
    assert rows[3][1:17] == " Version 126.778"


def test_display_is_on_after_boot(s):
    assert s.display_on
    assert s.board.display.bad_frames == 0 and not s.board.display.lcd.unknown


def test_settings_system_page_2_shows_the_version(s):
    s.press("settings")
    assert s.screen_text()[0] == "SYSTEM          1/33"
    s.press("page_next")
    rows = s.screen_text()
    assert rows[0].endswith("2/33") and rows[2].split() == ["Version", "126.778"]
    s.press("page_prev")
    assert s.screen_text()[0].endswith("1/33")


def test_change_a_global_through_the_panel_and_save(s):
    s.press("settings")
    s.press("item3")  # Brightness
    before = s.global_setting(BRIGHTNESS)
    s.turn(2)
    assert s.global_setting(BRIGHTNESS) == before + 2
    assert s.screen_text()[3].split()[:2] == ["Brightness", str(before + 2)]
    s.turn(-1)
    assert s.global_setting(BRIGHTNESS) == before + 1
    s.press("item2")  # Pickup Off → On
    s.turn(1)
    assert s.global_setting(PICKUP) == 1 and s.screen_text()[2].split() == ["Pickup", "On", "▶"]
    s.press("save")
    assert s.screen_text()[0].strip() == "Settings Saved With"
    saved = s.board.flash[11].read(SETTINGS_FLASH, 0x10)
    assert saved[BRIGHTNESS] == before + 1 and saved[PICKUP] == 1


def test_patch_buttons_step_the_patch(s):
    s.press("patch_next")
    assert s.screen_text()[1].split()[:2] == ["Patch", "001"]
    s.press("patch_prev")
    assert s.screen_text()[1].split()[:2] == ["Patch", "000"]


def test_screenshot_writes_png(s, tmp_path):
    path = s.screenshot(tmp_path / "main.png")
    assert path.read_bytes()[:4] == b"\x89PNG"


@pytest.mark.parametrize("name, buttons", [
    ("main", []),
    ("settings-1", ["settings"]),
    ("settings-2", ["settings", "page_next"]),
    ("osc-1", ["osc"]),
    ("voice-1", ["voice"]),  # the MPE patch adds an item here (docs/mpe-design.md, "UI")
    ("save", ["save"]),
])
def test_golden_screens(s, name, buttons):
    for b in buttons:
        s.press(b)
    check_golden(name, s.screen_text())


def test_golden_boot_screen(s):
    check_golden("boot", s.boot_screen())


# ------------------------------------------------- the version-string patch

@pytest.mark.slow
def test_boot_screen_and_settings_with_version_string_patch(tmp_path):
    import patch
    import syx

    from emu.synth import SimulatedSummit

    definition_path = ROOT / "patches" / "version_string.py"
    definition = patch.load_definition(definition_path)
    if not (patch.FIRMWARE_DIR / definition.SOURCE).exists():
        pytest.skip(f"firmware/{definition.SOURCE} not present (run scripts/fetch-firmware.sh)")
    path, _ = patch.build(definition_path, out_dir=tmp_path, out=lambda line: None)
    stock = load_image(SUMMIT_2_2)
    s = SimulatedSummit(syx.decode(path.read_bytes())[1], flash_from=stock)
    assert s.boot_screen()[3][1:17] == "MPE0 Ver 126.778"
    s.press("settings")
    s.press("page_next")
    assert s.screen_text()[2].split() == ["MPE0Ver", "126.778"]
