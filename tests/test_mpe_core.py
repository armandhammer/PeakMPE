"""MPE core in Single mode: zones, RPN, Save, the flag, voice binding (patches/mpe).

Emulated: the patch runs in the simulated Summit (docs/SIMULATOR.md) and the
tests play MIDI through DIN. docs/mpe-design.md is the spec. After every
note-on and note-off, mpe_sim.Mpe.check() asserts the binding invariants.
"""

import pytest

from mpe_sim import (FLAG, G_MASTER_RANGE, G_MEMBERS, G_NOTE_RANGE, G_ZONE, LOWER, MODE, RELEASE_MS, UNISON, built,
                     mpe_summit, stock_image, summit)

# The quick run (-m "not slow") keeps these; every other test here plays
# long enough in the simulator (3-20 s each) to be marked slow at the end.
QUICK = {
    "test_boots_with_mpe_off_and_the_default_ranges",
    "test_lower_zone_member_notes_bind_voices_and_others_are_ignored",
    "test_rpn_6_configures_the_zones_live_as_the_spec_says",
    "test_note_off_releases_only_the_voice_of_its_channel",
}

ENV1_CMD = 0x3F
ENV_START, ENV_RELEASE = 0, 3


@pytest.fixture
def m(tmp_path_factory):
    return mpe_summit(tmp_path_factory).reset()


def starts(s, voice=None):
    return [e.voice for e in s.fpga_events(voice=voice, param=ENV1_CMD) if e.value & 3 == ENV_START]


def releases(s, voice=None):
    return [e.voice for e in s.fpga_events(voice=voice, param=ENV1_CMD) if e.value & 3 == ENV_RELEASE]


# -- the flag and its descriptor -----------------------------------------------------


def test_boots_with_mpe_off_and_the_default_ranges(m):
    assert m.s.patch_byte(FLAG) == 0
    assert m.zones() == {}
    assert m.live() == {"members": (0, 0), "note_range": (48, 48), "master_range": (2, 2)}
    assert m.voice_channel() == [None] * 16
    assert m.s.boot_screen()[3].strip().startswith("MPE3 Ver")


def test_the_voice_page_edits_the_flag(m):
    s = m.s
    s.press("voice")
    assert s.screen_text()[3].split() == ["MPE", "Off"]
    s.press("item3")
    s.turn(+1)
    assert s.patch_byte(FLAG) == 1
    assert s.screen_text()[3].split()[:2] == ["MPE", "On"]
    s.turn(+3)  # max 1
    assert s.patch_byte(FLAG) == 1
    s.turn(-1)
    assert s.patch_byte(FLAG) == 0


@pytest.mark.parametrize("value", [2, 0x7F])
def test_only_the_value_1_means_on(m, value):
    m.s.set_patch_byte(FLAG, value)
    m.s.note_on(60, channel=2)
    m.s.tick(5)
    assert m.zones() == {}
    assert m.s.active_voices() == []  # channel 2 isn't the global channel: dropped, as stock


# -- zones in Single mode ----------------------------------------------------------


def test_flag_on_without_a_zone_setting_plays_the_lower_zone_with_15_members(m):
    m.flag()
    m.on(60, 2)
    assert m.zones() == {"lower": (0, 1, 2, 16)}
    assert m.voice_channel()[m.s.active_voices()[0]] == 2


def test_lower_zone_member_notes_bind_voices_and_others_are_ignored(m):
    m.zone_setting(1, 5)  # Lower, members 2-6
    m.flag()
    for ch, note in ((2, 60), (3, 64), (6, 67)):
        m.on(note, ch)
    assert m.zones() == {"lower": (0, 1, 2, 6)}
    vc = m.voice_channel()
    assert {vc[v]: m.s.voice_note(v) for v in m.s.active_voices()} == {2: 60, 3: 64, 6: 67}
    for ch in (7, 10, 15, 16):  # outside the zone and not the global channel: dropped, as stock
        m.s.note_on(72, channel=ch)
        m.s.tick(4)
    assert len(m.s.active_voices()) == 3
    m.all_off()


