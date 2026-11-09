"""Hardware: the stage-2 and stage-3 runs (docs/hw-test-rig.md#checks) as tests.

Deselected unless `--hw`; asks for `play` once, so it needs `-s`, no `-n`:

    .venv/bin/python -m pytest --hw -s -m hw tests/test_hw_run.py

Uses work/hwrig.toml; the report lands in work/hw-runs/<timestamp>/.
"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from hwrig import audio, checks, checks3, cli, config, midi, params, run  # noqa: E402

pytestmark = pytest.mark.hw


@pytest.mark.parametrize("stage", ["2", "3"])
def test_stage_run(pytestconfig, stage):
    if pytestconfig.getoption("capture") != "no":
        pytest.skip("hardware tests ask for 'play': run with -s")
    if pytestconfig.getoption("numprocesses", None):
        pytest.skip("hardware tests run in one process: drop -n")
    cfg = config.load().validate()
    port = midi.check_port_name(midi.find_port(midi.output_ports(), cfg.usb_port))
    dev = audio.resolve_device(cfg.audio_device)
    rec = audio.SoundDeviceRecorder(dev[0], cfg.inputs, cfg.samplerate)
    plan = run.Plan(cfg, params.load_table(), checks.stage2() if stage == "2" else checks3.stage3())
    out = config.RUNS_DIR / time.strftime("%Y-%m-%d_%H%M%S")
    rows = run.run(plan, port, lambda: midi.RtMidiOut(port), rec, cli.confirm_play, out)
    if rows is None:
        pytest.skip("not confirmed: nothing sent")
    bad = [f"{r.check}: {r.item} ({r.measured})" for r in rows if r.status == "fail"]
    assert not bad, f"{bad}; report {out / 'report.md'}"
