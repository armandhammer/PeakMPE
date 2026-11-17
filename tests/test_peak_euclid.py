"""Peak Euclidean arp rhythms (patches/peak_mpe/euclid.c) in the simulator.

Settings > ARP EUCLID: Pulses notes spread evenly over Steps steps replace
the patch's Rhythm in the arpeggiator. The steps are read where stock plays
them (arp_step 0x080151A0, and arp_step_release 0x08014EC4 for a step's
end), not at the MIDI output: with Arp>MIDI on, the arp echo filter would
take a key released within 100 ms of the arp's own note off for the arp's
echo. At the simulator's default tempo and SyncRate a step is 125 ms, the
time measured on the synth for the Init Patch's arp.
"""
import pytest
import unicorn

from test_peak_arp_echo import ARP_ON
from test_peak_sim import GLOBALS, PATCHES, _boot, _call, _show, mpe_built  # noqa: F401

ARP_STEP, ARP_STEP_RELEASE = 0x080151A0, 0x08014EC4

G_PULSES, G_STEPS, G_ROTATE = 0x45, 0x46, 0x47
EUCLID_PAGE = 12                                         # Settings: after MORPH
RHYTHM, GATE = 0xF1, 0xF3
STEP_MS = 125

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def board(mpe_built):
    b = _boot(mpe_built.patched)
    b.uc.mem_write(PATCHES + ARP_ON, bytes([1]))
    b.arp_log = []
    for addr in (ARP_STEP, ARP_STEP_RELEASE):
        b.uc.hook_add(unicorn.UC_HOOK_CODE, lambda uc, a, size, user: b.arp_log.append((b.time_us / 1000.0, a)),
                      begin=addr, end=addr)
    b.run_ms(100)
    return b


def _play(b, pulses, steps, rotate, ms, note=60):
    """One key held for ms with the setting; returns what the arp did as
    (ms since the key, ARP_STEP or ARP_STEP_RELEASE)."""
    b.uc.mem_write(GLOBALS + G_PULSES, bytes([pulses, steps, rotate]))
    b.run_ms(50)
    b.arp_log.clear()
    start = b.time_us / 1000.0
    for x in (0x90, note, 100):
        b.din.rx_queue.append((b.time_us, x))
    b.run_ms(ms)
    for x in (0x80, note, 0):
        b.din.rx_queue.append((b.time_us, x))
    b.run_ms(300)
    assert b.arp_log[-1][0] - start < ms + 150           # the arp stopped with the key
    return [(t - start, a) for t, a in b.arp_log]


def _steps(notes):
    """Step starts, in steps since the first one."""
    on = [t for t, a in notes if a == ARP_STEP]
    return [round((t - on[0]) / STEP_MS, 1) for t in on]


def _first(notes):
    return next(t for t, a in notes if a == ARP_STEP)


def test_off_is_the_patchs_rhythm(board):
    assert _steps(_play(board, 0, 8, 0, 1000))[:6] == [0, 1, 2, 3, 4, 5]     # Rhythm 1: every step


def test_three_in_eight(board):
    assert _steps(_play(board, 3, 8, 0, 2200))[:7] == [0, 3, 6, 8, 11, 14, 16]   # x..x..x. twice


def test_five_in_eight(board):
    assert _steps(_play(board, 5, 8, 0, 2200))[:11] == [0, 2, 4, 5, 7, 8, 10, 12, 13, 15, 16]   # x.x.xx.x


def test_rotate_starts_the_pattern_later(board):
    b = board
    base = _play(b, 3, 8, 0, 1200)                       # x..x..x.
    late = _play(b, 3, 8, 1, 1200)                       # .x..x..x: the first step is a rest
    assert round((_first(late) - _first(base)) / STEP_MS) == 1
    assert _steps(late)[:4] == [0, 3, 6, 8]
    assert _steps(_play(b, 3, 8, 2, 1200))[:4] == [0, 2, 5, 8]   # x.x..x..


def test_a_note_is_half_a_step_long_at_gate_64(board):
    b = board
    b.uc.mem_write(PATCHES + GATE, bytes([64]))
    notes = _play(b, 3, 8, 0, 900)
    on = [t for t, a in notes if a == ARP_STEP]
    off = [t for t, a in notes if a == ARP_STEP_RELEASE]
    assert abs((off[0] - on[0]) - STEP_MS / 2) < 8, (on[:2], off[:2])


def test_one_in_thirty_two_keeps_time_over_a_long_gap(board):
    """A gap of 31 steps is longer than the arp's 16-bit clock can compare in
    one go (128 clocks): it is written as several rests."""
    assert _steps(_play(board, 1, 32, 0, 8300))[:3] == [0, 32, 64]


def test_more_pulses_than_steps_is_every_step(board):
    assert _steps(_play(board, 9, 4, 0, 900))[:5] == [0, 1, 2, 3, 4]


def test_a_new_rhythm_number_does_not_bring_stock_s_pattern_back(board):
    b = board
    _play(b, 3, 8, 0, 500)
    b.uc.mem_write(PATCHES + RHYTHM, bytes([7]))         # the patch's Rhythm changes while Pulses is on
    assert _steps(_play(b, 3, 8, 0, 1200))[:4] == [0, 3, 6, 8]
    notes = _play(b, 0, 8, 0, 1500)                      # Off: stock's Rhythm 8 plays (not every step)
    assert _steps(notes)[:6] != [0, 1, 2, 3, 4, 5]
    b.uc.mem_write(PATCHES + RHYTHM, bytes([0]))
    assert _steps(_play(b, 0, 8, 0, 1000))[:6] == [0, 1, 2, 3, 4, 5]


def test_euclid_page(mpe_built):
    b, blob = _boot(mpe_built.patched), mpe_built.blob
    rows = _show(b, 8, EUCLID_PAGE, 0)
    assert rows[0].startswith("ARP EUCLID"), rows
    assert rows[1].split()[:2] == ["Pulses", "Off"] and rows[2].split() == ["Steps", "16"], rows
    assert rows[3].split() == ["Rotate", "0"], rows
    for _ in range(5):
        _call(b, blob.address("mpe_ui_value_change"), 1)
    assert b.u8(GLOBALS + G_PULSES) == 5
    assert _show(b, 8, EUCLID_PAGE, 0)[1].split()[:2] == ["Pulses", "5"]
    _show(b, 8, EUCLID_PAGE, 1)
    _call(b, blob.address("mpe_ui_value_change"), -13)   # Steps 16 -> 3: Pulses in effect follows
    rows = _show(b, 8, EUCLID_PAGE, 0)
    assert rows[1].split()[:2] == ["Pulses", "3"] and rows[2].split() == ["Steps", "3"], rows
    _show(b, 8, EUCLID_PAGE, 2)
    _call(b, blob.address("mpe_ui_value_change"), 9)     # Rotate stops at Steps - 1
    assert _show(b, 8, EUCLID_PAGE, 0)[3].split() == ["Rotate", "2"]
    _show(b, 8, EUCLID_PAGE, 0)
    _call(b, blob.address("mpe_ui_value_change"), -9)
    assert _show(b, 8, EUCLID_PAGE, 0)[1].split()[:2] == ["Pulses", "Off"]
    rows = _show(b, 8, EUCLID_PAGE + 1, 0)               # the stock page after ours is still there
    assert rows[0].startswith("MIDI ENABLE"), rows
