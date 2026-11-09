"""The `hw` marker keeps hardware tests out of every normal run."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HW_TEST = """
import pytest

@pytest.mark.hw
def test_needs_the_synth():
    raise AssertionError("an hw test ran without --hw")

def test_normal():
    pass
"""


def test_hw_tests_are_deselected_by_default(pytester):
    pytester.makepyfile(HW_TEST)
    r = pytester.runpytest("-p", "hwmark")
    r.assert_outcomes(passed=1, deselected=1)


def test_hw_tests_are_deselected_under_m_expressions(pytester):
    pytester.makepyfile(HW_TEST)
    pytester.runpytest("-p", "hwmark", "-m", "hw").assert_outcomes(deselected=2)
    pytester.runpytest("-p", "hwmark", "-m", "not slow").assert_outcomes(passed=1, deselected=1)


def test_hw_tests_run_with_the_flag(pytester):
    pytester.makepyfile(HW_TEST)
    r = pytester.runpytest("-p", "hwmark", "--hw")
    r.assert_outcomes(passed=1, failed=1)


def test_the_repo_suite_collects_no_hw_test(request):
    """In this very run (whatever -m or -n), no collected item is hw-marked
    unless --hw was given."""
    if request.config.getoption("--hw"):
        return
    assert not [i for i in request.session.items if i.get_closest_marker("hw")]


def test_hw_test_files_are_marked():
    """Every tests/test_hw_*.py marks all of its tests hw (module pytestmark)."""
    for f in sorted((ROOT / "tests").glob("test_hw_*.py")):
        assert "pytestmark = pytest.mark.hw" in f.read_text(), f.name
