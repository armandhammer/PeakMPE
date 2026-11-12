/* Peak MPE, per-note expression: interfaces between its modules (the
 * Summit patch's mpe_expr.h for 8 voices and one part).
 *
 *   mpe_expr.c      osc_pitch's six call sites; each voice's role once per
 *                   tick and at note-on
 *   mpe_bend.c      per-note and master bend, as an offset to osc_pitch's
 *                   result (params 0x000-0x002)
 *   mpe_pressure.c  member pressure into the voice's AftTouch slot (0x61)
 *   mpe_slide.c     CC 74 as the voice's own ModWheel (0x60), without the
 *                   broadcast 0x60
 */
#ifndef MPE_EXPR_H
#define MPE_EXPR_H

#include "mpe.h"

enum {
    MPE_ROLE_STOCK,   /* MPE off, or unbound: as stock */
    MPE_ROLE_MASTER,  /* bound to its zone's master channel */
    MPE_ROLE_MEMBER,  /* bound to a member channel */
};

int mpe_voice_role(uint32_t v, const struct mpe_zone **zone);
static inline int mpe_zone_kind(const struct mpe_zone *z) { return z->master == 0 ? MPE_LOWER : MPE_UPPER; }

/* Once per voice: every tick from mod_tick's voice loop (note_on = 0), and
 * at note-on from voice_alloc (note_on = 1), before the osc_pitch calls. */
void mpe_bend_voice(uint32_t v, int role, const struct mpe_zone *z, int note_on);
void mpe_pressure_voice(uint32_t v, int role, int note_on);
void mpe_slide_voice(uint32_t v, int role, int note_on);

int mpe_bend_stock(uint32_t v);
void mpe_bend_add(uint8_t *osc, uint32_t v);
extern int16_t mpe_bend_in;      /* osc_pitch's part-bend literal (0x08010C24) points here */

/* osc_pitch stores voice v's result as s32 at osc + 0x2C + 4v (Peak; observed
 * at 0x08010BEC). The Summit's is at +0xC. */
#define OSC_RESULT(osc, v) ((int32_t *)((osc) + 0x2C) + (v))

#define AFTERTOUCH_N 1           /* voice_mod_write n: param 0x61 */
#define MODWHEEL_N 0             /* voice_mod_write n: param 0x60 */

#endif
