"""MPE step 3: the Settings MPE pages, through the panel and the screen.

docs/mpe-design.md, "UI". Emulated. Settings → page 5/35 "MPE" (Zone,
Members, Channels) and 6/35 "MPE BEND RANGE" (Note Bend, MasterBend), after
MIDI CHANNEL. The pages show the live state (Settings plus RPN 6 / RPN 0);
a value that differs from the Settings value has a '*'. Save stores it.
Golden screens: tests/golden/screens/mpe-*.txt (UPDATE_GOLDEN=1 rewrites).
"""

import pytest

from mpe_sim import G_MASTER_RANGE, G_MEMBERS, G_NOTE_RANGE, G_ZONE, built, mpe_summit, stock_image, summit
from mpe_ui_sim import BEND_PAGE, MIDI_CHANNEL, MPE_PAGE, SETTINGS_FLASH, items, rows, settings_page
from test_screen_sim import check_golden


SAVED_MESSAGE_MS = 2500


@pytest.fixture
def m(tmp_path_factory):
    return mpe_summit(tmp_path_factory).reset()


def mpe_globals(s):
    return [s.global_setting(G_ZONE + i) for i in range(4)]


def select(s, row):
    s.press(f"item{row}")
    assert rows(s)[row - 1][2], f"row {row} not selected: {s.screen_text()}"


# ------------------------------------------------------------ the pages

def test_mpe_pages_follow_midi_channel(m):
    s = m.s
    settings_page(s, MIDI_CHANNEL)
    assert s.screen_text()[0] == "MIDI CHANNEL    4/35"
    settings_page(s, MPE_PAGE)
    check_golden("mpe-settings-zone", s.screen_text())
    settings_page(s, BEND_PAGE)
    check_golden("mpe-settings-bend", s.screen_text())


def test_every_item_shows_its_default(m):
    """Globals +0x30..+0x33 are 0 after a factory initialise: 0 shows as the default."""
    s = m.s
    assert mpe_globals(s) == [0, 0, 0, 0]
    settings_page(s, MPE_PAGE)
    assert items(s) == {"Zone": "Off", "Members": "15", "Channels": "OK"}
    settings_page(s, BEND_PAGE)
    assert items(s) == {"Note Bend": "48", "MasterBend": "2"}


def test_zone_steps_off_lower_upper_and_clamps(m):
    s = m.s
    settings_page(s, MPE_PAGE)
    select(s, 1)
    for want, zone, live in (("Lower", 1, (15, 0)), ("Upper", 2, (0, 15)), ("Upper", 2, (0, 15))):
        s.turn(1)
        assert items(s)["Zone"] == want and s.global_setting(G_ZONE) == zone
        assert m.live()["members"] == live
    s.turn(-3)
    assert items(s)["Zone"] == "Off" and s.global_setting(G_ZONE) == 0
    assert m.live()["members"] == (0, 0)


@pytest.mark.slow
def test_members_edit_and_clamp(m):
    s = m.s
    settings_page(s, MPE_PAGE)
    select(s, 1)
    s.turn(1)  # Lower
    select(s, 2)
    s.turn(-3)
    assert items(s)["Members"] == "12" and s.global_setting(G_MEMBERS) == 12
    assert m.live()["members"] == (12, 0)
    assert m.zones() == {}  # no MPE patch: nothing routed
    s.set_global(G_MEMBERS, 2)
    s.turn(-3)
    assert items(s)["Members"] == "1" and s.global_setting(G_MEMBERS) == 1
    s.press("value_inc")  # the value buttons take the same path
    assert items(s)["Members"] == "2" and s.global_setting(G_MEMBERS) == 2
    s.set_global(G_MEMBERS, 14)
    s.turn(3)
    assert items(s)["Members"] == "15" and s.global_setting(G_MEMBERS) == 15


@pytest.mark.slow
def test_members_setting_kept_while_the_zone_is_off(m):
    s = m.s
    settings_page(s, MPE_PAGE)
    select(s, 2)
    s.turn(-10)
    assert items(s) == {"Zone": "Off", "Members": "5", "Channels": "OK"}
    assert mpe_globals(s)[:2] == [0, 5] and m.live()["members"] == (0, 0)
    s.press("save")
    assert s.board.flash[11].read(SETTINGS_FLASH + G_ZONE, 2) == bytes([0, 5])


@pytest.mark.slow
def test_bend_ranges_edit_and_clamp(m):
    s = m.s
    settings_page(s, BEND_PAGE)
    select(s, 1)
    s.turn(2)
    assert items(s)["Note Bend"] == "50" and s.global_setting(G_NOTE_RANGE) == 50
    assert m.live()["note_range"] == (50, 50)
    s.set_global(G_NOTE_RANGE, 95)
    s.turn(3)
    assert items(s)["Note Bend"] == "96" and s.global_setting(G_NOTE_RANGE) == 96
    select(s, 2)
    s.turn(-3)
    assert items(s)["MasterBend"] == "1" and s.global_setting(G_MASTER_RANGE) == 1
    s.turn(11)
    assert items(s)["MasterBend"] == "12" and m.live()["master_range"] == (12, 12)
    check_golden("mpe-settings-bend-edited", s.screen_text())


def test_channels_item_is_read_only(m):
    s = m.s
    settings_page(s, MPE_PAGE)
    select(s, 3)
    before = mpe_globals(s) + [s.global_setting(0x34)]
    s.turn(2)
    assert items(s)["Channels"] == "OK"
    assert mpe_globals(s) + [s.global_setting(0x34)] == before


# ------------------------------------------------------- live values (RPN)

