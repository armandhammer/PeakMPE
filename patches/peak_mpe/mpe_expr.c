/* Peak MPE expression: the osc_pitch call sites.
 *
 * osc_pitch (0x08010B60) runs three times per voice (Osc 1-3), for the voice
 * in voice_loop_index:
 *   mod_tick (0x08010EB8, 0x08010EC2, 0x08010ECC)  every voice, every tick,
 *       after that tick's mod_update (the Peak runs mod_update first)
 *   voice_alloc (0x0801264A, 0x08012654, 0x0801265E)  the new voice at
 *       note-on, after the core's voice_glide hook bound it
 * Before Osc 1's call (osc[0] == 0, the oscillator index) the voice's role
 * goes to the bend, pressure and Slide modules; then every call adds the bend
 * offset to the result. Stock voices are unchanged.
 */

#include "mpe_expr.h"

int mpe_voice_role(uint32_t v, const struct mpe_zone **zone)
{
    uint8_t ch = voice_channel[v];
    const struct mpe_zone *z;
    *zone = 0;
    if (ch == MPE_NONE || !mpe_part_on(0))
        return MPE_ROLE_STOCK;
    z = mpe_zone_of(ch);
    if (!z)  /* the layout changed under a held voice */
        return MPE_ROLE_STOCK;
    *zone = z;
    return ch == z->master ? MPE_ROLE_MASTER : MPE_ROLE_MEMBER;
}

static void pitch(uint8_t *osc, uint32_t part, int note_on)
{
    uint32_t v = voice_loop_index & (MPE_VOICES - 1);
    if (osc[0] == 0) {
        const struct mpe_zone *z;
        int role = mpe_voice_role(v, &z);
        mpe_bend_voice(v, role, z, note_on);
        mpe_pressure_voice(v, role, note_on);
        mpe_slide_voice(v, role, note_on);
    }
    mpe_bend_in = mpe_bend_stock(v) ? part_bend_smoothed : 0;
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
