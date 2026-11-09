"""A Summit board around the firmware: peripheral models and an interrupt clock.

:class:`Board` extends :class:`emu.machine.Machine` from "call one function" to
"run the firmware": it starts ``main`` from the reset path, keeps a virtual
clock, and preempts the main thread with the interrupts the MIDI path needs.

Time model (inferred CPU rate, see the findings "Modulation tick"):

* The clock advances in 50 µs slots, one TIM6 update each (TIM6 runs at
  20 kHz). A slot gives the main thread :data:`SLOT_INSTRUCTIONS` = 6000
  instructions, 120 MHz at one instruction per cycle, minus what the
  interrupts in that slot used.
* Optional, closer to the board (:attr:`Board.spi1_frame_cycles`,
  :attr:`Board.cpu_scale`; both off by default so every existing timing
  holds): each 16-bit SPI1 frame to the FPGA costs the CPU its wire time
  (SPI1 runs at PCLK2/4, CR1 ``0xB0F`` at ``0x080129FA``: 15 MHz with the
  inferred 60 MHz PCLK2, so 128 cycles a frame). In an interrupt that time
  comes out of the next slot's budget, as the busy-wait on TXE/BSY does on
  the board; in the main thread it is carried into the next slot.
  ``cpu_scale`` is the main thread's instructions per cycle (flash wait
  states, branches; 1.0 = the old model; the real value is unknown).
* Between slots the board raises, in this order and when the firmware has
  enabled them (peripheral enable bits and NVIC ISER) and FAULTMASK/PRIMASK
  are clear: USART6 (DIN MIDI receive/transmit, one byte per 320 µs at
  31250 baud), EXTI15_10 (an external edge, presumably from the FPGA, every
  :data:`EXTI_PERIOD_US`; the real rate is unknown) and TIM6.
* An interrupt runs to completion on the current stack with the main
  thread's full CPU context saved and restored (``uc.context_save``), like
  exception entry and return. There is no nesting and no priority model.

Peripheral models (everything else is a register file: reads return the last
value written, 0 at reset):

* **SPI1 + GPIOB PB6/PB7:** the FPGA bus, decoded by :class:`emu.fpga.FpgaBus`.
* **SPI4 + GPIOE chip selects:** the external DataFlash (AT45-style commands
  ``0x03`` read, ``0x02`` program, ``0x81`` page erase, ``0xD7`` status, binary
  512-byte pages), two chips selected by the pin number at RAM ``0x20000088``
  (PE11 and PE15). It holds the global settings (``0x300000``), patches and
  the FPGA bitstream. Blank at power-on, so the firmware formats it with its
  own defaults during the first boot.
* **USART6:** DIN MIDI in and out.
* **SPI status registers:** always TXE and RXNE, never BSY.
* **GPIO inputs** (``IDR``) read all ones: inputs pulled up, no panel button
  pressed (the panel scan treats a low input as pressed).
* **Poll-loop breaker** (not for GPIO inputs):** when the same instruction reads the same peripheral
  register 32 times in a row, with no write to that peripheral in between,
  the next read returns the bitwise complement.
  That ends any wait-for-flag loop on hardware the board doesn't model
  (clock ready bits, I2C, the panel). Every break is counted in
  :attr:`Board.poll_breaks`, so nothing is silently faked.

* **SPI2 + GPIOB PB11/PB10:** the OLED (:mod:`emu.display`).
* **GPIOC PC10/PC11/PC12, GPIOB PB2, GPIOA PA15:** the panel button chain and
  encoder (:mod:`emu.panel`); ``GPIOC_IDR`` answers from it.

Not modelled: the FPGA itself (writes are recorded, reads return 0), the
FPGA bitstream upload (the part of ``boot_screen`` ``0x08012084`` after its
text is skipped), the pots and pedals (ADC + DMA) and the keybed, USB
at the register level (see :mod:`emu.synth`), DMA, and any interrupt other
than TIM6, USART6 and EXTI15_10.
"""

from __future__ import annotations

