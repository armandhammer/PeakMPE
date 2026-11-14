/* Peak MPE expression: pressure (the Summit patch's mpe_pressure.c).
 *
 * Aftertouch is per voice in stock already: each voice has an AftTouch slot
 * (voice_state+0x44+2v, value << 8) that mod_update smooths and sends as
 * 0x61, one voice per call, round-robin (0x08010A1A-0x08010A7C: each voice
 * every 8 ms). chan_at (0x08011D98) writes the channel pressure into
 * parts+7 and every voice's slot.
 *
 * The master channel's pressure takes that stock path. A member channel's
 * pressure (channel or poly, stored by the core) goes to the voices bound to
 * that channel: every tick their slot becomes the larger of the member's and
 * the master's pressure. A slot this module wrote goes back to the master's
 * value as soon as its voice stops being a member voice. At note-on a bound
 * voice's smoother jumps to its slot and its 0x61 is written at once.
 *
 * Peak: mod_update runs before mod_tick's voice loop, so a slot written here
 * is sent from the next tick's mod_update (1 ms later than on the Summit).
 */

#include "mpe_expr.h"

static uint8_t owned;  /* voices whose slot holds a member value */
static int32_t last_linear;  /* the voice write's value, for the part write after it */

/* The value mod_update sends for a smoother: stock squares it (x*x >> 15),
 * Settings "PressCurve" Linear sends x itself (0x7F00 for pressure 127,
 * stock's 0x7E00). x is mod_update's ubfx #12, #16 of the smoother. */
static int32_t curve(uint32_t x, int32_t squared)
{
    return globals[MPE_G_CURVE] == 1 ? (int32_t)x : squared;
}

/* mod_update's pressure writes (0x08010A7C, 0x08010A84; patch.py): voice
 * write, then the part write with the same value. */
void mpe_pressure_write_voice(uint8_t v, uint8_t n, int32_t value)
{
    last_linear = curve(((uint32_t)VOICE_AT_SMOOTH(v) >> 12) & 0xFFFF, value);
    voice_mod_write(v, n, last_linear);
}

void mpe_pressure_write_part(uint8_t n, int32_t value)
{
    part_mod_write(n, globals[MPE_G_CURVE] == 1 ? last_linear : value);
}

void mpe_pressure_voice(uint32_t v, int role, int note_on)
{
    uint8_t bit = (uint8_t)(1u << v);
    uint8_t master = parts[7];
    if (role == MPE_ROLE_MEMBER) {
        uint8_t p = mpe_chan_pressure[voice_channel[v]];
        VOICE_AT_SLOT(v) = (uint16_t)((p > master ? p : master) << 8);
        owned |= bit;
    } else if (owned & bit) {
        VOICE_AT_SLOT(v) = (uint16_t)(master << 8);
        owned &= (uint8_t)~bit;
    }
    if (note_on && role != MPE_ROLE_STOCK) {
        /* mod_update's maths (0x08010A28-0x08010A74) at a settled smoother */
        int32_t smooth = (VOICE_AT_SLOT(v) >> 4) << 16;
        uint32_t x = ((uint32_t)smooth >> 12) & 0xFFFF;
        VOICE_AT_SMOOTH(v) = smooth;
        voice_mod_write((uint8_t)v, AFTERTOUCH_N, curve(x, (int32_t)((x * x >> 15) & 0xFFFF)));
    }
}
