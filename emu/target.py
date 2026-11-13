"""Per-firmware addresses for the simulator: Summit 2.2/2121 and Peak 2.2/2108.

The board and machine read their firmware addresses from the Target picked
by the image's reset vector. A field left None isn't known for that image
yet: the board skips the step that needs it. Sources: docs/symbols/*.csv.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional

IMAGE_BASE = 0x0800C000


@dataclass(frozen=True)
class Target:
    name: str
    image: str                      # official file name in firmware/
    reset_handler: int
    reset_stop: int                 # Reset_Handler: the instruction after the .data copy
    reset_call_main: int            # Reset_Handler's `bl main_loop`
    main: int
    main_loop_head: int             # first instruction of main_loop's endless loop
    settings_load_call: int         # main_loop's first `bl settings_load`
    delay_loop: Optional[int]       # busy-wait used by the factory initialise
    factory_init: Optional[int]     # formats patches/globals in the DataFlash
    boot_screen: Optional[int]
    boot_fpga_upload: Optional[int]
    boot_fpga_upload_end: Optional[int]
    fpga_build: int                 # FPGA build word seeded at DataFlash 0x2FFE00
    voices: int
    lcd_cs_pin: int                 # GPIOB pin of the OLED's chip select
    fpga_single_cs: Optional[int] = None  # one FPGA engine on this GPIOB mask (Peak)
    init_patch: Optional[int] = None      # flash address of the Init Patch, to seed a blank DataFlash


SUMMIT = Target(
    name="summit", image="summit-firmware-2.2-build2121.syx",
    reset_handler=0x0801D9BC, reset_stop=0x0801D9EA, reset_call_main=0x0801D9F2,
    main=0x0801C564, main_loop_head=0x0801C5D6, settings_load_call=0x0801C57A,
    delay_loop=0x0800F830, factory_init=0x0800FBE8,
    boot_screen=0x08012084, boot_fpga_upload=0x080120C4, boot_fpga_upload_end=0x0801216C,
    fpga_build=0x0778, voices=16, lcd_cs_pin=11,
)

# Peak 2.2 (build 2108): docs/symbols/peak-2.2-2108.csv. Observed in the
# disassembly; factory_init and the boot screen are not mapped yet.
PEAK = Target(
    name="peak", image="peak-firmware-2.2-build2108.syx",
    reset_handler=0x0801D6C4, reset_stop=0x0801D6F2, reset_call_main=0x0801D6FA,
    main=0x0800D11C, main_loop_head=0x0800D178, settings_load_call=0x0800D132,
    delay_loop=0x0800FC00, factory_init=None,
    boot_screen=None, boot_fpga_upload=None, boot_fpga_upload_end=None,
    fpga_build=0x0469, voices=8, lcd_cs_pin=12,  # lcd_select 0x08016820: BSRR bit 28
    fpga_single_cs=0x40,  # PB6 (fpga_write 0x0800EBF0)
    init_patch=0x08043160,  # name "Init Patch" at +2, as on the Summit
)

_BY_RESET = {SUMMIT.reset_handler: SUMMIT, PEAK.reset_handler: PEAK}


def target_for(image: bytes) -> Target:
    """The Target of a flat image, by its reset vector."""
    reset = struct.unpack_from("<I", image, 4)[0] & ~1
    if reset not in _BY_RESET:
        raise ValueError(f"unknown image: reset vector {reset:#x}")
    return _BY_RESET[reset]


def vector(image: bytes, irq: int) -> int:
    """Handler address (no Thumb bit) of external interrupt *irq*."""
    return struct.unpack_from("<I", image, 4 * (16 + irq))[0] & ~1
