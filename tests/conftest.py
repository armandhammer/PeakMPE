import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from emu.firmware import SUMMIT_2_2, load_image  # noqa: E402
from emu.machine import Machine  # noqa: E402

# hwmark: the `hw` marker and --hw (deselected by default); pytester: its tests;
# shard: --shard I/N for parallel CI jobs (tests/shard.py).
pytest_plugins = ["hwmark", "pytester", "shard"]


@pytest.fixture(scope="session")
def booted_machine():
    image = load_image(SUMMIT_2_2)
    if image is None:
        pytest.skip(f"firmware/{SUMMIT_2_2} not present (run scripts/fetch-firmware.sh)")
    machine = Machine(image)
    machine.boot()
    return machine


@pytest.fixture
def machine(booted_machine):
    """The stock Summit 2.2 machine, reset to its post-boot RAM snapshot."""
    booted_machine.restore()
    booted_machine.unstub_all()
    booted_machine.periph_values.clear()
    yield booted_machine
    booted_machine.unstub_all()


@pytest.hookimpl(tryfirst=True)  # before xdist reads the xdist_group marks
def pytest_collection_modifyitems(config, items):
    """Under pytest-xdist (``-n auto``, ``--dist loadgroup`` from pytest.ini),
    keep the tests that share a module-scoped fixture on one worker, so the
    fixture (a patch build, a long simulator play) runs once, not once per
    worker. The other tests spread freely. An explicit xdist_group mark wins:
    it can share a worker-level cache across modules (bend_play.played) or
    split one module's plays (test_mpe_expr_queue)."""
    for item in items:
        if item.get_closest_marker("xdist_group"):
            continue
        info = getattr(item, "_fixtureinfo", None)
        defs = info.name2fixturedefs.values() if info else ()
        if any(d and d[-1].scope == "module" for d in defs):
            item.add_marker(pytest.mark.xdist_group(item.module.__name__))
