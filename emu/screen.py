"""Screen views of the simulated OLED: text, a framed text dump and a PNG.

The PNG is drawn dot by dot, 5x8 dots per character as on the controller,
and written with :mod:`zlib` only (no imaging library). Custom characters
(codes 0-7) are drawn from the CGRAM bitmaps the firmware loaded. Character-ROM
glyphs use the 5x7 font below, drawn for this project in the usual
dot-matrix style; they are not the controller's ROM bitmaps, so a screenshot
shows what is written where, not the exact pixels of the real panel.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

from .display import COLS, ROWS, Us2066

# 5x7 glyphs: seven rows of five bits (bit 4 = left), top to bottom.
_FONT_ROWS = """
20 00 00 00 00 00 00 00
21 04 04 04 04 00 00 04
22 0A 0A 0A 00 00 00 00
23 0A 0A 1F 0A 1F 0A 0A
24 04 0F 14 0E 05 1E 04
25 18 19 02 04 08 13 03
26 0C 12 14 08 15 12 0D
27 0C 04 08 00 00 00 00
28 02 04 08 08 08 04 02
29 08 04 02 02 02 04 08
2A 00 04 15 0E 15 04 00
2B 00 04 04 1F 04 04 00
2C 00 00 00 00 0C 04 08
2D 00 00 00 1F 00 00 00
2E 00 00 00 00 00 0C 0C
2F 00 01 02 04 08 10 00
30 0E 11 13 15 19 11 0E
31 04 0C 04 04 04 04 0E
32 0E 11 01 02 04 08 1F
33 1F 02 04 02 01 11 0E
34 02 06 0A 12 1F 02 02
35 1F 10 1E 01 01 11 0E
36 06 08 10 1E 11 11 0E
37 1F 01 02 04 08 08 08
38 0E 11 11 0E 11 11 0E
39 0E 11 11 0F 01 02 0C
3A 00 0C 0C 00 0C 0C 00
3B 00 0C 0C 00 0C 04 08
3C 02 04 08 10 08 04 02
3D 00 00 1F 00 1F 00 00
3E 08 04 02 01 02 04 08
3F 0E 11 01 02 04 00 04
40 0E 11 01 0D 15 15 0E
41 0E 11 11 11 1F 11 11
42 1E 11 11 1E 11 11 1E
43 0E 11 10 10 10 11 0E
44 1C 12 11 11 11 12 1C
45 1F 10 10 1E 10 10 1F
46 1F 10 10 1E 10 10 10
47 0E 11 10 17 11 11 0F
48 11 11 11 1F 11 11 11
49 0E 04 04 04 04 04 0E
4A 07 02 02 02 02 12 0C
4B 11 12 14 18 14 12 11
4C 10 10 10 10 10 10 1F
4D 11 1B 15 15 11 11 11
4E 11 11 19 15 13 11 11
4F 0E 11 11 11 11 11 0E
50 1E 11 11 1E 10 10 10
51 0E 11 11 11 15 12 0D
52 1E 11 11 1E 14 12 11
53 0F 10 10 0E 01 01 1E
54 1F 04 04 04 04 04 04
55 11 11 11 11 11 11 0E
56 11 11 11 11 11 0A 04
57 11 11 11 15 15 15 0A
58 11 11 0A 04 0A 11 11
59 11 11 11 0A 04 04 04
5A 1F 01 02 04 08 10 1F
5B 0E 08 08 08 08 08 0E
5C 00 10 08 04 02 01 00
5D 0E 02 02 02 02 02 0E
5E 04 0A 11 00 00 00 00
5F 00 00 00 00 00 00 1F
60 08 04 02 00 00 00 00
61 00 00 0E 01 0F 11 0F
62 10 10 16 19 11 11 1E
63 00 00 0E 10 10 11 0E
64 01 01 0D 13 11 11 0F
65 00 00 0E 11 1F 10 0E
66 06 09 08 1C 08 08 08
67 00 0F 11 11 0F 01 0E
68 10 10 16 19 11 11 11
69 04 00 0C 04 04 04 0E
6A 02 00 06 02 02 12 0C
6B 10 10 12 14 18 14 12
6C 0C 04 04 04 04 04 0E
6D 00 00 1A 15 15 11 11
6E 00 00 16 19 11 11 11
6F 00 00 0E 11 11 11 0E
70 00 00 1E 11 1E 10 10
71 00 00 0D 13 0F 01 01
72 00 00 16 19 10 10 10
73 00 00 0E 10 0E 01 1E
74 08 08 1C 08 08 09 06
75 00 00 11 11 11 13 0D
76 00 00 11 11 11 0A 04
77 00 00 11 11 15 15 0A
78 00 00 11 0A 04 0A 11
79 00 00 11 11 0F 01 0E
7A 00 00 1F 02 04 08 1F
7B 02 04 04 08 04 04 02
7C 04 04 04 04 04 04 04
7D 08 04 04 02 04 04 08
7E 00 00 08 15 02 00 00
10 08 0C 0E 0F 0E 0C 08
11 02 06 0E 1E 0E 06 02
"""
FONT: Dict[int, List[int]] = {}
for _line in _FONT_ROWS.strip().splitlines():
    _code, *_rows = (int(x, 16) for x in _line.split())
    FONT[_code] = _rows + [0]
#: Drawn for any code without a glyph: an outlined box.
UNKNOWN_GLYPH = [0x1F, 0x11, 0x11, 0x11, 0x11, 0x11, 0x1F, 0]

Color = Tuple[int, int, int]
BACKGROUND: Color = (8, 10, 14)
DOT_OFF: Color = (24, 30, 38)
DOT_ON: Color = (200, 235, 255)
DOT_ON_DIM: Color = (60, 70, 80)  # display switched off: contents kept, dark


def glyph_rows(lcd: Us2066, code: int) -> List[int]:
    if code < 8:
        return lcd.glyph(code)
    return FONT.get(code, UNKNOWN_GLYPH)


def dump(lines: Sequence[str], title: Optional[str] = None, display_on: bool = True) -> str:
    """The screen rows in a frame, for printing."""
    width = max([COLS] + [len(line) for line in lines])
    head = f"+{'-' * width}+"
    if title:
        head = f"+- {title} " + "-" * max(0, width - len(title) - 3) + "+"
    out = [head] + [f"|{line.ljust(width)}|" for line in lines] + [f"+{'-' * width}+"]
    if not display_on:
        out.append("(display off)")
    return "\n".join(out)


def render(lcd: Us2066, scale: int = 4, display_on: bool = True) -> Tuple[int, int, bytes]:
    """RGB pixels of the panel: (width, height, rows of RGB bytes)."""
    dot, gap = scale, max(1, scale // 4)
    pitch = dot + gap
    char_w, char_h = 5 * pitch + 2 * pitch, 8 * pitch + 2 * pitch  # one dot column/row between cells, ×2 for air
    margin = 4 * pitch
    width = 2 * margin + COLS * char_w - 2 * pitch
    height = 2 * margin + ROWS * char_h - 2 * pitch
    img = [bytearray(bytes(BACKGROUND) * width) for _ in range(height)]
    on_color = bytes(DOT_ON if display_on else DOT_ON_DIM)
    off_color = bytes(DOT_OFF)
    for r, row in enumerate(lcd.codes()):
        for c, code in enumerate(row):
            rows = glyph_rows(lcd, code)
            x0, y0 = margin + c * char_w, margin + r * char_h
            for gy in range(8):
                bits = rows[gy]
                for gx in range(5):
                    color = on_color if bits >> (4 - gx) & 1 else off_color
                    x, y = x0 + gx * pitch, y0 + gy * pitch
                    for yy in range(y, y + dot):
                        img[yy][3 * x : 3 * (x + dot)] = color * dot
    return width, height, b"".join(bytes(line) for line in img)


def write_png(path: Union[str, Path], width: int, height: int, rgb: bytes) -> Path:
    """Write 8-bit RGB pixels as a PNG (stdlib only)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stride = 3 * width
    raw = b"".join(b"\x00" + rgb[y * stride : (y + 1) * stride] for y in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    path.write_bytes(png)
    return path


def screenshot(lcd: Us2066, path: Union[str, Path], scale: int = 4, display_on: bool = True) -> Path:
    return write_png(path, *render(lcd, scale, display_on))
