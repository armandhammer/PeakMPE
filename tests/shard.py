"""Split the suite into N shards for parallel CI jobs (``--shard I/N``).

The unit is what pytest-xdist keeps on one worker: an ``xdist_group`` (set in
conftest.py for tests that share a module-scoped fixture, or explicitly), else
the test file. A unit is never split, so a long simulator play still runs once.
Units go to shards greedily, heaviest first, by their weight in
``tests/shard_weights.json`` (seconds measured by ``--shard-weights-out``);
a unit not in the file counts 1 s per test. Every shard computes the same
assignment from the same collection, so together the shards run each test
exactly once.

Refresh the weights after adding or changing slow tests (a full run, with -n):

    scripts/dev python -m pytest -q -n auto --shard-weights-out tests/shard_weights.json
"""
import json
from collections import defaultdict
from pathlib import Path

import pytest

WEIGHTS = Path(__file__).resolve().parent / "shard_weights.json"


def pytest_addoption(parser):
    g = parser.getgroup("shard")
    g.addoption("--shard", metavar="I/N", help="run only shard I of N (1-based), for parallel CI jobs")
    g.addoption("--shard-weights-out", metavar="FILE",
                help="after the run, write the seconds per unit (xdist group or file) to FILE; use with -n")


def parse(spec):
    try:
        i, n = (int(x) for x in spec.split("/"))
    except ValueError:
        raise pytest.UsageError(f"--shard wants I/N, for example 2/6, not {spec!r}")
    if not 1 <= i <= n:
        raise pytest.UsageError(f"--shard {spec}: I must be between 1 and N")
    return i, n


def unit(item):
    mark = item.get_closest_marker("xdist_group")
    if mark:
        return mark.args[0] if mark.args else mark.kwargs.get("name", "default")
    return item.nodeid.split("::", 1)[0]


def assign(units, weights, n):
    """{unit: shard index 0..n-1}: heaviest first, each to the lightest shard."""
    load = [0.0] * n
    out = {}
    for name in sorted(units, key=lambda u: (-weights.get(u, units[u]), u)):
        k = min(range(n), key=lambda s: (load[s], s))
        out[name] = k
        load[k] += weights.get(name, units[name])
    return out


@pytest.hookimpl(trylast=True)  # after conftest.py has added the xdist groups
def pytest_collection_modifyitems(config, items):
    spec = config.getoption("--shard")
    if not spec:
        return
    i, n = parse(spec)
    counts = defaultdict(int)
    for item in items:
        counts[unit(item)] += 1
    weights = json.loads(WEIGHTS.read_text()) if WEIGHTS.exists() else {}
    shard_of = assign(counts, weights, n)
    keep, drop = [], []
    for item in items:
        (keep if shard_of[unit(item)] == i - 1 else drop).append(item)
    if drop:
        config.hook.pytest_deselected(items=drop)
    items[:] = keep


class _Timer:
    def __init__(self, path):
        self.path = Path(path)
        self.seconds = defaultdict(float)

    def pytest_runtest_logreport(self, report):
        # Under xdist --dist loadgroup the controller sees "file::test@group".
        nodeid, _, group = report.nodeid.partition("@")
        self.seconds[group or nodeid.split("::", 1)[0]] += report.duration

    def pytest_sessionfinish(self):
        data = {k: round(v, 1) for k, v in sorted(self.seconds.items())}
        self.path.write_text(json.dumps(data, indent=1) + "\n")


def pytest_configure(config):
    out = config.getoption("--shard-weights-out", None)
    if out and not hasattr(config, "workerinput"):  # the controller (or no xdist)
        config.pluginmanager.register(_Timer(out), "shard-timer")
