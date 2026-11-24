"""Peak: the section randomiser (Settings > RANDOMISE; patches/peak_mpe/rand.c).

A roll writes one section's controls through stock's setter, each inside its
safe range (switches from their useful values), and then holds the patch to
the checks of that section. The ranges below restate rand.c's table: a
change to one of them must be made in both places.
"""
import pytest

from test_peak_sim import GLOBALS, MOD_PRESS, PATCHES, _boot, _call, _show, mpe_built  # noqa: F401

S_OSC1, S_OSC2, S_OSC3, S_MIXER, S_FILTER, S_AMP, S_ENV1, S_ENV2, S_LFO1, S_LFO2, S_FX, S_ALL = range(12)
NAMES = ["Osc 1", "Osc 2", "Osc 3", "Mixer", "Filter", "Amp Env", "Mod Env1", "Mod Env2", "LFO 1", "LFO 2",
         "FX", "All"]
G_RAND_SECT, G_RAND_AMT, G_RAND_ROLL = 0x4B, 0x4C, 0x4D
G_ENVSYNC = 0x35
RAND_PAGE = 15                         # Settings: after RELEASE VEL
COMPARE_HELD = 0x200111F2
UNDO_LEFT = (34 << 8) | 1
PATCH_LOAD, INIT_PATCH = 0x0801AEB8, 0x08043160
G_LOCK_FX = 0x36

pytestmark = pytest.mark.slow


def _osc(b, coarse):
    t = {b + 3: ("h", 118, 138), b + 8: ("pick", 0, 4), b + 9: ("pick", 4, 63), b + 0xB: ("c", 16, 112),
         b + 0xC: ("c", 40, 88), b + 0xD: ("c", 40, 88), b + 0xE: ("c", 0, 64), b + 0xF: ("c", 0, 127),
         b + 0x10: ("c", 0, 127)}
    t[b] = ("list", [63, 64, 65] if not coarse else [63, 64, 65, 66])
    if coarse:
        t[b + 1] = ("hlist", [128, 203, 74, 255, 0, 182])
    return t


def _env(b):
    return {b: ("c", 0, 100), b + 1: ("c", 0, 110), b + 2: ("c", 0, 127), b + 3: ("c", 0, 110),
            b + 4: ("c", 24, 104), b + 6: ("c", 0, 40)}


def _lfo(b):
    return {b: ("h", 40, 220), b + 3: ("pick", 0, 3), b + 5: ("c", 0, 80), b + 6: ("c", 0, 80)}


SECTIONS = {
    S_OSC1: _osc(0x30, False), S_OSC2: _osc(0x45, True), S_OSC3: _osc(0x5A, True),
    S_MIXER: {0x6F: ("h", 0, 255), 0x71: ("h", 0, 255), 0x73: ("h", 0, 255), 0x75: ("h", 0, 160),
              0x77: ("h", 0, 120)},
    S_FILTER: {0x7D: ("c", 0, 64), 0x7E: ("c", 0, 48), 0x7F: ("pick", 0, 1), 0x80: ("list", [0, 1, 2]),
               0x81: ("c", 32, 127), 0x82: ("c", 0, 96), 0x83: ("h", 0, 255), 0x85: ("h", 88, 168),
               0x87: ("c", 0, 40), 0x89: ("c", 40, 110), 0x8A: ("c", 40, 110), 0x8B: ("c", 0, 64)},
    S_AMP: {0x92: ("c", 0, 72), 0x93: ("c", 20, 110), 0x94: ("c", 0, 127), 0x95: ("c", 10, 96),
            0x96: ("c", 64, 104)},
    S_ENV1: _env(0x9B), S_ENV2: _env(0xA3), S_LFO1: _lfo(0xAC), S_LFO2: _lfo(0xBA),
    S_FX: {0xC7: ("c", 0, 48), 0xCC: ("c", 0, 80), 0xCD: ("c", 20, 127), 0xCF: ("c", 64, 127),
           0xD2: ("c", 0, 90), 0xD9: ("c", 0, 80), 0xDA: ("pick", 0, 2), 0xDB: ("c", 40, 110),
           0xDE: ("c", 40, 127), 0xE5: ("c", 0, 80), 0xE6: ("pick", 0, 2), 0xE7: ("c", 0, 90),
           0xE8: ("c", 20, 127), 0xE9: ("c", 40, 88), 0xEC: ("pick", 0, 2)},
}
ALL = {o: r for s in SECTIONS.values() for o, r in s.items()}


