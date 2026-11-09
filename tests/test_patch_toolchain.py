"""The C patch toolchain: tools/patch_build.py, hooks and --verify in tools/patch.py.

Three layers, each skipping when what it needs is missing:
  * BL encoding and hook checks on synthetic data (always run);
  * building blobs (needs arm-none-eabi-gcc): layout, ABI and refusals;
  * the demo patch patches/demo_note_hook/ on the real image (also needs the
    official firmware): verify, then the emulator feeds note-ons through
    the real input path (midi_parse_byte -> midi_channel_filter -> handler
    table) and compares with the stock image.
"""

import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import flash  # noqa: E402
import patch  # noqa: E402
import patch_build  # noqa: E402
import syx  # noqa: E402
from patch import PatchError  # noqa: E402
from patch_build import BuildError  # noqa: E402

from emu.firmware import SUMMIT_2_2, load_image  # noqa: E402
from emu.machine import CCM_BASE, CCM_SIZE, SRAM_BASE, SRAM_SIZE, Machine  # noqa: E402

DEMO = ROOT / "patches" / "demo_note_hook" / "patch.py"
BASE = patch.IMAGE_BASE

# Firmware addresses (docs/findings/summit-2.2-build2121.md, "The MIDI path").
MIDI_QUEUE_SELECT = 0x080100F4
MIDI_PARSE_BYTE = 0x080107B0
NOTE_ON, NOTE_ON_DIRECT = 0x08010AB0, 0x08010B30   # 0x08010B30: (note, vel, part), keybed/arp path
VOICE_TRIGGER, VOICE_ALLOC = 0x08017244, 0x08016B40
MAIN_LOOP, STARTUP_BL = 0x0801C564, 0x0801D9F2
HANDLER_9X = 0x200002D8                             # RAM entry, initialiser at flash 0x0804C058
PARTS, LAST_NOTE = 0x20013388, 0x126
VOICE_NOTE = 0x20014950
SPI1_SR = 0x40013008                                # FPGA writes wait for TXE
DEMO_MAGIC = 0x4D504530

needs_gcc = pytest.mark.skipif(not patch_build.available(), reason="arm-none-eabi-gcc not installed")
needs_llvm = pytest.mark.skipif(not (patch.LLVM_BIN / "llvm-objdump").exists(), reason="llvm-objdump not installed")


# ------------------------------------------------------------ BL encoding

@pytest.mark.parametrize("site, raw, target", [
    (0x08010B0A, "06f09bfb", 0x08017244),   # note_on -> voice_trigger (forward)
    (0x0801D9F2, "fef7b7fd", 0x0801C564),   # Reset_Handler -> main_loop (backward)
])
def test_bl_decodes_firmware_calls(site, raw, target):
    assert patch.decode_bl(site, bytes.fromhex(raw)) == target
    assert patch.encode_bl(site, target) == bytes.fromhex(raw)


@pytest.mark.parametrize("delta", [4, -4, 0x100000, -0x100000, (1 << 24) - 2, -(1 << 24)])
def test_bl_round_trips(delta):
    site = 0x08030000
    assert patch.decode_bl(site, patch.encode_bl(site, site + 4 + delta)) == site + 4 + delta


def test_bl_refuses_out_of_range_and_odd_targets():
    with pytest.raises(PatchError, match="cannot reach"):
        patch.encode_bl(0x08000000, 0x08000004 + (1 << 24))
    with pytest.raises(PatchError, match="cannot reach"):
        patch.encode_bl(0x08000000, 0x08000005)


def test_decode_bl_rejects_other_instructions():
    assert patch.decode_bl(0, bytes.fromhex("00bf00bf")) is None   # nop; nop
    assert patch.decode_bl(0, bytes.fromhex("00f000b8")) is None   # b.w, not bl


# --------------------------------------------------------- hook checking

class FakeBlob:
    origin, data, bss = 0x08000100, b"\0" * 0x40, (0x10000000, 0x10000010)
    symbols = {"fn": (0x08000111, "FUNC"), "buf": (0x10000004, "OBJECT"),
               "fw": (0x08010AB1, "NOTYPE")}

    def address(self, name):
        return self.symbols[name][0]

    def is_function(self, name):
        return self.symbols[name][1] == "FUNC"


def synthetic_image():
    img = bytearray(0x100)
    img[0x10:0x14] = patch.encode_bl(BASE + 0x10, BASE + 0x80)
    img[0x20:0x24] = struct.pack("<I", 0x08010AB1)
    return bytes(img)


