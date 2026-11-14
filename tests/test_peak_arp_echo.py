"""Peak arp echo filter (patches/peak_mpe/arp_echo.c) in the simulator.

A DAW that routes the Peak's MIDI out back to its MIDI in returns the arp's
own notes. Stock treats a returned note off as a key let go
(arp_note_off 0x08014E10), so the arp empties its play map and stops while
the chord is still held: on the rig, 6 note messages (2026-11-13,
work/loopback_test.py; docs/findings/peak-2.2-build2108.md). Here the DIN
port is looped back: every byte the Peak sends goes straight back in.

Each boot takes about 25 s of wall time, so these are marked slow.
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
ARP_ON, ARP_MIDI = 0xF5, 0x13   # patch +0xF5; globals +0x13 (Arp>Midi, inferred)
CHORD = (60, 64, 67)

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


def _notes(log):
    """Note messages in a DIN byte log [(ms, byte)], with running status."""
    out, status, data = [], None, []
    for t, x in log:
        if x >= 0xF8:
            continue
        if x & 0x80:
            status, data = x, []
            continue
        if status is None:
            continue
        data.append(x)
        if len(data) == 2:
            if status & 0xE0 == 0x80:   # 0x8n / 0x9n
                out.append((t, status, data[0], data[1]))
            data = []
    return out


def _arp_loopback(b, hold_ms=3000, after_ms=2000):
    """Arp on, Arp>Midi on, chord held hold_ms then released, DIN looped back.
    Returns the note messages the Peak sent: (ms since chord, status, note, vel)."""
    b.uc.mem_write(PATCHES + ARP_ON, b"\x01")
    b.uc.mem_write(GLOBALS + ARP_MIDI, b"\x01")
    b.run_ms(100)
    b.din.tx_log.clear()
    start = b.time_us / 1000.0
    for n in CHORD:
        for x in (0x90, n, 100):
            b.din.rx_queue.append((b.time_us, x))
    seen = 0
    released = False
    while b.time_us / 1000.0 - start < hold_ms + after_ms:
        if not released and b.time_us / 1000.0 - start >= hold_ms:
            for n in CHORD:
                for x in (0x80, n, 0):
                    b.din.rx_queue.append((b.time_us, x))
            released = True
        b.run_ms(1)
        new = b.din.tx_log[seen:]
        seen = len(b.din.tx_log)
        for _t, x in new:                       # the DAW's return path
            b.din.rx_queue.append((b.time_us, x))
    b.uc.mem_write(PATCHES + ARP_ON, b"\x00")
    return [(t - start, s, n, v) for t, s, n, v in _notes(b.din.tx_log)]


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    _stock()
    if not patch_build.available():
        pytest.skip("arm-none-eabi-gcc not installed")
    return patch.build_image(PEAK_MPE, build_dir=tmp_path_factory.mktemp("peak-arp-echo"))


def test_stock_arp_stops_when_its_notes_come_back():
    notes = _arp_loopback(_boot(_stock()))
    held = [x for x in notes if 1000 <= x[0] < 3000]
    assert notes, "the arp sent nothing: arp or Arp>Midi not on in the simulator"
    assert not held, f"stock arp still playing 1-3 s into the held chord: {held[:6]}"


def test_filter_keeps_the_arp_playing(built):
    b = _boot(built.patched)
    notes = _arp_loopback(b)
    held = [x for x in notes if 1000 <= x[0] < 3000]
    ons = {n for _t, s, n, _v in held if s & 0xF0 == 0x90}
    assert ons == set(CHORD), f"arp notes 1-3 s into the held chord: {sorted(ons)}"
    late = [x for x in notes if x[0] >= 3500]
    assert not late, f"arp still playing 0.5 s after release: {late[:6]}"


def test_filter_clock_counts_milliseconds(built):
    """ECHO_WINDOW is in mod_tick ticks. Measured against the arp, not the
    simulator's clock: on the Peak a 16th at 120 BPM is 125 ms (rig,
    2026-11-13), and the simulator runs the Peak's timers at twice its own
    ms (62.5 sim-ms per step), so ticks per arp step is the check."""
    b = _boot(built.patched)
    b.uc.mem_write(PATCHES + ARP_ON, b"\x01")
    b.uc.mem_write(GLOBALS + ARP_MIDI, b"\x01")
    b.run_ms(100)
    addr = built.blob.address("arp_echo_now")
    b.din.tx_log.clear()
    for x in (0x90, 60, 100):
        b.din.rx_queue.append((b.time_us, x))
    ticks = []
    while len(ticks) < 6:
        before = len(_notes(b.din.tx_log))
        b.run_ms(1)
        if any(s & 0xF0 == 0x90 for _t, s, _n, _v in _notes(b.din.tx_log)[before:]):
            ticks.append(int.from_bytes(b.uc.mem_read(addr, 2), "little"))
    steps = [(ticks[i + 1] - ticks[i]) & 0xFFFF for i in range(5)]
    assert all(120 <= s <= 130 for s in steps), steps   # 1 tick = 1 ms