def _bytes(t):
    """The patch bytes a section's controls occupy (two for a 9-bit control)."""
    out = set()
    for o, r in t.items():
        out.add(o)
        if r[0] in ("h", "hlist"):
            out.add(o + 1)
    return out


def _patch(b):
    return bytes(b.uc.mem_read(PATCHES, 0x1A2))


def _v(p, o, kind):
    return (p[o] * 2 + (p[o + 1] >> 6)) & 0xFF if kind in ("h", "hlist") else p[o]


def _in_range(p, t):
    bad = {}
    for o, r in t.items():
        v = _v(p, o, r[0])
        ok = v in r[1] if r[0] in ("list", "hlist") else r[1] <= v <= r[2]
        if not ok:
            bad[hex(o)] = v
    return bad


def _checks(p, section):
    h = lambda o: _v(p, o, "h")  # noqa: E731
    out = {}
    if section in (S_MIXER, S_ALL):
        lv = [h(0x6F), h(0x71), h(0x73), h(0x75), h(0x77)]
        out["mixer"] = (max(lv[:3]) >= 100 or lv[4] >= 160) and sum(lv) <= 420
    if section in (S_FILTER, S_ALL):
        c, shape = h(0x83), p[0x80]
        ok = not (p[0x82] > 80 and p[0x7E] > 24)
        if shape == 0:
            ok &= c >= 90 or (c >= 40 and p[0x89] >= 80)
        elif shape == 1:
            ok &= 64 <= c <= 150 and p[0x82] >= 40 and 48 <= p[0x89] <= 80
        else:
            ok &= c <= 110
        out["filter"] = ok
    if section in (S_AMP, S_ALL):
        out["amp"] = p[0x92] <= 80 and (p[0x94] >= 48 or p[0x93] >= 60)
    if section in (S_FX, S_ALL):
        out["fx"] = p[0xCC] + p[0xD9] + p[0xE5] <= 170 and p[0xC7] <= 64 and p[0xD2] <= 100
    return out


def _roll(b, blob, section, amount):
    b.run_ms(3)                                    # a new tick count stirs the generator
    return _call(b, blob.address("rand_roll"), section, amount)


@pytest.fixture(scope="module")
def board(mpe_built):
    return _boot(mpe_built.patched)


def test_a_roll_changes_only_its_section(board, mpe_built):
    b, blob = board, mpe_built.blob
    for s in range(S_ALL):
        before = _patch(b)
        n = _roll(b, blob, s, 10)
        after = _patch(b)
        changed = {o for o in range(0x1A2) if before[o] != after[o]}
        assert changed <= _bytes(SECTIONS[s]), (NAMES[s], sorted(hex(o) for o in changed - _bytes(SECTIONS[s])))
        assert n >= 1, NAMES[s]
        assert not _in_range(after, SECTIONS[s]) or s == S_FILTER, (NAMES[s], _in_range(after, SECTIONS[s]))


def test_osc1_coarse_stays_put(board, mpe_built):
    b, blob = board, mpe_built.blob
    before = _patch(b)[0x31:0x33]
    for _ in range(10):
        _roll(b, blob, S_OSC1, 10)
    assert _patch(b)[0x31:0x33] == before


