"""MPE conformance: the complete patch (core, expression, UI) under the
traffic of the user's senders and the MPE 1.0 edge cases (patches/mpe).

Every play runs under tests/mpe_traffic.py's Invariants: after every
main-loop pass that handled a message or ran a tick, the channel binding
against what the sender holds, per-voice pitch within osc_pitch's range and
without a jump a wrap would make, 0x60 in range and the FPGA queue below its
limit. At the quiet points the tests call ``expression()``: each voice's
0x000-0x002, AftTouch slot, 0x61 and 0x60 are what its own channel and the
master give. Emulated.

Senders: tests/mpe_traffic.py (Ableton Live via Push 3, Squarp Hapax), the
user's recordings in ``work/capture/`` when present (one pinned by SHA-256).
"""

import hashlib
import random
from pathlib import Path

import pytest

from mpe_sim import MODE, UNISON, mpe_summit
from mpe_traffic import (ChannelPool, Invariants, Zone, at, base_pitch_table, bend, cc, din_bytes, freeze, hapax,
                         live, mcm, mmon_events, note_off, note_on, play, pressure, reset_burst, rpn)

ROOT = Path(__file__).resolve().parent.parent
CAPTURES = ROOT / "work" / "capture"
# The recording test_live_capture_replays_cleanly is pinned to: Live's MPE
# output from Push 3, mashed with both hands (2026-11-07, run L4 of
# the MPE v1 hardware run, docs/hardware-log.md): 2,225 messages in 2.3 s, notes on
# members 2-16, CC 74, pressure and bend, no MCM, no reset burst. Over DIN
# one note stuck on the synth; the recording has every note-off.
CAPTURE = CAPTURES / "stuck note from ableton.mmon"
LIVE_CAPTURE_SHA256 = "1d3596f18695685e4a0e9d60a72b14a7f17f79176df96e069ecd0d1d469ad621"

QUICK = {
    "test_live_rotates_free_channels_least_recently_used_first",
    "test_din_bytes",
    "test_live_reset_burst_changes_nothing",
    "test_channel_reuse_before_release",
}


@pytest.fixture
def m(tmp_path_factory):
    return mpe_summit(tmp_path_factory).reset()


@pytest.fixture
def base(tmp_path_factory):
    return base_pitch_table(mpe_summit(tmp_path_factory))


def setup(m, zone=1, members=15):
    m.zone_setting(zone, members)
    m.flag()


def phrase(m, base, events, port="usb", freeze_at=None, din_kw=None):
    """Play events, stop the expression at freeze_at with the sounding notes
    held, check expression() at the quiet point, then release. Returns the
    checker (its hooks are gone) and how many voices were checked."""
    if freeze_at is None:
        freeze_at = max(t for t, _ in events) * 0.8
    events = freeze(events, freeze_at, 300)
    with Invariants(m, base=base) as inv:
        t0 = play(m.s, [e for e in events if e[0] <= freeze_at], port, din_kw=din_kw)
        inv.settle(220)
        checked = inv.expression()
        play(m.s, [e for e in events if e[0] > freeze_at], port, t0=t0, din_kw=din_kw)
        inv.all_released()
    return inv, checked


# -- the senders themselves ---------------------------------------------------------------


def test_live_rotates_free_channels_least_recently_used_first():
    assert Zone("lower", 15).channels == list(range(2, 17))
    assert Zone("upper", 5).channels == [15, 14, 13, 12, 11]
    pool = ChannelPool([2, 3, 4])
    assert [pool.take(0), pool.take(1)] == [2, 3]
    pool.give(2)
    assert [pool.take(2), pool.take(3)] == [4, 2]
    assert pool.take(4) == 3  # all busy: the oldest note's channel again, before its note-off
    ev = live(Zone("lower", 15), random.Random(3), 10, master=False, burst=False)
    first = [e for e in ev if e[1][0] & 0xF0 == 0x90][0]
    before = [m for t, m in ev if t == first[0] and m[0] & 0x0F == first[1][0] & 0x0F]
    assert [m[0] & 0xF0 for m in before[:4]] == [0xD0, 0xB0, 0xE0, 0x90]  # the capture's order


def test_din_bytes():
    ev = [(0, bend(2, 0)), (1, bend(2, 100)), (2, cc(2, 74, 3)), (3, cc(2, 74, 4))]
    assert b"".join(d for _, d in din_bytes(ev)) == bytes.fromhex("e1 00 40 64 40 b1 4a 03 4a 04")
    chunks = din_bytes(ev, clock_ms=1, sysex_ms=2)
    stream = b"".join(d for _, d in chunks)
    assert stream.count(0xF8) == 4 and stream.count(0xF0) == 1
    after = stream[stream.index(0xF7) + 1:].replace(b"\xf8", b"")
    assert after[0] == 0xB1  # running status starts again after the SysEx


