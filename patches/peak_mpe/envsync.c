/* Peak tempo-synced envelope times (docs/peak-features.md, step 11).
 *
 * Settings > MPE > EnvSync (globals +0x35): Off, or a note length (1/2, 1/4,
 * 1/8, 1/16). While on, the amp envelope's Decay and Release are set to the
 * value whose measured time (docs/peak-units.md: the time to -40 dB) is
 * nearest that note length at the current tempo, when the tempo or the
 * setting changes (a changed setting after it has held about 1 s,
 * so scrolling past a choice applies nothing). Nothing else is touched, and a knob turn between changes
 * stays.
 *
 * Tempo (observed in the disassembly; docs/findings/peak-2.2-build2108.md):
 * the effective tempo is one word at 0x20000264, 1,717,984 per BPM
 * (internal: (ClockRate * 2 + (patch+0xEE >> 6)) * 0x1A36E0, written by
 * FUN_0800F9F8 on every arp_tick; the BPM display reads the same word with
 * external clock too). The word is read as it is, so internal and external
 * tempo are both covered; a changing external tempo is applied only after it
 * has held for about 0.5 s and moved by 1 BPM or more, so clock
 * jitter doesn't cause constant writes. If the clock stops the word keeps its
 * last value (as the display does).
 *
 * The values go in through stock's own parameter setter (0x0800F6AC, value
 * and CC number: the path a received CC takes after its receive check), so
 * the patch, the FPGA update and the pickup state follow as for a CC.
 */

#include "mpe.h"
#include "disp_tables.h"

#define TEMPO_WORD (*(volatile uint32_t *)0x20000264)
#define WORD_PER_BPM100 17180u        /* 0x1A36E0 / 100 */
#define CC_AMP_DECAY 0x57
#define CC_AMP_RELEASE 0x59
/* mpe_mod_update runs 1000 times per second (TIM6 at 10 kHz, a tick every 10th
 * interrupt; docs/findings/peak-2.2-build2108.md, "Timers and the 1 kHz tick"). Up to
 * v0.13 these counts were twice as large, written for a simulator that ran the
 * Peak's timers 2x fast, so on the synth the holds were 2 s and 1 s. */
#define CHECK_TICKS 64                /* ticks between checks: 64 ms */
#define DIV_HOLD_CHECKS 16            /* a changed setting applies after about 1 s */
#define TEMPO_HOLD_CHECKS 8           /* a changed tempo after about 0.5 s */

/* Note length in quarter-note eighths per setting 1..4: 1/2 = 8, 1/4 = 4, 1/8 = 2, 1/16 = 1. */
static const uint8_t len_eighths[] = {0, 8, 4, 2, 1};

static uint32_t ticks, last_check;
static uint32_t pending_bpm100, stable;
static uint32_t pending_div, div_stable;   /* a changed setting applies once it has held */
static uint32_t applied_bpm100, applied_div;

void envsync_tick(void)
{
    ticks++;
}

uint32_t mpe_ticks(void)
{
    return ticks;
}

/* The table index whose time is nearest ms (ratio, so a log scale). */
static uint32_t nearest(const uint16_t *table, uint32_t ms)
{
    uint32_t best = 0, best_ratio = 0xFFFFFFFFu;
    for (uint32_t i = 0; i < 128; i++) {
        uint32_t t = table[i] ? table[i] : 1;
        uint32_t hi = t > ms ? t : ms, lo = t > ms ? ms : t;
        uint32_t ratio = hi * 1024u / (lo ? lo : 1);
        if (ratio < best_ratio) {
            best_ratio = ratio;
            best = i;
        }
    }
    return best;
}

static void apply(uint32_t bpm100, uint32_t div)
{
    /* ms = 60000 / bpm * (eighths / 4) = 6,000,000 * eighths / (4 * bpm100) */
    uint32_t ms = (uint32_t)(1500000u * len_eighths[div] / bpm100);
    param_set_by_id(nearest(disp_decay_ms, ms), CC_AMP_DECAY);
    param_set_by_id(nearest(disp_release_ms, ms), CC_AMP_RELEASE);
    applied_bpm100 = bpm100;
    applied_div = div;
}

/* Main-loop pass (mpe_ui_poll). */
void envsync_poll(void)
{
    if ((uint32_t)(ticks - last_check) < CHECK_TICKS)
        return;
    last_check = ticks;
    /* Compare held: stock throws away the patch it plays at the release, so
     * times set there would be lost and still count as applied; up to v0.43
     * the edited patch then kept the old tempo's times (outside audit MED-6a).
     * A tempo that changed meanwhile applies once Compare is let go. */
    if (compare_held)
        return;
    uint32_t div = globals[MPE_G_ENVSYNC];
    if (div > 4)
        div = 0;
    if (div != pending_div) {          /* scrolling past a choice must not apply it */
        pending_div = div;
        div_stable = 0;
    } else if (div_stable < 255) {
        div_stable++;
    }
    if (div == 0) {
        applied_div = 0;
        stable = 0;
        return;
    }
    if (div_stable < DIV_HOLD_CHECKS)
        return;
    uint32_t bpm100 = (TEMPO_WORD + WORD_PER_BPM100 / 2) / WORD_PER_BPM100;
    if (bpm100 < 2000 || bpm100 > 50000)   /* no tempo yet, or not a tempo */
        return;
    uint32_t moved = bpm100 > pending_bpm100 ? bpm100 - pending_bpm100 : pending_bpm100 - bpm100;
    if (moved > 50) {
        pending_bpm100 = bpm100;
        stable = 0;
    } else if (stable < 255) {
        stable++;
    }
    if (div != applied_div) {
        apply(bpm100, div);
        return;
    }
    uint32_t off = bpm100 > applied_bpm100 ? bpm100 - applied_bpm100 : applied_bpm100 - bpm100;
    if (off >= 100 && stable >= TEMPO_HOLD_CHECKS)
        apply(bpm100, div);
}
