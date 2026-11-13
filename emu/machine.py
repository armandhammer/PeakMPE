"""Function-level emulation of the Summit firmware image (Unicorn, Cortex-M4).

The flat image produced by ``tools/syx.py decode`` is mapped at its load base
and executed in Thumb mode. This is not a system emulator: there is no NVIC,
no interrupts and no peripheral models. It exists to call individual firmware
functions with controlled inputs and observe their outputs (docs/SIMULATOR.md).

Memory map (STM32F42x-style; the Summit's MCU is not confirmed, see
docs/firmware-format.md):

* flash   ``0x08000000`` 1 MiB. The image sits at ``0x0800C000``. Everything
  else (the bootloader area below the image, free space above it) is filled
  with ``0xFF``, the erased-flash value. What is really there on a Summit is
  unknown.
* CCM     ``0x10000000`` 64 KiB.
* SRAM    ``0x20000000`` 192 KiB, matching the initial SP ``0x20030000``.
* peripherals: ``0x40000000-0x5FFFFFFF`` (APB/AHB and their bit-band alias),
  ``0x60000000-0x9FFFFFFF`` (FMC, where external buses such as an FPGA
  interface would sit) and ``0xE0000000-0xE00FFFFF`` (Cortex-M system
  control space). These are MMIO: every access is logged, reads return
  values from :attr:`Machine.periph_values` (default 0), writes are dropped.

Any other unmapped access stops emulation with :class:`EmulationError`, since
it usually means a wrong address or a wrong argument.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Union

from unicorn import (
    UC_ARCH_ARM,
    UC_HOOK_CODE,
    UC_HOOK_MEM_INVALID,
    UC_MODE_MCLASS,
    UC_MODE_THUMB,
    Uc,
    UcError,
)
from unicorn.arm_const import (
    UC_ARM_REG_LR,
    UC_ARM_REG_PC,
    UC_ARM_REG_R0,
    UC_ARM_REG_R1,
    UC_ARM_REG_R2,
    UC_ARM_REG_R3,
    UC_ARM_REG_SP,
    UC_CPU_ARM_CORTEX_M4,
)

IMAGE_BASE = 0x0800C000
FLASH_BASE = 0x08000000
FLASH_SIZE = 0x00100000
CCM_BASE = 0x10000000
CCM_SIZE = 0x00010000
SRAM_BASE = 0x20000000
SRAM_SIZE = 0x00030000
PERIPH_REGIONS = (
    (0x40000000, 0x20000000),
    (0x60000000, 0x40000000),
    (0xE0000000, 0x00100000),
)

# Return trap: an otherwise unused page holding `b .`. call() puts its address
# in LR, so a function returning there ends the emulation.
TRAP_BASE = 0x0F000000
TRAP_SIZE = 0x1000
RETURN_TRAP = TRAP_BASE

# Reset_Handler (0x0801D9BC) zeroes 0x20000000-0x20030000, copies .data from
# flash to 0x20000000, then loads SP from address 0 and calls 0x0801C564.
# boot() runs it up to the instruction after the copy loop, before the SP
# reload: address 0 is the boot-memory alias, which this machine does not map.
RESET_HANDLER = 0x0801D9BC
RESET_STOP = 0x0801D9EA
MAIN = 0x0801C564

ARG_REGS = (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)


class EmulationError(RuntimeError):
    """Emulation stopped on a fault, an unmapped access or a blown budget."""


@dataclass
class PeriphAccess:
    kind: str  # "r" or "w"
    pc: int
    addr: int
    size: int
    value: int


PeriphValue = Union[int, Callable[[int, int], int]]
Stub = Callable[["Machine"], Optional[int]]


class Machine:
    """One emulated CPU with the firmware image loaded.

    Construct it with the decoded image, call :meth:`boot` once to run the
    startup code, then :meth:`call` firmware functions. :meth:`restore` resets
    RAM, CCM and logs to the post-boot snapshot between tests.
    """

    def __init__(self, image: bytes, base: int = IMAGE_BASE):
        if base < FLASH_BASE or base + len(image) > FLASH_BASE + FLASH_SIZE:
            raise ValueError("image does not fit the flash mapping")
        self.image = bytes(image)
        self.base = base
        self.initial_sp, self.reset_vector = struct.unpack_from("<II", self.image, 0)
        from .target import target_for
        self.target = target_for(self.image)

        self.uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        self.uc.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_M4)

        flash = bytearray(b"\xff" * FLASH_SIZE)
        flash[base - FLASH_BASE : base - FLASH_BASE + len(self.image)] = self.image
        self.uc.mem_map(FLASH_BASE, FLASH_SIZE)
        self.uc.mem_write(FLASH_BASE, bytes(flash))
        self.uc.mem_map(CCM_BASE, CCM_SIZE)
        self.uc.mem_map(SRAM_BASE, SRAM_SIZE)
        self.uc.mem_map(TRAP_BASE, TRAP_SIZE)
        self.uc.mem_write(TRAP_BASE, b"\xfe\xe7" * (TRAP_SIZE // 2))

        #: Peripheral read values, by absolute address: an int, or a callable
        #: ``(addr, size) -> int``. Unlisted addresses read as 0.
        self.periph_values: Dict[int, PeriphValue] = {}
        #: Every peripheral access since the last :meth:`restore`.
        self.periph_log: List[PeriphAccess] = []
        for start, size in PERIPH_REGIONS:
            self.uc.mmio_map(start, size, self._periph_read, start, self._periph_write, start)

        self._stubs: Dict[int, Stub] = {}
        self._stub_hooks: Dict[int, int] = {}
        self._fault: Optional[str] = None
        self.uc.hook_add(UC_HOOK_MEM_INVALID, self._on_invalid)

        self._snapshot: Optional[Tuple[bytes, bytes]] = None

    @classmethod
    def from_file(cls, path: Union[str, Path], base: int = IMAGE_BASE) -> "Machine":
        return cls(Path(path).read_bytes(), base)

    # -- startup ---------------------------------------------------------------

    def boot(self, budget: int = 2_000_000) -> None:
        """Run Reset_Handler's ``.bss`` zero and ``.data`` copy, then snapshot RAM.

        Stops at ``RESET_STOP``, before the call into ``MAIN``; none of main's
        own initialisation runs, so RAM holds only the linker-initialised
        state.
        """
        t = self.target
        if self.reset_vector & ~1 != t.reset_handler:
            raise EmulationError(
                f"reset vector {self.reset_vector:#x} is not the known Reset_Handler; "
                "boot() only knows the images in emu/target.py"
            )
        self.uc.reg_write(UC_ARM_REG_SP, self.initial_sp)
        self._run(t.reset_handler | 1, t.reset_stop, budget)
        self._snapshot = (
            bytes(self.uc.mem_read(SRAM_BASE, SRAM_SIZE)),
            bytes(self.uc.mem_read(CCM_BASE, CCM_SIZE)),
        )
        self.periph_log.clear()

    def restore(self) -> None:
        """Return RAM, CCM and the peripheral log to the post-boot snapshot.

        Stubs and :attr:`periph_values` are kept; use :meth:`unstub` to remove
        stubs.
        """
        if self._snapshot is None:
            raise EmulationError("restore() before boot()")
        sram, ccm = self._snapshot
        self.uc.mem_write(SRAM_BASE, sram)
        self.uc.mem_write(CCM_BASE, ccm)
        self.periph_log.clear()

    # -- calling firmware -----------------------------------------------------

    def call(self, addr: int, *args: int, budget: int = 1_000_000, timeout_us: int = 2_000_000) -> int:
        """Call the Thumb function at *addr* with AAPCS arguments; return r0.

        Up to four arguments go in r0-r3, the rest on the stack. Arguments are
        32-bit integers (negative values are two's complement). LR is set to
        :data:`RETURN_TRAP`; the call fails with :class:`EmulationError` if it
        has not returned within *budget* instructions or *timeout_us*
        microseconds.
        """
        sp = self.initial_sp
        stack_args = [a & 0xFFFFFFFF for a in args[4:]]
        sp -= 4 * len(stack_args)
        sp &= ~7  # AAPCS: 8-byte aligned at the call boundary
        if stack_args:
            self.uc.mem_write(sp, struct.pack(f"<{len(stack_args)}I", *stack_args))
        for reg, value in zip(ARG_REGS, args[:4]):
            self.uc.reg_write(reg, value & 0xFFFFFFFF)
        self.uc.reg_write(UC_ARM_REG_SP, sp)
        self.uc.reg_write(UC_ARM_REG_LR, RETURN_TRAP | 1)
        self._run(addr | 1, RETURN_TRAP, budget, timeout_us)
        return self.uc.reg_read(UC_ARM_REG_R0)

    def run(self, begin: int, until: int, budget: int = 1_000_000, sp: Optional[int] = None) -> None:
        """Execute from *begin* until the PC reaches *until*, without a return trap.

        For code that isn't a function call, such as the tail of
        Reset_Handler. SP is set to *sp* if given, else left as it is.
        """
        if sp is not None:
            self.uc.reg_write(UC_ARM_REG_SP, sp)
        self._run(begin | 1, until, budget)

    def stub(self, addr: int, fn: Stub) -> None:
        """Replace the function at *addr* with a Python callable.

        When execution reaches *addr*, ``fn(machine)`` runs with the callee's
        arguments still in r0-r3 (see :meth:`arg`). If it returns an int, that
        goes into r0. Execution then continues at LR, as if the function had
        returned.
        """
        self.unstub(addr)
        self._stubs[addr] = fn
        self._stub_hooks[addr] = self.uc.hook_add(UC_HOOK_CODE, self._on_stub, begin=addr, end=addr)

    def unstub(self, addr: int) -> None:
        if addr in self._stub_hooks:
            self.uc.hook_del(self._stub_hooks.pop(addr))
            del self._stubs[addr]

    def unstub_all(self) -> None:
        for addr in list(self._stubs):
            self.unstub(addr)

    def arg(self, n: int) -> int:
        """Argument *n* (0-3) of the current call, for use inside stubs."""
        return self.uc.reg_read(ARG_REGS[n])

    # -- memory helpers --------------------------------------------------------

    def read(self, addr: int, size: int) -> bytes:
        return bytes(self.uc.mem_read(addr, size))

    def write(self, addr: int, data: bytes) -> None:
        """Write memory and drop any cached translation of it, so code
        written here (patches, test routines) runs as written."""
        self.uc.mem_write(addr, bytes(data))
        self.uc.ctl_remove_cache(addr, addr + len(data))

    def u8(self, addr: int) -> int:
        return self.read(addr, 1)[0]

    def u32(self, addr: int) -> int:
        return struct.unpack("<I", self.read(addr, 4))[0]

    def write_u32(self, addr: int, value: int) -> None:
        self.write(addr, struct.pack("<I", value & 0xFFFFFFFF))

    # -- internals -------------------------------------------------------------

    def _run(self, begin: int, until: int, budget: int, timeout_us: int = 0) -> None:
        self._fault = None
        try:
            self.uc.emu_start(begin, until, timeout=timeout_us, count=budget)
        except UcError as e:
            pc = self.uc.reg_read(UC_ARM_REG_PC)
            raise EmulationError(f"{self._fault or e} (pc={pc:#010x})") from None
        pc = self.uc.reg_read(UC_ARM_REG_PC)
        if pc != until:
            raise EmulationError(f"budget exhausted before reaching {until:#010x} (pc={pc:#010x})")

    def _on_stub(self, uc: Uc, address: int, size: int, _user) -> None:
        fn = self._stubs.get(address)
        if fn is None:
            return
        result = fn(self)
        if result is not None:
            uc.reg_write(UC_ARM_REG_R0, result & 0xFFFFFFFF)
        uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

    def _periph_read(self, uc: Uc, offset: int, size: int, region: int) -> int:
        addr = region + offset
        source = self.periph_values.get(addr, 0)
        value = source(addr, size) if callable(source) else source
        value &= (1 << (8 * size)) - 1
        self.periph_log.append(PeriphAccess("r", uc.reg_read(UC_ARM_REG_PC), addr, size, value))
        return value

    def _periph_write(self, uc: Uc, offset: int, size: int, value: int, region: int) -> None:
        self.periph_log.append(PeriphAccess("w", uc.reg_read(UC_ARM_REG_PC), region + offset, size, value))

    def _on_invalid(self, uc: Uc, access: int, address: int, size: int, value: int, _user) -> bool:
        self._fault = f"invalid memory access type {access} at {address:#010x} size {size}"
        return False
