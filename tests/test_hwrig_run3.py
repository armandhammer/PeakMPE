"""Stage-3 checks (tools/hwrig/checks3.py) without hardware.

Against the fake Summit (tests/hwrig_fake.py): every check passes when it
behaves as designed and catches its injected fault; the run restores Single
mode and the zone after the Multi checks, at the end, and after an abort.
In the simulator with the MPE patch (emulated): the stage-3 timelines do
what the analysis expects (per-voice oscillator pitch, voice counts, parts,
`mpe_clash`), and the restore leaves Single mode and the fallback zone.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

from emu.firmware import load_image  # noqa: E402
from hwrig import checks3, config, midi, params, run, setup, recipes, stimulus  # noqa: E402
from hwrig_fake import FakeMpeSummit  # noqa: E402
from hwrig_simutil import SIM_SETTLE_MS, SIM_TAIL_MS, fast_timing, sim_steps, sim_wait_ms  # noqa: E402,F401

IMAGE = load_image()
needs_firmware = pytest.mark.skipif(IMAGE is None, reason="firmware not present (scripts/fetch-firmware.sh)")
CFG = dict(part_a_channel=5, part_b_channel=6)


@pytest.fixture(scope="module")
def table():
    if IMAGE is None:
        pytest.skip("firmware not present")
    return params.Table(IMAGE)


def do_run(table, tmp_path, faults=(), names=None, b1_trials=6, cfg=None, synth=None):
    cfg = cfg or config.Config(**CFG)
    synth = synth or FakeMpeSummit(faults, part_chans=(cfg.part_a_channel, cfg.part_b_channel))
    allc = checks3.all_checks(b1_trials)
    chosen = [allc[n] for n in names] if names else checks3.stage3(b1_trials)
    plan = run.Plan(cfg, table, chosen)
    said = []
    rows = run.run(plan, "Summit", synth.open_port, synth, lambda: True, tmp_path, say=said.append,
                   sleep=lambda s: None)
    return rows, synth, "\n".join(said), plan


def failing(rows, check=None):
    return {r.item for r in rows if r.status == "fail" and (check is None or r.check == check)}


# -- plan --------------------------------------------------------------------------

def test_plan_shows_part_channels_and_restore(table):
    plan = run.Plan(config.Config(**CFG), table, checks3.stage3(6))
    text = plan.text("Summit")
    assert "Part A = 5, Part B = 6. CHECK they match" in text
    assert text.count("then restore: Single mode") == 3  # b1, m1, f5
    assert "Single mode and the MCM for 'off'" in text
    assert plan.changes_layout


def test_part_channels_outside_4_to_8_skip_the_multi_checks(table, tmp_path):
    # the Summit's default Part channels 2/3: inside the setup layout's Lower 2-3 (and F5's zone): skipped
    rows, _, out, plan = do_run(table, tmp_path, cfg=config.Config(), names=["multi_m1", "global_master_multi"])
    text = plan.text("Summit")
    assert "multi_m1: SKIPPED" in text and "global_master_multi: SKIPPED" in text
    assert {r.item for r in rows} == {"skipped"}
    assert failing(rows) == set()


@pytest.mark.parametrize("stored", [(0, 0), (1, 1), (1, 0), (0, 1)])
def test_multi_setup_works_whatever_the_stored_multi(table, tmp_path, stored):
    """The first hardware run (2026-11-08) lost a part's setup: the stored
    Multi had MPE on in both parts, so the firmware split the channels and
    a Part channel was a zone member. The setup layout keeps 4-8 free."""
    synth = FakeMpeSummit(part_chans=(5, 6), stored_flags=stored)
    rows, _, _, _ = do_run(table, tmp_path, names=["multi_m1", "global_master_multi"], synth=synth)
    assert failing(rows) == set()


def test_old_multi_order_fails_on_a_both_mpe_multi(table, tmp_path):
    """The order before the fix (MCMs, then Multi, then the parts) on a
    stored Multi with both parts MPE: the parts' setups are dropped."""
    synth = FakeMpeSummit(part_chans=(5, 6), stored_flags=(1, 1))
    steps = setup.plan(table, recipes.RECIPES["m1"], config.Config(**CFG))
    old = steps[-3:-1] + steps[:1] + steps[3:-3]
    port = synth.open_port()
    for st in old:
        for d in st.data:
            port.send(d)
    assert synth.multi and synth.parts[1].octave == 0  # Part B never got P5o's octave