# -- the user's capture --------------------------------------------------------------------


def test_live_reset_burst_changes_nothing(m):
    """The capture starts with 16 x E0 00 40 on channel 1 (the master): with
    nothing playing, the voices' registers and the part bend stay as they
    were."""
    setup(m)
    m.s.tick(50)  # the Slide module's first per-voice 0x60 sends are done
    s = m.s
    def regs():
        return {k: v for k, v in s.fpga_state().items() if k[1] < 0x10 or k[2] in (0x68, 0x69, 0x868, 0x869)}
    before, bend_before = regs(), s.part_bend(0)
    with Invariants(m) as inv:
        play(s, reset_burst(0, 1), "usb", until=60)
        assert inv.handled == 16
    assert regs() == before and s.part_bend(0) == bend_before == 0
    assert s.active_voices() == []


@pytest.mark.parametrize("port", ["usb", "din"])
def test_live_capture_replays_cleanly(m, base, port):
    """The L4 recording (Live on Lower 15, the Settings Lower 15), over USB
    and over DIN at 31,250 baud, gaps over 30 ms shortened, up to its last
    note-on; the notes held then are checked at a quiet point and released.
    On the synth one note stuck over DIN; here every note must play and
    release (emulated)."""
    capture = pinned_capture(CAPTURE, LIVE_CAPTURE_SHA256)
    setup(m)
    events = mmon_events(capture, max_gap_ms=30)
    ons = [t for t, msg in events if msg[0] & 0xF0 == 0x90 and msg[2]]
    assert {(msg[0] & 0x0F) + 1 for _, msg in events if msg[0] & 0xF0 == 0x90} == set(range(2, 17))
    assert len(ons) == 160
    inv, checked = phrase(m, base, events, port=port, freeze_at=max(ons))
    assert inv.handled > 1500 and checked >= 1


def pinned_capture(path, sha256):
    """The user's capture at *path* if it is the exact recording a test was
    written for; otherwise the test skips (recordings in work/ are the
    user's and change; never committed)."""
    rel = path.relative_to(ROOT)
    if not path.exists():
        pytest.skip(f"{rel} not present (the user's capture, never committed); expected sha256 {sha256}")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != sha256:
        pytest.skip(f"{rel}: capture changed; expected sha256 {sha256}, found {actual}")
    return path


def any_captures():
    found = sorted(CAPTURES.glob("*.mmon")) if CAPTURES.is_dir() else []
    return [pytest.param(p, id=p.name) for p in found] or [pytest.param(None, id="none")]


@pytest.mark.parametrize("capture", any_captures())
def test_any_capture_replays_without_violations(m, base, capture):
    """Whatever recordings are in work/capture/ (any content, any hash):
    their channel messages, both directions, the first 1.5 s with gaps over
    30 ms shortened, into an MPE patch on Lower 15, under the invariant
    checker; then nothing may sound. A recording with no notes, or no MPE,
    simply passes. SysEx is left out (a firmware update capture)."""
    if capture is None:
        pytest.skip("no .mmon in work/capture/")
    events = mmon_events(capture, max_gap_ms=30, directions=(">", "<"), channel_only=True)
    if not events:
        pytest.skip(f"{capture.name}: no channel messages")
    sounding = set()  # a recording can stop with notes held: release them at its end
    for _, msg in events:
        if msg[0] & 0xF0 == 0x90 and msg[2]:
            sounding.add((msg[0] & 0x0F, msg[1]))
        elif msg[0] & 0xF0 in (0x80, 0x90):
            sounding.discard((msg[0] & 0x0F, msg[1]))
    end = events[-1][0]
    events += [(end, bytes([0x80 | ch, note, 0])) for ch, note in sorted(sounding)]
    setup(m)
    phrase(m, base, events, freeze_at=min(1500, end))


# -- Ableton Live ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind,setting", [("lower", 1), ("upper", 2)])
def test_live_zone_without_mcm(m, base, kind, setting):
    """Live sends no MCM: the Settings layout has to match its zone."""
    setup(m, setting, 15)
    inv, checked = phrase(m, base, live(Zone(kind, 15), random.Random(1), 20, span_ms=300), freeze_at=200)
    assert checked >= 5 and inv.handled > 400


