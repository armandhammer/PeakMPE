"""Osc Fine over MIDI (patches/peak_mpe/ccpair.c, v0.22).

Stock's setter behind a received CC holds the coarse byte of a 9-bit pair
against the pair's 9-bit range, so Osc 1/2/3 Fine (CC 15, 18, 21: coarse
byte 14-114 for -100 to +100) drops 14-27 (findings, "The parameter setter
and 9-bit controls"). The patch holds that byte against half the range and
clamps it. These tests send real CCs over DIN, through stock's cc handler,
with Settings set to receive CCs.
"""
import pytest

from test_peak_sim import PATCHES, _boot, _last_pitch, _send, _stock, mpe_image  # noqa: F401

GLOBALS, G_RX = 0x20014494, 0x14                     # cc 0x0800F124 tests globals+0x14 bit 0
PARAM_DESC = 0x200017CC                              # patch_param_desc, 12 B per patch offset
FINES = ((15, 0x33), (18, 0x48), (21, 0x5D))         # (CC, patch offset of the coarse byte)
CC_RESONANCE, RESONANCE = 79, 0x82
CC_FILT_FREQ, FILT_FREQ = 29, 0x83                   # a 9-bit pair with range 0-255

pytestmark = pytest.mark.slow


def _rx(b):
    b.uc.mem_write(GLOBALS + G_RX, bytes([b.u8(GLOBALS + G_RX) | 1]))
    return b


@pytest.fixture(scope="module")
def stock():
    return _rx(_boot(_stock()))


@pytest.fixture(scope="module")
def patched(mpe_image):
    return _rx(_boot(mpe_image))


def _sweep(b, cc, offset, start):
    """Sends CC values 0-127, each after `start`; the byte stored for each."""
    out = []
    for v in range(128):
        _send(b, 0xB0, cc, start, ms=2)
        _send(b, 0xB0, cc, v, ms=2)
        out.append(b.u8(PATCHES + offset))
    return out


def test_stock_drops_fine_14_to_27(stock):
    got = _sweep(stock, 15, 0x33, 64)
    assert got[14:28] == [64] * 14                      # -100 to -73: the value stays
    assert got[28:128] == list(range(28, 128))


@pytest.mark.parametrize("cc,offset", FINES)
def test_fine_reaches_minus_100_and_clamps(patched, cc, offset):
    got = _sweep(patched, cc, offset, 64)
    assert got[14:115] == list(range(14, 115))          # -100 to +100, as sent
    assert got[:14] == [14] * 14                        # below the range: -100
    assert got[115:] == [114] * 13                      # above it: +100


def test_other_controls_as_stock(stock, patched):
    for cc, offset in ((CC_RESONANCE, RESONANCE), (CC_FILT_FREQ, FILT_FREQ)):
        assert _sweep(patched, cc, offset, 50) == _sweep(stock, cc, offset, 50)


def test_descriptors_stay_stock(stock, patched):
    """The menu encoder (ui_value_change) and the knob's value bar read these."""
    for _, offset in FINES:
        a = bytes(stock.uc.mem_read(PARAM_DESC + 12 * offset, 4))
        assert bytes(patched.uc.mem_read(PARAM_DESC + 12 * offset, 4)) == a
        assert a[:2] == bytes([28, 228])


def test_fine_minus_100_reaches_the_sound(patched):
    b = patched
    _send(b, 0xB0, 15, 64, ms=20)
    _send(b, 0x90, 60, 100, ms=100)
    b.fpga.reset()
    _send(b, 0xB0, 15, 28, ms=100)
    at_73 = _last_pitch(b)
    b.fpga.reset()
    _send(b, 0xB0, 15, 14, ms=100)
    at_100 = _last_pitch(b)
    _send(b, 0x80, 60, 0, ms=20)
    _send(b, 0xB0, 15, 64, ms=20)
    voices = set(at_73) & set(at_100)
    assert voices
    assert all(at_100[v] < at_73[v] for v in voices)