def test_upper_zone_member_notes_bind_voices(m):
    m.zone_setting(2, 4)  # Upper, members 12-15
    m.flag()
    assert m.zones() == {"upper": (0, 16, 12, 15)}
    m.on(60, 15)
    m.on(62, 12)
    m.s.note_on(64, channel=11)
    m.s.tick(4)
    vc = m.voice_channel()
    assert sorted(vc[v] for v in m.s.active_voices()) == [12, 15]
    m.all_off()


def test_the_global_channel_outside_the_zone_keeps_playing_unbound(m):
    m.zone_setting(1, 3)  # Lower 1-4
    m.flag()
    m.s.set_channels(global_=10)
    m.on(60, 2)
    m.on(64, 10)  # not a zone channel: stock path, no binding
    vc = m.voice_channel()
    assert {m.s.voice_note(v): vc[v] for v in m.s.active_voices()} == {60: 2, 64: None}
    m.s.note_off(64, channel=10)
    m.off(60, 2)
    m.s.tick(RELEASE_MS)
    assert m.s.active_voices() == []


def test_notes_on_the_master_channel_play_bound_to_it(m):
    m.flag()
    m.on(60, 1)
    assert [m.voice_channel()[v] for v in m.s.active_voices()] == [1]
    m.all_off()


def test_member_bend_pressure_and_slide_are_stored_per_channel(m):
    m.flag()
    m.on(60, 3)
    s = m.s
    s.clear()
    s.bend(4096, channel=3)
    s.channel_pressure(90, channel=3)
    s.cc(74, 33, channel=3)
    s.cc(1, 127, channel=3)  # mod wheel on a member channel: dropped
    s.tick(20)
    board, a = s.board, m.addr
    assert int.from_bytes(board.read(a("mpe_chan_bend") + 2 * 2, 2), "little", signed=True) == 4096
    assert board.u8(a("mpe_chan_pressure") + 2) == 90
    assert board.u8(a("mpe_chan_slide") + 2) == 33
    assert s.part_bend(0) == 0 and s.part_modwheel(0) == 0
    # Not through the part: step 2 gives the pressure to the channel's voice
    # only (tests/test_mpe_expr_single.py).
    assert s.voice_aftertouch(s.active_voices()[0]) == 90 << 8
    m.all_off()


def test_master_channel_bend_and_controllers_reach_the_part(m):
    m.flag()
    m.on(60, 3)
    m.s.bend(4096, channel=1)
    m.s.cc(1, 100, channel=1)
    m.s.tick(5)
    assert m.s.part_bend(0) != 0
    assert m.s.part_modwheel(0) == 100
    m.all_off()


def test_all_notes_off_on_a_member_channel_releases_the_part(m):
    m.flag()
    m.on(60, 2)
    m.on(64, 3)
    m.s.cc(123, 0, channel=4)
    m.s.tick(5)
    assert m.s.active_voices() == []


# -- RPN 6, RPN 0, Settings and Save --------------------------------------------------


def test_rpn_6_configures_the_zones_live_as_the_spec_says(m):
    m.mcm(1, 5)
    assert m.live()["members"] == (5, 0)
    m.mcm(16, 6)
    assert m.live()["members"] == (5, 6)
    m.mcm(16, 12)  # overlaps: the Lower Zone shrinks to 14 - 12
    assert m.live()["members"] == (2, 12)
    m.mcm(1, 15)  # takes everything
    assert m.live()["members"] == (15, 0)
    m.mcm(1, 0)
    assert m.live()["members"] == (0, 0)
    m.mcm(5, 3)  # not channel 1 or 16: no MCM
    assert m.live()["members"] == (0, 0)
    assert m.s.global_setting(G_ZONE) == 0  # not saved