def test_live_into_a_smaller_settings_zone(m, base):
    """Live on Lower 15, the Settings on Lower 5: notes on channels 7-16 are
    outside the zone and Single mode drops them (not the global channel);
    the rest plays per note. Nothing sticks."""
    setup(m, 1, 5)
    phrase(m, base, live(Zone("lower", 15), random.Random(2), 20, span_ms=300))


# -- Squarp Hapax ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["lower", "upper"])
def test_hapax_with_mcm_overrides_the_settings(m, base, kind):
    setup(m, 2 if kind == "lower" else 1, 3)  # the other zone in the Settings
    inv, checked = phrase(m, base, hapax(Zone(kind, 14), random.Random(4), 20, span_ms=300))
    zones = m.zones()
    assert list(zones) == [kind] and zones[kind][1] == (1 if kind == "lower" else 16)
    assert checked >= 3


def test_hapax_without_mcm(m, base):
    setup(m, 1, 14)
    phrase(m, base, hapax(Zone("lower", 14), random.Random(5), 20, span_ms=300, mcm_first=False, tracks=2))


@pytest.mark.parametrize("shared", [True, False])
def test_hapax_four_tracks_on_one_output(m, base, shared):
    """Four MPE tracks in one Upper zone. Not shared: their rotations collide
    and reuse channels before the release."""
    setup(m, 2, 14)
    phrase(m, base, hapax(Zone("upper", 14), random.Random(6), 32, span_ms=300, tracks=4, shared_pool=shared))


# -- edge cases ------------------------------------------------------------------------------


def test_mcm_changes_the_layout_mid_performance(m, base):
    """15 notes held in Lower 15; an MCM for Upper 7 shrinks Lower to 2-8.
    The voices on 9-15 lose their zone (stock role: no per-note bend) but
    stay bound and release by their note-offs; the others keep theirs."""
    setup(m)
    s = m.s
    ev = [(i * 2, bend(2 + i, 1000 * i - 6000)) for i in range(15)] + \
         [(i * 2 + 1, note_on(2 + i, 40 + i)) for i in range(15)]
    with Invariants(m, base=base) as inv:
        play(s, ev)
        inv.settle(220)
        assert inv.expression() == 15
        play(s, at(0, mcm(16, 7)))
        assert m.zones() == {"lower": (0, 1, 2, 8), "upper": (0, 16, 9, 15)}
        play(s, [(0, bend(10, 5000)), (0, bend(3, -5000)), (0, cc(16, 1, 60))])
        inv.settle(220)
        assert inv.expression() == 15  # channels 9-15 are Upper members now
        play(s, at(0, mcm(1, 0)) + at(0, mcm(16, 0)))  # both zones gone: Lower 15 again
        play(s, [(i, note_off(2 + i, 40 + i)) for i in range(15)])
        inv.all_released()


def test_rpn_0_on_member_and_master_channels(m, base):
    setup(m)
    s = m.s
    with Invariants(m, base=base) as inv:
        play(s, [(0, bend(2, 4096)), (0, note_on(2, 60)), (0, bend(1, -4096)), (1, note_on(3, 64))])
        play(s, at(0, rpn(5, 0, 0, 12)) + at(5, rpn(1, 0, 0, 7)))  # member 5: note range; master: master range
        assert m.live()["note_range"][0] == 12 and m.live()["master_range"][0] == 7
        inv.settle(400)  # the master bend's stock smoother
        assert inv.expression() == 2
        play(s, [(0, note_off(2, 60)), (0, note_off(3, 64)), (0, bend(1, 0))])
        inv.all_released()


def test_channel_reuse_before_release(m, base):
    setup(m)
    s = m.s
    with Invariants(m, base=base) as inv:
        play(s, [(0, note_on(2, 60)), (5, bend(2, 3000)), (10, note_on(2, 67)), (12, note_on(3, 60))])
        assert len(m.bound(2)) == 1 and s.voice_note(m.bound(2)[0]) == 67
        play(s, [(0, note_off(2, 60))])  # the first note's off: 67 keeps sounding, 60 on 3 too
        assert len(m.bound(2)) == 1 and len(m.bound(3)) == 1
        inv.settle(220)
        assert inv.expression() == 2
        play(s, [(0, note_off(2, 67)), (0, note_off(3, 60))])
        inv.all_released()


def test_more_notes_than_voices_with_unison(m, base):
    """Unison 1 (two voices a note) and 30 notes on all 16 channels, master
    included: stealing moves the bindings with the voices."""
    setup(m)
    m.s.set_patch_byte(UNISON, 1)
    ev = []
    for i in range(30):
        ch = 1 + i % 16
        ev += [(i * 3, bend(ch, (i * 1234) % 16000 - 8000)), (i * 3, note_on(ch, 30 + i))]
    with Invariants(m, base=base) as inv:
        play(m.s, ev)
        inv.settle(220)
        assert inv.expression() == 16
        play(m.s, [(i * 0.5, note_off(1 + i % 16, 30 + i)) for i in range(30)])
        inv.all_released()


