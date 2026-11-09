"""The simulator cache (emu/cache.py): keys, atomic writes, locks, clearing."""

import multiprocessing
import threading
import time

import pytest

from emu import cache


def test_key_separates_every_part():
    assert cache.key("a", "bc") != cache.key("ab", "c")
    assert cache.key("a", b"b") == cache.key("a", "b")
    assert cache.key("x", "1") != cache.key("x", "2")


def test_emu_sources_hash_is_stable():
    assert cache.emu_sources_hash() == cache.emu_sources_hash()
    assert len(cache.emu_sources_hash()) == 64


def test_write_is_atomic_and_leaves_no_temp_files(tmp_path):
    entry = tmp_path / "kind" / "k.bin"
    assert cache.read(entry) is None
    cache.write(entry, b"one")
    cache.write(entry, b"two")
    assert cache.read(entry) == b"two"
    assert [p.name for p in entry.parent.iterdir()] == ["k.bin"]


def _hold(entry, held, release):
    with cache.locked(entry):
        held.set()
        release.wait(10)


def test_lock_excludes_other_processes(tmp_path):
    entry = tmp_path / "k.bin"
    ctx = multiprocessing.get_context("spawn")
    held, release = ctx.Event(), ctx.Event()
    p = ctx.Process(target=_hold, args=(entry, held, release))
    p.start()
    try:
        assert held.wait(30)
        release_at = time.monotonic() + 0.5
        threading.Timer(0.5, release.set).start()
        with cache.locked(entry):
            assert time.monotonic() >= release_at - 0.05
    finally:
        release.set()
        p.join(10)


def test_clear_removes_entries(tmp_path):
    cache.write(tmp_path / "a" / "x.bin", b"1")
    cache.write(tmp_path / "b" / "y.bin", b"2")
    assert cache.clear([tmp_path]) == 2
    assert list(tmp_path.iterdir()) == []


@pytest.mark.slow
def test_a_cold_boot_matches_a_cached_one():
    """The cache only saves time: formatting afresh boots to the same state."""
    from emu.firmware import SUMMIT_2_2, load_image
    from emu.synth import SimulatedSummit

    if load_image(SUMMIT_2_2) is None:
        pytest.skip(f"firmware/{SUMMIT_2_2} not present")
    warm, cold = SimulatedSummit(), SimulatedSummit(cache=False)
    assert warm.board.flash[11].snapshot() == cold.board.flash[11].snapshot()
    assert warm._ready[2:4] == cold._ready[2:4]  # SRAM and CCM
    warm.note_on(60)
    cold.note_on(60)
    warm.tick(20)
    cold.tick(20)
    assert warm.board.fpga.events == cold.board.fpga.events
