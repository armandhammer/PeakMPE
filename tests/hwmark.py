"""The `hw` marker: tests that drive the real Summit (docs/hw-test-rig.md).

They are deselected unless pytest gets `--hw`, so `pytest -n auto` and the
merge hooks never send MIDI. Even with `--hw`, every hardware test prints
what it will send and waits for the user to type `play` (run with `-s`).

Loaded from tests/conftest.py as a plugin.
"""


def pytest_addoption(parser):
    parser.addoption("--hw", action="store_true", default=False,
                     help="also run tests marked hw: they send MIDI to the real Summit "
                          "after you type 'play' (use -s, without -n)")


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "hw: drives the real Summit over MIDI and records audio; "
                   "deselected unless --hw is given")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--hw"):
        return
    hw = [i for i in items if i.get_closest_marker("hw")]
    if hw:
        config.hook.pytest_deselected(items=hw)
        items[:] = [i for i in items if not i.get_closest_marker("hw")]
