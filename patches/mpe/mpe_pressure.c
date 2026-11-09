/* MPE step 2: pressure (docs/mpe-design.md).
 *
 * Aftertouch is per voice in stock already: each voice has an AftTouch slot
 * (voice_state+0xE4+2v, value << 8) that mod_update smooths and sends as
 * 0x61, one voice per call, round-robin (each voice every 8 ms).
 * chan_at_store (0x080159B8) writes the part's channel pressure into the
 * slot of every voice of the part, and into parts[p]+7.
 *
 * The master channel's pressure takes that stock path unchanged, so it
 * reaches every voice of the zone. A member channel's pressure (the core
 * stores it in mpe_chan_pressure) goes to the voices bound to that channel:
 * every tick, before mod_update, their slot becomes the larger of the
 * member's and the master's pressure. So the master never overwrites what a
 * member drives, and a member never pushes a voice below the master.
 *
 * A slot this module wrote goes back to the master's value as soon as its
 * voice stops being a member voice (a keybed note takes it, MPE goes off),
 * so no pressure is left behind. At note-on a bound voice's smoother jumps
 * to its slot and its 0x61 is written at once, as voice_alloc writes the
 * oscillator pitch, instead of easing in from the previous note's pressure
 * over the next 8-30 ms.
 */

#include "mpe_expr.h"

#define AFTERTOUCH 0x61

static uint16_t owned;  /* voices whose slot holds a member value */

void mpe_pressure_voice(uint32_t v, uint32_t part, int role, int note_on)
{
    uint16_t bit = (uint16_t)(1u << v);
    uint8_t master = parts[part & 1][7];
    if (role == MPE_ROLE_MEMBER) {
        uint8_t p = mpe_chan_pressure[voice_channel[v]];
        MPE_AT_SLOT(v) = (uint16_t)((p > master ? p : master) << 8);
        owned |= bit;
    } else if (owned & bit) {
        MPE_AT_SLOT(v) = (uint16_t)(master << 8);
        owned &= (uint16_t)~bit;
    }
    if (note_on && role != MPE_ROLE_STOCK) {
        /* mod_update's maths (0x080143A0-0x080143F4) at a settled smoother */
        int32_t smooth = (MPE_AT_SLOT(v) >> 4) << 16;
        uint32_t x = ((uint32_t)smooth >> 12) & 0xFFFF;
        MPE_AT_SMOOTH(v) = smooth;
        fpga_voice_write((uint8_t)v, AFTERTOUCH, (int32_t)((x * x >> 15) & 0xFFFF));
    }
}
