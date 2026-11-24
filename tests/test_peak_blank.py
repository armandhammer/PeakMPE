"""Peak: a blank settings chip (DataFlash all 0xFF), roadmap step 3.

The simulator normally seeds a blank DataFlash with the Init Patch and
neutral globals (Board._seed_dataflash). These tests switch that off.

- Stock's settings_load (0x0801AFD8) copies the 0x200 stored bytes into the
  globals and hands globals+6 to the patch loader (0x0801AF78), which does
  nothing for 0xFFFF (bit 15 set): it reads no index from the blank bytes.
  Only +0x1E/+0x1F are forced to 1.
- The patch's stored settings (globals 0x30-0x38, 0x3E-0x40, 0x45-0x4A)
  read 0xFF there, as on any unit whose bytes were never written; every
  reader falls back to its default (mpe.h), so the pages show the defaults
  and the features run as Off.
"""
import re

import pytest

from test_peak_sim import GLOBALS, PATCHES, _send, _show, _stock, mpe_built  # noqa: F401

pytestmark = pytest.mark.slow

STORED = list(range(0x30, 0x39)) + [0x3E, 0x3F, 0x40] + list(range(0x45, 0x4B))
MPE_PAGE_AT = 4                       # Settings index of the first MPE page
DEFAULTS = {                          # page offset: (title, value per item row)
    0: ("MPE", ["Off", "15"]),
    1: ("MPE BEND RANGE", ["48", "2"]),
    2: ("MPE EXTRAS", ["Squared", "Off", "Stock"]),
    3: ("PARAM LOCK", ["Off", "Off", "Off"]),
    6: ("MOTION", ["1 bar"]),
    7: ("MORPH", ["Off"]),
    8: ("ARP EUCLID", ["Off", "16", "0"]),
    9: ("ARP RATCHET", ["Off", "1"]),
    10: ("RELEASE VEL", ["Off"]),
}


def _blank_boot(image):
    from emu.board import Board
    b = Board(image)
    b._seed_dataflash = lambda: None    # leave the chip blank
    b.power_on(max_ms=20000)
    return b


def _value(row, value):
    return re.search(r"\s" + re.escape(value) + r"\W*$", row.rstrip()) is not None


def test_blank_chip_settings_load_reads_no_index():
    b = _blank_boot(_stock())
    g = bytes(b.uc.mem_read(GLOBALS, 0x200))
    assert g[0x1E] == 1 and g[0x1F] == 1
    assert g[:0x1E] == b"\xff" * 0x1E and g[0x20:] == b"\xff" * 0x1E0
    assert bytes(b.uc.mem_read(PATCHES, 0x10)) == b"\xff" * 0x10   # no patch loaded either


def test_blank_chip_mpe_pages_show_the_defaults(mpe_built):
    b = _blank_boot(mpe_built.patched)
    assert all(b.u8(GLOBALS + o) == 0xFF for o in STORED)
    for k, (title, values) in DEFAULTS.items():
        rows = _show(b, 8, MPE_PAGE_AT + k, 0)
        assert rows[0].startswith(title + " "), rows
        for row, value in zip(rows[1:], values):
            assert _value(row, value), (title, value, rows)


def test_stored_settings_at_0xff_run_as_off(mpe_built):
    """A seeded chip whose MPE bytes were never written: notes play and
    release as stock, the ticks that read the settings run."""
    from test_peak_sim import _boot
    b = _boot(mpe_built.patched)
    for o in STORED:
        b.uc.mem_write(GLOBALS + o, b"\xff")
    _send(b, 0x90, 60, 100, ms=40)
    on = {e.target for e in b.fpga.events if not e.read and e.target < 8 and e.param == 0x3F}
    assert len(on) == 1, on             # the amp envelope of one voice started
    b.fpga.reset()
    _send(b, 0xD0, 90, 0xB0, 1, 100, 0xB0, 2, 100, 0xE0, 0, 0x60, ms=300)   # pressure, wheel, breath, bend
    assert [e for e in b.fpga.events if not e.read and e.target == 0x1A and e.param == 0x63]  # BrthPED2 still broadcast
    b.fpga.reset()
    _send(b, 0x80, 60, 30, ms=40)
    off = {e.target for e in b.fpga.events if not e.read and e.target < 8 and e.param == 0x3F and e.value & 3 == 3}
    assert off == on
