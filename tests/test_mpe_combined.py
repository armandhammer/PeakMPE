"""MPE steps 2 and 3 in one image: the Settings pages drive what the
expression plays, and RPN 6 / Save show on the page and persist.

Emulated, in its own simulator (it power-cycles). Through the panel: Zone
Lower 5, Note Bend 24, the VOICE item on. Then a member channel's bend,
pressure and CC 74 move only its own voice, at the page's range; an RPN 6
widens the zone and the page shows it live; Save and a power cycle keep it.
"""

import pytest

from mpe_expr_sim import AFTERTOUCH, MODWHEEL, OSC, member_offset, moved, osc, shifted
from mpe_sim import G_ZONE, Mpe, built, stock_image, summit
from mpe_ui_sim import BEND_PAGE, MPE_PAGE, SETTINGS_FLASH, items, settings_page

pytestmark = pytest.mark.slow  # about 1 min: panel steps, playing, a power cycle

BEND_MS, AT_MS, SLIDE_MS = 50, 200, 120
SAVED_MESSAGE_MS = 2500


def chord(m, notes):
    for ch, n in notes:
        m.on(n, ch)
    m.s.tick(20)
    voices = {ch: m.bound(ch) for ch, _ in notes}
    assert all(len(v) == 1 for v in voices.values()), voices
    return {ch: v[0] for ch, v in voices.items()}


def expression_moves_only(m, ch, v, others, note_range):
    """Bend, pressure and CC 74 on member channel ch move voice v alone."""
    s = m.s
    base = osc(s, v)
    t = s.time_ms
    s.bend(8191, channel=ch)
    s.tick(BEND_MS)
    assert osc(s, v) == shifted(base, member_offset(8191, note_range))
    assert moved(s, t, OSC) == {v}
    t = s.time_ms
    s.channel_pressure(100, channel=ch)
    s.tick(AT_MS)
    assert moved(s, t, AFTERTOUCH) == {v}
    t = s.time_ms
    s.cc(74, 100, channel=ch)
    s.tick(SLIDE_MS)
    assert moved(s, t, MODWHEEL) == {v}
    assert not set(others) & (moved(s, t, OSC) | moved(s, t, AFTERTOUCH))
    s.bend(0, channel=ch)
    s.channel_pressure(0, channel=ch)
    s.cc(74, 0, channel=ch)
    s.tick(AT_MS)  # settled again, the slowest (aftertouch) included


def test_settings_page_drives_expression_and_persists(tmp_path_factory):
    b = built(tmp_path_factory)
    m = Mpe(summit(b.patched, flash_from=stock_image()), b.blob)
    s = m.s

    # The panel: Zone Lower, Members 5, Note Bend 24, then the VOICE item.
    settings_page(s, MPE_PAGE)
    s.press("item1")
    s.turn(1)
    s.press("item2")
    s.turn(-10)
    settings_page(s, BEND_PAGE)
    s.press("item1")
    s.turn(-24)
    assert items(s) == {"Note Bend": "24", "MasterBend": "2"}
    s.press("voice")
    s.press("item3")
    s.turn(1)
    s.tick(5)
    assert m.zones() == {"lower": (0, 1, 2, 6)}
    assert m.live()["note_range"] == (24, 24)

    # Step 2 at the page's range: each member moves only its voice.
    v = chord(m, ((2, 60), (3, 64), (4, 67)))
    expression_moves_only(m, 3, v[3], [v[2], v[4]], 24)
    expression_moves_only(m, 4, v[4], [v[2], v[3]], 24)
    m.all_off()

    # RPN 6 widens the zone; the page shows it live, channel 8 now plays MPE.
    settings_page(s, MPE_PAGE)
    m.mcm(1, 7)
    s.tick(20)
    assert items(s) == {"Zone": "Lower", "Members": "7*", "Channels": "OK"}
    assert m.zones() == {"lower": (0, 1, 2, 8)}
    v = chord(m, ((2, 60), (8, 72)))
    expression_moves_only(m, 8, v[8], [v[2]], 24)
    m.all_off()

    # Save, power cycle: the layout and the range are back, and play again.
    s.press("save")
    assert s.board.flash[11].read(SETTINGS_FLASH + G_ZONE, 4) == bytes([1, 7, 24, 2])
    s.tick(SAVED_MESSAGE_MS)
    s.power_cycle()
    settings_page(s, MPE_PAGE)
    assert items(s) == {"Zone": "Lower", "Members": "7", "Channels": "OK"}
    settings_page(s, BEND_PAGE)
    assert items(s) == {"Note Bend": "24", "MasterBend": "2"}
    m.flag()  # the flag is per patch, and the patch wasn't saved
    assert m.zones() == {"lower": (0, 1, 2, 8)}
    v = chord(m, ((5, 62), (8, 72)))
    expression_moves_only(m, 8, v[8], [v[5]], 24)
    m.all_off()
