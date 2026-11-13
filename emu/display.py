"""The front-panel character OLED, observed at the peripheral level (SPI2 + GPIOB).

Evidence (static, ``docs/findings/summit-2.2-build2121.md`` "Display and
front panel"):

* SPI2 (``0x40003800``) is used only by the display driver: ``lcd_spi_tx``
  ``0x08012CD0`` waits for TXE and writes ``SPI2_DR`` ``0x4000380C``;
  ``lcd_spi_wait`` ``0x08012CE8`` waits for TXE and not BSY.
* ``lcd_write_cmd`` ``0x08019D40`` and ``lcd_write_data`` ``0x08019D68`` pull
  PB11 low (``GPIOB_BSRR`` ``0x40020418`` bit 27), send a start byte ``0x1F``
  (command) or ``0x5F`` (data), then the byte as two frames, low nibble first,
  wait, and release PB11. That is the serial interface of the US2066 / SSD1311
  family of OLED character controllers (start byte ``11111 RW RS 0`` sent LSB
  first, then ``D0-D3 0000`` and ``D4-D7 0000``); which chip it is exactly is
  inferred.
* ``lcd_cursor`` ``0x08019DB4`` sends ``0x80 | (col + row * 32)``: four lines
  at DDRAM ``0x00/0x20/0x40/0x60``, the US2066's 4-line layout. 20 columns:
  ``2/33`` is drawn at column 16 of a Settings title row.
* ``lcd_load_cgram`` ``0x08019D90`` sends ``0x40`` (CGRAM address 0) and 64
  bytes from ``0x20001098``: eight 5x8 custom characters, codes 0-7.
* PB10 is switched with the display on/off commands (``lcd_wake``
  ``0x08019E24`` sets it before ``0x0C``, ``lcd_sleep`` ``0x08019E54`` clears it
  after ``0x08``): presumably the panel supply (inferred).

:class:`Us2066` interprets the byte stream as the controller would: the
fundamental command set (clear, home, entry mode, display on/off, shift,
function set with the RE/IS bits, CGRAM and DDRAM addresses), the extended
commands that take an argument (``0x71``/``0x72`` with RE=1 take one data byte)
and the OLED command set (``0x79`` … ``0x78``, SD=1), whose bytes don't touch
display RAM. Data goes to CGRAM or DDRAM, wherever the last address command
pointed, and the address counter follows the entry mode. Anything the model
doesn't recognise is counted in :attr:`Us2066.unknown`, not guessed.

The text view maps character codes to Unicode: ASCII 0x20-0x7E as themselves,
the codes the firmware is seen to use from the character ROM through
:data:`ROM_TEXT`, custom characters 0-7 through :data:`CGRAM_TEXT` (the glyphs
the firmware loads, read from their bitmaps), and anything else as ``·``.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

SPI2_BASE = 0x40003800
SPI2_DR = SPI2_BASE + 0x0C
GPIOB_BSRR = 0x40020418
CS_PIN = 11  # PB11, active low
POWER_PIN = 10  # PB10, high while the display is on (inferred: panel supply)

COLS, ROWS = 20, 4
LINE_ADDR = (0x00, 0x20, 0x40, 0x60)
START_CMD, START_DATA = 0x1F, 0x5F

#: Character-ROM codes above 0x7F that the firmware sends, as Unicode.
#: ``lcd_putc`` maps its own codes 0xBB-0xBF to ROM 0xDA-0xD6 and 0xBA to a
#: space; the glyph shapes are inferred from where they are used.
ROM_TEXT: Dict[int, str] = {}

#: Custom characters 0-7 as the stock firmware defines them (the 64 bytes at
#: ``0x20001098``), as Unicode approximations; see :func:`glyph_ascii`.
CGRAM_TEXT: Dict[int, str] = {0: "┌", 1: "┐", 2: "└", 3: "┘", 4: "▔", 5: "▁", 6: "▏", 7: "▕"}

#: Codes 0x10-0x1F of the US2066 ROM A that the firmware uses.
LOW_ROM_TEXT: Dict[int, str] = {
    0x10: "▶",  # drawn after the selected item (inferred from use)
    0x11: "◀",  # Save page, before the name (inferred: the mirror of 0x10)
}


def char_text(code: int) -> str:
    """One display character code as text."""
    if 0x20 <= code <= 0x7E:
        return chr(code)
    if code < 8:
        return CGRAM_TEXT.get(code, "·")
    if code < 0x20:
        return LOW_ROM_TEXT.get(code, "·")
    return ROM_TEXT.get(code, "·")


@dataclass
class DisplayEvent:
    time_ms: float
    kind: str  # "cmd" or "data"
    value: int


class Us2066:
    """A US2066-style 4-line character OLED controller. See the module docstring."""

    def __init__(self) -> None:
        self.ddram = bytearray(b" " * 0x80)
        self.cgram = bytearray(64)
        self.ac = 0
        self.cg_mode = False  # last address command was CGRAM
        self.increment = True
        self.display_on = False
        self.cursor_on = False
        self.blink_on = False
        self.re = False
        self.is_ = False
        self.sd = False
        self.four_line = False
        self.two_line = False
        self.shift = 0
        self._arg_pending = 0  # command bytes still owed to an OLED command (SD=1)
        self._data_arg = False  # next data byte is a function-selection argument
        self.unknown: collections.Counter = collections.Counter()
        self.commands = 0
        self.writes = 0

    # -- bus side ---------------------------------------------------------------

    def command(self, c: int) -> None:
        self.commands += 1
        c &= 0xFF
        if self.sd:
            if self._arg_pending:
                self._arg_pending -= 1
            elif c == 0x78:
                self.sd = False
            elif c in (0x81, 0xD5, 0xD9, 0xDA, 0xDB, 0xDC):
                self._arg_pending = 1
            else:
                self.unknown[("oled", c)] += 1
            return
        if c >= 0x80:
            if self.re:
                self.unknown[("re", c)] += 1  # scroll quantity: not used
                return
            self.ac, self.cg_mode = c & 0x7F, False
        elif c >= 0x40:
            if self.re:
                if c in (0x71, 0x72):
                    self._data_arg = True
                elif c == 0x79:
                    self.sd = True
                else:
                    self.unknown[("re", c)] += 1
                return
            self.ac, self.cg_mode = c & 0x3F, True
        elif c >= 0x20:
            self.re = bool(c & 0x02)
            self.two_line = bool(c & 0x08)
            if not c & 0x02:
                self.is_ = bool(c & 0x01)
        elif c >= 0x10:
            if self.re or self.is_:
                return  # double height / bias / shift enable: no effect on the text
            if c & 0x08:  # display shift
                self.shift = (self.shift + (1 if c & 0x04 else -1)) % 0x20
            else:  # cursor move
                self.ac = (self.ac + (1 if c & 0x04 else -1)) & 0x7F
        elif c >= 0x08:
            if self.re:
                self.four_line = bool(c & 0x01)
            else:
                self.display_on = bool(c & 0x04)
                self.cursor_on = bool(c & 0x02)
                self.blink_on = bool(c & 0x01)
        elif c >= 0x04:
            if not self.re:
                self.increment = bool(c & 0x02)
                if c & 0x01:
                    self.unknown[("entry_shift", c)] += 1
        elif c >= 0x02:
            self.ac, self.cg_mode, self.shift = 0, False, 0
        elif c == 0x01:
            self.ddram[:] = b" " * 0x80
            self.ac, self.cg_mode, self.shift, self.increment = 0, False, 0, True
        else:
            self.unknown[("cmd", c)] += 1

    def data(self, d: int) -> None:
        self.writes += 1
        d &= 0xFF
        if self._data_arg:
            self._data_arg = False
            return
        step = 1 if self.increment else -1
        if self.cg_mode:
            self.cgram[self.ac & 0x3F] = d
            self.ac = (self.ac + step) & 0x3F
        else:
            self.ddram[self.ac & 0x7F] = d
            self.ac = (self.ac + step) & 0x7F

    # -- views ------------------------------------------------------------------

    def codes(self) -> List[bytes]:
        """The visible character codes, one ``bytes`` of :data:`COLS` per row."""
        return [
            bytes(self.ddram[(base + (self.shift + c) % 0x20) & 0x7F] for c in range(COLS))
            for base in LINE_ADDR[:ROWS]
        ]

    def text(self) -> List[str]:
        return ["".join(char_text(c) for c in row) for row in self.codes()]

    def glyph(self, code: int) -> List[int]:
        """Rows (5 bits each, bit 4 leftmost) of custom character *code* (0-7)."""
        return [self.cgram[(code & 7) * 8 + r] & 0x1F for r in range(8)]


class DisplayBus:
    """Decodes the SPI2 frames inside each PB11 chip-select window."""

    def __init__(self, clock: Callable[[], float], cs_pin: int = CS_PIN):
        self.cs_pin = cs_pin  # PB11 on the Summit, PB12 on the Peak
        self.clock = clock
        self.lcd = Us2066()
        self.selected = False
        self.powered = False
        #: Every decoded command and data byte, for debugging (bounded).
        self.log: collections.deque = collections.deque(maxlen=4096)
        self.bad_frames = 0
        #: Named copies of the screen text, e.g. ``"boot"`` (taken by the board
        #: when ``boot_screen`` has printed, before its FPGA upload).
        self.snapshots: Dict[str, List[str]] = {}
        self._start: Optional[int] = None
        self._lo: Optional[int] = None

    def gpiob_bsrr(self, value: int) -> None:
        if value >> (self.cs_pin + 16) & 1:
            self.selected, self._start, self._lo = True, None, None
        elif value >> self.cs_pin & 1:
            if self.selected and self._lo is not None:
                self.bad_frames += 1
            self.selected = False
        if value >> POWER_PIN & 1:
            self.powered = True
        elif value >> (POWER_PIN + 16) & 1:
            self.powered = False

    def spi_write(self, value: int) -> None:
        if not self.selected:
            return
        value &= 0xFF
        if self._start is None:
            if value not in (START_CMD, START_DATA):
                self.bad_frames += 1
            self._start = value
            return
        if self._lo is None:
            self._lo = value
            return
        byte = (self._lo & 0x0F) | (value & 0x0F) << 4
        if (self._lo | value) & 0xF0:
            self.bad_frames += 1
        self._lo = None
        if self._start == START_DATA:
            self.log.append(DisplayEvent(self.clock(), "data", byte))
            self.lcd.data(byte)
        else:
            self.log.append(DisplayEvent(self.clock(), "cmd", byte))
            self.lcd.command(byte)

    def snapshot(self, name: str) -> None:
        self.snapshots[name] = self.lcd.text()

    @property
    def on(self) -> bool:
        """Display enabled (command ``0x0C``) and its supply pin high."""
        return self.lcd.display_on and self.powered


def glyph_ascii(rows: List[int], on: str = "#", off: str = ".") -> List[str]:
    return ["".join(on if r >> (4 - b) & 1 else off for b in range(5)) for r in rows]
