"""C patches in the simulated Summit: the demo note hook (patches/demo_note_hook).

Builds the demo with tools/patch.py (needs arm-none-eabi-gcc), boots it in
SimulatedSummit with the stock image's cached DataFlash (the patch doesn't
touch the factory initialise), and plays a note through the real DIN path:
USART6 interrupt → midi_drain → handler table → demo_note_on → note_on →
demo_voice_trigger → voice_trigger. Emulated.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import patch  # noqa: E402
import patch_build  # noqa: E402

from emu.firmware import SUMMIT_2_2, load_image  # noqa: E402

DEMO = ROOT / "patches" / "demo_note_hook" / "patch.py"
DEMO_MAGIC = 0x4D504530


@pytest.fixture(scope="module")
def demo_summit(tmp_path_factory):
    stock = load_image(SUMMIT_2_2)
    if stock is None:
        pytest.skip(f"firmware/{SUMMIT_2_2} not present")
    if not patch_build.available():
        pytest.skip("arm-none-eabi-gcc not installed")
    from emu.synth import SimulatedSummit

    demo = patch.build_image(DEMO, build_dir=tmp_path_factory.mktemp("build"))
    return demo, SimulatedSummit(demo.patched, flash_from=stock)


@pytest.mark.slow  # builds the demo patch and boots a second simulator, about 7 s
def test_demo_patch_counts_notes_and_plays_as_stock(demo_summit):
    demo, s = demo_summit
    s.reset()

    def u32(name):
        return s.board.u32(demo.blob.address(name))

    assert u32("demo_magic") == DEMO_MAGIC  # startup hook ran patch_init
    calls, triggers = u32("demo_note_on_calls"), u32("demo_voice_trigger_calls")
    s.note_on(64, 100)
    s.tick(10)
    assert u32("demo_note_on_calls") == calls + 1
    assert u32("demo_voice_trigger_calls") == triggers + 1
    assert s.board.u8(demo.blob.address("demo_last_note")) == 64
    assert s.active_voices() == [0]
    assert s.last_value(voice=0, param="velocity") == 100 << 8
    assert s.last_value(voice=0, param="pitch") == 4 << 8
    assert {e.param for e in s.fpga_events(voice=0)} >= {0x3F, 0x40, 0x43, 0x46, 0x66}