import collections
import copy
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from unicorn import UC_HOOK_CODE, UcError
from unicorn.arm_const import (
    UC_ARM_REG_FAULTMASK,
    UC_ARM_REG_LR,
    UC_ARM_REG_PC,
    UC_ARM_REG_PRIMASK,
    UC_ARM_REG_SP,
)

from . import display as display_mod
from . import panel as panel_mod
from .fpga import GPIOB_BSRR, SPI1_DR, FpgaBus
from .machine import CCM_BASE, CCM_SIZE, RETURN_TRAP, SRAM_BASE, SRAM_SIZE, EmulationError, Machine, PeriphAccess

SLOT_US = 50
SLOT_INSTRUCTIONS = 6000
ISR_BUDGET = 400_000
POLL_BREAK_AFTER = 32
MASKED_STEP = 16
MASKED_STEPS = 256

# Interrupt sources (IRQ numbers from the vector table).
TIM6_ISR = 0x08011F90
TIM6_IRQ = 54
USART6_ISR = 0x08010C40
USART6_IRQ = 71
# EXTI15_10 (vector 56): an external edge, presumably from the FPGA. The
# handler starts ADC2, bit-bangs 12 bits on GPIOE and counts edges at
# 0x200052D4+0x4B4; voice_env_poll 0x08014D54 waits for 2-3 counts before it
# reads voice states. The edge rate is unknown; EXTI_PERIOD_US is a guess.
EXTI15_ISR = 0x08012250
EXTI15_IRQ = 40
EXTI_PERIOD_US = 100

TIM6_CR1, TIM6_DIER = 0x40001000, 0x4000100C
NVIC_ISER = 0xE000E100
NVIC_ICER = 0xE000E180

USART6_BASE = 0x40011400
USART6_SR, USART6_DR, USART6_CR1 = USART6_BASE, USART6_BASE + 4, USART6_BASE + 0x0C
USART_TXE, USART_TC, USART_RXNE = 0x80, 0x40, 0x20
USART_CR1_UE, USART_CR1_TXEIE, USART_CR1_RXNEIE = 0x2000, 0x80, 0x20
DIN_BYTE_US = 320  # 10 bits at 31250 baud

# SPI1 (the FPGA bus) as configured for the main loop: CR1 0xB0F (0x080129FA,
# BR = 001, PCLK2/4 = 15 MHz), 16-bit frames: 16 / 15 MHz = 1.07 us = 128
# cycles at 120 MHz. Used when Board.spi1_frame_cycles is set (opt-in).
SPI1_FRAME_CYCLES = 128

SPI_SR_ADDRS = tuple(base + 8 for base in (0x40013000, 0x40003800, 0x40003C00, 0x40013400, 0x40015000, 0x40015400))
GPIO_BASE, GPIO_END = 0x40020000, 0x40022C00
SPI4_DR = 0x4001340C
GPIOE_BSRR = 0x40021018
# The DataFlash driver selects a chip by GPIOE pin number (u8 at 0x20000088:
# 11 normally, 15 for the update SysEx path); the board follows BSRR writes.

BOOT_SCREEN = 0x08012084  # prints the boot screen, then uploads the FPGA bitstream
# boot_screen's FPGA upload: from the `ldrh` of the panel-input test (both
# buttons of word 1 bits 6-7 held skip it on hardware) to the code after it.
BOOT_FPGA_UPLOAD = 0x080120C4
BOOT_FPGA_UPLOAD_END = 0x0801216C
# The FPGA build word the version formatter reads from DataFlash 0x2FFE00
# (`0x0800EA0C`); on a unit it comes with the FPGA image, here it is seeded.
FPGA_BUILD_FLASH = 0x2FFE00
FPGA_BUILD = 0x0778
SETTINGS_LOAD_CALL = 0x0801C57A  # main: first `bl settings_load`
FACTORY_INIT = 0x0800FBE8  # init patches, multis and globals in the DataFlash
DELAY_LOOP = 0x0800F830  # busy-wait (r0 iterations), used by the factory init
GLOBALS_FLASH = 0x300000
MAIN_LOOP_HEAD = 0x0801C5D6  # first instruction of main_loop's endless loop
# Reset_Handler's `bl main_loop`, after `ldr sp, [0]` (address 0 isn't mapped,
# so the board sets SP itself). Running this instruction rather than jumping
# to main keeps a C patch's startup hook (`bl __patch_start`) in the path.
RESET_CALL_MAIN = 0x0801D9F2


