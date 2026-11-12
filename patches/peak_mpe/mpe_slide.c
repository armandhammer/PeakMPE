/* Peak MPE expression: Slide (CC 74) as each voice's own ModWheel (the
 * Summit patch's mpe_slide.c, without its FPGA queue handling).
 *
 * On the Summit (experiment D2, observed there): a 0x60 written to a voice
 * target drives that voice's ModWheel source, while a broadcast 0x60
 * overwrites every voice. Whether the Peak's FPGA (build 469) behaves the
 * same is NOT yet known; it is the first hardware check for Slide.
 *
 * With MPE on, mod_update's broadcast 0x60 (0x08010972, voice_mod_write(0xA,
 * 0, wheel)) isn't sent. Each voice gets 0x60 = the stock-smoothed mod wheel
 * of the part (the master channel's CC 1, voice_state+0x36) + its own Slide,
 * clamped to 0x7FFF:
 *   member voice   its channel's CC 74 << 8 (127 -> 0x7FFF), smoothed by
 *                  1/8 of the step per tick and set at once at note-on
 *   other voices   0, so they follow the wheel as on stock
 * 0x860 (part-level destinations) stays stock: the master's wheel only.
 *
 * The Peak has no FPGA write queue (fpga_write 0x0800EBF0 is a direct SPI
 * transaction, observed), so each write here is direct, made after mod_update
 * in the main loop, only when the voice's value changed, at most
 * SLIDE_PER_TICK per tick, round-robin: 8 voices all moving are each
 * refreshed every 2 ms. When MPE goes off the stock broadcast resumes on the
 * next tick and sets every voice again.
 */

#include "mpe_expr.h"

#define SLIDE_PER_TICK 4
#define SMOOTH_SHIFT 3                /* 1/8 of the step per tick */

static int32_t smoothed[MPE_VOICES];  /* Slide per voice, 16.16 */
static int32_t target[MPE_VOICES];    /* the Slide target, 16.16 */
static int32_t sent[MPE_VOICES];      /* last 0x60 the voice got from this module */
static uint8_t known;                 /* sent[v] is what the voice holds */
static uint8_t next;                  /* round-robin start */

static int32_t value(uint32_t v)
{
    int32_t x = PART_WHEEL + ((smoothed[v] + 0x8000) >> 16);
    return x < 0 ? 0 : x > 0x7FFF ? 0x7FFF : x;
}

static void send(uint32_t v)
{
    sent[v] = value(v);
    voice_mod_write((uint8_t)v, MODWHEEL_N, sent[v]);
    known |= (uint8_t)(1u << v);
}

void mpe_slide_voice(uint32_t v, int role, int note_on)
{
    uint8_t cc = role == MPE_ROLE_MEMBER ? mpe_chan_slide[voice_channel[v]] : 0;
    target[v] = (cc == 127 ? 0x7FFF : cc << 8) * 65536;
    if (note_on && mpe_part_on(0)) {
        smoothed[v] = target[v];
        send(v);
    }
}

/* Replaces mod_update's broadcast 0x60 write (0x08010972). */
void mpe_wheel_write(uint8_t target_, uint8_t n, int32_t value_)
{
    if (mpe_part_on(0))
        return;
    known = 0;  /* the broadcast sets every voice: rewrite them when MPE turns on */
    voice_mod_write(target_, n, value_);
}

/* Replaces mod_tick's mod_update() call (0x08010E70). */
void mpe_mod_update(void)
{
    mod_update();
    if (!mpe_part_on(0)) {
        for (uint32_t v = 0; v < MPE_VOICES; v++)
            smoothed[v] = 0;
        return;
    }
    uint8_t dirty = 0;
    for (uint32_t v = 0; v < MPE_VOICES; v++) {
        smoothed[v] += (target[v] - smoothed[v]) >> SMOOTH_SHIFT;
        if (!(known & (1u << v)) || value(v) != sent[v])
            dirty |= (uint8_t)(1u << v);
    }
    int n = 0;
    for (uint32_t i = 0; i < MPE_VOICES && n < SLIDE_PER_TICK; i++) {
        uint32_t v = (next + i) & (MPE_VOICES - 1);
        if (dirty & (1u << v)) {
            send(v);
            next = (uint8_t)(v + 1);
            n++;
        }
    }
}
