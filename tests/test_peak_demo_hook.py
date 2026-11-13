"""Peak demo hook (patches/peak_demo_note_hook) in the simulator.

A MIDI note is shifted +12 by the pointer hooks and +7 by the bl hooks once
patch_init has armed them: note 57 (A3) sounds as 76 (E5), at the pitch stock
writes for note 76, and its note-off ends it, in poly and in mono.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import patch  # noqa: E402
import patch_build  # noqa: E402
from test_peak_sim import PATCHES, _boot, _gated, _last_pitch, _send, _stock  # noqa: E402

DEMO = ROOT / "patches" / "peak_demo_note_hook" / "patch.py"
VOICE_MODE = PATCHES + 0x22      # note_off: <= 2 mono, else poly (0x0800F4CC)

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    _stock()
    if not patch_build.available():
        pytest.skip("arm-none-eabi-gcc not installed")
    built = patch.build_image(DEMO, build_dir=tmp_path_factory.mktemp("peak-demo"))
    return built.patched, built.blob


@pytest.fixture(scope="module")
def stock_pitch():
    """Pitch word stock writes for a gated voice playing each note."""
    b = _boot(_stock())
    out = {}
    for note in (57, 76):
        b.fpga.reset()
        _send(b, 0x90, note, 100, ms=40)
        (v,) = _gated(b)
        out[note] = _last_pitch(b)[v]
        _send(b, 0x80, note, 0, ms=40)
    return out


def _play(b, note):
    b.fpga.reset()
    _send(b, 0x90, note, 100, ms=40)
    gated = _gated(b)
    assert len(gated) == 1, gated
    return _last_pitch(b)[gated[0]]


def test_boot_screen_mark(demo):
    image, _ = demo
    assert b"DEMO Ver " in image and b"DEMOVer\x00" in image


def test_poly_note_sounds_19_up_and_ends(demo, stock_pitch):
    image, blob = demo
    b = _boot(image)
    assert b.u8(VOICE_MODE) > 2                       # the Init Patch is poly
    assert _play(b, 57) == stock_pitch[76]
    assert b.u8(blob.address("demo_last_note")) == 76
    _send(b, 0x80, 57, 0, ms=40)
    assert _gated(b) == []
    _play(b, 57)
    _send(b, 0x90, 57, 0, ms=40)                     # note-on velocity 0 ends it too
    assert _gated(b) == []


def test_mono_retrigger_and_release_stay_paired(demo, stock_pitch):
    image, _ = demo
    b = _boot(image)
    b.uc.mem_write(VOICE_MODE, b"\x00")
    _send(b, 0x90, 57, 100, 0x90, 50, 100, ms=60)      # hold A3, then D3 on top
    _send(b, 0x80, 50, 0, ms=60)                       # back to the held A3
    gated = _gated(b)
    assert len(gated) == 1
    assert _last_pitch(b)[gated[0]] == stock_pitch[76]
    _send(b, 0x80, 57, 0, ms=60)
    assert _gated(b) == []


def test_unarmed_plays_as_stock(demo, stock_pitch):
    image, blob = demo
    b = _boot(image)
    b.uc.mem_write(blob.address("demo_magic"), bytes(4))
    assert _play(b, 57) == stock_pitch[57]
    _send(b, 0x80, 57, 0, ms=40)
    assert _gated(b) == []
    assert b.u32(blob.address("demo_note_on_calls")) == 1
