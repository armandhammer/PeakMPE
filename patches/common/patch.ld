/* Linker script for patch blobs (docs/patch-howto.md).
 *
 * tools/patch_build.py generates the two included files in the build
 * directory:
 *   layout.ld       MEMORY: FREE_FLASH from the end of the official image
 *                   (4-byte aligned) up to the sector-6 limit 0x08060000,
 *                   and PATCH_RAM (CCM, see the findings, "Patch RAM").
 *   fw_symbols.ld   firmware functions (address | 1) and globals from
 *                   docs/symbols/summit-2.2-2121.csv.
 *
 * Only .text (code and read-only data) goes into flash and only .bss into
 * RAM. Nothing initialises patch RAM except __patch_start (common/start.c),
 * so initialised data (.data) is refused. Variables in section ".noinit"
 * (PATCH_NOINIT in firmware.h) follow the zeroed part and are left as they
 * are, for tables that are written whole before their first use: clearing
 * them would only lengthen the startup.
 */

INCLUDE layout.ld
INCLUDE fw_symbols.ld

ENTRY(__patch_start)

SECTIONS
{
    .text : ALIGN(4)
    {
        __patch_text_start = .;
        KEEP(*(.text.__patch_start))
        *(.text .text.*)
        *(.rodata .rodata.*)
        . = ALIGN(4);
        __patch_text_end = .;
    } > FREE_FLASH

    .data : { *(.data .data.*) } > PATCH_RAM AT > FREE_FLASH

    .bss (NOLOAD) : ALIGN(4)
    {
        __patch_bss_start = .;
        *(.bss .bss.*)
        *(COMMON)
        . = ALIGN(4);
        __patch_bss_end = .;
        *(.noinit .noinit.*)
        . = ALIGN(4);
        __patch_ram_end = .;
    } > PATCH_RAM

    /DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) *(.comment) *(.note*) }
}

ASSERT(SIZEOF(.data) == 0, "patch code needs .data: patch RAM is zero-initialised only; set values in patch_init()")
