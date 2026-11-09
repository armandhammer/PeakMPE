"""Hardware: the stage-1 probe as a test (docs/hw-test-rig.md).

Deselected unless `--hw`. Sends MIDI to the real Summit only after you type
`play`, so it needs `-s` (no output capture) and no `-n`:

    .venv/bin/python -m pytest --hw -s -m hw tests/test_hw_probe.py

Uses work/hwrig.toml. Test patch: "P1 sine" in its reserved slot, selected
on the Summit by hand (or with probe.program in the config).
"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from hwrig import audio, cli, config, midi, probe  # noqa: E402

pytestmark = pytest.mark.hw


def test_probe_notes_in_tune(pytestconfig):
    if pytestconfig.getoption("capture") != "no":
        pytest.skip("hardware tests ask for 'play': run with -s")
    if pytestconfig.getoption("numprocesses", None):
        pytest.skip("hardware tests run in one process: drop -n")
    cfg = config.load().validate()
    port = midi.find_port(midi.output_ports(), cfg.usb_port)
    dev = audio.resolve_device(cfg.audio_device)
    rec = audio.SoundDeviceRecorder(dev[0], cfg.inputs, cfg.samplerate)
    out = config.RUNS_DIR / time.strftime("%Y-%m-%d_%H%M%S") / "probe"
    res = probe.run(cfg, port, lambda: midi.RtMidiOut(port), rec, cli.confirm_play, out)
    if res is None:
        pytest.skip("not confirmed: nothing sent")
    bad = [f"{r.name}: {r.status}" for r in res if r.status != "ok"]
    assert not bad, f"{bad}; WAVs in {out}"
