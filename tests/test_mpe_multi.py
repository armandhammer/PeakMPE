"""MPE core in Multi mode: zone mapping, 8 voices per part, the channel-conflict rule.

docs/mpe-design.md, "Multi mode (version 1)". Emulated. Part A plays
voices 0-7, Part B 8-15 (stock). Mpe.check() asserts the binding invariants
after every note.
"""

import pytest

from mpe_sim import UNISON, mpe_summit

pytestmark = pytest.mark.slow  # about 4 s per test in the simulator

PART_A_CH, PART_B_CH = 11, 12  # the Part channels these tests set, outside the default zones


@pytest.fixture
def m(tmp_path_factory):
    m = mpe_summit(tmp_path_factory).reset()
    m.s.set_mode("multi")
    m.s.set_channels(global_=16, part_a=PART_A_CH, part_b=PART_B_CH)
    return m


def flags(m, a, b):
    m.flag(a, part=0)
    m.flag(b, part=1)
    m.s.tick(2)


def voices_of(m, ch):
    return sorted(m.bound(ch))


def test_both_parts_on_split_lower_to_a_and_upper_to_b(m):
    flags(m, True, True)
    # No zone configured: Lower 7 (channels 2-8) and Upper 7 (9-15).
    assert m.zones() == {"lower": (0, 1, 2, 8), "upper": (1, 16, 9, 15)}
    m.on(60, 2)
    m.on(64, 8)
    m.on(67, 9)
    m.on(72, 15)
    assert all(v < 8 for v in voices_of(m, 2) + voices_of(m, 8))
    assert all(v >= 8 for v in voices_of(m, 9) + voices_of(m, 15))
    m.all_off()


def test_both_parts_on_keep_the_configured_lower_count(m):
    m.zone_setting(1, 5)
    flags(m, True, True)
    assert m.zones() == {"lower": (0, 1, 2, 6), "upper": (1, 16, 7, 15)}
    m.zone_setting(1, 15)  # at most 13 for Lower, at least 1 for Upper
    assert m.zones() == {"lower": (0, 1, 2, 14), "upper": (1, 16, 15, 15)}
    m.zone_setting(2, 3)  # Upper configured: the 7 + 7 split
    assert m.zones() == {"lower": (0, 1, 2, 8), "upper": (1, 16, 9, 15)}


def test_an_rpn_6_for_both_zones_overrides_the_split(m):
    flags(m, True, True)
    m.mcm(1, 3)
    m.mcm(16, 4)
    assert m.zones() == {"lower": (0, 1, 2, 4), "upper": (1, 16, 12, 15)}
    m.on(60, 4)
    m.on(62, 12)
    m.s.note_on(64, channel=8)  # in neither zone, not a Part channel: dropped
    m.s.tick(4)
    assert len(m.s.active_voices()) == 2
    m.all_off()


def test_one_part_on_takes_the_configured_zone_the_other_plays_its_channel(m):
    m.zone_setting(1, 4)  # Lower, members 2-5
    flags(m, True, False)
    assert m.zones() == {"lower": (0, 1, 2, 5)}
    assert m.clash() == 0
    m.on(60, 3)
    m.on(64, PART_B_CH)  # Part B, MPE off: as stock, unbound
    vc = m.voice_channel()
    assert [(v, vc[v]) for v in m.s.active_voices()] == [(voices_of(m, 3)[0], 3), (m.s.active_voices()[1], None)]
    assert m.s.active_voices()[0] < 8 <= m.s.active_voices()[1]
    m.s.note_off(64, channel=PART_B_CH)
    m.all_off()


def test_part_b_alone_takes_the_upper_zone(m):
    m.zone_setting(2, 3)  # Upper, members 13-15
    flags(m, False, True)
    assert m.zones() == {"upper": (1, 16, 13, 15)}
    m.on(60, 14)
    assert all(v >= 8 for v in voices_of(m, 14))
    m.s.note_on(62, channel=PART_A_CH)
    m.s.tick(4)
    assert any(v < 8 for v in m.s.active_voices())
    m.s.note_off(62, channel=PART_A_CH)
    m.all_off()


def test_one_part_on_without_a_zone_setting_takes_lower_15(m):
    flags(m, False, True)
    assert m.zones() == {"lower": (1, 1, 2, 16)}


def test_conflict_the_zone_wins_over_a_normal_parts_channel(m):
    """Part A on (Lower 15 by default), Part B off on channel 12, inside the
    zone: channel 12 plays Part A, bound; Part B can't be reached there."""
    flags(m, True, False)
    assert m.clash() & 2  # Part B's channel lies in the zone
    assert m.clash() & 4  # so does the global channel, 16
    m.on(60, PART_B_CH)
    (v,) = m.s.active_voices()
    assert v < 8 and m.voice_channel()[v] == PART_B_CH
    m.all_off()
    m.s.set_channels(part_b=1)  # the master channel: the zone's too
    assert m.clash() & 2
    m.zone_setting(1, 4)
    m.s.set_channels(part_b=PART_B_CH, global_=14)
    assert m.clash() == 0


def test_the_global_channel_inside_a_zone_belongs_to_the_zone(m):
    """Stock dispatches the Multi global channel to both parts
    (multi_global_dispatch). Inside a zone, the zone gets it."""
    m.zone_setting(2, 15)  # Upper with 15 members: channels 1-15, master 16
    flags(m, True, False)
    m.on(60, 16)  # global channel = the zone's master
    vc = m.voice_channel()
    assert [(v < 8, vc[v]) for v in m.s.active_voices()] == [(True, 16)]
    m.all_off()


def test_an_mpe_part_allocates_and_steals_only_within_its_eight_voices(m):
    flags(m, True, False)
    m.zone_setting(1, 10)
    for i in range(10):
        m.on(60 + i, 2 + i)
    assert len(m.s.active_voices()) == 8
    assert all(v < 8 for v in m.s.active_voices())
    m.on(80, PART_B_CH)  # Part B still has its own voices
    assert any(v >= 8 for v in m.s.active_voices())
    m.s.note_off(80, channel=PART_B_CH)
    m.all_off()


def test_two_mpe_parts_with_unison_stay_in_their_halves(m):
    flags(m, True, True)
    m.s.set_patch_byte(UNISON, 3, part=0)  # A: 4 voices per note
    m.s.set_patch_byte(UNISON, 1, part=1)  # B: 2 voices per note
    m.on(60, 2)
    m.on(62, 3)
    m.on(64, 10)
    m.on(65, 11)
    assert voices_of(m, 2) + voices_of(m, 3) == list(range(8))
    assert len(voices_of(m, 10)) == 2 and len(voices_of(m, 11)) == 2
    assert all(v >= 8 for v in voices_of(m, 10) + voices_of(m, 11))
    m.on(67, 4)  # A's third note steals inside A
    assert len(voices_of(m, 4)) == 4 and all(v < 8 for v in voices_of(m, 4))
    assert len(voices_of(m, 10)) == 2 and len(voices_of(m, 11)) == 2
    m.all_off()


def test_back_to_single_mode_keeps_working(m):
    flags(m, True, True)
    m.on(60, 2)
    m.all_off()
    m.s.set_mode("single")
    m.s.set_patch_byte(0x1A2, 1)
    m.s.tick(2)
    assert m.zones() == {"lower": (0, 1, 2, 16)}
    m.on(60, 9)
    m.all_off()
