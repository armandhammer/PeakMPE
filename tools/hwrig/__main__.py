"""Entry point: `.venv/bin/python -I tools/hwrig <command>` (see cli.py)."""
import sys
from pathlib import Path

if __package__ in (None, ""):
    # Run as a directory: put tools/ on the path and import as a package.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from hwrig.cli import main
else:
    from .cli import main

sys.exit(main())