@pytest.mark.parametrize("check", checks3.stage3(4), ids=lambda c: c.name)
def test_stage3_timelines_are_sendable(check):
    for tl in check.timelines(config.Config(**CFG)):
        assert tl.held_at_end() == set()
        msgs = tl.messages()
        assert all(midi.check_message(e.data) for e in msgs)
        for t0 in [e.t for e in msgs]:
            assert sum(len(e.data) for e in msgs if t0 <= e.t < t0 + 0.1) <= 0.6 * 312.5


def test_b1_trials_cover_every_delay_and_layout_change():
    c = checks3.B1ZoneChange(trials_per_delay=20)
    tls = c.timelines(config.Config())
    assert len(c.trials) == 100 and len(tls) == 4
    for d in c.DELAYS:
        assert sum(tr["delay"] == d for tr in c.trials) == 20
    for a, b in zip(c.trials, c.trials[1:]):
        assert (a["zone"], a["members"]) != (b["zone"], b["members"])
    for tr in c.trials:
        members = c.members(tr["zone"], tr["members"])
        assert all(ch in members for ch, _ in tr["chord"]) and 3 <= len(tr["chord"]) <= 6
        notes = sorted(n for _, n in tr["chord"])
        assert all(b - a >= 3 for a, b in zip(notes, notes[1:]))
    assert checks3.B1ZoneChange(20).plan_trials() == checks3.B1ZoneChange(20).plan_trials()  # seeded
    # burst: no RPN null, so the MCM is 8 messages; otherwise 12
    assert len(c.mcm("lower", 9, null=False)) == 8 and len(c.mcm("upper", 6)) == 12


# -- the fake ---------------------------------------------------------------------

def test_stage3_passes_on_a_correct_synth_and_restores(table, tmp_path):
    rows, synth, _, _ = do_run(table, tmp_path)
    assert failing(rows) == set()
    info = {r.item: r for r in rows if r.status == "info"}
    assert info["B1 (a note lost after a zone change)"].measured == "0 of 30 trials (not reproduced)"
    assert "CH CLASH on Settings page 5" in info
    assert not synth.multi and synth.zones == {}  # Single mode, no MCM zone: the Settings' Zone Off
    assert all(v == 0 for v in synth.state["bend"].values())
    rep = json.loads((tmp_path / "report.json").read_text())
    assert rep["part_channels"] == [5, 6] and rep["zone"] == "off"


@pytest.mark.parametrize("fault, check, items", [
    ("master_ignored", "master_channel", {"master +4096: G3 (G3 on ch 2)", "master +4096: C5 (C5 on ch 1)"}),
    ("master_ignored", "multi_m1", {"master 16 +4096: G3 (A) (G3 on ch 9)"}),
    ("partb_follows", "multi_m1", {"master 16 +4096: C4 (B) (C5 on ch 6) unchanged"}),
    ("global_layers", "global_master_multi", {"no global note on Part B"}),
    ("partb_double", "multi_m1", {"no doubled Part B note"}),
    ("mono_stale_bend", "mono_legato", {"fallback: pitch re C4"}),
    ("broadcast_bend", "mono_legato", {"legato: pitch re C4"}),
])
def test_stage3_checks_catch_injected_faults(table, tmp_path, fault, check, items):
    rows, _, _, _ = do_run(table, tmp_path, faults=[fault], names=[check])
    assert items <= failing(rows, check)
    assert list(tmp_path.glob(f"{check}*.wav"))


def test_b1_drop_rate_per_delay_and_failing_takes(table, tmp_path):
    rows, _, _, _ = do_run(table, tmp_path, faults=["b1_fast"], names=["b1_zone_change"], b1_trials=6)
    by = {r.item: r for r in rows if r.check == "b1_zone_change"}
    for label in ("burst (same pass, no RPN null)", "0 ms", "1 ms"):
        r = by[f"chords complete, delay {label}"]
        assert r.status == "fail" and r.measured.startswith("6 / 6")
    for label in ("5 ms", "20 ms"):
        assert by[f"chords complete, delay {label}"].measured == "0 / 6 (0.0 %)"
    assert "REPRODUCED" in by["B1 (a note lost after a zone change)"].measured
    wavs = sorted(tmp_path.glob("b1_zone_change-t*.wav"))
    assert len(wavs) == 18
    log = (tmp_path / (wavs[0].stem + ".midi.txt")).read_text()
    assert log.startswith("# trial") and "missing" in log and " 90 " not in log.split("\n")[0]


