"""Locate and decode the stock firmware image for the harness.

Images are never committed: ``scripts/fetch-firmware.sh`` puts them in the
git-ignored ``firmware/``. When the file is missing, :func:`load_image`
returns None so tests can skip. ``SUMMIT_MPE_FIRMWARE_DIR`` overrides the
directory.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
FIRMWARE_DIR = Path(os.environ.get("SUMMIT_MPE_FIRMWARE_DIR", REPO_ROOT / "firmware"))
SUMMIT_2_2 = "summit-firmware-2.2-build2121.syx"


def _syx_module():
    spec = importlib.util.spec_from_file_location("syx", REPO_ROOT / "tools" / "syx.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def expected_sha256(name: str) -> Optional[str]:
    sums = FIRMWARE_DIR / "SHA256SUMS"
    if not sums.exists():
        return None
    for line in sums.read_text().splitlines():
        digest, _, file = line.partition("  ")
        if file.strip() == name:
            return digest
    return None


def load_image(name: str = SUMMIT_2_2) -> Optional[bytes]:
    """Decode ``firmware/<name>`` to a flat image, or return None if absent.

    Raises ValueError if the file does not match its hash in
    ``firmware/SHA256SUMS``: the harness addresses are specific to one build.
    """
    path = FIRMWARE_DIR / name
    if not path.exists():
        return None
    data = path.read_bytes()
    expected = expected_sha256(name)
    if expected and hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"{path} does not match firmware/SHA256SUMS")
    _header, image = _syx_module().decode(data)
    return image
