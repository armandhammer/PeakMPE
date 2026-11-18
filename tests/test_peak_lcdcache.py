"""The LCD cache (patches/peak_mpe/lcdcache.c): characters the display already
shows aren't sent again, and the display ends up exactly as on stock.

The same stream of characters, cursor escapes and clears goes through stock's
escape layer (lcd_putc_esc 0x0800D21C) on the stock image and on the patched
one; the display model's 128 DDRAM cells must agree after every chunk, while
the patched image sends fewer data writes.
"""
import random

import pytest

from test_peak_disp import _boot, _call, _stock, built  # noqa: F401  (fixture)

LCD_PUTC_ESC = 0x0800D21C
LCD_DISPLAY_ON, LCD_DISPLAY_OFF = 0x08016924, 0x08016950

# Codes lcd_putc writes (0xBA, 0xBB-0xBF translated), and some it ignores.
WRITTEN = [0xBA, 0xBB, 0xBF, 0, 1, 7, 0x1F] + list(range(0x20, 0x7F))
IGNORED = [0x0A, 0x80, 0xB9, 0xC0, 0xFF]


MS_COUNTER = 0x20003AD0 + 0xD2   # u16 the delay 0x0800E50C polls (literal 0x0800E524)


def _ticking(b):
    """A called function runs no interrupts, so the clear's 1 ms delay would
    wait for ever: every read of the ms counter advances it here."""
    from unicorn import UC_HOOK_MEM_READ

    def bump(uc, access, address, size, value, user):
        v = int.from_bytes(uc.mem_read(MS_COUNTER, 2), "little")
        uc.mem_write(MS_COUNTER, ((v + 1) & 0xFFFF).to_bytes(2, "little"))

    b.uc.hook_add(UC_HOOK_MEM_READ, bump, begin=MS_COUNTER, end=MS_COUNTER + 1)
    b.uc.ctl_flush_tb()            # code translated at boot doesn't report reads otherwise
    return b


@pytest.fixture(scope="module")
def pair(built):  # noqa: F811
    return _ticking(_boot(_stock())), _ticking(_boot(built.patched)), built


def _ddram(b):
    return bytes(b.display.lcd.ddram)


def _esc(b, *codes):
    for c in codes:
        _call(b, LCD_PUTC_ESC, c)


def _stream(rng, n):
    out = []
    for _ in range(n):
        r = rng.random()
        if r < 0.15:
            out += [9, rng.randrange(20), rng.randrange(4)]
        elif r < 0.17:
            out += [9, rng.randrange(20, 32), rng.randrange(4)]   # hidden columns
        elif r < 0.18:
            out.append(8)                                          # clear
        elif r < 0.20:
            out.append(rng.choice(IGNORED))
        else:
            # mostly the same few characters, so many writes repeat a cell
            out.append(rng.choice(WRITTEN[:12] if rng.random() < 0.3 else [0x20, 0x41, 0x42, 0x31]))
    return out


def test_same_display_as_stock(pair):
    stock, pat, _ = pair
    for b in (stock, pat):
        _esc(b, 8)
    rng = random.Random(23)
    sent = {"stock": 0, "patched": 0}
    for chunk in range(12):
        codes = _stream(rng, 60)
        for name, b in (("stock", stock), ("patched", pat)):
            b.display.lcd.writes = 0
            _esc(b, *codes)
            sent[name] += b.display.lcd.writes
        assert _ddram(pat) == _ddram(stock), f"chunk {chunk}"
    print(f"data writes: stock {sent['stock']}, patched {sent['patched']}")
    assert sent["patched"] < sent["stock"]


def test_redraw_of_the_same_text_sends_nothing(pair):
    _, pat, _ = pair
    rows = [b"AmpAttack           ", b"  current 519ms     ", b"saved val 1.36s     ", b" " * 20]
    for _ in range(2):
        pat.display.lcd.writes = pat.display.lcd.commands = 0
        for r, text in enumerate(rows):
            _esc(pat, 9, 0, r, *text)
    assert pat.display.lcd.writes == 0 and pat.display.lcd.commands == 0
    assert bytes(pat.display.lcd.codes()[1]) == rows[1]


def test_screen_saver_wake_forgets_the_copy(pair):
    """After the display is powered up again every character is sent once,
    in case the panel lost its RAM (inferred not to, but not checked)."""
    _, pat, _ = pair
    _esc(pat, 9, 0, 0, *b"Hello")
    _call(pat, LCD_DISPLAY_OFF)
    _call(pat, LCD_DISPLAY_ON)
    pat.display.lcd.writes = 0
    _esc(pat, 9, 0, 0, *b"Hello")
    assert pat.display.lcd.writes == 5
    pat.display.lcd.writes = 0
    _esc(pat, 9, 0, 0, *b"Hello")
    assert pat.display.lcd.writes == 0


def test_boot_writes_nothing_past_column_19(built):  # noqa: F811
    b = _boot(built.patched)       # its own board: the stream test writes there on purpose
    spills = int.from_bytes(b.uc.mem_read(built.blob.address("lcd_cache_spills"), 4), "little")
    assert spills == 0