def test_abort_in_multi_restores_single_and_zone(table, tmp_path):
    synth = FakeMpeSummit(part_chans=(5, 6))
    real = synth.record
    calls = []

    def boom(duration, events):
        calls.append(1)
        if synth.multi:  # stop in the middle of the M1 take
            for at_s, fn in sorted(events, key=lambda e: e[0])[:4]:
                synth.now = at_s
                fn()
            raise KeyboardInterrupt
        return real(duration, events)
    synth.record = boom
    plan = run.Plan(config.Config(**CFG), table, [checks3.all_checks()["multi_m1"]])
    with pytest.raises(KeyboardInterrupt):
        run.run(plan, "Summit", synth.open_port, synth, lambda: True, tmp_path, say=lambda s: None,
                sleep=lambda s: None)
    assert not synth.multi and synth.zones == {} and synth.voices == []


def test_restore_messages_follow_the_configured_zone():
    hexes = lambda msgs: [d.hex() for d in msgs]
    off = hexes(run.restore_msgs(config.Config(**CFG)))
    assert off[:9] == ["b4633e", "b46200", "b40600", "b5633e", "b56200", "b50600", "b0633e", "b06200", "b00600"]
    assert "bf0600" in off and "b00600" in off  # MCM 0 on 16, then 0 on 1
    low = hexes(run.restore_msgs(config.Config(zone="lower 7", **CFG)))
    assert low.index("bf0600") < low.index("b00607")
    up = hexes(run.restore_msgs(config.Config(zone="upper 5", **CFG)))
    assert up.index("b00600") < up.index("bf0605")
    with pytest.raises(ValueError):
        config.Config(zone="side 3").validate()


# -- the simulator with the MPE patch -------------------------------------------------

@pytest.fixture(scope="module")
def mpe(tmp_path_factory):
    import mpe_sim
    return mpe_sim.mpe_summit(tmp_path_factory)


def sim_start(m, table, recipe=None, part_a=5, part_b=6):
    s = m.reset().s
    s.set_cc_nrpn_receive(True)
    s.set_global(0x15, s.global_setting(0x15) | 1)
    s.set_channels(global_=1, part_a=part_a, part_b=part_b)
    s.set_patch_byte(0x1A2, 1)
    s.tick(5)
    for d in run.preamble(config.Config()):
        s.midi_in(d, port="usb", run_ms=2)
    if recipe:
        r = recipes.RECIPES[recipe]
        for st in sim_steps(setup.plan(table, r, config.Config(**CFG))):
            if st.what.startswith("select") and getattr(r, "base", "") != "multi":
                continue  # the simulator's slots are Init: keep the poked flag
            s.midi_in(b"".join(st.data), port="usb", run_ms=sim_wait_ms(st))
            if st.what.startswith("Part A") and "select" in st.what:
                s.set_patch_byte(0x1A2, 1, part=0)
                s.tick(5)
        s.tick(100)
    return s


def sim_play(s, tl, probes, settle_ms=SIM_SETTLE_MS):
    """Play `tl` over USB at its times; a probe for a label runs `settle_ms`
    after every event at that label's instant has been sent (a chord's
    note-ons share one)."""
    out, last, pending = {}, 0.0, []
    events = tl.sorted()
    for k, e in enumerate(events):
        s.tick(max(0.0, (e.t - last) * 1000))
        last = e.t
        if e.data:
            s.midi_in(e.data, port="usb")
        if e.label in probes:
            pending.append(e.label)
        if pending and (k + 1 == len(events) or events[k + 1].t > e.t):
            s.tick(settle_ms)
            last += settle_ms / 1000
            for label in pending:
                out[label] = probes[label]()
            pending = []
    s.tick(SIM_TAIL_MS)
    return out


UNITS_PER_CENT = 4096 / 1200


def osc_by_note(s):
    return {s.voice_note(v): s.last_value(voice=v, param=0x000) for v in s.active_voices()}


@needs_firmware
@pytest.mark.slow
@pytest.mark.xdist_group("test_sim3_master")
def test_sim_master_channel(mpe, table, fast_timing):
    s = sim_start(mpe, table, "p1")
    c = checks3.MasterChannel()
    tl = c.timeline(config.Config())
    got = sim_play(s, tl, {m: (lambda: osc_by_note(s)) for m, _, _ in c.STEPS} | {"base": lambda: osc_by_note(s)})
    base = got["base"]
    for mark, _, want in c.STEPS:
        for label, ch, n, _ in c.NOTES:
            delta = got[mark][n] - base[n]
            assert delta == pytest.approx(want.get(label, 0.0) * UNITS_PER_CENT, abs=1.5), (mark, label)
    assert s.active_voices() == []


