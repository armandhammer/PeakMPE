"""Stack high-water mark of the Peak with the MPE patch (docs/peak-features.md,
"Timing budget": painted stack in the simulator).

The Peak runs on one stack, from 0x20030000 down, shared by the main loop and
every interrupt; the patch's code runs on it too (it is called from stock's
paths). Stock's own data ends near 0x20015200 (highest non-zero word after
boot), so about 100 KB lie between the two. Measured (emulated, v0.43):
the patch takes at most 16 B more than stock, 496 B in all.

Each scenario starts from the board held at the main-loop head, paints the
free stack below the main loop's SP with a pattern, plays its load, and reads
the lowest word that no longer holds the pattern. The same scenarios run on
the stock image where they apply, so the patch's own share shows.

Limits of the model: an interrupt here runs 64 bytes below the main thread's
SP with its context saved by the simulator, not pushed (Cortex-M4 pushes 32
bytes, or 104 with a lazy FPU frame), and interrupts don't nest. The calls
that draw pages and the knob screen are made from the main loop's SP, as
main_loop calls them (inferred). Each boot takes about 25 s of wall time, so
these are marked slow.
"""
import sys
from pathlib import Path

import pytest
from unicorn.arm_const import UC_ARM_REG_SP

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import patch  # noqa: E402
import patch_build  # noqa: E402
from emu.firmware import load_image  # noqa: E402

PEAK = "peak-firmware-2.2-build2108.syx"
PEAK_MPE = ROOT / "patches" / "peak_mpe" / "patch.py"
PATCHES, GLOBALS = 0x20012340, 0x20014494
STACK_TOP = 0x20030000
DATA_END = 0x20015200       # stock's highest non-zero RAM word after boot: 0x200151E0
FLOOR = 0x20020000          # painted from here up to the main loop's SP
PATTERN = b"\xA5\x5A\xC3\x3C"

FLAG, ARP_ON = 0x1A2, 0xF5
G_CLOCK_SOURCE, G_ARP_MIDI, G_BANK_PATCH = 0x08, 0x13, 0x15
G_PULSES, G_CHANCE, G_PDUMP, G_PTIME = 0x45, 0x59, 0x4E, 0x4F
G_MORPH = 0x40
MENUS, UI_STATE = 0x20002E90, 0x20011200
UI_DRAW_PAGE, UI_DRAW_VALUES, LCD_PUTC_ESC = 0x08017F14, 0x08018070, 0x0800D21C
KNOB_OVERLAY = 0x08016B14
MSG_STATE, OVERLAY_STATE = 0x20011208, 0x200111E4
ANIMATE1_PRESS, ANIMATE1_RELEASE = (14 << 8) | 0x01, (14 << 8) | 0xFF
KNOBS = (146, 147, 149, 131, 130, 142)   # amp attack, decay, release; filter frequency, resonance; pan

#: The deepest the patched image may go, in bytes below STACK_TOP. Measured
#: 2026-11-24 (v0.43): 496 B at most, stock 480 B in every scenario (its
#: deepest point, 0x2002FE20, is reached by the page drawing that every load
#: ends up in). The limit is about 8x that and still far above DATA_END.
DEPTH_LIMIT = 4096
#: How much deeper than stock the patch may make any one scenario (measured: 16 B).
PATCH_SHARE_LIMIT = 256

pytestmark = pytest.mark.slow


def _stock():
    image = load_image(PEAK)
    if image is None:
        pytest.skip(f"firmware/{PEAK} not present")
    return image


class Rig:
    def __init__(self, image, blob=None):
        from emu.board import Board
        self.b = Board(image)
        self.b.power_on(max_ms=20000)
        self.blob = blob
        self.state = self.b.save_state()
        self.sp = self.b.uc.reg_read(UC_ARM_REG_SP)

    def fresh(self):
        """The board at the main-loop head, the free stack painted."""
        b = self.b
        b.load_state(self.state)
        n = (self.sp - FLOOR) // 4
        b.uc.mem_write(FLOOR, PATTERN * n)
        return b

    def high_water(self):
        """Bytes used below STACK_TOP, from the lowest word not holding the pattern."""
        mem = bytes(self.b.uc.mem_read(FLOOR, self.sp - FLOOR))
        for i in range(0, len(mem), 4):
            if mem[i:i + 4] != PATTERN:
                assert i > 0, "the stack went below the painted area"
                return STACK_TOP - (FLOOR + i)
        return STACK_TOP - self.sp

    def call(self, addr, *args):
        """A function called from the main loop's frame (only at the loop head)."""
        b = self.b
        saved = b.initial_sp
        b.initial_sp = self.sp & ~7
        try:
            return b.call(addr | 1, *args)
        finally:
            b.initial_sp = saved


