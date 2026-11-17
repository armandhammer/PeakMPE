/* Peak parameter lock (docs/peak-features.md, step 14).
 *
 * Settings > PARAM LOCK (globals +0x36 .. +0x38): FX, Arp and Voice, each Off or
 * On. A group that is On keeps its current values when a patch loads, so a
 * patch change leaves the FX, the arpeggiator or the voice settings (mode,
 * unison, glide, diverge, drift, noise filters) as they are.
 *
 * Patch load is one function (0x0801AEB8, observed: the trace of a program
 * change in the simulator): it copies 0x201 bytes into the patch (0x20012340)
 * with the firmware's byte loop at 0x0801D736, then pushes the patch to the
 * sound chip and resets the arp. The copy is hooked (0x0801AECC): the locked
 * ranges are saved first and written back after the copy, so the push that
 * follows sends them. The same function loads the Initialise patch and a
 * compare buffer; only a load into the current patch is touched. The first
 * load after power-up is skipped (the patch RAM is still empty).
 *
 * The hook is also where the undo step, the motion lane and the morph learn of
 * a patch load. The Compare button's load (compare_held set, 0x200111F2) is
 * not one for them: stock copies the patch back at the release, so all three
 * stand still while the button is held and go on afterwards.
 *
 * Ranges (patch offsets, from the parameter table; the groups are mine):
 *   FX     0xC7-0xEB  distortion, delay, reverb, chorus
 *   Arp    0xEC-0xFA  arp mode, tempo (ClockRate), rate, type, rhythm, octaves, gate, swing, latch
 *   Voice  0x22-0x2F  mode, unison, detune, spread, glide, diverge, drift, noise LPF/HPF, key sync
 */

#include "mpe.h"

#define GROUPS 3
static const struct { uint8_t lo, hi; } ranges[GROUPS] = {
    {0xC7, 0xEB}, {0xEC, 0xFA}, {0x22, 0x2F},
};

static uint8_t seen;   /* a patch has been loaded since power-up (zero-initialised patch RAM) */

/* The firmware's copy in patch load (0x0801AECC): the same arguments as stock. */
void *plock_copy(void *dst, const void *src, uint32_t n)
{
    uint8_t keep[0x40];
    uint8_t take = 0;
    uint32_t k = 0;
    if (seen && dst == (void *)patches) {
        for (uint32_t g = 0; g < GROUPS; g++) {
            if (globals[MPE_G_LOCK_FX + g] != 1)
                continue;
            take |= (uint8_t)(1u << g);
            for (uint32_t o = ranges[g].lo; o <= ranges[g].hi; o++)
                keep[k++] = patches[o];
        }
    }
    void *r = fw_memcpy(dst, src, n);
    if (dst == (void *)patches) {
        if (!compare_held) {     /* not the load Compare makes: that patch is only listened to */
            undo_clear();
            motion_clear();
            morph_clear();
        }
        seen = 1;
        k = 0;
        for (uint32_t g = 0; g < GROUPS; g++) {
            if (!(take & (1u << g)))
                continue;
            for (uint32_t o = ranges[g].lo; o <= ranges[g].hi; o++)
                patches[o] = keep[k++];
        }
    }
    return r;
}
