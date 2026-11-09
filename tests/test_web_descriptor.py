"""tools/web_descriptor.py: the web patcher's descriptor holds no Novation bytes
and reproduces tools/patch.py's output (docs/web.md)."""
import base64
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import patch  # noqa: E402
import web_descriptor as wd  # noqa: E402

DEFINITION = ROOT / "patches" / "mpe" / "patch.py"
DESCRIPTOR = ROOT / "web" / "patches" / "mpe.json"


def test_changed_runs_drop_unchanged_bytes_and_keep_bytes_past_the_end():
    image = b"abcdef"
    base = patch.IMAGE_BASE
    assert wd.changed_runs(image, base + 1, b"bXdY") == [(base + 2, b"X"), (base + 4, b"Y")]
    assert wd.changed_runs(image, base + 4, b"efgh") == [(base + 6, b"gh")]
    assert wd.changed_runs(image, base, b"abc") == []


def test_split_at_pointers_cuts_out_aligned_firmware_addresses():
    ram = (0x20004B20).to_bytes(4, "little")
    flash = (0x0801D9BD).to_bytes(4, "little")
    ccm = (0x10000224).to_bytes(4, "little")  # patch RAM: ours, not a firmware address
    data = b"\x01\x02\x03\x04" + ram + ccm + flash + b"\x05"
    assert wd.split_at_pointers(0x08050000, data) == [b"\x01\x02\x03\x04", ccm, b"\x05"]
    # Alignment follows the absolute address, not the start of the run.
    assert wd.split_at_pointers(0x08050002, b"\xaa\xbb" + ram) == [b"\xaa\xbb"]


def test_longest_shared():
    hay = b"0123456789abcdef"
    assert wd.longest_shared([b"xx456789yy"], [hay]) == 6
    assert wd.longest_shared([b"zzz"], [hay]) == 0
    assert wd.longest_shared([b"zz", b"--cdef"], [b"", hay]) == 4


@pytest.fixture(scope="module")
def committed():
    if not (patch.FIRMWARE_DIR / "summit-firmware-2.2-build2121.syx").exists():
        pytest.skip("firmware/summit-firmware-2.2-build2121.syx not present (run scripts/fetch-firmware.sh)")
    return json.loads(DESCRIPTOR.read_text())


def test_committed_descriptor_passes_the_no_novation_bytes_check(committed):
    lines = wd.check(committed)
    assert lines[-1].startswith("check   ok")


def test_committed_descriptor_is_up_to_date(committed, tmp_path):
    fresh = wd.export(DEFINITION, build_dir=tmp_path)
    fresh["built"] = committed["built"]
    assert fresh == committed, "web/patches/mpe.json is stale: re-run tools/web_descriptor.py export"


def test_descriptor_rebuilds_patch_py_output(committed, tmp_path):
    path, digest = patch.build(DEFINITION, out_dir=tmp_path, out=lambda s: None, build_dir=tmp_path / "b")
    official = patch.read_official(patch.FIRMWARE_DIR, committed["input"]["fileName"])
    header, image = wd.apply_descriptor(committed, official)
    assert wd.syx.encode(header, image) == path.read_bytes()
    assert committed["output"]["sha256"] == digest


def test_check_rejects_a_copied_stock_byte(committed):
    bad = copy.deepcopy(committed)
    w = bad["writes"][0]
    off = int(w["address"], 16) - patch.IMAGE_BASE
    _, image = wd.syx.decode(patch.read_official(patch.FIRMWARE_DIR, bad["input"]["fileName"]))
    w["data"] = base64.b64encode(image[off:off + 1]).decode()
    with pytest.raises(patch.PatchError, match="equals the official byte"):
        wd.check(bad)


def test_check_rejects_a_copied_run_past_the_end(committed):
    bad = copy.deepcopy(committed)
    _, image = wd.syx.decode(patch.read_official(patch.FIRMWARE_DIR, bad["input"]["fileName"]))
    blob = next(w for w in bad["writes"] if w["why"].startswith("patch blob"))
    data = bytearray(base64.b64decode(blob["data"]))
    data[100:132] = image[0x1000:0x1020]
    blob["data"] = base64.b64encode(bytes(data)).decode()
    with pytest.raises(patch.PatchError, match="occurs in the official firmware"):
        wd.check(bad)


def test_check_rejects_extra_fields(committed):
    bad = copy.deepcopy(committed)
    bad["original"] = "00"
    with pytest.raises(patch.PatchError, match="top-level keys"):
        wd.check(bad)


needs_gcc = pytest.mark.skipif(not patch.patch_build.available(), reason="arm-none-eabi-gcc not installed")


@needs_gcc
def test_compare_blob_needs_no_firmware(tmp_path):
    """`compare --blob-only` (what runs without Novation's file) rebuilds
    the blob from source and finds it equal to the committed descriptor."""
    desc = json.loads(DESCRIPTOR.read_text())
    lines = wd.compare(desc, DEFINITION, firmware_dir=tmp_path, blob_only=True)
    assert any(line.startswith("blob    ") and "equal to the descriptor" in line for line in lines)
    assert lines[-1] == "compare ok"
    lines = wd.compare(desc, DEFINITION, firmware_dir=tmp_path)  # no firmware there: full skipped
    assert any(line.startswith("full    skipped: no ") for line in lines)


@needs_gcc
def test_compare_refuses_a_changed_blob(tmp_path):
    desc = json.loads(DESCRIPTOR.read_text())
    bad = copy.deepcopy(desc)
    w = next(w for w in bad["writes"] if w["why"].startswith("patch blob mpe"))
    data = bytearray(base64.b64decode(w["data"]))
    data[10] ^= 0x01
    w["data"] = base64.b64encode(bytes(data)).decode()
    with pytest.raises(patch.PatchError, match="compiled blob differs"):
        wd.compare(bad, DEFINITION, firmware_dir=tmp_path, blob_only=True)


@needs_gcc
def test_compare_full_against_the_firmware(committed):
    lines = wd.compare(committed, DEFINITION)
    assert any(line.startswith("full    fresh export equal") for line in lines)
