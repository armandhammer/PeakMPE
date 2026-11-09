"""MPE step 3: the per-patch flag's VOICE page item (built in step 1), through
the panel, in Single mode and per part in Multi mode.

docs/mpe-design.md, "UI": VOICE page 1, item 3 "MPE" edits the flag
(patch byte 0x1A2) of the patch the page edits, patches[multi + edit_part].
Emulated; Multi on hardware is still open.
"""

import pytest

from mpe_sim import FLAG, mpe_summit
from mpe_ui_sim import items, rows
from test_screen_sim import check_golden


@pytest.fixture
def m(tmp_path_factory):
    return mpe_summit(tmp_path_factory).reset()


def voice_mpe_item(s):
    s.press("voice")
    assert s.screen_text()[0].startswith("VOICE") and s.screen_text()[0].endswith("1/5")
    s.press("item3")
    assert rows(s)[2][:1] == ("MPE",) and rows(s)[2][2]


def test_single_mode_toggles_the_flag(m):
    s = m.s
    voice_mpe_item(s)
    assert items(s)["MPE"] == "Off" and s.patch_byte(FLAG) == 0
    s.turn(1)
    assert items(s)["MPE"] == "On" and s.patch_byte(FLAG) == 1
    check_golden("mpe-voice-on", s.screen_text())
    s.tick(5)
    assert m.zones() == {"lower": (0, 1, 2, 16)}  # no zone configured: Lower, 15 members
    s.turn(1)
    assert s.patch_byte(FLAG) == 1  # clamped
    s.press("value_dec")
    assert items(s)["MPE"] == "Off" and s.patch_byte(FLAG) == 0


@pytest.mark.slow
def test_multi_mode_edits_the_selected_part(m):
    s = m.s
    s.set_mode("multi")
    voice_mpe_item(s)
    s.turn(1)  # Part A is selected after the mode change
    assert (s.patch_byte(FLAG, 0), s.patch_byte(FLAG, 1)) == (1, 0)
    s.press("part_b")
    assert items(s)["MPE"] == "Off"
    s.turn(1)
    assert (s.patch_byte(FLAG, 0), s.patch_byte(FLAG, 1)) == (1, 1)
    s.tick(5)
    assert set(m.zones()) == {"lower", "upper"}  # A = Lower, B = Upper
    s.press("part_a")
    assert items(s)["MPE"] == "On"
    s.turn(-1)
    assert (s.patch_byte(FLAG, 0), s.patch_byte(FLAG, 1)) == (0, 1)
    s.tick(5)
    assert m.zones() == {"lower": (1, 1, 2, 16)}  # B alone takes the default zone
