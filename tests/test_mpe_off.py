"""MPE off everywhere: the patched Summit plays exactly as stock (patches/mpe).

With the flag 0 in every patch, the MPE patch must not change anything the
synth does, even with a zone configured in the Settings and with RPN 6 /
RPN 0 arriving. One varied sequence goes to the stock image and to the
patch, over DIN and USB, in Single and Multi mode: chords, unison, mono and
legato, sustain, bend, pressures, CCs, NRPN, RPN (including stock's CC 6 to
the last NRPN), notes on other channels. Emulated.

What "identical" means here, checked at every quiet point of the sequence
(a pause of QUIET_MS or more) and at the end:
* the notes sounding, per engine, and every settled register of their
  voices (pitch, velocity, aftertouch, mod wheel, ...), matched by note:
  the same voices with the same values, whichever voice index each got;
* every settled broadcast and part register (target >= 0x10);
* the MIDI out: the same bytes in the same order;
* the final FPGA state, and nothing left playing.
Settled: unchanged for the last SETTLE_MS in that run. A register still
moving at a quiet point (an LFO, an envelope) is compared where it rests.

Not compared: the exact sequence of values written between those points,
and event times. Those depend on where in a millisecond each input and each
main-loop pass falls, for stock itself: stock against stock with the input
moved 50-100 µs gives 15-84 registers with a different value sequence
(MPE step 3, 2026-11-01), because writers that share a register (both parts,
the per-tick rotations) interleave differently, smoothing starts a tick
earlier or later, and EXTI15-timed envelope reads steer voice allocation.
The patch's code changes main-loop timing a little, so those sequences
would differ by chance, not by behaviour. With MPE off the patch's wrappers
pass every call through unchanged and only write patch RAM. For the same
reason the steal burst is spaced by 4 ms.
"""

import pytest

import collections
from mpe_sim import FLAG, G_MEMBERS, G_ZONE, built, mpe_summit, stock_summit

pytestmark = pytest.mark.slow  # plays a long sequence on two images


def rpn(s, ch, msb, lsb, value, port="din"):
    c = 0xB0 | (ch - 1)
    s.midi_in([c, 101, msb, c, 100, lsb, c, 6, value], port=port)


def play(s):
    s.set_soft_thru(True)
    s.set_cc_nrpn_receive(True)
    s.set_global(G_MEMBERS, 5, run_ms=0)
    s.set_global(G_ZONE, 1)  # a Lower Zone configured, every flag 0
    for n in (60, 64, 67):
        s.note_on(n)
    s.tick(20)
    s.note_on(72, channel=2)  # other channels: dropped in Single mode
    s.note_on(74, channel=16)
    s.bend(4096)
    s.tick(15)
    s.channel_pressure(80)
    s.poly_pressure(64, 50)
    s.cc(1, 90)
    s.cc(74, 30)
    s.cc(74, 30, channel=3)
    s.tick(20)
    s.cc(64, 127)
    for n in (60, 64, 67):
        s.note_off(n)
    s.tick(10)
    s.cc(64, 0)
    s.bend(0)
    s.tick(30)
    s.nrpn(0, 3, 1)  # Unison 1: two voices per note
    s.tick(5)
    rpn(s, 1, 0, 0, 12)  # RPN 0: stock applies the 12 to the last NRPN, Unison (range-checked)
    rpn(s, 1, 0, 6, 3)  # an MCM on channel 1: the same, Unison 3
    rpn(s, 16, 0, 6, 4)  # on channel 16: not the global channel, dropped
    s.tick(5)
    for n in (48, 55):
        s.note_on(n, port="usb")
    s.tick(20)
    s.note_off(48, port="usb")
    s.note_off(55)
    s.tick(20)
    s.nrpn(0, 3, 0)
    s.nrpn(0, 2, 1)  # MonoLG
    s.tick(5)
    s.note_on(60)
    s.tick(10)
    s.note_on(62)  # legato
    s.tick(10)
    s.note_off(62)  # back to 60
    s.tick(10)
    s.note_off(60)
    s.tick(20)
    s.nrpn(0, 2, 3)  # Poly
    s.tick(5)
    for i in range(18):  # steal; spaced, so the choice doesn't hinge on sub-ms timing
        s.note_on(40 + i, velocity=60 + i)
        s.tick(4)
    s.tick(30)
    s.cc(123, 0)
    s.tick(20)
    # Multi: Part A channel 1, Part B 2, the global channel 16.
    s.set_mode("multi")
    s.set_channels(global_=16, part_a=1, part_b=2)
    s.note_on(60, channel=1)
    s.note_on(64, channel=2)
    s.note_on(67, channel=16)  # split/layer to both parts
    s.note_on(70, channel=5)  # no part: dropped
    s.tick(20)
    s.bend(-3000, channel=2)
    s.channel_pressure(70, channel=1)
    rpn(s, 1, 0, 6, 2)
    rpn(s, 16, 0, 6, 2)
    s.tick(20)
    for ch, n in ((1, 60), (2, 64), (16, 67)):
        s.note_off(n, channel=ch)
    s.tick(20)
    s.set_mode("single")
    s.set_channels(global_=1)
    s.note_on(65)
    s.tick(10)
    s.note_off(65)
    s.tick(300)


QUIET_MS = 20   # a pause this long or longer in play() is a checkpoint
SETTLE_MS = 12  # unchanged this long at a checkpoint: settled (aftertouch is resent every 8 ms)


