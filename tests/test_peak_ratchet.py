"""Peak arp ratchets (patches/peak_mpe/euclid.c) in the simulator.

Settings > ARP RATCHET: Ratchet (Off, x2, x3) plays a note two or three
times within its step; Every (1-8) says which notes. Read where stock plays
a step (arp_step 0x080151A0: r0 is the note before the octave is added), as
tests/test_peak_euclid.py does.
"""
import pytest
import unicorn
from unicorn.arm_const import UC_ARM_REG_R0

from test_peak_arp_echo import ARP_ON
from test_peak_euclid import EUCLID_PAGE, G_PULSES, STEP_MS
from test_peak_sim import GLOBALS, PATCHES, _boot, _call, _show, mpe_built  # noqa: F401

ARP_STEP = 0x080151A0
G_RATCHET, G_EVERY = 0x48, 0x49
RATCHET_PAGE = EUCLID_PAGE + 1
TYPE, VOICE_MODE = 0xF0, 0x22
X2, X3 = 1, 2

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def board(mpe_built):
    b = _boot(mpe_built.patched)
    b.uc.mem_write(PATCHES + ARP_ON, bytes([1]))
    b.arp_log = []
    b.uc.hook_add(unicorn.UC_HOOK_CODE,
                  lambda uc, a, size, user: b.arp_log.append((b.time_us / 1000.0, uc.reg_read(UC_ARM_REG_R0) & 0xFF)),
                  begin=ARP_STEP, end=ARP_STEP)
    b.run_ms(100)
    return b


def _play(b, ratchet, every, ms, keys=(60,), pulses=0, steps=8):
    """Keys held for ms; returns the arp's steps as (steps since the first one, note)."""
    b.uc.mem_write(GLOBALS + G_PULSES, bytes([pulses, steps, 0, ratchet, every]))
    b.run_ms(50)
    b.arp_log.clear()
    for k in keys:
        for x in (0x90, k, 100):
            b.din.rx_queue.append((b.time_us, x))
    b.run_ms(ms)
    for k in keys:
        for x in (0x80, k, 0):
            b.din.rx_queue.append((b.time_us, x))
    b.run_ms(300)
    t0 = b.arp_log[0][0]
    return [(round((t - t0) / STEP_MS, 2), n) for t, n in b.arp_log]


def _times(played):
    return [t for t, _n in played]


def _notes(played):
    return [n for _t, n in played]


def _near(got, want):
    return len(got) >= len(want) and all(abs(g - w) < 0.07 for g, w in zip(got, want))


def test_off_plays_each_step_once(board):
    assert _near(_times(_play(board, 0, 1, 700)), [0, 1, 2, 3, 4])


def test_x2_plays_every_note_twice_in_its_step(board):
    assert _near(_times(_play(board, X2, 1, 700)), [0, 0.5, 1, 1.5, 2, 2.5, 3])


def test_x3_plays_every_note_three_times(board):
    assert _near(_times(_play(board, X3, 1, 500)), [0, 1 / 3, 2 / 3, 1, 4 / 3, 5 / 3, 2])


def test_the_repeat_is_the_same_note_and_the_chord_moves_on(board):
    played = _play(board, X2, 1, 1000, keys=(60, 64, 67))
    assert _notes(played)[:8] == [60, 60, 64, 64, 67, 67, 60, 60], played


def test_every_second_note_ratchets(board):
    played = _play(board, X2, 2, 1100, keys=(60, 64, 67))
    assert _notes(played)[:9] == [60, 64, 64, 67, 60, 60, 64, 67, 67], played
    assert _near(_times(played), [0, 1, 1.5, 2, 3, 3.5, 4, 5, 5.5])


def test_a_ratchet_on_a_euclidean_rhythm(board):
    played = _play(board, X2, 1, 1300, pulses=3, steps=8)            # x..x..x. with every note doubled
    assert _near(_times(played), [0, 0.5, 3, 3.5, 6, 6.5, 8, 8.5])


@pytest.mark.parametrize("arp_type", range(6))
def test_every_type_repeats_its_own_note(board, arp_type):
    """Up, down, up-down, played order, random: whatever note the type picks,
    the ratchet plays it again (the choice is put back before stock picks)."""
    b = board
    b.uc.mem_write(PATCHES + TYPE, bytes([arp_type]))
    try:
        notes = _notes(_play(b, X2, 1, 1300, keys=(60, 64, 67, 71)))
    finally:
        b.uc.mem_write(PATCHES + TYPE, bytes([0]))
    # The first step sounds as soon as the first key arrives, before the
    # other three are in: its repeat is chosen from the whole chord. From
    # the second step on the chord stands still.
    pairs = [(notes[i], notes[i + 1]) for i in range(2, len(notes) - 1, 2)]
    assert len(pairs) >= 8 and all(a == c for a, c in pairs), notes
    assert len({a for a, _c in pairs}) > 1, notes                    # and the arp still moves through the chord


def test_mono_retriggers_one_voice(board):
    b = board
    b.uc.mem_write(PATCHES + VOICE_MODE, bytes([0]))
    try:
        assert _near(_times(_play(b, X2, 1, 700)), [0, 0.5, 1, 1.5, 2])
    finally:
        b.uc.mem_write(PATCHES + VOICE_MODE, bytes([3]))


def test_ratchet_page(mpe_built):
    b, blob = _boot(mpe_built.patched), mpe_built.blob
    b.uc.mem_write(GLOBALS + G_RATCHET, bytes([0xFF, 0xFF]))         # bytes never written
    rows = _show(b, 8, RATCHET_PAGE, 0)
    assert rows[0].startswith("ARP RATCHET"), rows
    assert rows[1].split()[:2] == ["Ratchet", "Off"] and rows[2].split() == ["Every", "1"], rows
    _call(b, blob.address("mpe_ui_value_change"), 1)
    assert b.u8(GLOBALS + G_RATCHET) == 1
    assert _show(b, 8, RATCHET_PAGE, 0)[1].split()[:2] == ["Ratchet", "x2"]
    _call(b, blob.address("mpe_ui_value_change"), 5)
    assert _show(b, 8, RATCHET_PAGE, 0)[1].split()[:2] == ["Ratchet", "x3"]
    _show(b, 8, RATCHET_PAGE, 1)
    _call(b, blob.address("mpe_ui_value_change"), 20)
    assert _show(b, 8, RATCHET_PAGE, 0)[2].split() == ["Every", "8"]
    assert _show(b, 8, RATCHET_PAGE + 1, 0)[0].startswith("RELEASE VEL ")
    assert _show(b, 8, RATCHET_PAGE + 2, 0)[0].startswith("RANDOMISE ")
    assert _show(b, 8, RATCHET_PAGE + 3, 0)[0].startswith("PATCH DUMP ")
    rows = _show(b, 8, RATCHET_PAGE + 4, 0)              # the stock page after ours is still there
    assert rows[0].startswith("MIDI ENABLE"), rows


@pytest.mark.parametrize("arp_type", (6, 7))
def test_the_chord_types_repeat_the_whole_chord(board, arp_type):
    b = board
    b.uc.mem_write(PATCHES + TYPE, bytes([arp_type]))
    try:
        played = _play(b, X2, 1, 700, keys=(60, 64, 67))
    finally:
        b.uc.mem_write(PATCHES + TYPE, bytes([0]))
    chords = {}
    for t, n in played[3:]:                              # after the three keys are in
        chords.setdefault(round(t * 2) / 2, set()).add(n)
    assert sorted(chords)[:4] == [0.5, 1.0, 1.5, 2.0], played
    assert all(chords[t] == {60, 64, 67} for t in sorted(chords)[:4]), played
