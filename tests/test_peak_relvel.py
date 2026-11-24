"""Peak: release velocity as a per-voice mod source (Settings > RELEASE
VELOCITY > Source; patches/peak_mpe/relvel.c).

The matrix runs in the sound chip, whose sources are parameters 0x60 + n:
ExprPED1 is 0x62 and BrthPED2 0x63, which stock sends to every voice
(target 0x1A) on every tick. With Source set to one of them, that broadcast
stops and a note-off writes its velocity into the source of the voices it
releases, just before their release command (0x3F, command 3).
"""
import pytest

from test_peak_sim import FLAG, GLOBALS, PATCHES, _boot, _call, _send, _show, _voice_of, mpe_built  # noqa: F401

G_RELVEL = 0x4A
OFF, EXPR, BREATH = 0, 1, 2
EXPR_P, BREATH_P = 0x62, 0x63
BROADCAST = 0x1A
AMP_ENV = 0x3F
RELVEL_PAGE = 14                       # Settings: after ARP RATCHET

pytestmark = pytest.mark.slow


def _board(image, source):
    b = _boot(image)
    b.uc.mem_write(GLOBALS + G_RELVEL, bytes([source]))
    return b


def _writes(b):
    return [e for e in b.fpga.events if not e.read]


def _release(b, *msg):
    """Send a note-off; return the writes it caused, in order."""
    b.fpga.reset()
    _send(b, *msg, ms=5)
    return _writes(b)


def _released(ws):
    return {e.target for e in ws if e.target < 8 and e.param == AMP_ENV and e.value & 3 == 3}


def test_off_is_stock(mpe_built):
    b = _board(mpe_built.patched, OFF)
    _send(b, 0x90, 60, 100)
    ws = _release(b, 0x80, 60, 20)
    assert _released(ws)
    assert not [e for e in ws if e.target < 8 and e.param in (EXPR_P, BREATH_P)]
    assert [e for e in ws if e.target == BROADCAST and e.param == EXPR_P]
    assert [e for e in ws if e.target == BROADCAST and e.param == BREATH_P]


def test_expr_gets_the_release_velocity_before_the_release(mpe_built):
    b = _board(mpe_built.patched, EXPR)
    _send(b, 0x90, 60, 100)
    ws = _release(b, 0x80, 60, 20)
    voices = _released(ws)
    assert len(voices) == 1, voices
    v = voices.pop()
    order = [(e.param, e.value) for e in ws if e.target == v and e.param in (EXPR_P, AMP_ENV)]
    assert order[0] == (EXPR_P, 20 << 8), order            # the source first,
    assert order[1][0] == AMP_ENV and order[1][1] & 3 == 3  # then the release
    assert not [e for e in ws if e.target == BROADCAST and e.param == EXPR_P]   # no broadcast over it
    assert [e for e in ws if e.target == BROADCAST and e.param == BREATH_P]     # the other pedal as stock
    b.run_ms(50)
    assert not [e for e in _writes(b) if e.param == EXPR_P and e.target != v]


def test_breath_full_scale_and_note_on_velocity_zero(mpe_built):
    b = _board(mpe_built.patched, BREATH)
    _send(b, 0x90, 60, 100)
    ws = _release(b, 0x80, 60, 127)
    v = _released(ws).pop()
    assert [e.value for e in ws if e.target == v and e.param == BREATH_P] == [0x7FFF]
    assert not [e for e in ws if e.target == BROADCAST and e.param == BREATH_P]
    assert [e for e in ws if e.target == BROADCAST and e.param == EXPR_P]
    _send(b, 0x90, 62, 100)
    ws = _release(b, 0x90, 62, 0)                           # note-on velocity 0: the default 64
    v = _released(ws).pop()
    assert [e.value for e in ws if e.target == v and e.param == BREATH_P] == [64 << 8]


def test_chord_each_note_its_own_velocity(mpe_built):
    b = _board(mpe_built.patched, EXPR)
    _send(b, 0x90, 60, 100, 0x90, 64, 100, 0x90, 67, 100)
    got = {}
    for note, vel in ((60, 10), (64, 70), (67, 120)):
        ws = _release(b, 0x80, note, vel)
        v = _released(ws).pop()
        got[note] = [e.value >> 8 for e in ws if e.param == EXPR_P and e.target < 8]
        assert [e.target for e in ws if e.param == EXPR_P] == [v]
    assert got == {60: [10], 64: [70], 67: [120]}


def test_mpe_note_off_writes_only_its_channels_voice(mpe_built):
    b = _board(mpe_built.patched, EXPR)
    b.uc.mem_write(PATCHES + FLAG, b"\x01")
    _send(b, 0x91, 60, 100, 0x92, 60, 100, ms=40)           # note 60 on member channels 2 and 3
    v2, v3 = _voice_of(b, mpe_built.blob, 1), _voice_of(b, mpe_built.blob, 2)
    ws = _release(b, 0x81, 60, 33)
    assert [(e.target, e.value) for e in ws if e.param == EXPR_P] == [(v2, 33 << 8)]
    ws = _release(b, 0x82, 60, 99)
    assert [(e.target, e.value) for e in ws if e.param == EXPR_P] == [(v3, 99 << 8)]


def test_back_to_off_resumes_the_broadcast(mpe_built):
    b = _board(mpe_built.patched, EXPR)
    b.fpga.reset()
    b.run_ms(20)
    assert not [e for e in _writes(b) if e.target == BROADCAST and e.param == EXPR_P]
    b.uc.mem_write(GLOBALS + G_RELVEL, bytes([OFF]))
    b.fpga.reset()
    b.run_ms(20)
    assert [e for e in _writes(b) if e.target == BROADCAST and e.param == EXPR_P]


def test_setting_page(mpe_built):
    b = _boot(mpe_built.patched)
    b.uc.mem_write(GLOBALS + G_RELVEL, b"\x00")
    rows = _show(b, 8, RELVEL_PAGE, 0)
    assert rows[0].startswith("RELEASE VEL "), rows
    assert rows[1][:19].split() == ["Source", "Off"], rows
    _call(b, mpe_built.blob.address("mpe_ui_value_change"), 1)
    assert b.u8(GLOBALS + G_RELVEL) == EXPR
    assert _show(b, 8, RELVEL_PAGE, 0)[1][:19].split() == ["Source", "ExprPED1"]
    _call(b, mpe_built.blob.address("mpe_ui_value_change"), 5)
    assert b.u8(GLOBALS + G_RELVEL) == BREATH
    assert _show(b, 8, RELVEL_PAGE, 0)[1][:19].split() == ["Source", "BrthPED2"]
    rows = _show(b, 8, RELVEL_PAGE - 1, 0)
    assert rows[0].startswith("ARP RATCHET"), rows
