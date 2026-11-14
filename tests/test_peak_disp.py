"""Peak knob display (patches/peak_mpe/disp.c) in the simulator: ms and Hz
units, value bars and the pickup arrow.

The simulator does not model the pots, so a test does what knob_poll does: it
calls knob_overlay (stock) or disp_knob_overlay (patched) with the knob's
(id, previous, current, saved, hires) and reads the LCD model's DDRAM codes
and custom-character bitmaps. Each boot takes about 25 s of wall time, so
these are marked slow.
"""
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
PATCHES, GLOBALS = 0x20012340, 0x20014494
PICKUP_STATE, MSG_STATE = 0x20014054, 0x20011208
OVERLAY_STATE = 0x200111E4
KNOB_OVERLAY, LCD_WRITE_CMD, LCD_WRITE_DATA, LCD_CURSOR = 0x08016B14, 0x08016840, 0x08016868, 0x080168B4
G_PICKUP = 0x0C
AMP_ATTACK, AMP_DECAY, AMP_RELEASE, HOLD, FILT_FREQ, RESONANCE, PAN = 146, 147, 149, 152, 131, 130, 142
FULL, L1, L2, ARROW_R, ARROW_L = 5, 1, 2, ord(">"), ord("<")

pytestmark = pytest.mark.slow


def _stock():
    image = load_image(PEAK)
    if image is None:
        pytest.skip(f"firmware/{PEAK} not present")
    return image


def _boot(image):
    from emu.board import Board
    b = Board(image)
    b.power_on(max_ms=20000)
    b.run_ms(50)
    return b


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    _stock()
    if not patch_build.available():
        pytest.skip("arm-none-eabi-gcc not installed")
    return patch.build_image(PEAK_MPE, build_dir=tmp_path_factory.mktemp("peak-disp"))


@pytest.fixture(scope="module")
def board(built):
    return _boot(built.patched)


@pytest.fixture(scope="module")
def stock():
    return _boot(_stock())


def _call(b, addr, *args):
    sp = b.initial_sp
    b.initial_sp = 0x2002C000
    try:
        return b.call(addr | 1, *args)
    finally:
        b.initial_sp = sp


def _overlay(b, addr, pid, prev, cur, saved, hires=0, pickup=None, patch_value=None):
    """One knob event as knob_poll makes it. Returns (applied, rows) with rows
    as lists of DDRAM codes."""
    b.uc.mem_write(GLOBALS + G_PICKUP, bytes([1 if pickup is not None else 0]))
    if pickup is not None:
        b.uc.mem_write(PICKUP_STATE + pid, bytes([pickup]))
    if patch_value is not None:
        b.uc.mem_write(PATCHES + pid, bytes([patch_value >> 1 if hires else patch_value]))
    # The overlay is already up for this knob (message 2, countdown running),
    # so knob_overlay redraws in place and doesn't clear the display (stock's
    # clear waits for a timer tick that doesn't run inside a called function).
    b.uc.mem_write(MSG_STATE + 2, bytes([5, 2]))
    b.uc.mem_write(OVERLAY_STATE + 4, pid.to_bytes(2, "little"))
    for row in range(4):
        _call(b, LCD_CURSOR, 0, row)
        for _ in range(20):
            _call(b, LCD_WRITE_DATA, 0x20)
    applied = _call(b, addr, pid, prev, cur, saved, hires)
    return applied, [list(r) for r in b.display.lcd.codes()]


def _s(row):
    return "".join(chr(c) if 0x20 <= c < 0x7F else "." for c in row)


def _patched(b, built, *a, **k):
    return _overlay(b, built.blob.address("disp_knob_overlay"), *a, **k)


def test_stock_overlay_layout(stock):
    applied, rows = _overlay(stock, KNOB_OVERLAY, AMP_ATTACK, 63, 64, 80)
    assert applied == 1
    assert _s(rows[0]).startswith("AmpAttack")
    assert _s(rows[1]).startswith("  current ") and _s(rows[1])[10:].strip() == "64"
    assert _s(rows[2]).startswith("saved val ") and _s(rows[2])[10:].strip() == "80"