class DataFlash:
    """AT45-style serial DataFlash in binary (512-byte) page mode."""

    PAGE = 0x200
    SIZE = 0x800000

    def __init__(self):
        self.pages: Dict[int, bytearray] = {}
        self.unknown_commands: collections.Counter = collections.Counter()
        self._cmd: Optional[int] = None
        self._addr_bytes: List[int] = []
        self._addr = 0
        self.response = 0xFF

    def read(self, addr: int, size: int) -> bytes:
        out = bytearray()
        for a in range(addr, addr + size):
            page = self.pages.get((a % self.SIZE) // self.PAGE)
            out.append(page[a % self.PAGE] if page else 0xFF)
        return bytes(out)

    def write(self, addr: int, data: bytes) -> None:
        """Set bytes directly (test set-up; not a flash program operation)."""
        for i, b in enumerate(data):
            self._page((addr + i) % self.SIZE)[(addr + i) % self.PAGE] = b

    def _page(self, addr: int) -> bytearray:
        n = addr // self.PAGE
        if n not in self.pages:
            self.pages[n] = bytearray(b"\xff" * self.PAGE)
        return self.pages[n]

    def select(self) -> None:
        self._cmd = None
        self._addr_bytes = []

    def deselect(self) -> None:
        self._cmd = None

    def transfer(self, byte: int) -> None:
        byte &= 0xFF
        if self._cmd is None:
            self._cmd = byte
            self.response = 0xFF
            return
        cmd = self._cmd
        if cmd == 0xD7:  # status: ready, 512-byte pages
            self.response = 0x81
            return
        if cmd in (0x03, 0x02, 0x81) and len(self._addr_bytes) < 3:
            self._addr_bytes.append(byte)
            self.response = 0xFF
            if len(self._addr_bytes) == 3:
                a = self._addr_bytes
                self._addr = (a[0] << 16 | a[1] << 8 | a[2]) % self.SIZE
                if cmd == 0x81:
                    self._page(self._addr)[:] = b"\xff" * self.PAGE
            return
        if cmd == 0x03:
            page = self.pages.get(self._addr // self.PAGE)
            self.response = page[self._addr % self.PAGE] if page else 0xFF
            self._addr = (self._addr + 1) % self.SIZE
        elif cmd == 0x02:
            page = self._page(self._addr)
            page[self._addr % self.PAGE] &= byte
            base = self._addr - self._addr % self.PAGE
            self._addr = base + (self._addr + 1) % self.PAGE  # wraps inside the page
        elif cmd == 0x3D:  # configuration (page size): accepted, nothing to do
            pass
        else:
            self.unknown_commands[cmd] += 1

    def snapshot(self):
        return {n: bytes(p) for n, p in self.pages.items()}

    def restore(self, snap) -> None:
        self.pages = {n: bytearray(p) for n, p in snap.items()}
        self._cmd = None


@dataclass
class DinPort:
    """USART6 as seen from the MIDI DIN sockets."""

    rx_queue: collections.deque = field(default_factory=collections.deque)  # (due_us, byte)
    rx_data: Optional[int] = None
    tx_log: List[Tuple[float, int]] = field(default_factory=list)  # (time_ms, byte)
    next_rx_us: int = 0
    next_tx_us: int = 0


class Board(Machine):
    """The firmware image plus the board around it. See the module docstring."""

    def __init__(self, image: bytes):
        super().__init__(image)
        self.regs: Dict[int, int] = {}
        self.time_us = 0
        self.fpga = FpgaBus(lambda: self.time_us / 1000.0)
        self.flash = {11: DataFlash(), 15: DataFlash()}
        self.din = DinPort()
        self.iser = 0
        #: (pc, address) → number of poll-loop breaks (see module docstring).
        self.poll_breaks: collections.Counter = collections.Counter()
        self.record_periph = False
        self.irq_counts: collections.Counter = collections.Counter()
        #: Python callables run between slots, in the main thread's place:
        #: ``fn(board)``. Used by :mod:`emu.synth` to inject USB packets.
        self.slot_hooks: List[Callable[["Board"], None]] = []
        self._poll_key = None
        self._poll_n = 0
        self._flash_cs: Optional[int] = None
        self._isr_instructions = 0
        #: Cycles each SPI1 frame costs (0: free, the old model). See the
        #: module docstring; :data:`SPI1_FRAME_CYCLES` is the board's value.
        self.spi1_frame_cycles = 0
        #: Main-thread instructions per cycle (1.0: the old model).
        self.cpu_scale = 1.0
        self._in_isr = False
        self._main_debt = 0
        self._main_ctx = None
        self._factory_done = False
        self.factory_initialised = False
        #: Observers of peripheral writes, by absolute address: ``fn(value)``.
        #: They run before the board's own handling (see emu.display, emu.panel).
        self.write_taps: Dict[int, List[Callable[[int], None]]] = collections.defaultdict(list)
        #: The OLED on SPI2 (emu.display) and the panel chain (emu.panel).
        self.display = display_mod.DisplayBus(lambda: self.time_us / 1000.0)
        self.panel = panel_mod.PanelChain()
        self.write_taps[display_mod.SPI2_DR].append(self.display.spi_write)
        self.write_taps[GPIOB_BSRR] += [self.display.gpiob_bsrr, self.panel.gpiob_bsrr]
        self.write_taps[panel_mod.GPIOC_BSRR].append(self.panel.gpioc_bsrr)
        self.write_taps[panel_mod.GPIOA_BSRR].append(self.panel.gpioa_bsrr)
        self.periph_values[panel_mod.GPIOC_IDR] = self.panel.idr
        #: False: stub all of boot_screen, as before the display model.
        self.run_boot_screen = True

    # -- running --------------------------------------------------------------

    def power_on(self, max_ms: int = 5000) -> None:
        """Run the reset path and main's initialisation up to the main loop.

        ``boot()`` runs Reset_Handler's RAM set-up; then the board sets SP and
        continues at its ``bl main_loop`` (or a patch's startup hook there).

        ``boot_screen`` prints the boot screen; its FPGA bitstream upload is
        skipped (or all of it, with :attr:`run_boot_screen` False).
        Afterwards :meth:`save_state` holds the board at the main-loop head.
        """
        self.boot()
        if self.run_boot_screen:
            if self.flash[11].read(FPGA_BUILD_FLASH, 2) == b"\xff\xff":
                self.flash[11].write(FPGA_BUILD_FLASH, FPGA_BUILD.to_bytes(2, "little"))
            self.uc.hook_add(
                UC_HOOK_CODE,
                lambda uc, addr, size, user: (
                    self.display.snapshot("boot"),
                    uc.reg_write(UC_ARM_REG_PC, BOOT_FPGA_UPLOAD_END | 1),
                ),
                begin=BOOT_FPGA_UPLOAD,
                end=BOOT_FPGA_UPLOAD,
            )
        else:
            self.stub(BOOT_SCREEN, lambda m: None)
        self.uc.reg_write(UC_ARM_REG_SP, self.initial_sp)
        self.uc.reg_write(UC_ARM_REG_LR, RETURN_TRAP | 1)
        self.uc.reg_write(UC_ARM_REG_PC, RESET_CALL_MAIN | 1)
        self._main_ctx = self.uc.context_save()
        reached = []
        hooks = [
            self.uc.hook_add(
                UC_HOOK_CODE,
                lambda uc, addr, size, user: (reached.append(addr), uc.emu_stop()),
                begin=MAIN_LOOP_HEAD,
                end=MAIN_LOOP_HEAD,
            )
        ]
        if self.flash[11].read(GLOBALS_FLASH, 0x30) == b"\xff" * 0x30:
            hooks.append(self.uc.hook_add(UC_HOOK_CODE, self._factory_init, begin=SETTINGS_LOAD_CALL, end=SETTINGS_LOAD_CALL))
        try:
            while not reached:
                if self.time_us > max_ms * 1000:
                    raise EmulationError(f"main loop not reached within {max_ms} ms")
                self._slot()
        finally:
            for h in hooks:
                self.uc.hook_del(h)
            self.unstub(DELAY_LOOP)
        self.factory_initialised = self._factory_done

    def _factory_init(self, uc, addr, size, user) -> None:
        """Blank DataFlash: call the firmware's own factory initialise first.

        On a real unit the DataFlash was formatted at the factory (or by the
        boot-time button combination that runs ``FACTORY_INIT``). Here main
        is redirected once into ``FACTORY_INIT``, which returns to the
        ``settings_load`` call. Its busy-wait delays are skipped.
        """
        if self._factory_done:
            return
        self._factory_done = True
        self.stub(DELAY_LOOP, lambda m: None)
        uc.reg_write(UC_ARM_REG_LR, SETTINGS_LOAD_CALL | 1)
        uc.reg_write(UC_ARM_REG_PC, FACTORY_INIT | 1)

    def run_us(self, us: int) -> None:
        end = self.time_us + us
        while self.time_us < end:
            self._slot()

    def run_ms(self, ms: float) -> None:
        self.run_us(int(round(ms * 1000)))

    def _slot(self) -> None:
        uc = self.uc
        cycles = SLOT_INSTRUCTIONS - self._isr_instructions - self._main_debt
        self._main_debt = max(0, -cycles)  # more than a slot: carried on
        budget = max(int(max(cycles, 0) * self.cpu_scale), 500)
        self._isr_instructions = 0
        uc.context_restore(self._main_ctx)
        pc = uc.reg_read(UC_ARM_REG_PC)
        if pc == RETURN_TRAP:
            raise EmulationError("main returned")
        self._fault = None
        try:
            uc.emu_start(pc | 1, RETURN_TRAP, count=budget)
        except UcError as e:
            pc = uc.reg_read(UC_ARM_REG_PC)
            raise EmulationError(f"{self._fault or e} in main thread (pc={pc:#010x})") from None
        if self._masked():
            # Interrupts are held off (cpsid f around an SPI transaction):
            # run on in small steps until they're enabled again, as the
            # NVIC would take the pending interrupt right after cpsie.
            for _ in range(MASKED_STEPS):
                pc = uc.reg_read(UC_ARM_REG_PC)
                try:
                    uc.emu_start(pc | 1, RETURN_TRAP, count=MASKED_STEP)
                except UcError as e:
                    raise EmulationError(f"{self._fault or e} in main thread (pc={pc:#010x})") from None
                if not self._masked():
                    break
        self._main_ctx = uc.context_save()
        self.time_us += SLOT_US
        for hook in list(self.slot_hooks):
            hook(self)
        self._interrupts()

    def _masked(self) -> bool:
        return bool(self.uc.reg_read(UC_ARM_REG_PRIMASK) & 1 or self.uc.reg_read(UC_ARM_REG_FAULTMASK) & 1)

    def _irq_enabled(self, irq: int) -> bool:
        return bool(self.iser >> irq & 1)

    def _interrupts(self) -> None:
        if self._masked():
            return
        din = self.din
        cr1 = self.regs.get(USART6_CR1, 0)
        if cr1 & USART_CR1_UE and self._irq_enabled(USART6_IRQ):
            if din.rx_data is None and din.rx_queue and din.rx_queue[0][0] <= self.time_us:
                if self.time_us >= din.next_rx_us:
                    din.rx_data = din.rx_queue.popleft()[1]
                    din.next_rx_us = self.time_us + DIN_BYTE_US
            rx = din.rx_data is not None and cr1 & USART_CR1_RXNEIE
            tx = cr1 & USART_CR1_TXEIE and self.time_us >= din.next_tx_us
            if rx or tx:
                self.run_isr(USART6_ISR, "usart6")
        if self._irq_enabled(EXTI15_IRQ) and self.time_us % EXTI_PERIOD_US == 0:
            self.run_isr(EXTI15_ISR, "exti15")
        if (
            self.regs.get(TIM6_CR1, 0) & 1
            and self.regs.get(TIM6_DIER, 0) & 1
            and self._irq_enabled(TIM6_IRQ)
        ):
            self.run_isr(TIM6_ISR, "tim6")

    def run_isr(self, addr: int, name: str = "") -> None:
        """Run a handler to completion on the main thread's stack."""
        uc = self.uc
        uc.context_restore(self._main_ctx)
        sp = (uc.reg_read(UC_ARM_REG_SP) - 0x40) & ~7
        uc.reg_write(UC_ARM_REG_SP, sp)
        uc.reg_write(UC_ARM_REG_LR, RETURN_TRAP | 1)
        self._fault = None
        self._in_isr = True
        try:
            uc.emu_start(addr | 1, RETURN_TRAP, count=ISR_BUDGET)
        except UcError as e:
            pc = uc.reg_read(UC_ARM_REG_PC)
            raise EmulationError(f"{self._fault or e} in ISR {name or hex(addr)} (pc={pc:#010x})") from None
        finally:
            self._in_isr = False
        if uc.reg_read(UC_ARM_REG_PC) != RETURN_TRAP:
            raise EmulationError(f"ISR {name or hex(addr)} did not return (pc={uc.reg_read(UC_ARM_REG_PC):#010x})")
        self.irq_counts[name or hex(addr)] += 1
        # Rough cost; Unicorn doesn't report counts. At cpu_scale < 1 the
        # handler's instructions take that much longer too.
        self._isr_instructions += 300 if self.cpu_scale == 1.0 else int(300 / self.cpu_scale)
        uc.context_restore(self._main_ctx)

    # -- state ----------------------------------------------------------------

    def save_state(self):
        return (
            self.uc.context_save(),
            self._main_ctx,
            bytes(self.uc.mem_read(SRAM_BASE, SRAM_SIZE)),
            bytes(self.uc.mem_read(CCM_BASE, CCM_SIZE)),
            dict(self.regs),
            self.iser,
            self.time_us,
            {pin: f.snapshot() for pin, f in self.flash.items()},
            (list(self.fpga.voices.state), list(self.fpga.voices.started_at), dict(self.fpga.values),
             list(self.fpga.voices.released_at)),
            copy.deepcopy((self.display.lcd, self.display.powered, self.panel)),
        )

    def load_state(self, state) -> None:
        ctx, main_ctx, sram, ccm, regs, iser, time_us, flash, voices, ui = state
        self.uc.context_restore(ctx)
        self._main_ctx = main_ctx
        self.uc.mem_write(SRAM_BASE, sram)
        self.uc.mem_write(CCM_BASE, ccm)
        self.regs = dict(regs)
        self.iser = iser
        self.time_us = time_us
        for pin, snap in flash.items():
            self.flash[pin].restore(snap)
        self.fpga.reset()
        self.fpga.voices.state, self.fpga.voices.started_at = list(voices[0]), list(voices[1])
        self.fpga.values = dict(voices[2])
        self.fpga.voices.released_at = list(voices[3])
        self.din = DinPort()
        self.din.next_rx_us = self.din.next_tx_us = time_us
        self.display.lcd, self.display.powered, panel = copy.deepcopy(ui)
        self.panel.__dict__.update(panel.__dict__)  # keep the object the taps point at
        self.irq_counts.clear()
        self.periph_log.clear()
        self._flash_cs = None
        self._isr_instructions = 0
        self._main_debt = 0

    # -- peripherals ----------------------------------------------------------

    def _periph_read(self, uc, offset: int, size: int, region: int) -> int:
        addr = region + offset
        pc = uc.reg_read(UC_ARM_REG_PC)
        if addr in self.periph_values:
            source = self.periph_values[addr]
            value = source(addr, size) if callable(source) else source
        elif addr == SPI1_DR:
            value = self.fpga.spi_read()
        elif addr in SPI_SR_ADDRS:
            value = 0x3
        elif addr == SPI4_DR:
            chip = self.flash.get(self._flash_cs)
            value = chip.response if chip else 0xFF
        elif addr == USART6_SR:
            value = USART_TXE | USART_TC | (USART_RXNE if self.din.rx_data is not None else 0)
        elif addr == USART6_DR:
            value = self.din.rx_data or 0
            self.din.rx_data = None
        else:
            word = addr & ~3
            gpio_idr = GPIO_BASE <= word < GPIO_END and word & 0x3FF == 0x10
            if gpio_idr:
                value = 0xFFFF >> (8 * (addr & 3))  # inputs pulled up: no button pressed
            else:
                value = self.regs.get(word, 0) >> (8 * (addr & 3))
            key = (pc, addr)
            if gpio_idr or addr & 3:
                pass  # never poll-broken
            elif key == self._poll_key:
                self._poll_n += 1
                if self._poll_n >= POLL_BREAK_AFTER:
                    value = ~value & 0xFFFFFFFF
                    self.regs[word] = value
                    self.poll_breaks[key] += 1
                    self._poll_n = 0
            else:
                self._poll_key, self._poll_n = key, 0
        value &= (1 << (8 * size)) - 1
        if self.record_periph:
            self.periph_log.append(PeriphAccess("r", pc, addr, size, value))
        return value

    def _periph_write(self, uc, offset: int, size: int, value: int, region: int) -> None:
        addr = region + offset
        if self._poll_key and self._poll_key[1] & ~0x3FF == addr & ~0x3FF:
            self._poll_key = None  # a loop that also writes this peripheral is not a poll
        if self.record_periph:
            self.periph_log.append(PeriphAccess("w", uc.reg_read(UC_ARM_REG_PC), addr, size, value))
        for tap in self.write_taps.get(addr, ()):
            tap(value)
        if addr == SPI1_DR:
            self.fpga.spi_write(value)
            if self.spi1_frame_cycles:
                if self._in_isr:
                    self._isr_instructions += self.spi1_frame_cycles
                else:
                    self._main_debt += self.spi1_frame_cycles
            return
        if addr == GPIOB_BSRR:
            self.fpga.gpiob_bsrr(value)
            return
        if addr == SPI4_DR:
            chip = self.flash.get(self._flash_cs)
            if chip:
                chip.transfer(value)
            return
        if addr == GPIOE_BSRR:
            self._gpioe_bsrr(value)
            return
        if addr == USART6_DR:
            self.din.tx_log.append((self.time_us / 1000.0, value & 0xFF))
            self.din.next_tx_us = self.time_us + DIN_BYTE_US
            return
        if NVIC_ISER <= addr < NVIC_ISER + 0x20:
            self.iser |= (value & 0xFFFFFFFF) << (32 * ((addr - NVIC_ISER) // 4))
            return
        if NVIC_ICER <= addr < NVIC_ICER + 0x20:
            self.iser &= ~((value & 0xFFFFFFFF) << (32 * ((addr - NVIC_ICER) // 4)))
            return
        word = addr & ~3
        shift = 8 * (addr & 3)
        mask = ((1 << (8 * size)) - 1) << shift
        self.regs[word] = (self.regs.get(word, 0) & ~mask) | ((value << shift) & mask)

    def _gpioe_bsrr(self, value: int) -> None:
        for pin, chip in self.flash.items():
            if value >> (pin + 16) & 1:
                self._flash_cs = pin
                chip.select()
            elif value >> pin & 1 and self._flash_cs == pin:
                chip.deselect()
                self._flash_cs = None