def test_full_rolls_of_everything_stay_in_range_and_pass_the_checks(board, mpe_built):
    b, blob = board, mpe_built.blob
    shapes = set()
    for _ in range(40):
        _roll(b, blob, S_ALL, 10)
        p = _patch(b)
        bad = {o: v for o, v in _in_range(p, ALL).items() if o != hex(0x83)}
        assert not bad, bad
        assert all(_checks(p, S_ALL).values()), _checks(p, S_ALL)
        shapes.add(p[0x80])
    assert shapes == {0, 1, 2}                      # the switches do move


def test_band_pass_keeps_the_note_and_brings_resonance(board, mpe_built):
    """v0.27, from the rig (findings, "Value scales for the randomiser"):
    band-pass cutoff 64-150 with resonance 40-96 and a small amp envelope
    depth; high-pass cutoff at most 110."""
    b, blob = board, mpe_built.blob
    band = 0
    for _ in range(60):
        _roll(b, blob, S_FILTER, 10)
        p = _patch(b)
        c = _v(p, 0x83, "h")
        if p[0x80] == 1:
            band += 1
            assert 64 <= c <= 150 and 40 <= p[0x82] <= 96 and 48 <= p[0x89] <= 80, (c, p[0x82], p[0x89])
        elif p[0x80] == 2:
            assert c <= 110, c
    assert band >= 3


def test_a_small_amount_only_nudges(board, mpe_built):
    b, blob = board, mpe_built.blob
    _roll(b, blob, S_ALL, 10)
    for _ in range(5):
        before = _patch(b)
        _roll(b, blob, S_ENV1, 1)                   # no checks for a mod envelope: only the nudge
        after = _patch(b)
        for o, (kind, lo, hi) in SECTIONS[S_ENV1].items():
            v0, v1 = _v(before, o, kind), _v(after, o, kind)
            assert abs(v1 - v0) <= (max(hi - v0, v0 - lo) + 9) // 10, (hex(o), v0, v1)


def test_below_100_percent_a_check_the_patch_failed_is_left_alone(board, mpe_built):
    b, blob = board, mpe_built.blob
    for _ in range(5):
        b.uc.mem_write(PATCHES + 0x92, bytes([10, 10, 0]))   # attack 10, decay 10, sustain 0: fails "amp"
        _roll(b, blob, S_AMP, 1)
        assert b.u8(PATCHES + 0x93) < 60                     # a nudge, not a repair
    b.uc.mem_write(PATCHES + 0x92, bytes([10, 10, 0]))
    _roll(b, blob, S_AMP, 10)
    assert _checks(_patch(b), S_AMP)["amp"]                  # at 100 % the result always passes


def test_a_nudge_never_breaks_a_check_the_patch_passed(board, mpe_built):
    b, blob = board, mpe_built.blob
    for _ in range(30):
        b.uc.mem_write(PATCHES + 0x92, bytes([0, 30, 50]))   # passes (sustain 50), close to failing
        _roll(b, blob, S_AMP, 5)
        assert _checks(_patch(b), S_AMP)["amp"], _patch(b)[0x92:0x97].hex()


def test_envsync_keeps_the_amp_decay_and_release(board, mpe_built):
    b, blob = board, mpe_built.blob
    b.uc.mem_write(GLOBALS + G_ENVSYNC, b"\x02")
    try:
        for _ in range(10):
            b.uc.mem_write(PATCHES + 0x93, bytes([5]))
            b.uc.mem_write(PATCHES + 0x95, bytes([7]))
            b.uc.mem_write(PATCHES + 0x94, bytes([0]))
            _roll(b, blob, S_AMP, 10)
            p = _patch(b)
            assert (p[0x93], p[0x95]) == (5, 7)
            assert p[0x94] >= 48                              # the check takes the sustain instead
    finally:
        b.uc.mem_write(GLOBALS + G_ENVSYNC, b"\x00")


