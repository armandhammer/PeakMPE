"""`hwrig run`: stimulus, analysis and report against a fake MPE Summit,
and the stimulus against the MPE patch in the simulator. No hardware.

The fake (tests/hwrig_fake.py) renders what the MIDI asks for, or, with a
fault injected, what a broken firmware would do; every check must pass on
the first and catch the second. The simulator part plays the exact
timelines into the patched firmware and reads the per-voice oscillator
pitch (params 0x000-0x002) and pressure (0x61): the stimulus does what the
analysis assumes.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

from emu.firmware import load_image  # noqa: E402
from hwrig import checks, config, midi, params, recipes, run, setup, stimulus  # noqa: E402
from hwrig_fake import FakeMpeSummit  # noqa: E402
from hwrig_simutil import SIM_SETTLE_MS, SIM_TAIL_MS, fast_timing, sim_steps, sim_wait_ms  # noqa: E402,F401

IMAGE = load_image()
needs_firmware = pytest.mark.skipif(IMAGE is None, reason="firmware not present (scripts/fetch-firmware.sh)")


@pytest.fixture(scope="module")
def table():
    if IMAGE is None:
        pytest.skip("firmware not present")
    return params.Table(IMAGE)


def do_run(table, tmp_path, faults=(), names=None, answer=True):
    synth = FakeMpeSummit(faults)
    chosen = [checks.by_name()[n] for n in names] if names else checks.stage2()
    plan = run.Plan(config.Config(), table, chosen)
    said = []
    rows = run.run(plan, "Summit", synth.open_port, synth, lambda: answer, tmp_path,
                   say=said.append, sleep=lambda s: None)
    return rows, synth, "\n".join(said)


def failing(rows):
    return {(r.check, r.item) for r in rows if r.status == "fail"}


# -- stimulus ---------------------------------------------------------------------

def test_bend_messages_and_cents():
    assert stimulus.bend(3, 0) == bytes([0xE2, 0x00, 0x40])
    assert stimulus.bend(2, -8192) == bytes([0xE1, 0x00, 0x00])
    assert stimulus.bend(2, 8191) == bytes([0xE1, 0x7F, 0x7F])
    assert stimulus.bend_cents(683, 48) == pytest.approx(400.2, abs=0.1)
    assert stimulus.bend_cents(-8192, 48) == -4800.0
    assert stimulus.rpn(2, 0, 0, 48)[:3] == [bytes([0xB1, 101, 0]), bytes([0xB1, 100, 0]), bytes([0xB1, 6, 48])]


@pytest.mark.parametrize("check", checks.stage2(), ids=lambda c: c.name)
def test_timelines_are_sendable_and_end_with_nothing_held(check):
    tl = check.timeline(config.Config())
    assert tl.held_at_end() == set()
    msgs = tl.messages()
    assert msgs and all(midi.check_message(e.data) for e in msgs)
    assert tl.duration > max(e.t for e in msgs) + checks.TAIL_S - 0.01
    assert "pre" in {e.label for e in tl.events} and "last_off" in {e.label for e in tl.events}
    # never more than 60 % of DIN in any 100 ms (so the same run works over DIN)
    ts = [e.t for e in msgs]
    for t0 in ts:
        burst = sum(len(e.data) for e in msgs if t0 <= e.t < t0 + 0.1)
        assert burst <= 0.6 * 312.5, (check.name, t0, burst)


def test_chord_notes_never_collide_with_the_bends():
    c = checks.BendOneNote()
    target = c.CHORD[c.TARGET][1] * 100.0
    others = [n * 100.0 for k, (_, n) in enumerate(c.CHORD) if k != c.TARGET]
    for v in c.BENDS:
        moved = target + stimulus.bend_cents(v, 48)
        assert all(abs(moved - o) > checks.FIND_TOL_C + 30 for o in others)


# -- plan, confirmation, report ----------------------------------------------------

def test_plan_text_lists_everything(table):
    plan = run.Plan(config.Config(), table, checks.stage2())
    text = plan.text("Summit")
    for c in checks.stage2():
        assert c.name in text
    assert "setup p1" in text and "setup p2" in text and "select D002" in text
    assert text.count("setup p1") == 1  # p1 is built once for its three checks
    assert "RPN 0 = 48 on ch 2" in text and "No SysEx" in text
    listing = plan.listing()
    assert listing.count("# setup") == 4 and listing.count("# check") == 6
    assert 30 < plan.seconds() < 90


def test_nothing_sent_without_confirmation(table, tmp_path):
    rows, synth, out = do_run(table, tmp_path, answer=False)
    assert rows is None and synth.opened == 0 and synth.sent == []
    assert "nothing sent" in out and (tmp_path / "messages.txt").exists()


def test_full_run_passes_on_a_correct_synth(table, tmp_path):
    rows, synth, out = do_run(table, tmp_path)
    assert failing(rows) == set()
    assert {r.check for r in rows} == {c.name for c in checks.stage2()}
    assert [r for r in rows if r.status == "info"] == [r for r in rows if r.item == "range in tolerance"]
    rep = json.loads((tmp_path / "report.json").read_text())
    assert rep["summary"].endswith("0 fail, 1 info") and rep["failed_takes"] == []
    assert "| bend_one_note" in (tmp_path / "report.md").read_text()
    assert not list(tmp_path.glob("*.wav"))
    # the preamble set the bend range the checks assume
    assert synth.note_range == 48 and synth.sent[:3] == stimulus.rpn(2, 0, 0, 48)[:3]


@pytest.mark.parametrize("fault, check, items", [
    ("broadcast_bend", "bend_one_note", {"bend +683: C4 (ch 2) unchanged", "bend +683: G4 (ch 4) unchanged"}),
    ("range24", "bend_one_note", {"bend +683: E4 (ch 3)", "bend +2048: E4 (ch 3)"}),
    ("range24", "bend_range_48", {"bend +2048", "bend -4096"}),
    ("pressure_all", "pressure_right_note", {"at 127: G3 (ch 2) unchanged", "at 127: C5 (ch 4) unchanged"}),
    ("pressure_all", "pressure_level_right_note", {"at 127: G3 (ch 2) unchanged"}),
    ("stuck", "stuck_notes_stress", {"silent after the last note-off"}),
])
def test_checks_catch_injected_faults(table, tmp_path, fault, check, items):
    rows, _, _ = do_run(table, tmp_path, faults=[fault], names=[check])
    got = {item for c, item in failing(rows) if c == check}
    assert items <= got
    assert (tmp_path / f"{check}.wav").exists() and (tmp_path / f"{check}.midi.txt").exists()
    assert check in json.loads((tmp_path / "report.json").read_text())["failed_takes"]


def test_range_clamp_is_reported_not_failed(table, tmp_path):
    rows, _, _ = do_run(table, tmp_path, faults=["clamp3000"], names=["bend_range_48"])
    assert failing(rows) == set()
    info = {r.item: r for r in rows if r.status == "info"}
    assert info["bend -8192"].measured == "-3000.00 c" and "exploratory" in info["bend -8192"].note
    assert info["range in tolerance"].measured == "-2400 c to +2400 c"


def test_slide_without_routing_is_caught(table, tmp_path):
    rows, _, _ = do_run(table, tmp_path, names=["slide_right_note"])
    assert failing(rows) == set()
    rows, _, _ = do_run(table, tmp_path / "b", names=["slide_right_note"], faults=["no_matrix"])
    assert ("slide_right_note", "single note E4: response to 127") in failing(rows)


def test_interrupted_run_releases_and_resets(table, tmp_path):
    synth = FakeMpeSummit()
    real = synth.record

    def boom(duration, events):
        for at_s, fn in sorted(events, key=lambda e: e[0])[:8]:
            synth.now = at_s
            fn()
        synth.now = None
        raise KeyboardInterrupt
    synth.record = boom
    plan = run.Plan(config.Config(), table, [checks.BendOneNote()])
    with pytest.raises(KeyboardInterrupt):
        run.run(plan, "Summit", synth.open_port, synth, lambda: True, tmp_path, say=lambda s: None,
                sleep=lambda s: None)
    tail = synth.sent[-(3 + 48):]
    assert set(tail[:3]) == {stimulus.note_off(2, 60), stimulus.note_off(3, 64), stimulus.note_off(4, 67)}
    assert stimulus.bend(16, 0) in tail and stimulus.cc(16, 74, 0) in tail
    assert real  # the real recorder is untouched


def test_unknown_check_and_held_note_are_refused(table):
    class Leaky(checks.BendOneNote):
        def timeline(self, cfg):
            tl = super().timeline(cfg)
            tl.at(0.1, stimulus.note_on(9, 60))
            return tl
    with pytest.raises(ValueError, match="notes left on"):
        run.Plan(config.Config(), table, [Leaky()])


# -- M1 --------------------------------------------------------------------------

def test_m1_plan(table):
    steps = setup.plan(table, recipes.RECIPES["m1"], config.Config(part_a_channel=5, part_b_channel=6))
    assert [d.hex() for d in steps[0].data] == ["b0633e", "b06200", "b00601"]      # Multi
    assert [d.hex() for d in steps[1].data][:3] == ["b06500", "b06406", "b00602"]  # setup layout: Lower 2
    assert [d.hex() for d in steps[2].data][:3] == ["bf6500", "bf6406", "bf0607"]  # and Upper 7
    assert [d.hex() for d in steps[3].data] == ["b42004", "c402"]                  # Part A: D002 on ch 5
    assert [d.hex() for d in steps[-3].data][:3] == ["b06500", "b06406", "b00600"]  # final: MCM 0 on ch 1
    assert [d.hex() for d in steps[-2].data][:3] == ["bf6500", "bf6406", "bf0607"]  # and Upper 7
    assert [d.hex() for d in steps[-1].data][:3] == ["b86500", "b86400", "b80630"]  # RPN 0 = 48 on ch 9
    assert [d.hex() for d in steps[-1].data][5:8] == ["bf6500", "bf6400", "bf0602"]  # RPN 0 = 2 on ch 16
    part_b = [s for s in steps if s.what.startswith("Part B")]
    assert [d.hex() for d in part_b[0].data] == ["b52004", "c503"]                 # Part B: D003 on ch 6
    cfg = config.Config(part_a_channel=5, part_b_channel=6)
    text = setup.plan_text(table, recipes.RECIPES["m1"], cfg, "Summit", steps)
    assert "Upper Zone, master 16, members 9-15" in text and "Part B on ch 6: select D003" in text
    assert "Part channels from work/hwrig.toml: A = 5, B = 6" in text
    with pytest.raises(ValueError, match="lies in the upper zone"):
        setup.plan(table, recipes.RECIPES["m1"], config.Config(part_a_channel=5, part_b_channel=12))
    with pytest.raises(ValueError, match="needs both Part channels in 4-8"):
        setup.plan(table, recipes.RECIPES["m1"], config.Config())  # the Summit's defaults 2/3


# -- the stimulus in the MPE patch (simulator) --------------------------------------

@pytest.fixture(scope="module")
def mpe(tmp_path_factory):
    import mpe_sim
    return mpe_sim.mpe_summit(tmp_path_factory)


def sim_start(m, table, recipe=None):
    s = m.reset().s
    s.set_cc_nrpn_receive(True)
    s.set_global(0x15, s.global_setting(0x15) | 1)
    s.set_patch_byte(0x1A2, 1)  # the base slot's MPE flag (the simulator's slots are Init)
    s.tick(5)
    for d in run.preamble(config.Config()):
        s.midi_in(d, port="usb", run_ms=2)
    if recipe:
        for st in sim_steps(setup.plan(table, recipes.RECIPES[recipe], config.Config())[1:]):
            s.midi_in(b"".join(st.data), port="usb", run_ms=sim_wait_ms(st))
        s.tick(100)
    return s


def sim_play(s, tl, at_labels, settle_ms=SIM_SETTLE_MS):
    """Play `tl` over USB at its times; at each label in `at_labels`, after
    `settle_ms`, call the probe. Returns {label: probe()}."""
    out, last = {}, 0.0
    for e in tl.sorted():
        s.tick(max(0.0, (e.t - last) * 1000))
        last = e.t
        if e.data:
            s.midi_in(e.data, port="usb")
        if e.label in at_labels:
            s.tick(settle_ms)
            last += settle_ms / 1000
            out[e.label] = {v: (s.voice_note(v), s.last_value(voice=v, param=at_labels[e.label]))
                            for v in s.active_voices()}
    s.tick(SIM_TAIL_MS)
    return out


UNITS_PER_CENT = 4096 / 1200  # per-voice oscillator pitch: 4096 per octave (emulated)


@needs_firmware
@pytest.mark.slow
@pytest.mark.xdist_group("test_sim_bend_one_note_moves_only_its_voice")  # each on its own worker: 25-70 s apiece
def test_sim_bend_one_note_moves_only_its_voice(mpe, table, fast_timing):
    s = sim_start(mpe, table, "p1")
    c = checks.BendOneNote()
    labels = {"base": 0x000, **{f"bend{i}": 0x000 for i in range(len(c.BENDS))}}
    got = sim_play(s, c.timeline(config.Config()), labels)
    base = {note: osc for note, osc in got["base"].values()}
    target = c.CHORD[c.TARGET][1]
    for i, v in enumerate(c.BENDS):
        now = {note: osc for note, osc in got[f"bend{i}"].values()}
        want = stimulus.bend_cents(v, 48) * UNITS_PER_CENT
        assert now[target] - base[target] == pytest.approx(want, abs=1.5)
        assert all(now[n] == base[n] for n in base if n != target)
    assert s.active_voices() == []


@needs_firmware
@pytest.mark.slow
@pytest.mark.xdist_group("test_sim_bend_range_is_linear_to_48")  # each on its own worker: 25-70 s apiece
def test_sim_bend_range_is_linear_to_48(mpe, table, fast_timing):
    s = sim_start(mpe, table)
    c = checks.BendRange48()
    got = sim_play(s, c.timeline(config.Config()), {f"step{i}": 0x000 for i in range(len(c.STEPS))}, 200)
    zero = list(got["step0"].values())[0][1]
    for i, v in enumerate(c.STEPS):
        osc = list(got[f"step{i}"].values())[0][1]
        assert osc - zero == pytest.approx(stimulus.bend_cents(v, 48) * UNITS_PER_CENT, abs=2.5)
    assert s.active_voices() == []


@needs_firmware
@pytest.mark.slow
@pytest.mark.xdist_group("test_sim_stress_leaves_no_voice")  # each on its own worker: 25-70 s apiece
def test_sim_stress_leaves_no_voice(mpe, table, fast_timing):
    s = sim_start(mpe, table)
    sim_play(s, checks.StuckNotesStress().timeline(config.Config()), {})
    assert s.active_voices() == []
    mpe.check()


@needs_firmware
@pytest.mark.slow
@pytest.mark.xdist_group("test_sim_pressure_reaches_only_its_voice")  # each on its own worker: 25-70 s apiece
def test_sim_pressure_reaches_only_its_voice(mpe, table, fast_timing):
    s = sim_start(mpe, table)
    c = checks.PressureRightNote()
    got = sim_play(s, c.timeline(config.Config()), {"base": 0x61, "chord127": 0x61, "chord_back": 0x61})
    target = c.CHORD[c.TARGET][1]
    at = {note: p for note, p in got["chord127"].values()}
    assert at[target] > 30000 and all(at[n] == 0 for n in at if n != target)
    assert all(p == 0 for _, p in got["chord_back"].values())


@needs_firmware
@pytest.mark.slow
@pytest.mark.xdist_group("test_sim_m1_builds_both_parts_and_the_upper_zone")  # each on its own worker: 25-70 s apiece
def test_sim_m1_builds_both_parts_and_the_upper_zone(mpe, table, fast_timing):
    s = mpe.reset().s
    s.set_cc_nrpn_receive(True)
    s.set_global(0x15, s.global_setting(0x15) | 1)
    cfg = config.Config(part_a_channel=5, part_b_channel=6)
    s.set_channels(global_=1, part_a=5, part_b=6)
    for st in sim_steps(setup.plan(table, recipes.RECIPES["m1"], cfg)):
        s.midi_in(b"".join(st.data), port="usb", run_ms=sim_wait_ms(st))
        if st.what.startswith("Part A") and "select" in st.what:
            s.set_patch_byte(0x1A2, 1, part=0)  # D002 carries the MPE flag on the synth
            s.tick(5)
    s.tick(100)
    assert s.multi_mode and mpe.zones() == {"upper": (0, 16, 9, 15)} and mpe.clash() == 0
    for part, r in ((0, "p1"), (1, "p5o")):
        want = setup.expected_patch(table, recipes.RECIPES[r])
        assert {o: s.patch_byte(o, part) for o in want} == want
    mpe.on(60, 9)
    mpe.on(64, cfg.part_b_channel)
    parts = sorted(mpe.part_of_voice(v) for v in s.active_voices())
    assert parts == [0, 1]
    mpe.off(64, cfg.part_b_channel)  # not a zone channel: Mpe doesn't track it
    mpe.all_off()