def _din(b, data):
    for x in data:
        b.din.rx_queue.append((b.time_us, x))


def _drain(b, ms=50):
    while b.din.rx_queue:
        b.run_ms(ms)


def _globals(b, offset, *values):
    b.uc.mem_write(GLOBALS + offset, bytes(values))


# --- scenarios: each takes the Rig, returns nothing; the board starts fresh() --

def dense_mpe(rig):
    """Eight held notes, bend, pressure and Slide on every channel every 10 ms,
    back to back at the DIN line rate, MPE on (on stock: eight channels' worth
    of the same messages)."""
    b = rig.fresh()
    b.uc.mem_write(PATCHES + FLAG, b"\x01")
    data = []
    for ch in range(1, 9):
        data += [0x90 | ch, 50 + ch, 100]
    for t in range(100):
        for ch in range(1, 9):
            bend = 8192 + (t * 37 + ch * 500) % 4000 - 2000
            data += [0xE0 | ch, bend & 0x7F, bend >> 7, 0xD0 | ch, (t + ch) % 128,
                     0xB0 | ch, 74, (t * 3 + ch) % 128]
    for ch in range(1, 9):
        data += [0x80 | ch, 50 + ch, 0]
    _din(b, data)
    _drain(b)
    b.run_ms(300)


def arp_loop(rig):
    """Arp on with Arp>MIDI, a Euclid rhythm 5 of 8, Ratchet x3 every step at
    50 % chance, a three-note chord held 1.5 s with the Peak's DIN out fed back
    to its input (the echo filter at work)."""
    b = rig.fresh()
    b.uc.mem_write(PATCHES + ARP_ON, b"\x01")
    _globals(b, G_ARP_MIDI, 1)
    _globals(b, G_PULSES, 5, 8, 0, 2, 1)
    _globals(b, G_CHANCE, 5)
    b.run_ms(50)
    _din(b, [0x90, 60, 100, 0x90, 64, 100, 0x90, 67, 100])
    seen = len(b.din.tx_log)
    for ms in range(1800):
        if ms == 1500:
            _din(b, [0x80, 60, 0, 0x80, 64, 0, 0x80, 67, 0])
        b.run_ms(1)
        new, seen = b.din.tx_log[seen:], len(b.din.tx_log)
        _din(b, [x for _t, x in new])
    b.uc.mem_write(PATCHES + ARP_ON, b"\x00")