def test_hooks_become_checked_byte_patches():
    hooks = patch.resolve_hooks([("bl", BASE + 0x10, BASE + 0x80, "fn", "t"),
                                 ("pointer", BASE + 0x20, 0x08010AB1, "fn", "t")], FakeBlob())
    assert [h.target for h in hooks] == [0x08000110, 0x08000111]
    out = patch.apply(synthetic_image(), patch.hook_patches(synthetic_image(), hooks))
    assert patch.decode_bl(BASE + 0x10, out[0x10:0x14]) == 0x08000110
    assert struct.unpack_from("<I", out, 0x20)[0] == 0x08000111


@pytest.mark.parametrize("spec, message", [
    (("bl", BASE + 0x10, BASE + 0x84, "fn", "t"), "expected a BL to 0x0800c084, found a BL to 0x0800c080"),
    (("bl", BASE + 0x20, BASE + 0x80, "fn", "t"), "found not a BL"),
    (("pointer", BASE + 0x20, 0x08010AB0, "fn", "t"), "expected the word 0x08010ab0, found 0x08010ab1"),
    (("pointer", BASE + 0x22, 0, "fn", "t"), "4-byte aligned"),
])
def test_hooks_refuse_unexpected_originals(spec, message):
    hooks = patch.resolve_hooks([spec], FakeBlob())
    with pytest.raises(PatchError, match=message):
        patch.hook_patches(synthetic_image(), hooks)


@pytest.mark.parametrize("spec, message", [
    (("bl", BASE, 0, "missing", "t"), "not defined"),
    (("bl", BASE, 0, "buf", "t"), "not a patch function"),
    (("bl", BASE, 0, "fw", "t"), "not a patch function"),          # a firmware address, not the blob
    (("pointer", BASE, 0, "fw", "t"), "not in the patch blob"),
    (("jump", BASE, 0, "fn", "t"), "unknown kind"),
])
def test_hooks_must_target_the_blob(spec, message):
    with pytest.raises(PatchError, match=message):
        patch.resolve_hooks([spec], FakeBlob())


def test_pointer_hook_may_point_at_patch_ram():
    (hook,) = patch.resolve_hooks([("pointer", BASE + 0x20, 0, "buf", "t")], FakeBlob())
    assert hook.target == 0x10000004


def test_hooks_need_sources(tmp_path):
    d = tmp_path / "p.py"
    d.write_text("SOURCE = 'x'\nNAME = 'x'\nPATCHES = []\nHOOKS = [('bl', 0, 0, 'f', 'w')]\n")
    with pytest.raises(PatchError, match="HOOKS need SOURCES"):
        patch.load_definition(d)


def test_firmware_symbols_get_the_thumb_bit():
    syms = patch_build.firmware_symbols()
    assert syms["note_on"] == (0x08010AB1, "function")
    assert syms["midi_channel_handlers"] == (0x200002D0, "data")


# --------------------------------------------------------------- building

def c_file(tmp_path, text, name="t.c"):
    path = tmp_path / name
    path.write_text('#include "firmware.h"\n' + text)
    return path


@needs_gcc
def test_blob_layout(tmp_path):
    blob = patch_build.build("demo", patch.sources(patch.load_definition(DEMO)), build_dir=tmp_path)
    assert blob.origin == 0x080501C0 and blob.origin + len(blob.data) <= patch_build.FLASH_LIMIT
    assert blob.bss[0] == CCM_BASE and blob.bss[1] - blob.bss[0] == 16
    for fn in ("__patch_start", "demo_note_on", "demo_voice_trigger", "patch_init"):
        value, kind = blob.symbols[fn]
        assert kind == "FUNC" and value & 1 and blob.origin <= value < blob.origin + len(blob.data)
    assert blob.address("__patch_start") == blob.origin | 1      # first in .text
    assert blob.symbols["demo_note_on_calls"] == (CCM_BASE + 4, "OBJECT")


@needs_gcc
def test_blob_uses_the_firmware_float_abi(tmp_path):
    src = c_file(tmp_path, "float half(float x) { return x * 0.5f; }\n")
    blob = patch_build.build("abi", [src], build_dir=tmp_path)
    attrs = patch_build._run([patch_build.tool("readelf"), "-A", blob.elf])
    assert "Tag_ABI_VFP_args: VFP registers" in attrs
    assert "Tag_FP_arch: VFPv4-D16" in attrs


