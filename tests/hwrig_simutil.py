"""Shared speed-ups for the rig's simulator tests (tests/test_hwrig_run*.py).

The simulator runs the firmware several times slower than real time, so
the rig's hardware timing (0.35 s settles, 0.3 s windows, 1 s tails, ~800
Init-value messages per setup) dominated the full suite. In the simulator:

- `fast_timing`: shorter settles, windows and tails. The firmware's bend
  smoothing closes 1/16 of the step per tick, so 150 ms leaves well under
  one unit of the per-voice pitch (4096 per octave); the tests assert the
  exact values, so a too-short settle would fail, not pass by accident.
- the stress stream: 1.5 s instead of 3 s (the same seeded stream, cut
  short), still ending with every note off and no voice left.
- `sim_steps`: a setup without its "init" steps. The simulator's slots hold
  the Init Patch already, so they change nothing there; the full streams
  are checked byte for byte in tests/test_hwrig_setup.py.
"""
import pytest

from hwrig import checks, checks3

FAST = {"PRE_S": 0.1, "SETTLE_S": 0.15, "WIN_S": 0.05, "TAIL_S": 0.3}
SIM_SETTLE_MS = 150
SIM_TAIL_MS = 400


@pytest.fixture
def fast_timing(monkeypatch):
    for mod in (checks, checks3):
        for name, value in FAST.items():
            monkeypatch.setattr(mod, name, value)
    monkeypatch.setattr(checks3, "STEP_S", FAST["SETTLE_S"] + FAST["WIN_S"] + 0.05)
    monkeypatch.setattr(checks3.B1ZoneChange, "HOLD_S", 0.15)
    monkeypatch.setattr(checks3.B1ZoneChange, "GAP_S", 0.1)
    monkeypatch.setattr(checks.StuckNotesStress, "SECONDS", 1.5)  # the same seeded stream, cut short


def sim_steps(steps):
    return [st for st in steps if not st.what.startswith("init ")]


def sim_wait_ms(step):
    """How long the simulator needs after a setup step: an MCM, a mode
    switch or an RPN is applied within a main-loop pass (the rig waits
    0.3 s on hardware); a program change keeps its full wait."""
    if step.what.startswith(("MCM", "NRPN 62", "RPN 0")):
        return 20.0
    return step.wait_s * 1000
