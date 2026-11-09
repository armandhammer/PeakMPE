"""MPE step 3: Settings opened by MIDI while the synth starts.

NRPN 62:0 selects a UI mode, Settings (10) too. MIDI that arrives while the
firmware starts is queued by the USART interrupt and handled in the first
main-loop pass, so an NRPN 62:0 = 10 sent at power-up opens Settings before
anything else runs. The patch's Settings tables live in patch RAM (CCM),
which neither the hardware nor the startup clears for them (PATCH_NOINIT):
they must be complete before the main loop runs (mpe_ui_boot). Here patch
RAM is filled with garbage first, as a real power-up may leave it, and the
NRPN is queued before power-on. Emulated, stock and patched.
"""

import pytest

from mpe_sim import built, stock_image, summit
from mpe_ui_sim import MPE_PAGE, PAGES, STOCK_PAGES, items, settings_page

from emu.machine import CCM_BASE, CCM_SIZE

pytestmark = pytest.mark.slow  # two power-ups

NRPN_SETTINGS = bytes([0xB0, 99, 62, 0xB0, 98, 0, 0xB0, 6, 10])  # channel 1, NRPN 62:0 = 10
CC_NRPN = 0x14  # globals: CC/NRPN receive (bit 0)
SETTINGS_FLASH = 0x300000
UI_MODE = 0x20012534 + 2


def power_up_with_nrpn(s):
    # The NRPN has to be received: CC/NRPN receive on in the saved settings.
    s.set_cc_nrpn_receive(True)
    s.board.flash[11].write(SETTINGS_FLASH + CC_NRPN, bytes([s.global_setting(CC_NRPN)]))

    def before_boot(board):
        board.write(CCM_BASE, bytes((i * 37 + 0xA5) & 0xFF for i in range(CCM_SIZE)))
        for b in NRPN_SETTINGS:
            board.din.rx_queue.append((0, b))

    s.power_cycle(settle_ms=0, before_boot=before_boot)
    assert not s.board.din.rx_queue, "the NRPN must be in before the main loop runs"
    s.tick(50)


@pytest.mark.parametrize("image", ["stock", "mpe"])
def test_settings_opened_at_power_up(tmp_path_factory, image):
    if image == "stock":
        s, pages = summit(stock_image()), STOCK_PAGES
    else:
        s, pages = summit(built(tmp_path_factory).patched, flash_from=stock_image()), PAGES
    power_up_with_nrpn(s)
    assert s.board.u8(UI_MODE) == 10
    assert s.screen_text() == [f"SYSTEM          1/{pages}", "Protect    Off     ▶", "Pickup     Off      ",
                               "Brightness  64      "]
    assert s.board.display.bad_frames == 0 and not s.board.display.lcd.unknown
    if image == "mpe":
        settings_page(s, MPE_PAGE)
        assert items(s) == {"Zone": "Off", "Members": "15", "Channels": "OK"}
        s.press("page_next")
        assert items(s) == {"Note Bend": "48", "MasterBend": "2"}