@needs_firmware
@pytest.mark.slow
@pytest.mark.xdist_group("test_sim3_mono")
def test_sim_mono_legato(mpe, table, fast_timing):
    s = sim_start(mpe, table, "p6")
    c = checks3.MonoLegato()
    probes = {m: (lambda: (s.active_voices(), osc_by_note(s))) for m in ("ref", "bent", "legato", "held bent",
                                                                       "fallback")}
    got = sim_play(s, c.timeline(config.Config()), probes)
    ref = got["ref"][1][60]
    want = {"bent": (60, 683), "legato": (64, -341), "held bent": (64, -341), "fallback": (60, 1365)}
    for mark, (note, b) in want.items():
        voices, osc = got[mark]
        assert len(voices) == 1 and list(osc) == [note]
        semis = 4 if note == 64 else 0
        assert osc[note] - ref == pytest.approx((semis * 100 + b / 8192 * 4800) * UNITS_PER_CENT, abs=1.5)
    assert s.active_voices() == []


@needs_firmware
@pytest.mark.slow
@pytest.mark.xdist_group("test_sim3_b1")
def test_sim_b1_trials_sound_every_note(mpe, table, fast_timing):
    s = sim_start(mpe, table, "p1")
    c = checks3.B1ZoneChange(trials_per_delay=2)
    tl = c.timelines(config.Config())[0]
    probes = {f"t{tr['i']}_chord": (lambda tr=tr: (sorted(s.voice_note(v) for v in s.active_voices()),
                                                   sorted(n for _, n in tr["chord"]), mpe.zones()))
              for tr in c.trials}
    got = sim_play(s, tl, probes, settle_ms=60)
    for tr in c.trials:
        voices, chord, zones = got[f"t{tr['i']}_chord"]
        assert voices == chord, tr
        assert tr["zone"] in zones
    assert s.active_voices() == []


@needs_firmware
@pytest.mark.slow
@pytest.mark.parametrize("name, recipe, clash", [
    pytest.param("multi_m1", "m1", 0, marks=pytest.mark.xdist_group("test_sim3_m1")),
    pytest.param("global_master_multi", "f5", 4, marks=pytest.mark.xdist_group("test_sim3_f5")),
])
def test_sim_m1_f5_and_restore(mpe, table, fast_timing, name, recipe, clash):
    if True:
        s = sim_start(mpe, table, recipe)
        assert s.multi_mode and mpe.clash() == clash, name
        c = checks3.all_checks()[name]
        tl = c.timelines(config.Config(**CFG))[0]

        def probe():
            return {(s.voice_note(v), mpe.part_of_voice(v)): s.last_value(voice=v, param=0x000)
                    for v in s.active_voices()}
        got = sim_play(s, tl, {"base": probe} | {m: probe for m, _, _ in c.STEPS})
        notes = c.notes(config.Config(**CFG))
        # every note on its part (A = 0 for the zone notes, B = 1), none doubled
        assert sorted(got["base"]) == sorted((n, 0 if "(A)" in label else 1) for label, _, n, _ in notes)
        for mark, _, want in c.STEPS:
            for label, _, n, _ in notes:
                key = (n, 0 if "(A)" in label else 1)
                assert got[mark][key] - got["base"][key] == pytest.approx(
                    want.get(label, 0.0) * UNITS_PER_CENT, abs=1.5), (name, mark, label)
        for d in run.restore_msgs(config.Config(**CFG)):
            s.midi_in(d, port="usb", run_ms=2)
        s.tick(50)
        assert not s.multi_mode and mpe.zones() == {"lower": (0, 1, 2, 16)}


def test_part_b_on_its_own_inputs_is_in_the_mix(table, tmp_path):
    """The user's rig: Part A (and Single) on inputs 9/10, Part B on 11/12.
    The fake puts Part B's voices only on inputs 3/4 of four; every check
    still sees both parts."""
    synth = FakeMpeSummit(part_chans=(5, 6), inputs=(9, 10, 11, 12))
    synth.split_parts = True
    rows, _, _, _ = do_run(table, tmp_path, names=["master_channel", "multi_m1", "global_master_multi"],
                           synth=synth)
    assert failing(rows) == set()
    # and the old first-input-only analysis would have missed Part B entirely
    from hwrig import stimulus
    import numpy as np
    take = stimulus.Take(np.zeros((10, 4)), 48000, {})
    assert take.window(0, 1e-4, ch=0).shape == take.window(0, 1e-4).shape


