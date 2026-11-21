"""Peak just intonation: Settings JUST TUNE (patches/peak_mpe/ji.c).

Each voice gets a pitch offset added to osc_pitch's result (4,096 per octave:
1 = 0.29 cents). Read two ways: ji_offset(v), the patch's own number, and the
pitch the voice sends the sound chip (parameter 0x000, as the bend tests read
it), measured against the same note with Mode Off.
"""
import pytest

from test_peak_sim import FLAG, PATCHES, _boot, _call, _send, _show, mpe_built  # noqa: F401

pytestmark = pytest.mark.slow

GLOBALS, G_JI = 0x20014494, 0x56
OFF, FIXED, ADAPT = 0, 1, 2
VOICE_NOTE = 0x20012794
ARP_ON = 0xF5
JI_PAGE = 20
# 5-limit intervals above the root, osc units (cents x 4096 / 1200, rounded)
JI = {0: 0, 1: 40, 2: 13, 3: 53, 4: -47, 5: -7, 6: -33, 7: 7, 8: 47, 9: -53, 10: 60, 11: -40}
C4, E4, G4, A4, C5, E5, D4 = 60, 64, 67, 69, 72, 76, 62


@pytest.fixture
def board(mpe_built):
    b = _boot(mpe_built.patched)
    b.run_ms(200)
    b.offset = lambda v: _signed(_call(b, mpe_built.blob.address("ji_offset"), v))
    return b


def _signed(x):
    x &= 0xFFFFFFFF
    return x - (1 << 32) if x & 0x80000000 else x


def _mode(b, mode, root=0):
    b.uc.mem_write(GLOBALS + G_JI, bytes([mode, root]))


def _on(b, *notes, ms=40, ch=0):
    for n in notes:
        _send(b, 0x90 | ch, n, 100, ms=0)
    b.run_ms(ms)


def _off(b, *notes, ms=300, ch=0):
    for n in notes:
        _send(b, 0x80 | ch, n, 0, ms=0)
    b.run_ms(ms)


def _offsets(b):
    """{note: offset} of the gated voices."""
    notes = b.uc.mem_read(VOICE_NOTE, 8)
    gates = b.uc.mem_read(0x20004650 + 0x1F4, 8)
    return {notes[v]: b.offset(v) for v in range(8) if gates[v]}


def _pitches(b):
    """{note: the last pitch the gated voices sent} (sound chip parameter 0x000)."""
    out = {}
    for e in b.fpga.events:
        if not e.read and e.target < 8 and e.param == 0x000:
            out[e.target] = e.value
    notes = b.uc.mem_read(VOICE_NOTE, 8)
    return {notes[v]: p for v, p in out.items()}


def test_the_settings_page(board, mpe_built):
    b = board
    change = mpe_built.blob.address("mpe_ui_value_change")
    rows = _show(b, 8, JI_PAGE, 0)
    assert rows[0].startswith("JUST TUNE"), rows
    assert [r[:19].split() for r in rows[1:3]] == [["Mode", "Off"], ["Root", "C"]], rows
    _call(b, change, 1)
    assert b.u8(GLOBALS + G_JI) == FIXED
    _call(b, change, 5)
    assert b.u8(GLOBALS + G_JI) == ADAPT                   # Adapt is the end
    assert _show(b, 8, JI_PAGE, 1)[1][:19].split() == ["Mode", "Adapt"]
    _call(b, change, 9)
    assert _show(b, 8, JI_PAGE, 1)[2][:19].split() == ["Root", "A"]
    _call(b, change, 7)
    assert b.u8(GLOBALS + G_JI + 1) == 11                  # B is the end
    rows = _show(b, 8, JI_PAGE + 1, 0)                     # the stock page after ours
    assert rows[0].startswith("MIDI ENABLE"), rows


def test_off_changes_nothing(board):
    b = board
    _on(b, C4, E4, G4)
    assert _offsets(b) == {C4: 0, E4: 0, G4: 0}