@needs_gcc
@pytest.mark.parametrize("text, message", [
    ("int counter = 5;\nint get(void) { return counter++; }\n", "needs .data"),
    ("const char big[70000] = {1};\nchar get(int i) { return big[i]; }\n", "will not fit in region .FREE_FLASH"),
    ("void note_on(const uint8_t *d, uint32_t a, uint32_t b, uint32_t c) { (void)d; (void)a; (void)b; (void)c; }\n",
     "is a firmware symbol"),
    ("int f(void) { return undefined_thing(); }\n", "failed"),
])
def test_build_refuses(tmp_path, text, message):
    with pytest.raises(BuildError, match=message):
        patch_build.build("bad", [c_file(tmp_path, text)], build_dir=tmp_path)


@needs_gcc
def test_build_refuses_origin_past_the_sector():
    with pytest.raises(BuildError, match="not below"):
        patch_build.write_link_files(Path("."), patch_build.FLASH_LIMIT, {})


# ------------------------------------------------- the demo patch, emulated

@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    if load_image(SUMMIT_2_2) is None:
        pytest.skip(f"firmware/{SUMMIT_2_2} not present (run scripts/fetch-firmware.sh)")
    if not patch_build.available():
        pytest.skip("arm-none-eabi-gcc not installed")
    return patch.build_image(DEMO, build_dir=tmp_path_factory.mktemp("build"))


@pytest.fixture(scope="module")
def stock_and_patched(demo):
    machines = []
    for image in (demo.image, demo.patched):
        m = Machine(image)
        m.boot()
        machines.append(m)
    return machines


def reset(m, patched_startup):
    """Post-boot RAM, CCM filled with garbage (as on hardware), FPGA link ready."""
    m.restore()
    m.unstub_all()
    m.periph_values.clear()
    m.periph_values[SPI1_SR] = 0x03
    m.write(CCM_BASE, b"\xa5" * CCM_SIZE)
    if patched_startup:
        m.run(STARTUP_BL, MAIN_LOOP, budget=100_000, sp=m.initial_sp)
    m.periph_log.clear()


def send(m, *data, src=0):
    m.call(MIDI_QUEUE_SELECT, src)
    for b in data:
        m.call(MIDI_PARSE_BYTE, b, budget=500_000)


def demo_u32(m, demo, name):
    return m.u32(demo.blob.address(name))


@needs_llvm
def test_demo_verifies(demo):
    lines = []
    patch.verify(demo.patched, demo.hooks, demo.blob, out=lines.append)
    assert lines[-1] == "verify  ok"
    assert {h.symbol for h in demo.hooks} == {"__patch_start", "demo_note_on", "demo_voice_trigger"}


def test_demo_changes_only_hook_sites_and_appends(demo):
    sites = {h.site + i for h in demo.hooks for i in range(4)}
    changed = {a + i for a, old, new in patch.diff(demo.image, demo.patched[:len(demo.image)])
               for i in range(len(old))}
    assert changed <= sites
    end = BASE + len(demo.image)
    tail = demo.patched[len(demo.image):]
    assert tail[:len(demo.blob.data)] == demo.blob.data and set(tail[len(demo.blob.data):]) <= {0xFF}
    assert demo.blob.origin == end and len(demo.patched) % syx.BLOCK == 0


def test_demo_file_passes_flash_check_and_dry_run(demo):
    data = syx.encode(demo.new_header, demo.patched)
    plan = flash.Plan(data)
    assert plan.product == "Summit" and plan.image == demo.patched
    synth = flash.SimulatedSynth("Summit")
    flash.flash(plan, synth, flash.Log(out=lambda s: None), confirm=lambda q: True, sleep=lambda s: None)
    assert b"".join(synth.received) == data


def test_startup_hook_zeroes_patch_ram_and_runs_patch_init(demo, stock_and_patched):
    _, m = stock_and_patched
    reset(m, patched_startup=False)
    entered = []
    m.uc.hook_add(4, lambda uc, a, s, u: entered.append(a), begin=demo.blob.origin, end=demo.blob.origin)
    m.run(STARTUP_BL, MAIN_LOOP, budget=100_000, sp=m.initial_sp)  # stops on main_loop's first instruction
    assert entered == [demo.blob.origin]
    lo, hi = demo.blob.bss
    assert demo_u32(m, demo, "demo_magic") == DEMO_MAGIC
    assert m.read(lo + 4, hi - lo - 4) == bytes(hi - lo - 4)
    assert m.read(hi, 64) == b"\xa5" * 64                           # nothing past .bss


