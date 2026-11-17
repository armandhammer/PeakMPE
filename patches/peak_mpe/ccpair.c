/* The coarse byte of a 9-bit CC pair over MIDI (v0.22).
 *
 * Stock's setter behind a received CC, param_set_by_id (0x0800F6AC), holds the
 * value against the descriptor's min and max. For the coarse byte of a 9-bit
 * pair (descriptor NRPN msb 254) the descriptor holds the pair's 9-bit range,
 * so the 7-bit byte is compared with 9-bit bounds. Harmless where the range
 * is 0-255, but the three oscillator Fine controls have 28-228 (offsets 0x33,
 * 0x48, 0x5D; CC 15, 18, 21): their coarse byte runs 14-114 and stock drops
 * 14-27, Fine -100 to about -73 (findings, "The parameter setter and 9-bit
 * controls"; emulated).
 *
 * The descriptors stay as stock: ui_value_change (0x08018448) uses the same
 * min and max as 9-bit bounds for the menu encoder, and disp.c draws the knob's
 * value bar over them, so lowering the min would change both. Instead cc's
 * call of the setter for a plain CC (0x0800F318, in cc 0x0800F124; its other
 * call, 0x0800F30E, is NRPN data entry, ids from 0x80 up, never a pair's
 * coarse byte) comes here. A CC that is the coarse
 * byte of a pair is held against half the pair's range and clamped to it, so a
 * controller's knob reaches exactly the panel's -100 to +100 even when it
 * jumps past the ends; it is then written as stock's setter writes it
 * (param_write, pickup_arm). Everything else goes to stock's setter unchanged. */
#include "../common/peak.h"

#define N_DESCS 0x1A2
#define MSB_PAIR_COARSE 254

void ccpair_param_set(uint32_t value, uint32_t id)
{
    if (id < 128) {
        uint32_t o = param_offset_of_id(id);
        if (o < N_DESCS && patch_param_desc[o].nrpn_msb == MSB_PAIR_COARSE) {
            const struct param_desc *d = &patch_param_desc[o];
            uint32_t lo = (d->min + 1u) / 2u, hi = d->max / 2u;
            if (hi > 127)
                hi = 127;
            if (lo <= hi) {
                if (value < lo)
                    value = lo;
                if (value > hi)
                    value = hi;
                param_write(value, id);
                pickup_arm(o);
                return;
            }
        }
    }
    param_set_by_id(value, id);
}