def test_page_roll_message_and_undo(mpe_built):
    b = _boot(mpe_built.patched)
    blob = mpe_built.blob
    rows = _show(b, 8, RAND_PAGE, 0)
    assert rows[0].startswith("RANDOMISE"), rows
    assert rows[1][:19].split() == ["Section", "Osc", "1"], rows
    assert rows[2][:19].split() == ["Amount", "50%"], rows
    assert rows[3][:19].split() == ["Roll", "Off"], rows
    _call(b, blob.address("mpe_ui_value_change"), 4)            # Section: Filter
    rows = _show(b, 8, RAND_PAGE, 1)
    assert rows[1][:19].split() == ["Section", "Filter"], rows
    _call(b, blob.address("mpe_ui_value_change"), 9)            # Amount: 100 %
    rows = _show(b, 8, RAND_PAGE, 2)
    assert rows[2][:19].split() == ["Amount", "100%"], rows
    before = _patch(b)
    _call(b, blob.address("mpe_ui_value_change"), 1)            # Roll
    b.run_ms(1)
    rows = b.display.lcd.text()
    assert rows[0].startswith("RANDOMISE") and rows[1].startswith("Filter"), rows
    assert "changed" in rows[2] and rows[3].startswith("Undo: Mod+Page left"), rows
    assert _patch(b) != before
    _call(b, blob.address("mpe_ui_value_change"), -1)           # turning down: nothing
    _call(b, blob.address("qa_button"), MOD_PRESS)
    _call(b, blob.address("edit_button"), UNDO_LEFT)
    assert _patch(b) == before
    _call(b, blob.address("rand_edit"), G_RAND_AMT, -20)
    assert _call(b, blob.address("rand_amount")) == 1
    _call(b, blob.address("rand_edit"), G_RAND_SECT, 20)
    assert _show(b, 8, RAND_PAGE, 0)[1][:19].split() == ["Section", "All"]


def test_no_roll_during_compare(mpe_built):
    b = _boot(mpe_built.patched)
    blob = mpe_built.blob
    before = _patch(b)
    b.uc.mem_write(COMPARE_HELD, b"\x01")
    _call(b, blob.address("rand_edit"), G_RAND_ROLL, 1)
    assert "Not during Compare" in "\n".join(b.display.lcd.text())
    assert _patch(b) == before


def test_param_lock_chorus_mode_is_fx(mpe_built):
    """0xEC is the chorus Mode (Chorus/Flanger/Phlanger); v0.25 locked it with the arp."""
    b = _boot(mpe_built.patched)
    b.uc.mem_write(PATCHES + 0xEC, b"\x02")
    b.uc.mem_write(GLOBALS + G_LOCK_FX, bytes([1, 0, 0]))       # Lock FX
    _call(b, PATCH_LOAD, INIT_PATCH)
    assert b.u8(PATCHES + 0xEC) == 2
    b.uc.mem_write(GLOBALS + G_LOCK_FX, bytes([0, 1, 0]))       # Lock Arp only
    _call(b, PATCH_LOAD, INIT_PATCH)
    assert b.u8(PATCHES + 0xEC) != 2
    b.uc.mem_write(GLOBALS + G_LOCK_FX, bytes([1, 1, 1]))       # all three: 66 bytes kept
    for o, v in ((0xC7, 11), (0xEC, 1), (0xED, 90), (0xFA, 1), (0x22, 2), (0x2F, 1)):
        b.uc.mem_write(PATCHES + o, bytes([v]))
    _call(b, PATCH_LOAD, INIT_PATCH)
    assert [b.u8(PATCHES + o) for o in (0xC7, 0xEC, 0xED, 0xFA, 0x22, 0x2F)] == [11, 1, 90, 1, 2, 1]


def test_mixer_rolls_keep_a_loud_oscillator_within_the_headroom(board, mpe_built):
    """Mixer rolls at 100 % pass the mixer check. (v0.30's mixer_fix change was
    found by the full-roll test above, one roll in 40; this one doesn't hit
    that case with the old code: coverage, not a regression test.)"""
    b, blob = board, mpe_built.blob
    for _ in range(150):
        _roll(b, blob, S_MIXER, 10)
        assert _checks(_patch(b), S_MIXER)["mixer"]