class Checkpoints:
    """The simulator, noting after every pause of QUIET_MS or more the time
    and the sounding voices (voice, note)."""

    def __init__(self, s):
        self.s = s
        self.points = []

    def __getattr__(self, name):
        return getattr(self.s, name)

    def tick(self, ms=1):
        self.s.tick(ms)
        if ms >= QUIET_MS:
            self.note()

    def note(self):
        self.points.append((self.s.time_ms, [(v, self.s.voice_note(v)) for v in self.s.active_voices()]))


def record(s):
    s.reset()
    c = Checkpoints(s)
    play(c)
    c.note()
    assert all(s.patch_byte(FLAG, p) == 0 for p in (0, 1))
    return {"events": s.fpga_events(), "state": s.fpga_state(), "points": c.points,
            "midi": [(m.time_ms, m.port, m.data) for m in s.midi_out()], "voices": s.active_voices()}


def history(events):
    """(engines, target, param) -> [(time_ms, value)], broadcasts ever sent to
    both engines keyed "AB" (the engine select of a queued broadcast is
    timing, see tests/bend_play.py)."""
    both = {(e.target, e.param) for e in events if e.engines == "AB" and e.target >= 0x10}
    out = collections.defaultdict(list)
    for e in events:
        engines = "AB" if (e.target, e.param) in both else e.engines
        out[(engines, e.target, e.param)].append((e.time_ms, e.value))
    return out


def settled_at(writes, t):
    """The value at time t if it hasn't changed for SETTLE_MS, else None."""
    value, since = None, None
    for time, v in writes:
        if time > t:
            break
        if v != value:
            value, since = v, time
    return value if since is not None and t - since >= SETTLE_MS else None


def snapshot(run, point):
    """What a checkpoint compares: the sounding voices by (engine, note) with
    their settled registers, and the settled broadcast/part registers."""
    t, sounding = point
    hist = history(run["events"])
    voices = collections.defaultdict(list)
    for v, note in sounding:
        regs = {k[2]: val for k, writes in hist.items() if k[1] == v
                for val in [settled_at(writes, t)] if val is not None}
        voices[("A" if v < 8 else "B", note)].append(regs)
    for stack in voices.values():  # a unison stack: its voices by their oscillator pitches
        stack.sort(key=lambda regs: tuple(regs.get(p, 0) for p in (0, 1, 2)))
    parts = {k: val for k, writes in hist.items() if k[1] >= 0x10
             for val in [settled_at(writes, t)] if val is not None}
    return dict(voices), parts


def same_where_settled(a, b, what):
    """Registers settled in both have the same value, and at least 95% of
    those settled in stock (a) are settled here (b) too."""
    shared = {k: v for k, v in a.items() if k in b}
    assert {k: b[k] for k in shared} == shared, what
    assert len(shared) >= 0.95 * len(a), f"{what}: registers settled in stock but not here"
    return len(shared)


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    built(tmp_path_factory)
    return record(stock_summit()), record(mpe_summit(tmp_path_factory).s)


def test_the_sequence_is_varied(runs):
    stock, _ = runs
    assert len(stock["events"]) > 10_000
    assert {e.param for e in stock["events"]} >= {0x3F, 0x40, 0x61, 0x66, 0x67, 0x68, 0x69, 0x60}
    assert len({e.target for e in stock["events"] if e.target < 16}) == 16  # every voice played
    assert len(stock["midi"]) > 50


def test_every_checkpoint_matches_stock(runs):
    stock, mpe = runs
    assert len(mpe["points"]) == len(stock["points"]) >= 10
    compared = 0
    for i, (a, b) in enumerate(zip(stock["points"], mpe["points"])):
        voices_a, parts_a = snapshot(stock, a)
        voices_b, parts_b = snapshot(mpe, b)
        where = f"checkpoint {i} at {a[0]:.2f} ms"
        assert {k: len(v) for k, v in voices_b.items()} == {k: len(v) for k, v in voices_a.items()}, \
            f"{where}: sounding notes differ"
        for key, stack in voices_a.items():
            for n, (ra, rb) in enumerate(zip(stack, voices_b[key])):
                compared += same_where_settled(ra, rb, f"{where}, note {key} voice {n}")
        compared += same_where_settled(parts_a, parts_b, f"{where}, broadcast and part registers")
    assert compared > 1500  # not vacuous (1,762 settled values on 2026-11-01)


def test_the_final_fpga_state_is_stocks(runs):
    """Voice registers exactly; broadcast registers (target >= 0x10) by their
    last value per engine, a register ever sent to both engines as "AB"
    whatever engine select it went out with (the engine select of an
    occasional queued broadcast is timing, see tests/bend_play.py). Per
    engine, because each part sends its own 0x68/0x69 every tick: with the
    parts' values different, a last value across engines would depend on
    where in a tick the run stops."""
    def final(run):
        voices = {k: v for k, v in run["state"].items() if k[1] < 0x10}
        sent = [e for e in run["events"] if e.target >= 0x10]
        both = {(e.target, e.param) for e in sent if e.engines == "AB"}
        broadcast = {("AB" if (e.target, e.param) in both else e.engines, e.target, e.param): e.value for e in sent}
        return voices, broadcast

    assert final(runs[1]) == final(runs[0])


def test_midi_out_is_stocks(runs):
    stock, mpe = runs
    assert [m[1:] for m in mpe["midi"]] == [m[1:] for m in stock["midi"]]
    assert max(abs(a[0] - b[0]) for a, b in zip(stock["midi"], mpe["midi"])) < 2  # timing only


def test_nothing_is_left_playing(runs):
    stock, mpe = runs
    assert stock["voices"] == mpe["voices"] == []
