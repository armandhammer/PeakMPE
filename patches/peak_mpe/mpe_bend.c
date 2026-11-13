/* Peak MPE expression: per-note bend and the master bend (the Summit patch's
 * mpe_bend.c; see docs/mpe-design.md, "Bend").
 *
 * For an MPE voice:
 *   - osc_pitch reads a part bend of 0 (its literal for part_bend_smoothed,
 *     0x08010C24, points at mpe_bend_in), so the patch's BendRange doesn't
 *     apply;
 *   - an offset is added to osc_pitch's s32 result (4,096 per octave):
 *       member bend  -8192..8191 x note range / 24   (+-48 semitones = +-16,384)
 *       master bend  -8192..8191 x master range / 24 (its zone's master)
 *     clamped to what osc_pitch itself can return (its s16 sum x 0x5555 >>
 *     14, the same scaling as on the Summit, observed at 0x08010BDE).
 * The master bend is the voice's own zone's (mpe_master_bend, kept by the
 * channel filter), not the stock part bend: both zones play the Peak's one
 * part, so part_bend_smoothed holds whichever master bent last and moved
 * both zones (on hardware 2026-11-12). The scale is the stock one:
 * part_bend_smoothed is twice the raw bend (+-0x4000), x range / 48.
 *
 * Each voice smooths its member and master bends by 1/4 of the step per
 * tick; at note-on they jump to their channels' bends.
 */

#include "mpe_expr.h"

#define SMOOTH_SHIFT 2
#define OSC_MIN (-43691)             /* (s16) -32768 * 0x5555 >> 14 */
#define OSC_MAX 43689                /* 32767 * 0x5555 >> 14 */

int16_t mpe_bend_in;

static int32_t smoothed[MPE_VOICES]; /* member bend per voice, 16.16 */
static int32_t smoothed_master[MPE_VOICES]; /* its zone's master bend, 16.16 */
static int32_t offset[MPE_VOICES];   /* added to osc_pitch's result */
static uint8_t mpe_voices;           /* voices with an MPE role */

void mpe_bend_voice(uint32_t v, int role, const struct mpe_zone *z, int note_on)
{
    uint8_t bit = (uint8_t)(1u << v);
    if (role == MPE_ROLE_STOCK) {
        mpe_voices &= (uint8_t)~bit;
        smoothed[v] = 0;
        smoothed_master[v] = 0;
        offset[v] = 0;
        return;
    }
    int kind = mpe_zone_kind(z);
    int32_t target = role == MPE_ROLE_MEMBER ? mpe_chan_bend[voice_channel[v]] * 65536 : 0;
    int32_t target_master = mpe_master_bend[kind] * 65536;
    if (note_on || !(mpe_voices & bit)) {
        smoothed[v] = target;
        smoothed_master[v] = target_master;
    } else {
        smoothed[v] += (target - smoothed[v]) >> SMOOTH_SHIFT;
        smoothed_master[v] += (target_master - smoothed_master[v]) >> SMOOTH_SHIFT;
    }
    mpe_voices |= bit;
    int32_t bend = (smoothed[v] + 0x8000) >> 16;
    int32_t master = (smoothed_master[v] + 0x8000) >> 16;
    offset[v] = bend * mpe_live.note_range[kind] / 24
              + master * mpe_live.master_range[kind] / 24;
}

int mpe_bend_stock(uint32_t v)
{
    return !(mpe_voices & (1u << v));
}

void mpe_bend_add(uint8_t *osc, uint32_t v)
{
    if (!(mpe_voices & (1u << v)))
        return;
    int32_t *out = OSC_RESULT(osc, v);
    int32_t pitch = *out + offset[v];
    *out = pitch < OSC_MIN ? OSC_MIN : pitch > OSC_MAX ? OSC_MAX : pitch;
}
