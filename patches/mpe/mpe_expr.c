/* MPE step 2: the osc_pitch call sites, where each voice's expression is
 * worked out (docs/mpe-design.md, "Step 2: expression").
 *
 * osc_pitch (0x08013A2C) runs three times per voice (Osc 1-3), for the voice
 * in voice_loop_index:
 *   mod_tick (0x08014526, 0x08014530, 0x0801453A)  every voice, every tick,
 *       before that tick's mod_update calls
 *   voice_alloc (0x08016F66, 0x08016F72, 0x08016F7C)  the new voice at
 *       note-on, after the core's voice_glide hook bound it to its channel
 * Before Osc 1's call (osc[0] == 0, the struct's oscillator index) the voice's
 * role goes to the bend, pressure and Slide modules; then every call adds
 * the bend offset to the result. For a stock voice nothing changes: the
 * bend input is part_bend_smoothed and the offset isn't added.
 */

#include "mpe_expr.h"

int mpe_voice_role(uint32_t v, uint32_t part, const struct mpe_zone **zone)
{
    uint8_t ch = voice_channel[v];
    const struct mpe_zone *z;
    *zone = 0;
    if (ch == MPE_NONE || part > 1 || !mpe_part_on(part))
        return MPE_ROLE_STOCK;
    z = mpe_zone_of(ch);
    if (!z || z->part != part)  /* the layout changed under a held voice */
        return MPE_ROLE_STOCK;
    *zone = z;
    return ch == z->master ? MPE_ROLE_MASTER : MPE_ROLE_MEMBER;
}

static void pitch(uint8_t *osc, uint32_t part, int note_on)
{
    uint32_t v = voice_loop_index & 0x0F;
    if (osc[0] == 0) {
        const struct mpe_zone *z;
        int role = mpe_voice_role(v, part, &z);
        mpe_bend_voice(v, part, role, z, note_on);
        mpe_pressure_voice(v, part, role, note_on);
        mpe_slide_voice(v, role, note_on);
    }
    mpe_bend_in[part & 1] = mpe_bend_stock(v) ? part_bend_smoothed[part & 1] : 0;
    osc_pitch(osc, part);
    mpe_bend_add(osc, v);
}

/* Replaces mod_tick's three osc_pitch calls. */
void mpe_osc_pitch_tick(uint8_t *osc, uint32_t part)
{
    pitch(osc, part, 0);
}

/* Replaces voice_alloc's three osc_pitch calls. */
void mpe_osc_pitch_alloc(uint8_t *osc, uint32_t part)
{
    pitch(osc, part, 1);
}
