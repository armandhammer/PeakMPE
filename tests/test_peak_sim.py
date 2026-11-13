"""Peak 2.2 (build 2108) in the simulator: stock boot and the first MPE checks.

The board runs the Peak image with emu/target.py's Peak table: one FPGA
engine on PB6, the OLED's chip select on PB12, and a seeded DataFlash (the
Peak application has no factory initialise; see Board._seed_dataflash).
Each boot takes about 25 s of wall time, so these are marked slow.
"""
import collections
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import patch  # noqa: E402
import patch_build  # noqa: E402
from emu.firmware import load_image  # noqa: E402

PEAK = "peak-firmware-2.2-build2108.syx"
PEAK_MPE = ROOT / "patches" / "peak_mpe" / "patch.py"
PATCHES, FLAG = 0x20012340, 0x1A2

pytestmark = pytest.mark.slow


def _stock():
    image = load_image(PEAK)
    if image is None:
        pytest.skip(f"firmware/{PEAK} not present")
    return image


@pytest.fixture(scope="module")
def mpe_image(tmp_path_factory):
    _stock()
    if not patch_build.available():
        pytest.skip("arm-none-eabi-gcc not installed")
    return patch.build_image(PEAK_MPE, build_dir=tmp_path_factory.mktemp("peak-mpe")).patched


def _boot(image):
    from emu.board import Board
    b = Board(image)
    b.power_on(max_ms=20000)
    b.run_ms(50)
    b.fpga.reset()
    return b


def _send(b, *data, ms=20):
    for x in data:
        b.din.rx_queue.append((b.time_us, x))
    b.run_ms(ms)


def _writes(b):
    return collections.Counter((e.target, e.param) for e in b.fpga.events if not e.read)


def _last_pitch(b):
    out = {}
    for e in b.fpga.events:
        if not e.read and e.target < 8 and e.param == 0x000:
            out[e.target] = e.value
    return out


@pytest.fixture(scope="module")
def stock_board():
    return _boot(_stock())


def test_stock_boots_to_the_patch_page(stock_board):
    assert stock_board.display.lcd.text()[0].startswith("Init Patch")
    assert not stock_board.fpga.malformed


def test_stock_note_reaches_the_fpga(stock_board):
    stock_board.fpga.reset()
    _send(stock_board, 0x90, 60, 100)
    voices = {e.target for e in stock_board.fpga.events if not e.read and e.target < 8}
    assert voices == set(range(8))
    _send(stock_board, 0x80, 60, 0)


def test_mpe_off_writes_as_stock(mpe_image):
    s, m = _boot(_stock()), _boot(mpe_image)
    for b in (s, m):
        _send(b, 0x90, 60, 100)
        _send(b, 0x80, 60, 0)
    ws, wm = _writes(s), _writes(m)
    assert set(ws) == set(wm)
    assert abs(sum(ws.values()) - sum(wm.values())) <= sum(ws.values()) * 0.02


def test_mpe_member_bend_moves_one_voice(mpe_image):
    b = _boot(mpe_image)
    b.uc.mem_write(PATCHES + FLAG, b"\x01")
    _send(b, 0x91, 60, 100, 0x92, 67, 100, ms=40)  # member channels 2 and 3
    before = _last_pitch(b)
    b.fpga.reset()
    _send(b, 0xE1, 0x00, 0x60, ms=60)                # channel 2: bend +4096 of 8192
    after = _last_pitch(b)
    moved = {v: after[v] - before[v] for v in after if v in before and after[v] != before[v]}
    assert len(moved) == 1
    assert list(moved.values())[0] == 8192           # +24 semitones at the default range 48


# --- Expression and UI with MPE on (one board, steps in order) --------------

VOICE_STATE = 0x20004650
GATE = VOICE_STATE + 0x1F4
MENUS = 0x20002E90
UI_STATE = 0x20011200
UI_DRAW_PAGE = 0x08017F14
UI_DRAW_VALUES = 0x08018070
LCD_WRITE_CMD = 0x08016840


@pytest.fixture(scope="module")
def mpe_built(tmp_path_factory):
    _stock()
    if not patch_build.available():
        pytest.skip("arm-none-eabi-gcc not installed")
    return patch.build_image(PEAK_MPE, build_dir=tmp_path_factory.mktemp("peak-mpe-ui"))


@pytest.fixture(scope="module")
def mpe_on(mpe_built):
    """MPE on, notes held on member channels 2 and 3 (note 60 on both)."""
    b = _boot(mpe_built.patched)
    b.uc.mem_write(PATCHES + FLAG, b"\x01")
    _send(b, 0x91, 60, 100, 0x92, 60, 100, ms=40)
    return b, mpe_built.blob


def _voice_of(b, blob, ch):
    chans = bytes(b.uc.mem_read(blob.address("voice_channel"), 8))
    voices = [v for v in range(8) if chans[v] == ch]
    assert len(voices) == 1, chans
    return voices[0]


def _last(b, param):
    out = {}
    for e in b.fpga.events:
        if not e.read and e.target < 8 and e.param == param:
            out[e.target] = e.value
    return out


