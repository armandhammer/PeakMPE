"""Harness self-tests: startup state, calling convention, budgets, MMIO."""

import struct

import pytest

from emu.machine import SRAM_BASE, SRAM_SIZE, EmulationError

# Free flash above the image end (0x080501C0), used for hand-assembled
# Thumb test routines.
SCRATCH = 0x08060000

# Reset_Handler's .data copy: 0x4440 bytes from flash 0x0804BD80 to 0x20000000
# (literals at 0x0801DA00-0x0801DA08).
DATA_LMA = 0x0804BD80
DATA_SIZE = 0x4440


def thumb(machine, *halfwords, literals=()):
    code = struct.pack(f"<{len(halfwords)}H", *halfwords)
    code += b"".join(struct.pack("<I", x) for x in literals)
    machine.write(SCRATCH, code)
    return SCRATCH


def test_boot_copies_data_and_zeroes_bss(machine):
    sram = machine.read(SRAM_BASE, SRAM_SIZE)
    data = machine.image[DATA_LMA - machine.base : DATA_LMA - machine.base + DATA_SIZE]
    assert sram[:DATA_SIZE] == data
    assert sram[DATA_SIZE:] == bytes(SRAM_SIZE - DATA_SIZE)


def test_boot_reads_reset_literals_from_image(machine):
    assert machine.u32(0x0801D9F8) == 0x20000000  # .bss start
    assert machine.u32(0x0801D9FC) == 0x20030000  # .bss end
    assert machine.u32(0x0801DA00) == DATA_LMA
    assert machine.u32(0x0801DA04) == 0x20000000  # .data start
    assert machine.u32(0x0801DA08) == DATA_SIZE


def test_restore_undoes_ram_writes(machine):
    before = machine.read(SRAM_BASE, 16)
    machine.write(SRAM_BASE, b"\xaa" * 16)
    machine.restore()
    assert machine.read(SRAM_BASE, 16) == before


def test_call_register_args_and_return(machine):
    addr = thumb(machine, 0x1840, 0x4770)  # adds r0, r0, r1; bx lr
    assert machine.call(addr, 40, 2) == 42
    assert machine.call(addr, -1, 1) == 0


def test_call_stack_args(machine):
    addr = thumb(machine, 0x9801, 0x4770)  # ldr r0, [sp, #4]; bx lr
    assert machine.call(addr, 0, 1, 2, 3, 4, 5) == 5


def test_stub_replaces_callee(machine):
    # push {lr}; bl -> stubbed target; pop {pc}
    target = SCRATCH + 0x100
    machine.write(target, struct.pack("<H", 0xE7FE))  # b . (never runs)
    offset = target - (SCRATCH + 2 + 4)
    s = (offset >> 24) & 1
    i1, i2 = (offset >> 23) & 1, (offset >> 22) & 1
    j1, j2 = (~i1 ^ s) & 1, (~i2 ^ s) & 1
    hi = 0xF000 | (s << 10) | ((offset >> 12) & 0x3FF)
    lo = 0xD000 | (j1 << 13) | (j2 << 11) | ((offset >> 1) & 0x7FF)
    addr = thumb(machine, 0xB500, hi, lo, 0xBD00)
    seen = []
    machine.stub(target, lambda m: seen.append(m.arg(0)) or 7)
    assert machine.call(addr, 99) == 7
    assert seen == [99]


def test_budget_stops_infinite_loop(machine):
    addr = thumb(machine, 0xE7FE)  # b .
    with pytest.raises(EmulationError, match="budget"):
        machine.call(addr, budget=1000)


def test_peripheral_access_is_logged_and_configurable(machine):
    # ldr r1, [pc, #4]; ldr r0, [r1]; str r0, [r1]; bx lr; .word 0x40011004
    addr = thumb(machine, 0x4901, 0x6808, 0x6008, 0x4770, literals=[0x40011004])
    machine.periph_values[0x40011004] = 0x5A
    assert machine.call(addr) == 0x5A
    log = [(a.kind, a.addr, a.value) for a in machine.periph_log]
    assert log == [("r", 0x40011004, 0x5A), ("w", 0x40011004, 0x5A)]


def test_unmapped_access_raises(machine):
    addr = thumb(machine, 0x6800, 0x4770)  # ldr r0, [r0]; bx lr
    with pytest.raises(EmulationError, match="0x30000000"):
        machine.call(addr, 0x30000000)