@pytest.mark.slow
def test_rpn6_shows_the_live_zone_and_save_stores_it(m):
    s = m.s
    settings_page(s, MPE_PAGE)
    m.mcm(16, 5)  # Upper Zone, 5 members, while the page is shown
    s.tick(20)
    assert items(s) == {"Zone": "Upper*", "Members": "5*", "Channels": "OK"}
    check_golden("mpe-settings-zone-rpn6", s.screen_text())
    assert mpe_globals(s) == [0, 0, 0, 0]  # live until Save
    s.press("save")
    assert s.screen_text()[0].strip() == "Settings Saved With"
    assert mpe_globals(s) == [2, 5, 48, 2]
    assert s.board.flash[11].read(SETTINGS_FLASH + G_ZONE, 4) == bytes([2, 5, 48, 2])
    s.tick(SAVED_MESSAGE_MS)  # as stock, the message gives way to the Patch screen
    settings_page(s, MPE_PAGE)
    assert items(s) == {"Zone": "Upper", "Members": "5", "Channels": "OK"}


@pytest.mark.slow
def test_rpn0_shows_the_live_bend_ranges(m):
    s = m.s
    settings_page(s, MPE_PAGE)
    select(s, 1)
    s.turn(1)  # Lower 15
    settings_page(s, BEND_PAGE)
    m.rpn(2, 0, 0, 24)  # member channel: note range
    m.rpn(1, 0, 0, 12)  # master channel: master range
    s.tick(20)
    assert items(s) == {"Note Bend": "24*", "MasterBend": "12*"}
    assert mpe_globals(s) == [1, 0, 48, 2]  # the zone edit wrote the ranges in effect


@pytest.mark.slow
def test_two_zones_show_both_and_an_edit_keeps_the_lower(m):
    s = m.s
    settings_page(s, MPE_PAGE)
    m.mcm(1, 7)
    m.mcm(16, 7)
    s.tick(20)
    assert items(s) == {"Zone": "Lo+Up*", "Members": "7+7*", "Channels": "OK"}
    settings_page(s, BEND_PAGE)
    assert items(s) == {"Note Bend": "48+48*", "MasterBend": "2+2*"}
    select(s, 1)
    s.turn(1)  # takes the live layout over as Save would: the Lower Zone
    assert items(s) == {"Note Bend": "49", "MasterBend": "2"}
    assert mpe_globals(s) == [1, 7, 49, 2] and m.live()["members"] == (7, 0)


@pytest.mark.slow
def test_an_edit_keeps_what_rpn_changed(m):
    s = m.s
    m.mcm(16, 5)
    settings_page(s, BEND_PAGE)
    select(s, 2)
    s.turn(1)
    assert items(s) == {"Note Bend": "48", "MasterBend": "3"}
    assert mpe_globals(s) == [2, 5, 48, 3]
    settings_page(s, MPE_PAGE)
    assert items(s) == {"Zone": "Upper", "Members": "5", "Channels": "OK"}


# ---------------------------------------------------------------- CH CLASH

@pytest.mark.slow
def test_ch_clash_for_a_conflicting_multi(m):
    s = m.s
    s.set_mode("multi")  # Part A channel 2, Part B 3, global 1
    settings_page(s, MPE_PAGE)
    assert items(s)["Channels"] == "OK"
    m.flag(True, part=0)  # Part A MPE: the Lower Zone, 15 members, holds B's and the global channel
    s.tick(20)
    assert m.clash() == 0b110
    assert items(s)["Channels"] == "CH CLASH"
    check_golden("mpe-settings-zone-clash", s.screen_text())
    select(s, 1)
    s.turn(2)  # Upper
    select(s, 2)
    s.turn(-14)  # Upper 1: channels 15-16, clear of 1-3
    assert items(s) == {"Zone": "Upper", "Members": "1", "Channels": "OK"}
    assert m.clash() == 0


# ------------------------------------------------------ Save, power cycle

@pytest.mark.slow
def test_save_then_power_cycle(tmp_path_factory):
    """Its own simulator: the power cycle replaces the shared one's boot state."""
    from mpe_sim import Mpe

    b = built(tmp_path_factory)
    m = Mpe(summit(b.patched, flash_from=stock_image()), b.blob)
    s = m.s
    settings_page(s, MPE_PAGE)
    select(s, 1)
    s.turn(2)  # Upper
    select(s, 2)
    s.turn(-6)  # 9
    settings_page(s, BEND_PAGE)
    select(s, 1)
    s.turn(-24)  # 24
    select(s, 2)
    s.turn(1)  # 3
    s.press("save")
    assert s.board.flash[11].read(SETTINGS_FLASH + G_ZONE, 4) == bytes([2, 9, 24, 3])
    s.power_cycle()
    assert mpe_globals(s) == [2, 9, 24, 3]
    assert m.live() == {"members": (0, 9), "note_range": (24, 24), "master_range": (3, 3)}
    settings_page(s, MPE_PAGE)
    assert items(s) == {"Zone": "Upper", "Members": "9", "Channels": "OK"}
    check_golden("mpe-settings-zone-saved", s.screen_text())
    settings_page(s, BEND_PAGE)
    assert items(s) == {"Note Bend": "24", "MasterBend": "3"}


@pytest.mark.slow
def test_rpn_changes_are_lost_without_save(tmp_path_factory):
    from mpe_sim import Mpe

    b = built(tmp_path_factory)
    m = Mpe(summit(b.patched, flash_from=stock_image()), b.blob)
    m.mcm(16, 5)
    m.s.power_cycle()
    assert m.live()["members"] == (0, 0)
    settings_page(m.s, MPE_PAGE)
    assert items(m.s) == {"Zone": "Off", "Members": "15", "Channels": "OK"}