def test_mpe_binds_one_voice_per_channel(mpe_on):
    b, blob = mpe_on
    assert _voice_of(b, blob, 1) != _voice_of(b, blob, 2)


def test_mpe_member_pressure_reaches_only_its_voice(mpe_on):
    b, blob = mpe_on
    v2, v3 = _voice_of(b, blob, 1), _voice_of(b, blob, 2)
    b.fpga.reset()
    _send(b, 0xD1, 100, ms=80)          # channel 2 pressure; 0x61 is round-robin, 8 ms per voice
    at = _last(b, 0x61)
    assert at.get(v2, 0) > 0x1000
    assert at.get(v3, 0) == 0
    _send(b, 0xD1, 0, ms=80)


def test_mpe_member_slide_reaches_only_its_voice(mpe_on):
    b, blob = mpe_on
    v2, v3 = _voice_of(b, blob, 1), _voice_of(b, blob, 2)
    b.fpga.reset()
    _send(b, 0xB1, 74, 127, ms=60)      # channel 2 CC 74 full
    wheel = _last(b, 0x60)
    assert wheel.get(v2) == 0x7FFF
    assert wheel.get(v3, 0) == 0
    broadcast = [e for e in b.fpga.events if not e.read and e.target == 0x1A and e.param == 0x60]
    assert not broadcast                 # the stock broadcast 0x60 is dropped while MPE is on
    _send(b, 0xB1, 74, 0, ms=60)


def test_mpe_note_off_releases_only_its_channel(mpe_on):
    b, blob = mpe_on
    v2, v3 = _voice_of(b, blob, 1), _voice_of(b, blob, 2)
    _send(b, 0x81, 60, 0, ms=20)        # note 60 off on channel 2 only
    assert b.u8(GATE + v2) == 0
    assert b.u8(GATE + v3) != 0
    _send(b, 0x82, 60, 0, ms=20)


def _call(b, addr, *args):
    """Call a firmware or patch function on a running board, on a stack below
    the main loop's (which sits at the top of RAM)."""
    sp = b.initial_sp
    b.initial_sp = 0x2002C000
    try:
        return b.call(addr | 1, *args)
    finally:
        b.initial_sp = sp


def _show(b, mode, page, item):
    """Select UI mode, page and item as the panel would, and draw the page."""
    b.uc.mem_write(UI_STATE, bytes([mode]))
    menu = int.from_bytes(b.uc.mem_read(MENUS + 4 * mode, 4), "little")
    b.uc.mem_write(menu, bytes([page]))
    rec = int.from_bytes(b.uc.mem_read(menu + 4 + 4 * page, 4), "little")
    b.uc.mem_write(rec + 5, bytes([item]))
    _call(b, LCD_WRITE_CMD, 0x01)                 # clear the display, as a page change does
    _call(b, UI_DRAW_PAGE)
    _call(b, UI_DRAW_VALUES)
    return b.display.lcd.text()


def test_voice_page_item_switches_the_flag(mpe_built):
    b = _boot(mpe_built.patched)
    rows = _show(b, 6, 0, 2)                      # VOICE page 1, item 3
    assert any(r.startswith("MPE") and "Off" in r for r in rows), rows
    _call(b, mpe_built.blob.address("mpe_ui_value_change"), 1)
    assert b.u8(PATCHES + FLAG) == 1
    rows = _show(b, 6, 0, 2)
    assert any(r.startswith("MPE") and "On" in r for r in rows), rows


def test_settings_has_the_mpe_pages(mpe_built):
    b = _boot(mpe_built.patched)
    rows = _show(b, 8, 4, 0)                      # Settings page 5: MPE
    text = "\n".join(rows)
    assert rows[0].startswith("MPE"), rows
    assert "Zone" in text and "Off" in text and "Members" in text and "15" in text, rows
    rows = _show(b, 8, 5, 0)                      # page 6: MPE BEND RANGE
    text = "\n".join(rows)
    assert rows[0].startswith("MPE BEND RANGE"), rows
    assert "Note Bend" in text and "48" in text and "MasterBend" in text, rows
    rows = _show(b, 8, 3, 0)                      # page 4: stock MIDI CONTROL, unchanged
    assert rows[0].startswith("MIDI CONTROL"), rows


# --- LinnStrument cases ------------------------------------------------------

DIN_RING = 0x20003EAC            # usart6_irq 0x0800EDD8: +0 head, +1 tail, +0x104 data, +0x204 overflows
RELEASE_MS = 300


def _rpn(b, ch, lsb, value):
    _send(b, 0xB0 | ch, 101, 0, 0xB0 | ch, 100, lsb, 0xB0 | ch, 6, value, ms=10)


def _zones(b, blob):
    raw = bytes(b.uc.mem_read(blob.address("mpe_zones"), 8))
    return [tuple(raw[0:4]), tuple(raw[4:8])]


def _gated(b):
    return [v for v in range(8) if b.u8(GATE + v)]


