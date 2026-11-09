"""On-disk cache for expensive simulator set-up, in ``work/cache/`` (never committed).

Entries are keyed by hashes of every input that can change them (see
:func:`key`), so a different image or a changed board model never reads an
old entry. Writes are atomic and a per-entry lock lets one process build an
entry while the others (pytest-xdist workers, other worktrees sharing
``work/``) wait for it instead of building it again.

Clear it with ``scripts/dev python -I tools/cache.py clear``; set
``SUMMIT_MPE_NO_CACHE=1`` to bypass it for one run.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import os
import tempfile
from pathlib import Path
from typing import Iterable, Iterator, Optional, Union

from .firmware import REPO_ROOT

CACHE_DIR = REPO_ROOT / "work" / "cache"
EMU_DIR = Path(__file__).resolve().parent


def enabled() -> bool:
    return not os.environ.get("SUMMIT_MPE_NO_CACHE")


def emu_sources_hash() -> str:
    """SHA-256 over the simulator's own sources (every ``emu/*.py``)."""
    h = hashlib.sha256()
    for path in sorted(EMU_DIR.glob("*.py")):
        h.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return h.hexdigest()


def key(*parts: Union[str, bytes]) -> str:
    h = hashlib.sha256()
    for part in parts:
        data = part.encode() if isinstance(part, str) else part
        h.update(len(data).to_bytes(8, "little") + data)
    return h.hexdigest()[:32]


def path(kind: str, entry_key: str, suffix: str) -> Path:
    return CACHE_DIR / kind / f"{entry_key}{suffix}"


def read(entry: Path) -> Optional[bytes]:
    try:
        return entry.read_bytes()
    except FileNotFoundError:
        return None


def write(entry: Path, data: bytes) -> None:
    """Write *entry* atomically: readers see the old file, none, or all of it."""
    entry.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=entry.parent, prefix=entry.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, entry)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


@contextlib.contextmanager
def locked(entry: Path) -> Iterator[None]:
    """Hold an exclusive lock for *entry* while it is checked and built."""
    entry.parent.mkdir(parents=True, exist_ok=True)
    with open(entry.with_name(entry.name + ".lock"), "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def clear(dirs: Iterable[Path] = (CACHE_DIR,)) -> int:
    """Delete every cache entry; return how many files were removed."""
    n = 0
    for d in dirs:
        for f in sorted(Path(d).rglob("*"), reverse=True):
            if f.is_file():
                f.unlink()
                n += 1
            elif f.is_dir():
                f.rmdir()
    return n
