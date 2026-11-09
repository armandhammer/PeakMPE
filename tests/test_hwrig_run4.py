"""Stage-4 check (tools/hwrig/checks4.py): MPE v1.1's voice rotation, without hardware.

Against the fake Summit (tests/hwrig_fake.py): the check passes on a synth
that rotates idle voices and takes a releasing one over, and fails on v1's
rule (pinned_voice) and on a synth that rotates during the release. In the
simulator with the MPE patch (emulated): the check's timeline takes the
voices the analysis expects, and Diverge 127 moves each voice's pitch by
the firmware table's amount.
"""
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

from emu.firmware import load_image  # noqa: E402
from hwrig import checks, checks3, checks4, config, params, recipes, run, stimulus  # noqa: E402
from hwrig_fake import DIVERGE_OSC1, FakeMpeSummit, diverge_cents  # noqa: E402
from hwrig_simutil import fast_timing, sim_steps, sim_wait_ms  # noqa: E402,F401

IMAGE = load_image()
needs_firmware = pytest.mark.skipif(IMAGE is None, reason="firmware not present (scripts/fetch-firmware.sh)")
IMAGE_BASE = 0x0800C000
DATA_INIT = 0x0804BD80  # flash initialiser of RAM 0x20000000 (.data)
DIVERGE_RAND = 0x200007CC


@pytest.fixture(scope="module")
def table():
    if IMAGE is None:
        pytest.skip("firmware not present")
    return params.Table(IMAGE)


def do_run(table, tmp_path, faults=()):
    cfg = config.Config()
    synth = FakeMpeSummit(faults)
    plan = run.Plan(cfg, table, [checks4.VoiceRotation()])
    said = []
    rows = run.run(plan, "Summit", synth.open_port, synth, lambda: True, tmp_path, say=said.append,
                   sleep=lambda s: None)
    return rows, synth


def failing(rows):
    return {r.item for r in rows if r.status == "fail" and r.check == "voice_rotation"}


AFTER = "after the release: each note on another voice than the one before"
DURING = "during the release: 4 notes on ch 3, 5 ms after each note-off"


@needs_firmware
def test_the_fakes_diverge_table_is_the_firmwares():
    off = DATA_INIT + (DIVERGE_RAND - 0x20000000) - IMAGE_BASE
    raw = struct.unpack("48b", IMAGE[off:off + 48])
    assert tuple(raw[3 * v] for v in range(8)) == DIVERGE_OSC1  # Osc 1, voices 0-7
    assert raw[:24] == raw[24:]  # voices 8-15 repeat 0-7
    cents = sorted(diverge_cents(127, v) for v in range(8))
    assert min(b - a for a, b in zip(cents, cents[1:])) >= 2.7
    assert -17.2 <= cents[0] and cents[-1] <= 14.0


def test_stage4_is_in_the_cli_and_all_checks():
    assert "voice_rotation" in checks3.all_checks(6)
    assert [c.name for c in checks4.stage4()] == ["voice_rotation"]


def test_timeline_is_sendable_and_keeps_the_gaps():
    c = checks4.VoiceRotation()
    tl = c.timeline(config.Config())
    assert tl.held_at_end() == set()
    assert all(len(e.data) in (2, 3) for e in tl.messages())
    t = {e.label: e.t for e in tl.sorted()}
    assert t["after1"] - t["after_off0"] == pytest.approx(c.AFTER_GAP_S)
    assert t["during1"] - t["during_off0"] == pytest.approx(c.DURING_GAP_S)


def test_recipe_p7_sets_diverge_and_release(table):
    vals = {p.name: v for p, v, _ in recipes.RECIPES["p7"].resolve(table)}
    assert vals["Diverge"] == 127 and vals["AmpRelease"] == 64 and vals["Wave"] == table.index(table.waves, "Sine",
                                                                                                    "w")


def test_passes_on_a_v1_1_synth(table, tmp_path):
    rows, _ = do_run(table, tmp_path)
    assert failing(rows) == set(), [r for r in rows if r.status == "fail"]
    by = {r.item: r for r in rows if r.check == "voice_rotation"}
    assert by[AFTER].measured == "5 of 5"
    assert by["after the release: voices used"].measured == "6 distinct"


@pytest.mark.parametrize("fault, items", [
    ("pinned_voice", {AFTER}),
    ("rotate_in_release", {DURING}),
])
def test_catches_the_wrong_reuse_rule(table, tmp_path, fault, items):
    rows, _ = do_run(table, tmp_path, faults=[fault])
    assert failing(rows) == items
    assert list(tmp_path.glob("voice_rotation*.wav"))


TAIL = "silent after the last note-off"