def test_note_on_reaches_the_wrapper_and_the_stock_handler(demo, stock_and_patched):
    _, m = stock_and_patched
    reset(m, patched_startup=True)
    assert m.u32(HANDLER_9X) == demo.blob.address("demo_note_on")   # .data initialiser was patched
    reached = []
    for addr in (NOTE_ON, VOICE_ALLOC):
        m.uc.hook_add(4, lambda uc, a, s, u: reached.append(a), begin=addr, end=addr)
    send(m, 0x90, 60, 100)
    assert demo_u32(m, demo, "demo_note_on_calls") == 1
    assert demo_u32(m, demo, "demo_voice_trigger_calls") == 1
    assert m.u8(demo.blob.address("demo_last_note")) == 60
    assert reached == [NOTE_ON, VOICE_ALLOC]
    assert m.u8(PARTS + LAST_NOTE) == 60 and 60 in m.read(VOICE_NOTE, 16)


def test_running_status_and_velocity_zero_go_through_the_wrapper(demo, stock_and_patched):
    _, m = stock_and_patched
    reset(m, patched_startup=True)
    send(m, 0x90, 60, 100, 64, 90, 60, 0)        # running status; the last is a note-off
    assert demo_u32(m, demo, "demo_note_on_calls") == 3
    assert demo_u32(m, demo, "demo_voice_trigger_calls") == 2
    send(m, 0x91, 61, 100)                        # channel 2: Single mode drops it
    assert demo_u32(m, demo, "demo_note_on_calls") == 3


def test_bl_hook_catches_callers_that_bypass_the_table(demo, stock_and_patched):
    _, m = stock_and_patched
    reset(m, patched_startup=True)
    m.call(NOTE_ON_DIRECT, 67, 100, 0, budget=500_000)
    assert demo_u32(m, demo, "demo_note_on_calls") == 0
    assert demo_u32(m, demo, "demo_voice_trigger_calls") == 1
    assert m.u8(demo.blob.address("demo_last_note")) == 67


SEQUENCE = [(0, (0x90, 60, 100, 64, 90)), (1, (0x90, 67, 127)), (0, (0x80, 60, 0)), (0, (0x90, 64, 0)),
            (0, (0xE0, 0, 0x50)), (1, (0x90, 72, 1))]


def test_patched_behaves_like_stock_apart_from_patch_ram(demo, stock_and_patched):
    runs = []
    for m, patched in zip(stock_and_patched, (False, True)):
        reset(m, patched_startup=patched)
        for src, data in SEQUENCE:
            send(m, *data, src=src)
        runs.append((m.read(SRAM_BASE, SRAM_SIZE),
                     [(a.kind, a.pc, a.addr, a.size, a.value) for a in m.periph_log]))
    (sram0, io0), (sram1, io1) = runs
    assert io1 == io0 and len(io0) > 100       # identical FPGA/peripheral traffic
    stack = m.initial_sp - 0x1000 - SRAM_BASE  # call frames differ: the wrappers are on the stack
    entry = HANDLER_9X - SRAM_BASE
    diffs = [i for i in range(stack) if sram0[i] != sram1[i]]
    assert all(entry <= i < entry + 4 for i in diffs) and diffs
    assert sram1[entry:entry + 4] == struct.pack("<I", demo.blob.address("demo_note_on"))


# ------------------------------------------------ byte patches unchanged

@pytest.mark.parametrize("definition, digest", [
    ("version_string.py", "dcbd553e6266f9151f2924d121c9e451eb59c98958ab7bd7d90e42e8dd2419c4"),
    ("version_word.py", "9352764666b672c03145fb0fa5a89e241b1981bbc3c12f343d212c86a984bb8c"),
])
def test_flashed_byte_patches_build_to_their_logged_hashes(tmp_path, definition, digest):
    """These exact images were flashed and booted on 2026-10-31 (docs/findings)."""
    if load_image(SUMMIT_2_2) is None:
        pytest.skip(f"firmware/{SUMMIT_2_2} not present (run scripts/fetch-firmware.sh)")
    _, built = patch.build(ROOT / "patches" / definition, out_dir=tmp_path, out=lambda s: None)
    assert built == digest