def test_rpn_6_moves_the_zone_while_playing(m):
    m.flag()
    m.mcm(16, 3)
    assert m.zones() == {"upper": (0, 16, 13, 15)}
    m.on(60, 14)
    m.s.note_on(62, channel=2)
    m.s.tick(5)
    assert [m.voice_channel()[v] for v in m.s.active_voices()] == [14]
    m.all_off()


def test_rpn_0_sets_the_note_and_master_ranges_of_the_zone(m):
    m.flag()
    m.rpn(4, 0, 0, 24)  # any member channel: the note range, zone-wide
    m.rpn(1, 0, 0, 12)  # master
    assert m.live()["note_range"][LOWER] == 24
    assert m.live()["master_range"][LOWER] == 12
    m.rpn(4, 0, 0, 120)
    assert m.live()["note_range"][LOWER] == 96
    m.mcm(1, 15)  # an MCM resets the zone's ranges to the Settings values
    assert m.live()["note_range"][LOWER] == 48 and m.live()["master_range"][LOWER] == 2


def test_rpn_data_entry_doesnt_reach_the_last_nrpn_on_a_zone_channel(m):
    """Stock applies CC 6 after an RPN select to the last NRPN (findings, "CC,
    NRPN and RPN"). In a zone the patch takes it; NRPN still works there."""
    m.flag()
    s = m.s
    s.set_cc_nrpn_receive(True)
    s.nrpn(0, 3, 2, channel=1)  # Unison 2, by NRPN on the master channel
    s.tick(5)
    assert s.patch_byte(UNISON) == 2
    m.rpn(1, 0, 0, 3)  # RPN 0 = 3: must not set the unison
    assert s.patch_byte(UNISON) == 2
    assert m.live()["master_range"][LOWER] == 3
    s.cc(6, 1, channel=1)  # still RPN 0 selected
    s.tick(5)
    assert s.patch_byte(UNISON) == 2 and m.live()["master_range"][LOWER] == 1
    s.nrpn(0, 3, 0, channel=1)  # selecting an NRPN again: CC 6 goes to it
    s.tick(5)
    assert s.patch_byte(UNISON) == 0


def test_rpn_outside_any_zone_still_reaches_the_firmware_as_stock(m):
    s = m.s  # MPE off: no zone in use
    s.set_cc_nrpn_receive(True)
    s.nrpn(0, 3, 2)
    s.tick(5)
    m.rpn(1, 0, 6, 3)  # an MCM: applied to the live layout ...
    assert m.live()["members"] == (3, 0)
    assert s.patch_byte(UNISON) == 3  # ... and, as stock, CC 6 hit the last NRPN (Unison)


def test_settings_layout_changes_apply_live(m):
    m.zone_setting(2, 9)
    assert m.live()["members"] == (0, 9)
    m.zone_setting(1, 0)  # members 0 = 15
    assert m.live()["members"] == (15, 0)
    m.zone_setting(7, 3)  # out of range = Off
    assert m.live()["members"] == (0, 0)
    m.s.set_global(G_NOTE_RANGE, 24)
    m.s.set_global(G_MASTER_RANGE, 0)
    assert m.live()["note_range"] == (24, 24) and m.live()["master_range"] == (2, 2)


def test_save_persists_the_live_state_and_a_power_cycle_reloads_it(tmp_path_factory):
    b = built(tmp_path_factory)
    from mpe_sim import Mpe

    m = Mpe(summit(b.patched, flash_from=stock_image()), b.blob)
    m.mcm(16, 6)
    m.rpn(15, 0, 0, 36)
    m.rpn(16, 0, 0, 7)
    assert m.live() == {"members": (0, 6), "note_range": (48, 36), "master_range": (2, 7)}
    m.s.power_cycle()  # not saved: lost
    assert m.live()["members"] == (0, 0)

    m.mcm(16, 6)
    m.rpn(15, 0, 0, 36)
    m.rpn(16, 0, 0, 7)
    m.s.press("settings")
    m.s.press("save")
    assert "Settings Saved" in m.s.screen_text()[0]
    assert [m.s.global_setting(o) for o in (G_ZONE, G_MEMBERS, G_NOTE_RANGE, G_MASTER_RANGE)] == [2, 6, 36, 7]
    m.s.power_cycle()
    assert [m.s.global_setting(o) for o in (G_ZONE, G_MEMBERS, G_NOTE_RANGE, G_MASTER_RANGE)] == [2, 6, 36, 7]
    assert m.live() == {"members": (0, 6), "note_range": (36, 36), "master_range": (7, 7)}


