/* MPE step 2: per-note bend and the master bend (docs/mpe-design.md).
 *
 * The oscillator pitch the FPGA plays is params 0x000-0x002, per voice,
 * computed by osc_pitch (experiment C, observed on hardware). For an MPE
 * voice this module:
 *   - feeds osc_pitch a part bend of 0 (its literal for part_bend_smoothed,
 *     0x08013AD4, points at mpe_bend_in), so the patch's BendRange doesn't
 *     apply;
 *   - adds an offset to osc_pitch's s32 result (4,096 per octave):
 *       member bend  -8192..8191 x note range / 24  (+-48 semitones = +-16,384)
 *       master bend  part_bend_smoothed x master range / 48  (+-16,384 = full)
 *     and clamps the sum to what osc_pitch itself can return (its s16 sum
 *     x 4/3, -43,691..43,689), so nothing wraps.
 * The master bend is the stock one: the master channel's bend message goes
 * to the part (parts[p]+4), mod_update smooths it (1/16 per tick). Only its
 * range changes. Voices bound to the master channel take the master bend
 * only; stock voices (MPE off, unbound) keep stock's term and get no offset.
 *
 * Smoothing: each voice smooths its member bend by 1/4 of the step per tick
 * (90 % in 8 ticks), lighter than stock's 1/16, since MPE senders stream
 * bend densely and per-note pitch should follow the finger. At note-on the
 * voice jumps to its channel's bend (senders send it just before the
 * note-on), so a note started while its channel is bent starts bent, also
 * for a channel reused and in mono/legato.
 */

#include "mpe_expr.h"

#define SMOOTH_SHIFT 2               /* 1/4 of the step per tick */
#define OSC_MIN (-43691)             /* (s16) -32768 * 0x5555 >> 14 */
#define OSC_MAX 43689                /* 32767 * 0x5555 >> 14 */

int16_t mpe_bend_in[2];              /* what osc_pitch reads as the part bend */

static int32_t smoothed[16];         /* member bend per voice, 16.16 */
static int32_t offset[16];           /* added to osc_pitch's result */
static uint16_t mpe_voices;          /* voices with an MPE role */

void mpe_bend_voice(uint32_t v, uint32_t part, int role, const struct mpe_zone *z, int note_on)
{
    uint16_t bit = (uint16_t)(1u << v);
    if (role == MPE_ROLE_STOCK) {
        mpe_voices &= (uint16_t)~bit;
        smoothed[v] = 0;
        offset[v] = 0;
        return;
    }
    int kind = mpe_zone_kind(z);
    int32_t target = role == MPE_ROLE_MEMBER ? mpe_chan_bend[voice_channel[v]] * 65536 : 0;
    if (note_on || !(mpe_voices & bit))
        smoothed[v] = target;
    else
        smoothed[v] += (target - smoothed[v]) >> SMOOTH_SHIFT;
    mpe_voices |= bit;
    int32_t bend = (smoothed[v] + 0x8000) >> 16;
    offset[v] = bend * mpe_live.note_range[kind] / 24
              + part_bend_smoothed[part & 1] * mpe_live.master_range[kind] / 48;
}

int mpe_bend_stock(uint32_t v)
{
    return !(mpe_voices & (1u << v));
}

void mpe_bend_add(uint8_t *osc, uint32_t v)
{
    if (!(mpe_voices & (1u << v)))
        return;
    int32_t *out = (int32_t *)(osc + 0xC) + v;
    int32_t pitch = *out + offset[v];
    *out = pitch < OSC_MIN ? OSC_MIN : pitch > OSC_MAX ? OSC_MAX : pitch;
}