def test_the_offset_reaches_the_sound_chip(board):
    b = board
    b.fpga.reset()
    _on(b, C4, E4, G4)
    stock = _pitches(b)
    _off(b, C4, E4, G4)
    _mode(b, FIXED, 0)
    b.fpga.reset()
    _on(b, C4, E4, G4)
    tuned = _pitches(b)
    assert {n: tuned[n] - stock[n] for n in (C4, E4, G4)} == {C4: 0, E4: JI[4], G4: JI[7]}


def test_fixed_tunes_every_note_to_the_root(board):
    b = board
    _mode(b, FIXED, 0)
    _on(b, C4, E4, G4, A4)
    assert _offsets(b) == {C4: 0, E4: JI[4], G4: JI[7], A4: JI[9]}
    _off(b, C4, E4, G4, A4)
    _mode(b, FIXED, 2)                                     # Root D: E is its 9/8
    _on(b, D4, E4)
    assert _offsets(b) == {D4: 0, E4: JI[2]}


def test_adapt_tunes_a_chord_to_its_root(board):
    b = board
    _mode(b, ADAPT)
    _on(b, C4, E4, G4)                                     # C major: root C at its equal pitch
    assert _offsets(b) == {C4: 0, E4: JI[4], G4: JI[7]}
    _off(b, C4, E4, G4)
    _on(b, A4, C5, E5)                                     # A minor alone: root A
    assert _offsets(b) == {A4: 0, C5: JI[3], E5: JI[7]}
    _off(b, A4, C5, E5)
    _on(b, E4, G4, C5)                                     # C major, E in the bass: still root C
    assert _offsets(b) == {E4: JI[4], G4: JI[7], C5: 0}


def test_adapt_a_note_played_alone_is_equal_tempered(board):
    b = board
    _mode(b, ADAPT)
    _on(b, E4)
    assert _offsets(b) == {E4: 0}


def test_adapt_a_held_note_keeps_its_pitch(board):
    """Hold C E G, let go of C and G, play A and C over the held E: E stays
    where C major put it, and A minor is tuned around it (E is A's fifth)."""
    b = board
    _mode(b, ADAPT)
    _on(b, C4, E4, G4, ms=100)
    _off(b, C4, G4, ms=50)
    _on(b, A4, C5)
    got = _offsets(b)
    ref = JI[4] - JI[7]                                    # A's pitch from the held E
    assert got == {E4: JI[4], A4: ref, C5: ref + JI[3]}, got


def test_adapt_notes_within_30_ms_are_one_chord(board):
    """The chord's notes arrive one by one; the first (E, its own root while
    alone) is tuned again when C and G come within 30 ms."""
    b = board
    _mode(b, ADAPT)
    _on(b, E4, ms=10)
    _on(b, C4, ms=10)
    _on(b, G4)
    assert _offsets(b) == {C4: 0, E4: JI[4], G4: JI[7]}


def test_adapt_works_on_mpe_member_channels(board):
    b = board
    b.uc.mem_write(PATCHES + FLAG, b"\x01")                # MPE on, Lower Zone
    _mode(b, ADAPT)
    for ch, n in ((1, C4), (2, E4), (3, G4)):
        _send(b, 0x90 | ch, n, 100, ms=0)
    b.run_ms(40)
    assert _offsets(b) == {C4: 0, E4: JI[4], G4: JI[7]}


def test_adapt_with_the_arp_tunes_its_notes_to_the_held_chord(board):
    b = board
    b.uc.mem_write(PATCHES + ARP_ON, b"\x01")
    _mode(b, ADAPT)
    seen = {}
    _on(b, C4, E4, G4, ms=0)
    for _ in range(60):
        b.run_ms(10)
        seen.update(_offsets(b))
    assert seen == {C4: 0, E4: JI[4], G4: JI[7]}, seen
