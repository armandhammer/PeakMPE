/* MPE step 2: Slide (CC 74) as each voice's own ModWheel (docs/mpe-design.md).
 *
 * Experiment D2 (observed on hardware): a 0x60 written to a voice target
 * drives that voice's ModWheel source, but a broadcast 0x60 (to 0x1A)
 * reaches every voice and overwrites it. So for an engine whose voices
 * belong to an MPE part (both engines in Single mode, the part's own in
 * Multi), mod_update's broadcast 0x60 (0x08014248) isn't sent. Each voice
 * gets 0x60 = the stock-smoothed mod wheel of its part (the master channel's
 * CC 1, voice_state+0xCA+4p) + its own Slide, clamped to 0x7FFF:
 *   member voice   its channel's CC 74 << 8 (127 -> 0x7FFF), smoothed per
 *                  voice by 1/8 of the step per tick (as stock smooths the
 *                  wheel) and set at once at note-on
 *   other voices   0, so they follow the wheel as on stock
 * The sum lets the wheel move every note while each note slides on its own.
 * 0x860 (to 0x19, the FX and other part-level destinations) stays stock:
 * the master's mod wheel only.
 *
 * The per-voice writes don't go through the FPGA queue (v1.2): each is a
 * direct fpga_voice_write (an SPI1 transaction under cpsid f, as
 * voice_alloc writes a note's pitch), after mod_update(1) (0x0801457E),
 * only when the voice's value changed, at most SLIDE_PER_TICK per tick,
 * round-robin, so 16 voices all moving are each refreshed every 4-6 ms. The
 * queue then carries stock's writes minus the dropped broadcasts, whatever
 * the timing: no tick, late or not, can take it past where stock does.
 * (v1 queued them, behind a check of the queue's depth; v1.1 added a guard
 * on the tick's phase, timer_state+0x4A8 >= 5, tuned in the simulator. On
 * the synth every tick ran at 5 or later and Slide was never sent:
 * docs/mpe-design.md#slide-v12.) At note-on the new voice's value is
 * written at once and again in the next tick, first.
 *
 * A broadcast 0x60 that mod_update queued while the engine was not MPE can
 * still be in the queue when the engine turns MPE (the flag, a mode or zone
 * change) and would land after a direct write. So when this module lets a
 * broadcast through it notes the drain count (voice_state+0x148) by which
 * the entry is sent, and while the drain hasn't got there the engine's
 * voices count as unknown and are written again.
 *
 * When MPE goes off for a part, its broadcast 0x60 resumes and sets every
 * voice of the engine again.
 */

#include "mpe_expr.h"

#define MODWHEEL 0x60
#define SLIDE_PER_TICK 4
#define SMOOTH_SHIFT 3                /* 1/8 of the step per tick, as mod_update's wheel */
#define WHEEL(e) (*(volatile int16_t *)&voice_state[0xCA + 4 * (e)])
#define QUEUE_WR (*(volatile uint16_t *)&voice_state[0xBC])   /* fpga_queue write index, entries */
#define QUEUE_RD (*(volatile uint16_t *)&voice_state[0x144])  /* read index (fpga_queue_drain) */
#define QUEUE_SENT (*(volatile uint32_t *)&voice_state[0x148]) /* entries the drain has sent */
#define QUEUE_ENTRIES 128

static int32_t smoothed[16];          /* Slide per voice, 16.16 */
static int32_t target[16];            /* this tick's Slide target, 16.16 */
static int32_t sent[16];              /* last 0x60 the voice got from this module */
static uint16_t known;                /* sent[v] is what the voice holds */
static uint16_t urgent;               /* note-on: queue again first */
static uint8_t next;                  /* round-robin start */
static uint32_t wheel_out[2];         /* QUEUE_SENT once the engine's last queued broadcast is out */

/* The broadcast 0x60 of engine e (part_mask 0x80 = A, 0x40 = B) is dropped. */
static int engine_mpe(uint32_t e)
{
    return mpe_part_on(multi_mode ? e : 0);
}

static int32_t value(uint32_t v)
{
    int32_t x = WHEEL(v >> 3) + ((smoothed[v] + 0x8000) >> 16);
    return x < 0 ? 0 : x > 0x7FFF ? 0x7FFF : x;
}

void mpe_slide_voice(uint32_t v, int role, int note_on)
{
    uint8_t cc = role == MPE_ROLE_MEMBER ? mpe_chan_slide[voice_channel[v]] : 0;
    target[v] = (cc == 127 ? 0x7FFF : cc << 8) * 65536;
    if (note_on && engine_mpe(v >> 3)) {
        smoothed[v] = target[v];
        sent[v] = value(v);
        fpga_voice_write((uint8_t)v, MODWHEEL, sent[v]);
        known &= (uint16_t)~(1u << v);
        urgent |= (uint16_t)(1u << v);
    }
}

/* Replaces mod_update's broadcast 0x60 write (0x08014248). */
void mpe_wheel_write(uint8_t part_mask, uint8_t target_, uint16_t param, int32_t value_)
{
    uint32_t e = part_mask == 0x40;
    if (engine_mpe(e))
        return;
    __asm volatile("cpsid f" ::: "memory");  /* the drain runs in TIM6 */
    fpga_mod_write(part_mask, target_, param, value_);
    wheel_out[e] = QUEUE_SENT + ((uint32_t)QUEUE_WR - QUEUE_RD) % QUEUE_ENTRIES;
    __asm volatile("cpsie f" ::: "memory");
}

static void send(uint32_t v)
{
    sent[v] = value(v);
    fpga_voice_write((uint8_t)v, MODWHEEL, sent[v]);
    known |= (uint16_t)(1u << v);
    urgent &= (uint16_t)~(1u << v);
}

/* Replaces mod_tick's mod_update(1) (0x0801457E), the tick's last part
 * update: then both parts' wheels are smoothed for this tick. */
void mpe_mod_update(uint32_t part)
{
    uint16_t dirty = 0, stale = 0;
    uint32_t out = QUEUE_SENT;
    mod_update(part);
    for (uint32_t e = 0; e < 2; e++) {
        if ((int32_t)(out - wheel_out[e]) < 0)
            stale |= (uint16_t)(0xFFu << (8 * e));  /* a broadcast is still queued */
        else
            wheel_out[e] = out;                     /* kept within reach of the count */
    }
    for (uint32_t v = 0; v < 16; v++) {
        uint16_t bit = (uint16_t)(1u << v);
        if (!engine_mpe(v >> 3)) {
            known &= (uint16_t)~bit;
            urgent &= (uint16_t)~bit;
            smoothed[v] = 0;
            continue;
        }
        if (stale & bit)
            known &= (uint16_t)~bit;  /* write again once the broadcast is out */
        smoothed[v] += (target[v] - smoothed[v]) >> SMOOTH_SHIFT;
        if (!(known & bit) || value(v) != sent[v])
            dirty |= bit;
    }
    int n = 0;
    for (uint32_t v = 0; v < 16 && n < SLIDE_PER_TICK; v++)
        if (urgent & dirty & (1u << v)) {
            send(v);
            dirty &= (uint16_t)~(1u << v);
            n++;
        }
    for (uint32_t i = 0; i < 16 && n < SLIDE_PER_TICK; i++) {
        uint32_t v = (next + i) & 0x0F;
        if (dirty & (1u << v)) {
            send(v);
            next = (uint8_t)(v + 1);
            n++;
        }
    }
}