# -- voice binding ---------------------------------------------------------------------


def test_note_off_releases_only_the_voice_of_its_channel(m):
    m.flag()
    m.on(64, 2)
    m.on(64, 3)  # the same note on two channels: two voices
    (v2,), (v3,) = m.bound(2), m.bound(3)
    m.s.clear()
    m.off(64, 2)
    assert releases(m.s) == [v2]
    assert m.s.active_voices() == [v3]
    m.all_off()


def test_unison_stacks_bind_together_and_release_together(m):
    m.flag()
    m.s.set_patch_byte(UNISON, 3)  # 4 voices per note
    m.on(60, 2)
    m.on(64, 3)
    assert len(m.bound(2)) == 4 and len(m.bound(3)) == 4
    m.off(60, 2)
    assert m.bound(2) == [] and len(m.bound(3)) == 4
    m.all_off()


def test_unison_8_fills_all_16_voices_with_two_notes(m):
    m.flag()
    m.s.set_patch_byte(UNISON, 4)  # 8 voices per note
    m.on(60, 2)
    m.on(64, 3)
    assert sorted(m.bound(2) + m.bound(3)) == list(range(16))
    m.all_off()


def test_a_reused_channel_takes_over_its_voice(m):
    """MPE: one note per channel. A new note on a channel whose note is
    still held, or still releasing, takes over that channel's voice (an
    idle one rotates since v1.1: tests/test_mpe_rotation.py). The release
    is the simulator's model: 100 ms to level 0."""
    m.s.release_ms = 100
    m.flag()
    m.on(60, 2)
    (v,) = m.bound(2)
    m.on(62, 3)
    m.on(67, 2)  # no note-off for 60 first
    assert m.bound(2) == [v] and m.s.voice_note(v) == 67
    m.off(67, 2)
    m.s.tick(5)  # releasing
    m.on(69, 2)
    assert m.bound(2) == [v] and m.s.voice_note(v) == 69
    m.s.note_off(60, channel=2)  # the stale note-off of 60: nothing to release
    m.s.tick(5)
    m.check()
    assert m.bound(2) == [v]
    m.all_off()


def test_a_reused_unison_channel_takes_over_its_whole_stack(m):
    m.flag()
    m.s.set_patch_byte(UNISON, 1)  # 2 voices per note
    m.on(60, 2)
    stack = m.bound(2)
    m.on(62, 2)
    assert m.bound(2) == stack
    m.all_off()


def test_stealing_moves_the_binding_and_leaves_no_orphan(m):
    m.flag()
    for i in range(16):
        m.on(48 + i, 2 + i % 15 if i < 15 else 1)  # 16 notes on 16 channels: every voice
    assert len(m.s.active_voices()) == 16
    # A 17th note: channel 2's note was the first, so channel 2 is reused;
    # first release one channel, then play on it again with all voices busy.
    m.off(48, 2)
    m.s.tick(20)
    m.on(70, 2)
    m.on(71, 3)  # channel 3 reused while its note is held: takes over its voice
    assert len(m.s.active_voices()) == 16
    m.all_off()


def test_stealing_a_voice_from_another_channel(m):
    m.flag()
    m.s.set_patch_byte(UNISON, 4)  # 8 voices per note: two notes fill the synth
    m.on(60, 2)
    m.on(64, 3)
    m.on(67, 4)  # steals from the others
    assert len(m.bound(4)) == 8
    assert len(m.bound(2)) + len(m.bound(3)) == 8
    m.off(60, 2)
    m.off(64, 3)
    assert len(m.s.active_voices()) == 8
    m.all_off()