def test_sustain_on_the_master_channel(m, base):
    """Two channels hold note 60; the pedal keeps the one released, lifting
    it releases only that one. A channel reused under the pedal takes its
    voice over."""
    setup(m)
    s = m.s
    with Invariants(m, base=base) as inv:
        play(s, [(0, note_on(2, 60)), (0, note_on(3, 60)), (5, cc(1, 64, 127)), (10, note_off(2, 60)),
                 (20, bend(3, 3000)), (30, bend(2, -3000))])
        inv.settle(220)
        assert inv.expression() == 2 and len(s.active_voices()) == 2
        play(s, [(0, note_on(4, 62)), (2, note_off(4, 62)), (10, note_on(4, 65))])  # 4 reused under the pedal
        assert len(m.bound(4)) == 1 and s.voice_note(m.bound(4)[0]) == 65
        play(s, [(0, cc(1, 64, 0))], until=20)
        assert sorted(s.voice_note(v) for v in s.active_voices()) == [60, 65]
        assert m.bound(3) and not m.bound(2)
        play(s, [(0, note_off(3, 60)), (0, note_off(4, 65))])
        inv.all_released()


@pytest.mark.parametrize("ch,num", [(1, 123), (5, 123), (1, 120), (5, 120)])
def test_all_notes_off_and_all_sound_off(m, base, ch, num):
    """CC 123 / 120 on the master or a member channel: the zone's part
    stops every note."""
    setup(m)
    with Invariants(m, base=base) as inv:
        play(m.s, [(i, note_on(2 + i, 50 + i)) for i in range(6)] + [(20, cc(ch, num, 0))], until=40)
        assert m.s.active_voices() == []
        inv.all_released()


def test_notes_on_non_member_channels(m, base):
    """Lower 5 (master 1, members 2-6): channels 7-16 aren't in the zone. In
    Single mode only the global channel plays outside it, and it is the
    master here, so they're dropped."""
    setup(m, 1, 5)
    with Invariants(m, base=base) as inv:
        play(m.s, [(0, note_on(10, 60)), (1, note_on(3, 62)), (2, note_on(16, 64)), (3, bend(10, 5000))])
        assert [m.s.voice_note(v) for v in m.s.active_voices()] == [62]
        inv.settle(220)
        assert inv.expression() == 1
        play(m.s, [(0, note_off(10, 60)), (0, note_off(3, 62)), (0, note_off(16, 64))])
        inv.all_released()


@pytest.mark.parametrize("mode", [0, 1, 2])
def test_mono_and_legato_follow_the_sounding_channel(m, base, mode):
    setup(m)
    m.s.set_patch_byte(MODE, mode)
    with Invariants(m, base=base) as inv:
        play(m.s, [(0, bend(2, 4000)), (0, note_on(2, 60)), (20, bend(3, -4000)), (25, note_on(3, 64)),
                   (50, note_on(4, 67)), (80, note_off(3, 64))])
        inv.settle(220)
        assert inv.expression() == 1
        play(m.s, [(0, note_off(4, 67))])  # back to 60 on channel 2, bent by its +4000
        inv.settle(220)
        assert inv.expression() == 1 and m.bound(2)
        play(m.s, [(0, note_off(2, 60))])
        inv.all_released()


def test_din_running_status_clock_and_sysex(m, base):
    """Live's traffic over DIN with running status, a clock every 5 ms (also
    in the middle of messages) and a SysEx for another device every 60 ms."""
    setup(m)
    ev = live(Zone("lower", 15), random.Random(7), 10, span_ms=300)
    inv, checked = phrase(m, base, ev, port="din", freeze_at=200, din_kw=dict(clock_ms=5, sysex_ms=60))
    assert checked >= 2


def test_pressure_and_slide_before_the_note_on(m, base):
    """MPE senders set a channel's expression just before its note-on: the
    note starts with it."""
    setup(m)
    with Invariants(m, base=base) as inv:
        play(m.s, [(0, pressure(6, 90)), (0, cc(6, 74, 100)), (0, bend(6, -2000)), (0, note_on(6, 70))])
        inv.settle(220)
        assert inv.expression() == 1
        play(m.s, [(0, note_off(6, 70))])
        inv.all_released()


for _name, _test in list(globals().items()):
    if _name.startswith("test_") and _name not in QUICK:
        globals()[_name] = pytest.mark.slow(_test)
