"""`hwrig setup` against the simulated Summit (emu/synth.py): no hardware.

The exact bytes setup would send go into the simulator over USB and DIN at
the rig's pacing, and the edit buffer is read back. The simulator starts
from a scrambled sound (every settable parameter at a random legal value),
standing in for whatever the user's base slot holds.
"""
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from emu.firmware import load_image  # noqa: E402
from hwrig import config, midi, params, recipes, setup  # noqa: E402

IMAGE = load_image()
pytestmark = pytest.mark.skipif(IMAGE is None, reason="firmware not present (scripts/fetch-firmware.sh)")

MPE_FLAG = 0x1A2


@pytest.fixture(scope="module")
def table():
    return params.Table(IMAGE)


@pytest.fixture(scope="module")
def summit():
    from emu.synth import SimulatedSummit
    return SimulatedSummit()


@pytest.fixture
def s(summit):
    summit.reset()
    summit.set_cc_nrpn_receive(True)
    summit.set_global(0x15, summit.global_setting(0x15) | 1)  # Bank/Patch receive
    return summit


def scramble(s, table, seed):
    rng = random.Random(seed)
    for p in table.sound_params():
        s.set_patch_byte(p.offset, rng.randint(p.min, min(p.max, 127)))
    s.set_patch_byte(MPE_FLAG, 1)


def play(s, steps, port, skip_select=True):
    for st in steps[1:] if skip_select else steps:
        s.midi_in(b"".join(st.data), port=port, run_ms=st.wait_s * 1000)
    s.tick(setup.SETTLE_S * 1000)


def test_table_matches_the_firmware(table):
    assert len(table.sound_params()) == 325
    unset = table.unsettable_sound_params()
    assert len(unset) == 21  # 5 'none' + FX-matrix slots 5-8 (NRPN 21-24, rejected by cc)
    assert {p.name for p in unset} == {"LevelComp", "text", "ClockRate", "SourceA", "SourceB",
                                       "Depth", "Fx Destin"}
    assert table.sources[:3] == ["Direct", "ModWheel", "AftTouch"] and len(table.sources) == 24
    assert table.dests[1] == "Osc1Ptch" and table.dests[10] == "Osc1 Lev" and len(table.dests) == 49
    assert table.waves == ["Sine", "Triangle", "Sawtooth", "Pulse", "BS sine"]
    assert table.modes == ["Mono", "MonoLG", "Mono2", "Poly", "Poly2"]
    assert str(table.param(0x083, "FiltFreq")) == "FiltFreq (0x083, CC 29)"
    assert str(table.param(0x0FE, "Depth")) == "Depth (0x0fe, NRPN 1:2)"
    with pytest.raises(ValueError, match="another firmware build"):
        table.param(0x083, "FiltReso")


@pytest.mark.slow
@pytest.mark.parametrize("name", [  # m1, f5: test_hwrig_run*.py; one worker each (7 s apiece)
    pytest.param(n, marks=pytest.mark.xdist_group(f"hwrig_setup_{n}"))
    for n, r in recipes.RECIPES.items() if r.base != "multi"])
def test_recipe_builds_its_sound_over_usb(s, table, name):
    recipe = recipes.RECIPES[name]
    scramble(s, table, seed=hash(name) & 0xFFFF)
    steps = setup.plan(table, recipe, config.Config())
    play(s, steps, "usb")
    want = setup.expected_patch(table, recipe)
    got = {o: s.patch_byte(o) for o in want}
    assert {o: (got[o], v) for o, v in want.items() if got[o] != v} == {}
    assert s.patch_byte(MPE_FLAG) == 1  # MIDI doesn't touch the flag: the base slot's stays


@pytest.mark.slow
@pytest.mark.xdist_group("hwrig_setup_din")
def test_recipe_over_din_on_another_channel(s, table):
    """DIN at the rig's pacing, on channel 1 after setting the global channel
    to 5 and sending on 5."""
    s.set_channels(global_=5)
    recipe = recipes.RECIPES["p4"]
    scramble(s, table, seed=4)
    steps = setup.plan(table, recipe, config.Config(channel=5))
    play(s, steps, "din")
    want = setup.expected_patch(table, recipe)
    assert all(s.patch_byte(o) == v for o, v in want.items())


def test_slot_select_loads_bank_d(s):
    for slot, shown in (("D002", "4-002"), ("D003", "4-003"), ("A000", "1-000")):
        s.midi_in(b"".join(m.data for m in midi.slot_msgs(1, slot)), port="usb", run_ms=300)
        bank, program = config.parse_slot(slot)
        assert (s.patch_byte(0x14), s.patch_byte(0x15)) == (bank, program)
        assert shown in s.screen_text()[0]


def test_plan_is_complete_and_paced(table):
    recipe = recipes.RECIPES["p2"]
    steps = setup.plan(table, recipe, config.Config())
    assert [d.hex() for d in steps[0].data] == ["b02004", "c002"]
    assert steps[0].wait_s == setup.PATCH_LOAD_S
    data = [d for st in steps for d in st.data]
    assert all(midi.check_message(d) for d in data)
    assert not [d for d in data if d[0] & 0xF0 == 0xB0 and d[1] == 0]  # never CC 0
    # paced no faster than DIN carries
    for st in steps[1:]:
        assert st.wait_s >= setup.BYTE_S * sum(len(d) for d in st.data)
    total = sum(st.wait_s for st in steps)
    assert 1.0 < total < 2.0
    text = setup.plan_text(table, recipe, config.Config(), "Summit", steps)
    assert "slot 1 source A = AftTouch" in text and "B0 63 01 | B0 62 00 | B0 06 02" in text
    assert "LevelComp" in text and "nothing is saved" in text
    assert "FX-matrix slots 5-8" in text


def test_recipes_reject_bad_names(table):
    bad = recipes.Recipe("x", "mpe", "", {(0x038, "Wave"): "Square"})
    with pytest.raises(ValueError, match="no Wave"):
        bad.resolve(table)
    with pytest.raises(ValueError, match="matrix destination"):
        recipes.Recipe("x", "mpe", "", matrix=[(1, "AftTouch", 10, "Pitch")]).resolve(table)
    with pytest.raises(ValueError, match="outside"):
        table.param(0x038, "Wave").messages(1, 9)
