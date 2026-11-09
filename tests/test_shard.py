"""tests/shard.py: the CI shard assignment."""
import pytest

import shard


def test_assign_balances_and_is_deterministic():
    units = {f"u{i}": 1 for i in range(10)}
    weights = {"u0": 50, "u1": 40, "u2": 30, "u3": 20}
    a = shard.assign(units, weights, 3)
    assert a == shard.assign(dict(reversed(units.items())), weights, 3)
    load = [0] * 3
    for u, k in a.items():
        load[k] += weights.get(u, units[u])
    assert max(load) - min(load) <= 10
    assert set(a) == set(units)


def test_unknown_units_count_their_tests():
    a = shard.assign({"big": 9, "s1": 1, "s2": 1}, {}, 2)
    assert a["s1"] == a["s2"] != a["big"]


@pytest.mark.parametrize("spec", ["0/3", "4/3", "x", "1/"])
def test_bad_specs_are_refused(spec):
    with pytest.raises(pytest.UsageError):
        shard.parse(spec)