def _bindings_ok(b, blob):
    chans = bytes(b.uc.mem_read(blob.address("voice_channel"), 8))
    held = [chans[v] for v in _gated(b)]
    return len(held) == len(set(held)) and 0xFF not in held


@pytest.fixture(scope="module")
def two_zones(mpe_built):
    """MPE on; RPN 6 from both masters as a LinnStrument with both splits in MPE."""
    b = _boot(mpe_built.patched)
    b.uc.mem_write(PATCHES + FLAG, b"\x01")
    _rpn(b, 0, 6, 7)    # Lower Zone: master 1, members 2-8
    _rpn(b, 15, 6, 7)   # Upper Zone: master 16, members 9-15
    return b, mpe_built.blob


def test_two_zones_from_rpn6(two_zones):
    b, blob = two_zones
    assert _zones(b, blob) == [(0, 0, 1, 7), (0, 15, 8, 14)]


def test_two_zones_each_bend_their_own_note(two_zones):
    b, blob = two_zones
    _send(b, 0x91, 60, 100, 0x9E, 67, 100, ms=40)   # channel 2 (Lower) and channel 15 (Upper)
    lo, up = _voice_of(b, blob, 1), _voice_of(b, blob, 14)
    before = _last_pitch(b)
    b.fpga.reset()
    _send(b, 0xEE, 0x00, 0x60, ms=60)                # channel 15: half up
    after = _last_pitch(b)
    assert after[up] - before[up] == 8192
    assert after[lo] == before[lo]


def test_poly_pressure_on_a_member_channel(two_zones):
    b, blob = two_zones
    lo, up = _voice_of(b, blob, 1), _voice_of(b, blob, 14)
    b.fpga.reset()
    _send(b, 0xA1, 60, 100, ms=80)                   # poly pressure, channel 2
    at = _last(b, 0x61)
    assert at.get(lo, 0) > 0x1000
    assert at.get(up, 0) == 0
    _send(b, 0xA1, 60, 0, ms=80)


def test_rpn0_sets_the_note_bend_range(two_zones):
    b, blob = two_zones
    lo = _voice_of(b, blob, 1)
    _rpn(b, 1, 0, 24)                                # RPN 0 on a Lower member channel: +-24
    before = _last_pitch(b)
    b.fpga.reset()
    _send(b, 0xE1, 0x00, 0x60, ms=60)                # half up: now 12 semitones
    assert _last_pitch(b)[lo] - before[lo] == 4096
    _send(b, 0xE1, 0x00, 0x40, 0x81, 60, 0, 0x8E, 67, 0, ms=RELEASE_MS)
    assert not _gated(b)


def test_fifteen_channels_share_eight_voices(mpe_built):
    b = _boot(mpe_built.patched)
    b.uc.mem_write(PATCHES + FLAG, b"\x01")          # no RPN 6: Lower Zone, 15 members
    blob = mpe_built.blob
    for ch in range(1, 13):                           # 12 held notes on channels 2-13
        _send(b, 0x90 | ch, 48 + ch, 100, ms=5)
    assert len(_gated(b)) == 8 and _bindings_ok(b, blob)
    for ch in range(1, 13):
        _send(b, 0x80 | ch, 48 + ch, 0, ms=2)
    b.run_ms(RELEASE_MS)
    assert not _gated(b)
    # A LinnStrument-like run: channels 2-16 in turn, three notes overlapping.
    for k in range(60):
        ch = 1 + k % 15
        _send(b, 0x90 | ch, 40 + k % 40, 90, ms=4)
        if k >= 3:
            pc = 1 + (k - 3) % 15
            _send(b, 0x80 | pc, 40 + (k - 3) % 40, 0, ms=4)
        assert _bindings_ok(b, blob), k
    for k in range(57, 60):
        _send(b, 0x80 | (1 + k % 15), 40 + k % 40, 0, ms=4)
    b.run_ms(RELEASE_MS)
    assert not _gated(b)


def test_dense_din_stream_loses_nothing(mpe_built):
    """Eight held notes with bend, pressure and Slide on every channel every
    10 ms for 1 s: more than DIN carries, so the bytes arrive back to back at
    the line rate. The firmware's DIN ring must not overflow and every note
    must end."""
    b = _boot(mpe_built.patched)
    b.uc.mem_write(PATCHES + FLAG, b"\x01")
    blob = mpe_built.blob
    data = []
    for ch in range(1, 9):
        data += [0x90 | ch, 50 + ch, 100]
    for t in range(100):
        for ch in range(1, 9):
            bend = 8192 + (t * 37 + ch * 500) % 4000 - 2000
            data += [0xE0 | ch, bend & 0x7F, bend >> 7, 0xD0 | ch, (t + ch) % 128, 0xB0 | ch, 74, (t * 3 + ch) % 128]
    for ch in range(1, 9):
        data += [0x80 | ch, 50 + ch, 0]
    for x in data:
        b.din.rx_queue.append((b.time_us, x))
    while b.din.rx_queue:
        b.run_ms(50)
    b.run_ms(RELEASE_MS)
    assert b.u8(DIN_RING + 0x204) == 0
    assert not _gated(b)