def test_tail_window_waits_for_p7s_release(table, tmp_path):
    """On the synth P7's release lasts about 0.9 s, so the shared tail
    window (0.5-1.0 s after the last note-off) still held it and the tail
    row failed on v1.1 over USB and DIN (2026-11-08). The check's own window
    starts after the release; a note left on still fails it."""
    c = checks4.VoiceRotation()
    assert c.TAIL_FROM_S >= 1.0 + 0.5 and c.TAIL_S - c.TAIL_FROM_S >= 0.5
    tl = c.timeline(config.Config())
    t = {e.label: e.t for e in tl.sorted()}
    assert tl.duration >= max(t.values()) + c.TAIL_S
    rows, _ = do_run(table, tmp_path, faults=["slow_release"])
    assert failing(rows) == set(), [r for r in rows if r.status == "fail"]
    rows, _ = do_run(table, tmp_path / "stuck", faults=["slow_release", "stuck"])
    assert TAIL in failing(rows)


def test_the_shared_tail_window_fails_on_a_slow_release(table, tmp_path, monkeypatch):
    """The rig bug itself: with the old window, the slow release fails the
    tail row although nothing is left on."""
    monkeypatch.setattr(checks4.VoiceRotation, "TAIL_FROM_S", 0.5)
    monkeypatch.setattr(checks4.VoiceRotation, "TAIL_S", checks.TAIL_S)
    rows, _ = do_run(table, tmp_path, faults=["slow_release"])
    assert failing(rows) == {TAIL}


def test_no_diverge_is_reported_as_no_spread(table, tmp_path, monkeypatch):
    p7 = recipes.RECIPES["p7"]
    monkeypatch.setitem(recipes.RECIPES, "p7", recipes.Recipe("p7", "mpe", p7.about, dict(recipes.SINE)))
    rows, _ = do_run(table, tmp_path)
    assert "chord: four voices, Diverge spreads them" in failing(rows)


# -- the simulator with the MPE patch -------------------------------------------------

@pytest.fixture(scope="module")
def mpe(tmp_path_factory):
    import mpe_sim
    return mpe_sim.mpe_summit(tmp_path_factory)


@pytest.fixture
def sim_timing(fast_timing, monkeypatch):
    monkeypatch.setattr(checks4.VoiceRotation, "AFTER_GAP_S", 0.12)
    monkeypatch.setattr(checks4.VoiceRotation, "DURING_GAP_S", 0.005)
    monkeypatch.setattr(checks4.VoiceRotation, "TAIL_FROM_S", 0.1)
    monkeypatch.setattr(checks4.VoiceRotation, "TAIL_S", checks.TAIL_S)


UNITS_PER_CENT = 4096 / 1200
SIM_RELEASE_MS = 60  # the modelled release: ends within AFTER_GAP_S, not within DURING_GAP_S


@needs_firmware
@pytest.mark.slow
@pytest.mark.xdist_group("test_sim4_rotation")
def test_sim_voice_rotation_timeline(mpe, table, sim_timing):
    s = mpe.reset().s
    s.release_ms = SIM_RELEASE_MS
    s.set_cc_nrpn_receive(True)
    s.set_patch_byte(0x1A2, 1)
    s.tick(5)
    for d in run.preamble(config.Config()):
        s.midi_in(d, port="usb", run_ms=2)
    for st in sim_steps(__import__("hwrig.setup", fromlist=["plan"]).plan(table, recipes.RECIPES["p7"],
                                                                           config.Config())):
        if st.what.startswith("select"):
            continue  # the simulator's slots are Init: keep the poked flag
        s.midi_in(b"".join(st.data), port="usb", run_ms=sim_wait_ms(st))
    s.tick(100)
    assert s.patch_byte(0x2B) == 127 and s.patch_byte(0x95) == 64
    c = checks4.VoiceRotation()
    s.clear()
    voice_of, osc_of = {}, {}
    last = 0.0
    for e in c.timeline(config.Config()).sorted():
        s.tick(max(0.0, (e.t - last) * 1000))
        last = e.t
        if e.data:
            t = s.time_ms
            if e.data[0] & 0xF0 == 0x80 and e.label.replace("_off", "") in voice_of:
                on = e.label.replace("_off", "")  # settled: the pitch the voice plays
                osc_of[on] = s.last_value(voice=voice_of[on], param=0x000)
            s.midi_in(e.data, port="usb", run_ms=3)
            last += 0.003
            if e.data[0] & 0xF0 == 0x90:
                (v,) = [x.voice for x in s.fpga_events(param=0x3F, since_ms=t) if x.value & 3 == 0]
                voice_of[e.label] = v
    s.tick(400)
    assert s.active_voices() == []
    after = [voice_of[f"after{i}"] for i in range(c.AFTER_N)]
    during = [voice_of[f"during{i}"] for i in range(len(c.DURING_NOTES))]
    assert all(a != b for a, b in zip(after, after[1:])), after
    assert len(set(during[1:])) == 1 and during[1] == during[0], during
    # Diverge's per-voice offset in the oscillator pitch, as the analysis assumes
    for k in range(1, c.AFTER_N):
        a, b = after[k - 1], after[k]
        want = (127 * DIVERGE_OSC1[b % 8] >> 5) - (127 * DIVERGE_OSC1[a % 8] >> 5)  # 8.8 semitones
        got = osc_of[f"after{k}"] - osc_of[f"after{k - 1}"]  # 4096 per octave: x 4/3 of 8.8
        assert got == pytest.approx(want * 4 / 3, abs=1.5), (a, b)
