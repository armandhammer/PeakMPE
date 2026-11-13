"""Stage-5 checks (tools/hwrig/checks5.py): LinnStrument patterns, without hardware.

Against the fake synth (tests/hwrig_fake.py): every check passes when the
synth behaves as designed and catches its injected fault; the two-zone check
changes the layout, so the run restores the configured zone after it.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

from emu.firmware import load_image  # noqa: E402
from hwrig import checks3, checks5, config, params, run  # noqa: E402
from hwrig_fake import FakeMpeSummit  # noqa: E402

IMAGE = load_image()


@pytest.fixture(scope="module")
def table():
    if IMAGE is None:
        pytest.skip("firmware not present")
    return params.Table(IMAGE)


def do_run(table, tmp_path, names, faults=()):
    synth = FakeMpeSummit(faults)
    allc = checks3.all_checks(6)
    plan = run.Plan(config.Config(), table, [allc[n] for n in names])
    rows = run.run(plan, "Summit", synth.open_port, synth, lambda: True, tmp_path, say=lambda s: None,
                   sleep=lambda s: None)
    return rows, synth


def failing(rows, check):
    return {r.item for r in rows if r.status == "fail" and r.check == check}


NAMES = ["two_zones_bend", "poly_pressure_right_note", "poly_pressure_level_right_note"]


def test_stage5_is_in_the_cli_and_all_checks():
    assert [c.name for c in checks5.stage5()] == NAMES
    assert set(NAMES) <= set(checks3.all_checks(6))


def test_timelines_are_sendable_and_end_with_nothing_held():
    for c in checks5.stage5():
        tl = c.timeline(config.Config())
        assert tl.held_at_end() == set()
        assert all(len(e.data) in (2, 3) for e in tl.messages())


def test_all_pass_on_a_synth_that_does_it_right(table, tmp_path):
    rows, synth = do_run(table, tmp_path, NAMES)
    assert [r for r in rows if r.status == "fail"] == []
    zone_rows = [r for r in rows if r.check == "two_zones_bend"]
    # sound; per step 4 notes at the step plus its movers back (1, 1, 2, 2); silence
    assert len(zone_rows) == 1 + (5 + 5 + 6 + 6) + 1
    assert synth.zones == {}                  # restored to the configured 'off' layout


@pytest.mark.parametrize("fault, items", [
    ("broadcast_bend", {"Lower member ch 3 +683: C4 (L2) unchanged",
                        "Lower member ch 3 +683: E5 (U15) unchanged",
                        "Lower member ch 3 +683: A5 (U14) unchanged",
                        "Upper member ch 14 -1365: C4 (L2) unchanged",
                        "Upper member ch 14 -1365: G4 (L3) unchanged",
                        "Upper member ch 14 -1365: E5 (U15) unchanged"}),
    ("master_all_zones", {"Lower master ch 1 +4096: E5 (U15) unchanged",
                          "Lower master ch 1 +4096: A5 (U14) unchanged",
                          "Upper master ch 16 -4096: C4 (L2) unchanged",
                          "Upper master ch 16 -4096: G4 (L3) unchanged"}),
    ("master_ignored", {"Lower master ch 1 +4096: C4 (L2)", "Lower master ch 1 +4096: G4 (L3)",
                        "Upper master ch 16 -4096: E5 (U15)", "Upper master ch 16 -4096: A5 (U14)"}),
])
def test_two_zones_catches_bends_leaving_their_zone(table, tmp_path, fault, items):
    rows, _ = do_run(table, tmp_path, ["two_zones_bend"], faults=[fault])
    got = failing(rows, "two_zones_bend")
    assert items <= got, got
    assert list(tmp_path.glob("two_zones_bend*.wav"))


@pytest.mark.parametrize("name", ["poly_pressure_right_note", "poly_pressure_level_right_note"])
def test_poly_pressure_ignored_is_caught(table, tmp_path, name):
    rows, _ = do_run(table, tmp_path, [name], faults=["poly_ignored"])
    assert any(i.startswith("single note") for i in failing(rows, name))


def test_poly_pressure_on_every_voice_is_caught(table, tmp_path):
    rows, _ = do_run(table, tmp_path, ["poly_pressure_level_right_note"], faults=["pressure_all"])
    assert {i for i in failing(rows, "poly_pressure_level_right_note") if "unchanged" in i}
