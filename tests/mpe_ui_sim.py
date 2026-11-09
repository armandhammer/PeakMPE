"""Panel and screen helpers for the MPE UI tests (tests/test_mpe_ui_*.py).

Settings pages are numbered as the screen counts them (1-based, the "n/35"
in the title row). The patch puts the MPE pages after MIDI CHANNEL: stock
page p (of 33) is patched page p for p <= 4 and p + 2 after that.
"""

STOCK_PAGES, PAGES = 33, 35
MIDI_CHANNEL, MPE_PAGE, BEND_PAGE = 4, 5, 6
SETTINGS_FLASH = 0x300000
FAST = {"hold_ms": 20, "after_ms": 30}  # still two button scans held, enough for the 10 ms poll


def patched_page(stock_page):
    return stock_page if stock_page <= MIDI_CHANNEL else stock_page + 2


def page_number(s):
    """(page, pages) from the title row's "n/m", or None."""
    last = s.screen_text()[0].split()[-1:]
    if last and "/" in last[0]:
        n, total = last[0].split("/")
        if n.isdigit() and total.isdigit():
            return int(n), int(total)
    return None


def settings_page(s, page, pages=PAGES):
    """Open Settings and step to page (1-based)."""
    now = page_number(s)
    if not now or now[1] != pages:
        s.press("settings", **FAST)
    while True:
        now = page_number(s)
        assert now and now[1] == pages, f"not in Settings: {s.screen_text()}"
        if now[0] == page:
            return
        s.press("page_next" if now[0] < page else "page_prev", **FAST)


def rows(s):
    """The item rows: [(name, value, selected)], from columns 0-10, 11-18, 19."""
    out = []
    for row in s.screen_text()[1:]:
        if row.strip():
            out.append((row[:11].strip(), row[11:19].strip(), row[19] == "▶"))
    return out


def items(s):
    """{name: value} of the page shown."""
    return {name: value for name, value, _ in rows(s)}


def without_counter(lines):
    """Screen rows with the title row's page counter cut off (columns 16-19)."""
    return [lines[0][:15].rstrip()] + list(lines[1:])
