/* Patch startup, linked into every C patch (docs/patch-howto.md).
 *
 * tools/patch.py rewrites Reset_Handler's `bl main_loop` (0x0801D9F2) to call
 * __patch_start instead. Patch RAM is CCM, which neither the hardware nor
 * Reset_Handler clears, so this zeroes the patch's .bss, runs the patch's
 * optional patch_init(), then calls main_loop as the stock code did.
 *
 * It runs before main's init, so the FPU is still off (CPACR is set at
 * 0x0801298A): this file and patch_init() must not use floating point. The
 * general-regs-only target stops the compiler from using FPU registers here.
 */

#include "firmware.h"

extern uint32_t __patch_bss_start[], __patch_bss_end[];

void patch_init(void) __attribute__((weak));

__attribute__((used, target("general-regs-only")))
void __patch_start(void)
{
    for (volatile uint32_t *p = __patch_bss_start; p < __patch_bss_end; p++)
        *p = 0;
    if (patch_init)
        patch_init();
    main_loop();
}