def test_no_stock_pickup_flash(built, board):
    # stock's "pickup" label never reaches the display, not even for an instant
    lcd = board.display.lcd
    seen = []
    orig = lcd.data
    lcd.data = lambda d: (seen.append(d), orig(d))[1]
    try:
        _patched(board, built, AMP_ATTACK, 59, 60, 80, pickup=3, patch_value=100)
    finally:
        lcd.data = orig
    assert b"pickup" not in bytes(seen)


def test_stock_pickup_row(stock):
    applied, rows = _overlay(stock, KNOB_OVERLAY, AMP_ATTACK, 59, 60, 80, pickup=3, patch_value=100)
    assert applied == 0
    assert "pickup" in _s(rows[3]) and _s(rows[3])[10:].strip() == "60"
    assert _s(rows[1])[10:].strip() == "100"            # "current" is the patch's value


@pytest.mark.parametrize("pid,cur,saved,now,was", [
    (AMP_ATTACK, 64, 80, "519ms", "1.36s"),
    (AMP_ATTACK, 127, 100, "17.9s", "4.26s"),
    (AMP_ATTACK, 5, 24, "<35ms", "35ms"),
    (AMP_DECAY, 100, 64, "4.91s", "601ms"),
    (AMP_RELEASE, 12, 127, "10ms", "20.6s"),
    (HOLD, 127, 0, "673ms", "0ms"),
    (158, 100, 100, "4.91s", "4.91s"),          # Mod Env 1 release: same curve (inferred)
])
def test_envelope_times_in_ms(built, board, pid, cur, saved, now, was):
    applied, rows = _patched(board, built, pid, cur - 1, cur, saved)
    assert applied == 1
    assert _s(rows[1]).startswith("  current " + now), _s(rows[1])
    assert _s(rows[2]).startswith("saved val " + was), _s(rows[2])


def test_filter_cutoff_matches_measured_points(built, board):
    # docs/peak-units.md, filter table: CC 64 = 672.0 Hz, CC 100 = 5322.2 Hz,
    # CC 127 = 23718.2 Hz; the knob value is 2 x CC
    for cc, hz in ((64, 672), (100, 5322), (127, 23718)):
        _a, rows = _patched(board, built, FILT_FREQ, 0, cc * 2, 0, hires=1)
        t = _s(rows[1])[10:].strip()
        val = float(t.replace("kHz", "").replace("Hz", "")) * (1000 if "k" in t else 1)
        assert abs(val - hz) / hz < 0.02, (cc, t)


def test_filter_floor(built, board):
    _a, rows = _patched(board, built, FILT_FREQ, 0, 0, 23, hires=1)
    assert _s(rows[1])[10:].strip() == "<33Hz"
    assert _s(rows[2])[10:].strip() == "<33Hz"
    _a, rows = _patched(board, built, FILT_FREQ, 23, 24, 25, hires=1)   # CC 12, the first measured point
    assert _s(rows[1])[10:].strip() == "33Hz"


def test_other_parameters_print_as_stock(built, board, stock):
    _a, sr = _overlay(stock, KNOB_OVERLAY, RESONANCE, 76, 77, 20)
    _a, pr = _patched(board, built, RESONANCE, 76, 77, 20)
    assert pr[:3] == sr[:3]


def test_unipolar_bar(built, board):
    _a, rows = _patched(board, built, AMP_ATTACK, 126, 127, 0)
    assert rows[3] == [FULL] * 20
    _a, rows = _patched(board, built, AMP_ATTACK, 1, 0, 0)
    assert rows[3] == [0x20] * 20
    _a, rows = _patched(board, built, AMP_ATTACK, 63, 64, 0)       # 64/127 = 50 px: 10 cells
    assert rows[3] == [FULL] * 10 + [0x20] * 10


def test_bipolar_bar_from_the_centre(built, board):
    _a, rows = _patched(board, built, PAN, 62, 64, 64)             # centre: nothing drawn
    assert rows[3] == [0x20] * 20
    _a, rows = _patched(board, built, PAN, 126, 127, 64)
    assert rows[3] == [0x20] * 10 + [FULL] * 10
    _a, rows = _patched(board, built, PAN, 1, 0, 64)
    assert rows[3] == [FULL] * 10 + [0x20] * 10


