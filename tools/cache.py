#!/usr/bin/env python3
"""Show or clear the simulator cache in work/cache/ (emu/cache.py).

  cache.py            list the entries and their size
  cache.py clear      delete them all (and the old work/sim-cache/)

Every entry is keyed by the hashes of its inputs, so clearing is never
needed for correctness; it frees space, or rules the cache out while
debugging (SUMMIT_MPE_NO_CACHE=1 bypasses it for one run). Run with
`scripts/dev python -I tools/cache.py ...`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from emu import cache  # noqa: E402

OLD_DIR = cache.REPO_ROOT / "work" / "sim-cache"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["clear"]:
        n = cache.clear([d for d in (cache.CACHE_DIR, OLD_DIR) if d.exists()])
        print(f"removed {n} files")
        return 0
    if argv:
        print(__doc__, file=sys.stderr)
        return 2
    files = [f for f in sorted(cache.CACHE_DIR.rglob("*")) if f.is_file() and not f.name.endswith(".lock")]
    for f in files:
        print(f"{f.stat().st_size:>10}  {f.relative_to(cache.REPO_ROOT)}")
    print(f"{len(files)} entries, {sum(f.stat().st_size for f in files)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
