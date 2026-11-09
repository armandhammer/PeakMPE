"""MPE step 3: the stock Settings pages are unchanged by the two MPE pages.

The patch moves the Settings menu to patch RAM and inserts its pages after
MIDI CHANNEL (stock page p > 4 becomes p + 2), and gives the stock code
that acts on page numbers the stock number (mpe_settings_page_index). These
tests compare the patched screens with the stock image's, the page counter
cut off. The version label differs on purpose (MPE3Ver; MPE1Ver in v1, MPE2Ver in v1.1).
"""

import pytest

from mpe_sim import mpe_summit, stock_summit
from mpe_ui_sim import FAST, MIDI_CHANNEL, PAGES, STOCK_PAGES, patched_page, settings_page, without_counter
from test_screen_sim import check_golden

pytestmark = pytest.mark.slow  # walks all Settings pages of both images, about 2 min


@pytest.fixture
def m(tmp_path_factory):
    return mpe_summit(tmp_path_factory).reset()


@pytest.fixture
def stock():
    s = stock_summit()
    s.reset()
    return s


def normalise(lines):
    return [line.replace("MPE3Ver", "Version") for line in without_counter(lines)]


def walk(s, pages):
    settings_page(s, 1, pages)
    screens = []
    for page in range(1, pages + 1):
        screens.append(s.screen_text())
        if page < pages:
            s.press("page_next", **FAST)
    return screens


def test_every_stock_page_unchanged(m, stock):
    want = walk(stock, STOCK_PAGES)
    got = walk(m.s, PAGES)
    for p in range(1, STOCK_PAGES + 1):
        q = patched_page(p)
        assert got[q - 1][0].endswith(f"{q}/{PAGES}")
        assert normalise(got[q - 1]) == normalise(want[p - 1]), f"stock page {p} (patched {q})"
    for name, p in (("mpe-settings-midi-channel", MIDI_CHANNEL), ("mpe-settings-midi-control", MIDI_CHANNEL + 1)):
        check_golden(name, got[patched_page(p) - 1])


@pytest.mark.parametrize("stock_page, button", [
    (2, "item3"),    # SYSTEM: Calibrate (stock page index 1)
    (10, "item3"),   # POT CALIBRATE: Go (index 9)
    (16, "item3"),   # BACKUP: Go (index 15)
    (20, "save"),    # TUNINGTABLE 3: Save saves the tuning table (index > 16)
    (17, "save"),    # KEYBOARD: Save saves the Settings (index 16)
])
def test_page_actions_as_stock(m, stock, stock_page, button):
    screens = []
    for s, page, pages in ((stock, stock_page, STOCK_PAGES), (m.s, patched_page(stock_page), PAGES)):
        settings_page(s, page, pages)
        s.press(button)
        s.tick(50)
        screens.append(normalise(s.screen_text()))
    assert screens[1] == screens[0]


def test_save_on_the_mpe_page_saves_the_settings(m):
    settings_page(m.s, 5)
    m.s.press("save")
    assert m.s.screen_text()[0].strip() == "Settings Saved With"