@pytest.mark.parametrize("mode", [0, 1, 2], ids=["mono", "monolg", "mono2"])
def test_mono_modes_follow_the_sounding_notes_channel(m, mode):
    m.flag()
    m.s.set_patch_byte(MODE, mode)
    s = m.s
    s.note_on(60, channel=2)
    s.tick(5)
    s.note_on(64, channel=3)  # the voice moves to channel 3
    s.tick(5)
    (v,) = s.active_voices()
    assert m.voice_channel()[v] == 3 and s.voice_note(v) == 64
    s.note_off(64, channel=3)  # back to the held note and its channel
    s.tick(5)
    (v,) = s.active_voices()
    assert m.voice_channel()[v] == 2 and s.voice_note(v) == 60
    s.note_off(60, channel=2)
    s.tick(RELEASE_MS)
    assert s.active_voices() == []


def test_mono_with_unison_binds_the_whole_stack(m):
    m.flag()
    m.s.set_patch_byte(MODE, 1)
    m.s.set_patch_byte(UNISON, 2)
    s = m.s
    s.note_on(60, channel=2)
    s.tick(5)
    s.note_on(62, channel=5)
    s.tick(5)
    vc = m.voice_channel()
    assert len(s.active_voices()) == 3 and {vc[v] for v in s.active_voices()} == {5}
    s.note_off(62, channel=5)
    s.tick(5)
    assert {m.voice_channel()[v] for v in s.active_voices()} == {2}
    s.note_off(60, channel=2)
    s.tick(RELEASE_MS)
    assert s.active_voices() == []


def test_sustain_on_the_master_holds_member_notes(m):
    m.flag()
    m.on(60, 2)
    m.s.cc(64, 127, channel=1)
    m.s.note_off(60, channel=2)
    m.s.tick(20)
    assert len(m.s.active_voices()) == 1
    m.s.cc(64, 0, channel=1)
    m.s.tick(RELEASE_MS)
    assert m.s.active_voices() == []


def test_switching_mpe_off_while_holding_leaves_nothing_stuck(m):
    m.flag()
    m.on(60, 2)
    m.on(64, 3)
    m.flag(False)  # e.g. a program change to a non-MPE patch
    m.s.note_off(60, channel=2)  # not a zone channel any more
    m.s.note_off(64, channel=3)
    m.s.tick(RELEASE_MS)
    assert m.s.active_voices() == []


def test_the_keybed_path_doesnt_release_mpe_voices(m):
    """A note-off that isn't from a zone channel (here: the global channel
    outside the zone) releases only unbound voices with that note."""
    m.zone_setting(1, 3)
    m.flag()
    m.s.set_channels(global_=10)
    m.on(60, 2)
    m.s.note_on(60, channel=10)
    m.s.tick(5)
    m.s.note_off(60, channel=10)
    m.s.tick(5)
    assert m.bound(2) != [] and len(m.s.active_voices()) == 1
    m.all_off()


def test_a_long_mpe_sequence_keeps_every_invariant(m):
    m.flag()
    m.s.set_patch_byte(UNISON, 1)
    notes = [60, 62, 64, 65, 67, 69, 71, 72, 74, 76, 77, 79]
    for i, n in enumerate(notes * 3):
        ch = 2 + (i * 7) % 15  # channels 2-16
        m.on(n, ch, ms=3)
        if i % 3 == 2:
            old = next(iter(m.held.items()))
            m.off(old[1], old[0], ms=3)
    m.all_off()
    assert set(releases(m.s)) <= set(starts(m.s))


for _name, _test in list(globals().items()):
    if _name.startswith("test_") and _name not in QUICK:
        globals()[_name] = pytest.mark.slow(_test)
