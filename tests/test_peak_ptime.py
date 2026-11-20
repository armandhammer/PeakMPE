"""Peak: patch change timed to the clock (Settings > PATCH TIMING; patches/peak_mpe/ptime.c).

The clock goes in over DIN like a DAW's: Start or Song Position Pointer and
Continue, then clock bytes (here 2 ms apart, well inside the 100 ms that
count as playing). A patch is loaded when patch_select +5 (the loaded
number) changes; patch_select_load sets it.
"""
import pytest

from test_peak_sim import _boot, _call, _send, _show, mpe_built  # noqa: F401

pytestmark = pytest.mark.slow

GLOBALS, G_PTIME, G_BANK_PATCH = 0x20014494, 0x4F, 0x15
PATCH_SELECT = 0x20002D14            # +4 bank, +5 number of the loaded patch
PTIME_PAGE = 17                      # Settings: after PATCH DUMP
NOW, BEAT, BAR = 0, 1, 2
START, CONTINUE, STOP, CLOCK, SPP = 0xFA, 0xFB, 0xFC, 0xF8, 0xF2


@pytest.fixture
def board(mpe_built):
    b = _boot(mpe_built.patched)
    b.run_ms(300)
    b.uc.mem_write(GLOBALS + G_BANK_PATCH, bytes([3]))   # Bank/Patch Rec+Tran (the simulator boots with 0)
    return b


def _timing(b, v):
    b.uc.mem_write(GLOBALS + G_PTIME, bytes([v]))


def _loaded(b):
    return b.u8(PATCH_SELECT + 5)


def _clocks(b, n, ms=2):
    for _ in range(n):
        _send(b, CLOCK, ms=ms)


def _clocks_until_loaded(b, want, limit):
    for n in range(1, limit + 1):
        _send(b, CLOCK, ms=2)
        if _loaded(b) == want:
            return n
    return None


def test_the_settings_page(board, mpe_built):
    b = board
    rows = _show(b, 8, PTIME_PAGE, 0)
    assert rows[0].startswith("PATCH TIMING"), rows
    assert rows[1][:19].split() == ["Change", "at", "Now"], rows
    _call(b, mpe_built.blob.address("mpe_ui_value_change"), 2)
    assert b.u8(GLOBALS + G_PTIME) == BAR
    assert _show(b, 8, PTIME_PAGE, 0)[1][:19].split() == ["Change", "at", "Bar"]
    _call(b, mpe_built.blob.address("mpe_ui_value_change"), 9)
    assert _show(b, 8, PTIME_PAGE, 0)[1][:19].split() == ["Change", "at", "4", "Bars"]


def test_a_program_change_waits_for_the_next_bar(board):
    b = board
    _timing(b, BAR)
    _send(b, START, ms=2)
    _clocks(b, 10)                                   # positions 0-9
    _send(b, 0xC0, 5, ms=5)
    assert _loaded(b) != 5                           # waiting
    rows = b.display.lcd.text()
    assert rows[0].startswith("PATCH TIMING") and rows[2].startswith("at the next bar"), rows
    n = _clocks_until_loaded(b, 5, 200)
    assert n == 96 - 10 + 1                          # positions 10..96: on the clock byte of position 96, bar 2's one


def test_beat_and_a_song_position(board):
    b = board
    _timing(b, BEAT)
    _send(b, SPP, 3, 0, ms=2)                        # the 4th 16th: position 18
    _send(b, CONTINUE, ms=2)
    _clocks(b, 2)                                    # positions 18, 19
    _send(b, 0xC0, 6, ms=5)
    assert _loaded(b) != 6
    assert _clocks_until_loaded(b, 6, 50) == 24 - 19  # the next beat: position 24


def test_now_and_no_clock_load_at_once(board):
    b = board
    _timing(b, NOW)
    _send(b, START, ms=2)
    _clocks(b, 5)
    _send(b, 0xC0, 7, ms=20)
    assert _loaded(b) == 7                           # Now: at once, clock or not
    _timing(b, BAR)
    _send(b, STOP, ms=2)
    _send(b, 0xC0, 8, ms=20)
    assert _loaded(b) == 8                           # Bar, but no clock plays: at once


def test_stop_or_a_lost_clock_loads_a_waiting_change(board):
    b = board
    _timing(b, BAR)
    _send(b, START, ms=2)
    _clocks(b, 3)
    _send(b, 0xC0, 9, ms=5)
    assert _loaded(b) != 9
    _send(b, STOP, ms=5)
    assert _loaded(b) == 9                           # Stop: now
    _send(b, START, ms=2)
    _clocks(b, 3)
    _send(b, 0xC0, 10, ms=5)
    assert _loaded(b) != 10
    b.run_ms(150)                                    # the clock just stops coming
    assert _loaded(b) == 10


def test_a_later_change_replaces_the_waiting_one(board):
    b = board
    _timing(b, BAR)
    _send(b, START, ms=2)
    _clocks(b, 3)
    _send(b, 0xC0, 11, ms=5)
    _send(b, 0xC0, 12, ms=5)
    assert _clocks_until_loaded(b, 12, 200) == 96 - 3 + 1   # positions 3..96; 11 never loads