def clock_and_patches(rig):
    """External MIDI clock with Start; program changes timed to the bar, each
    answered by a patch dump; held notes across the loads."""
    b = rig.fresh()
    _globals(b, G_CLOCK_SOURCE, 3)
    _globals(b, G_BANK_PATCH, b.u8(GLOBALS + G_BANK_PATCH) | 1)
    _globals(b, G_PDUMP, 1)
    _globals(b, G_PTIME, 2)
    _din(b, [0xFA])
    b.run_ms(2)
    _din(b, [0x90, 48, 90, 0x90, 55, 90])
    for n in range(400):
        if n % 96 == 10:
            _din(b, [0xB0, 32, 3, 0xC0, 1 + (n // 96) % 2])
        _din(b, [0xF8])
        b.run_ms(2)
    _din(b, [0xFC, 0x80, 48, 0, 0x80, 55, 0])
    b.run_ms(300)


def editor_requests(rig):
    """The editor's SysEx requests over DIN: identity, current patch, stored
    patch, settings; and an MTS single-note retune."""
    b = rig.fresh()
    hdr = [0xF0, 0x00, 0x20, 0x29, 0x01, 0x10, 0x00, 0x7E]
    _din(b, [0xF0, 0x7E, 0x7F, 0x06, 0x01, 0xF7])
    for req in ([0x40, 0, 0], [0x41, 1, 2], [0x44, 0, 0]):
        _din(b, hdr + req + [0, 0, 0xF7])
    _din(b, [0xF0, 0x7F, 0x00, 0x08, 0x02, 0x00, 0x01, 60, 61, 0x10, 0x00, 0xF7])
    _drain(b)
    b.run_ms(300)


def pages_and_knobs(rig):
    """Every Settings page drawn, then the knob screen for six knobs."""
    b = rig.fresh()
    menu = int.from_bytes(b.uc.mem_read(MENUS + 4 * 8, 4), "little")
    pages = b.u8(menu + 1)
    assert 8 < pages < 64, pages
    b.uc.mem_write(UI_STATE, bytes([8]))
    for page in range(pages):
        b.uc.mem_write(menu, bytes([page]))
        for row in range(4):
            for c in (9, 0, row) + (0x20,) * 20:
                rig.call(LCD_PUTC_ESC, c)
        rig.call(UI_DRAW_PAGE)
        rig.call(UI_DRAW_VALUES)
    overlay = rig.blob.address("disp_knob_overlay") if rig.blob else KNOB_OVERLAY
    for pid in KNOBS:
        # The overlay already up for this knob, so it redraws in place: stock's
        # clear waits for a timer tick, which a called function never gets.
        b.uc.mem_write(MSG_STATE + 2, bytes([5, 2]))
        b.uc.mem_write(OVERLAY_STATE + 4, pid.to_bytes(2, "little"))
        for prev, cur in ((10, 11), (63, 64), (126, 127)):
            rig.call(overlay, pid, prev, cur, 80, 0)


def morph_and_motion(rig):
    """Morph on, the mod wheel swept while a knob's lane plays (patch only)."""
    b = rig.fresh()
    blob = rig.blob
    _globals(b, G_MORPH, 1)
    assert rig.call(blob.address("motion_button"), ANIMATE1_PRESS, 1) == 1
    assert rig.call(blob.address("motion_button"), ANIMATE1_RELEASE, 1) == 1
    rig.call(blob.address("motion_knob"), 0x82, 40, 0)
    rig.call(blob.address("motion_knob"), 0x82, 90, 0)
    _din(b, [0x90, 60, 100])
    for v in list(range(0, 128, 8)) + list(range(127, -1, -8)):
        _din(b, [0xB0, 1, v])
        b.run_ms(40)
    _din(b, [0x80, 60, 0])
    b.run_ms(300)


SHARED = [dense_mpe, arp_loop, clock_and_patches, editor_requests, pages_and_knobs]
PATCH_ONLY = [morph_and_motion]


@pytest.fixture(scope="module")
def stock():
    return Rig(_stock())


@pytest.fixture(scope="module")
def patched(tmp_path_factory):
    _stock()
    if not patch_build.available():
        pytest.skip("arm-none-eabi-gcc not installed")
    built = patch.build_image(PEAK_MPE, build_dir=tmp_path_factory.mktemp("peak-stack"))
    return Rig(built.patched, built.blob)


def _run(rig, scenario):
    scenario(rig)
    return rig.high_water()


@pytest.mark.parametrize("scenario", SHARED, ids=lambda s: s.__name__)
def test_the_patch_keeps_the_stack_within_its_share(stock, patched, scenario):
    s, p = _run(stock, scenario), _run(patched, scenario)
    print(f"{scenario.__name__}: stock {s} B, patched {p} B")
    assert p <= DEPTH_LIMIT, f"{scenario.__name__}: {p} B of stack (limit {DEPTH_LIMIT})"
    assert p - s <= PATCH_SHARE_LIMIT, f"{scenario.__name__}: patched {p} B against stock {s} B"


@pytest.mark.parametrize("scenario", PATCH_ONLY, ids=lambda s: s.__name__)
def test_patch_only_loads_stay_within_the_limit(patched, scenario):
    p = _run(patched, scenario)
    print(f"{scenario.__name__}: patched {p} B")
    assert p <= DEPTH_LIMIT, f"{scenario.__name__}: {p} B of stack (limit {DEPTH_LIMIT})"


def test_the_limit_leaves_room_above_stocks_data():
    assert STACK_TOP - DEPTH_LIMIT > DATA_END + 0x8000