def test_pickup_arrow_rides_the_bar(built, board):
    # patch value 100, Pickup on, the knob at 60 (60/127 = 47 px: cell 9)
    applied, rows = _patched(board, built, AMP_ATTACK, 59, 60, 80, pickup=3, patch_value=100)
    assert applied == 0
    r = rows[3]
    assert "pickup" not in _s(r)
    assert r == [FULL] * 9 + [ARROW_R] + [0x20] * 10, r
    # "current" follows the knob while pickup holds it back (60 = 406 ms), not the patch's 4.26 s
    assert _s(rows[1])[10:].strip() == "406ms"
    # the arrow moves right with the knob (95/127 = 74 px: cell 14)
    _a, rows = _patched(board, built, AMP_ATTACK, 90, 95, 80, pickup=3, patch_value=100)
    assert rows[3] == [FULL] * 14 + [ARROW_R] + [0x20] * 5
    # above the value: the arrow points down/left, at the bar's end (120: 94 px, cell 18)
    _a, rows = _patched(board, built, AMP_ATTACK, 119, 120, 80, pickup=3, patch_value=100)
    assert rows[3] == [FULL] * 18 + [ARROW_L] + [0x20]
    # the knob at the very top: the arrow sits in the last cell
    _a, rows = _patched(board, built, AMP_ATTACK, 126, 127, 80, pickup=3, patch_value=100)
    assert rows[3] == [FULL] * 19 + [ARROW_L]


def test_pickup_arrow_on_a_bipolar_bar(built, board):
    # Pan: knob at 100 (79 px), patch value 120: the bar runs from the centre to the arrow
    _a, rows = _patched(board, built, PAN, 99, 100, 64, pickup=3, patch_value=120)
    assert rows[3] == [0x20] * 10 + [FULL] * 5 + [ARROW_R] + [0x20] * 4


def test_pickup_completes_and_the_bar_returns(built, board):
    _a, rows = _patched(board, built, AMP_ATTACK, 98, 99, 80, pickup=3, patch_value=100)
    assert ARROW_R in rows[3]
    state = board.u8(PICKUP_STATE + AMP_ATTACK)
    assert state != 0
    applied, rows = _patched(board, built, AMP_ATTACK, 99, 101, 80, pickup=state)
    assert applied == 1 and board.u8(PICKUP_STATE + AMP_ATTACK) == 0
    assert ARROW_R not in rows[3] and ARROW_L not in rows[3]
    assert rows[3].count(FULL) == 15                       # 101/127 -> 79 px: 15 full cells and 4 px (a bar, no arrow)


def test_pickup_off_is_just_the_bar(built, board):
    applied, rows = _patched(board, built, AMP_ATTACK, 59, 60, 80)
    assert applied == 1 and rows[3][0] == FULL


def _glyphs(b):
    return [tuple(b.display.lcd.glyph(c)) for c in range(8)]


def test_custom_characters_are_restored(built, board, stock):
    stock_set = _glyphs(stock)
    _a, _r = _patched(board, built, AMP_ATTACK, 63, 64, 0)
    ours = _glyphs(board)
    assert ours[FULL] == (0, 31, 31, 31, 31, 31, 31, 0)
    assert ours[L1] == (0, 16, 16, 16, 16, 16, 16, 0)
    assert ours[0] == stock_set[0]                     # code 0 is never used by the bars
    board.uc.mem_write(MSG_STATE + 2, b"\x00")           # the message time has run out
    board.run_ms(30)
    assert _glyphs(board) == stock_set


def test_overlay_cost(built, board, stock):
    """LCD data writes of one event (each is 3 SPI frames, about 50 us): stock
    vs patched. _overlay blanks the screen first with 80 writes, not counted."""
    blank = 80
    stock.display.lcd.writes = 0
    _overlay(stock, KNOB_OVERLAY, AMP_ATTACK, 63, 64, 80)
    base = stock.display.lcd.writes - blank
    board.display.lcd.writes = 0
    _patched(board, built, AMP_ATTACK, 63, 64, 80)
    first = board.display.lcd.writes - blank
    board.display.lcd.writes = 0
    _patched(board, built, AMP_ATTACK, 64, 65, 80)       # glyphs loaded: only the text and the bar
    second = board.display.lcd.writes - blank
    print(f"LCD data writes per event: stock {base}, patched first {first}, then {second}")
    assert second <= base + 40
    assert first <= second + 7 * 8
