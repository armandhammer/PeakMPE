/* MPE step 2, per-note expression: interfaces between its modules
 * (docs/mpe-design.md, "Step 2: expression").
 *
 *   mpe_expr.c      osc_pitch's six call sites; works out each voice's role
 *                   once per tick and at note-on, and hands it to the three
 *                   modules below
 *   mpe_bend.c      per-note bend and the master bend, as an offset to
 *                   osc_pitch's result (params 0x000-0x002)
 *   mpe_pressure.c  member pressure into the voice's AftTouch slot (0x61)
 *   mpe_slide.c     CC 74 as the voice's own ModWheel (0x60), without the
 *                   broadcast 0x60
 *
 * The step 1 core (mpe.h) is read only: voice_channel[], the per-channel
 * values, mpe_zones and mpe_live.
 */
#ifndef MPE_EXPR_H
#define MPE_EXPR_H

#include "mpe.h"

/* How a voice takes expression. */
enum {
    MPE_ROLE_STOCK,   /* MPE off for its part, unbound (keybed, a channel outside the zones): as stock */
    MPE_ROLE_MASTER,  /* bound to its zone's master channel: the master's controls only */
    MPE_ROLE_MEMBER,  /* bound to a member channel: that channel's and the master's */
};

/* Role of voice v in part (0 in Single mode), and its zone (0 for stock). */
int mpe_voice_role(uint32_t v, uint32_t part, const struct mpe_zone **zone);
static inline int mpe_zone_kind(const struct mpe_zone *z) { return z->master == 0 ? MPE_LOWER : MPE_UPPER; }

/* Once per voice: every tick (note_on = 0) from mod_tick, before mod_update;
 * and at note-on (note_on = 1) from voice_alloc, after the core bound the
 * voice and before its osc_pitch calls and FPGA writes. */
void mpe_bend_voice(uint32_t v, uint32_t part, int role, const struct mpe_zone *z, int note_on);
void mpe_pressure_voice(uint32_t v, uint32_t part, int role, int note_on);
void mpe_slide_voice(uint32_t v, int role, int note_on);

/* Bend, per osc_pitch call: whether stock's part-bend term applies, and the
 * offset to add to the result (0 for stock voices). */
int mpe_bend_stock(uint32_t v);
void mpe_bend_add(uint8_t *osc, uint32_t v);
extern int16_t mpe_bend_in[2];

/* AftTouch slot and smoother of voice v (voice_state+0xE4+2v, +0x104+4v). */
#define MPE_AT_SLOT(v) (*(volatile uint16_t *)&voice_state[0xE4 + 2 * (v)])
#define MPE_AT_SMOOTH(v) (*(volatile int32_t *)&voice_state[0x104 + 4 * (v)])

#endif