@needs_firmware
@pytest.mark.slow
@pytest.mark.parametrize("name, zone", [
    pytest.param("m1", {"upper": (0, 16, 9, 15)}, marks=pytest.mark.xdist_group("test_sim3_stored_m1")),
    pytest.param("f5", {"lower": (0, 1, 2, 4)}, marks=pytest.mark.xdist_group("test_sim3_stored_f5")),
])
def test_sim_multi_setup_whatever_the_stored_multi(mpe, table, fast_timing, name, zone):
    """Emulated: with the setup layout, both parts get their sounds and the
    zones end as the recipe wants, for every combination of MPE flags in the
    stored Multi (which NRPN 62:0 = 1 loads; poked right after it here)."""
    cfg = config.Config(**CFG)
    if True:
        for stored in ((0, 0), (1, 1), (1, 0), (0, 1)):
            s = mpe.reset().s
            s.set_cc_nrpn_receive(True)
            s.set_global(0x15, s.global_setting(0x15) | 1)
            s.set_channels(global_=1, part_a=5, part_b=6)
            s.set_patch_byte(0x1A2, 1)
            s.tick(5)
            for st in sim_steps(setup.plan(table, recipes.RECIPES[name], cfg)):
                s.midi_in(b"".join(st.data), port="usb", run_ms=sim_wait_ms(st))
                if st.what.startswith("NRPN 62:0"):
                    for part, f in enumerate(stored):
                        s.set_patch_byte(0x1A2, f, part=part)
                    s.tick(5)
                if "select" in st.what:  # the synth's D002 has MPE on, D003 off
                    part = 0 if st.what.startswith("Part A") else 1
                    s.set_patch_byte(0x1A2, 1 - part, part=part)
                    s.tick(5)
            s.tick(100)
            for part, r, slot in ((0, "p1", (4, 2)), (1, "p5o", (4, 3))):
                # the program change landed (the slot's bank/patch bytes), then the sound
                assert (s.patch_byte(0x14, part), s.patch_byte(0x15, part)) == slot, (name, stored, part)
                want = setup.expected_patch(table, recipes.RECIPES[r])
                assert {o: s.patch_byte(o, part) for o in want} == want, (name, stored, part)
            assert mpe.zones() == zone, (name, stored)


def test_multi_setup_sets_the_zone_bend_range_after_its_mcm(table, tmp_path):
    """On the synth the Upper Zone's note range after the MCM was ±49 (M1's
    member bend +408.4 c for +400.2). The setup now sends RPN 0 = 48 after
    the MCM; without that step the check fails on a fake that does the same."""
    rows, _, _, _ = do_run(table, tmp_path, faults=["mcm_range49"], names=["multi_m1"])
    assert failing(rows) == set()
    synth = FakeMpeSummit(["mcm_range49"], part_chans=(5, 6))
    plan = run.Plan(config.Config(**CFG), table, [checks3.all_checks()["multi_m1"]])
    plan.items[0].steps = plan.items[0].steps[:-1]  # the setup as it was on 2026-11-08
    rows = run.run(plan, "Summit", synth.open_port, synth, lambda: True, tmp_path / "b", say=lambda s: None,
                   sleep=lambda s: None)
    assert "member 9 +683: G3 (A) (G3 on ch 9)" in failing(rows, "multi_m1")


def test_a_lost_preamble_message_costs_no_check(table, tmp_path):
    """A DIN run on 2026-11-08 lost the run's first RPN 0 = 48 (the Settings
    say ±49), and the two checks after it ran at ±49. The preamble now goes
    out again before every check."""
    rows, _, _, _ = do_run(table, tmp_path, faults=["lose_first_rpn"], names=["master_channel", "mono_legato"])
    assert failing(rows) == set()


def test_b1_reports_a_stuck_note_apart_from_b1(table, tmp_path):
    """An earlier trial's note still sounding is an extra partial, not B1:
    the delay rows and the B1 row stay clean, the extra row fails."""
    rows, _, _, _ = do_run(table, tmp_path, faults=["stuck"], names=["b1_zone_change"], b1_trials=6)
    by = {r.item: r for r in rows if r.check == "b1_zone_change"}
    assert all(r.status == "pass" for k, r in by.items() if k.startswith("chords complete"))
    assert by["no extra partials (a note still sounding from an earlier trial)"].status == "fail"
    assert by["B1 (a note lost after a zone change)"].measured.endswith("(not reproduced)")
