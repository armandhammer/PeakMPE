/* Peak Euclidean arp rhythms (docs/peak-features.md step 17).
 *
 * Settings > ARP EUCLID (globals +0x45 .. +0x47): Pulses (Off, 1-32), Steps
 * (1-32) and Rotate (0-31). With Pulses on, the arpeggiator plays that many
 * notes spread as evenly as possible over Steps steps (5 in 8: x.x.xx.x) in
 * place of the patch's Rhythm; Rotate starts the pattern that many steps
 * later. Everything else stays stock's: SyncRate sets how long a step is,
 * and Type, Octaves, Gate, Swing, Latch and KeySync work as before.
 *
 * Stock's rhythms (findings, "Arp rhythm patterns"): the arp state
 * (arp_state_ptr) holds a pointer to the pattern's events at +8 and their
 * number at +0x1D4; an event is two bytes, a velocity in percent (0 = a
 * rest) and a length in arp clocks, six clocks to a step, and a note event
 * is always followed by a rest event, whose length the Gate setting may
 * use. arp_tick loads the patch's Rhythm (patch +0xF1) from the table at
 * arp_state_ptr + 8 whenever it differs from the number at +0x1D8, and then
 * restarts the pattern (0x08014F68).
 *
 * Here the call of arp_tick (0x08011956, in the main loop's tick work) is
 * hooked. With Pulses on, the events are built in patch RAM, the state is
 * pointed at them and +0x1D8 is kept equal to the patch's Rhythm, so stock
 * loads nothing over them. Back at Off, +0x1D8 is set to a number no Rhythm
 * has, and stock loads the patch's own pattern in the same tick.
 *
 * The arp compares times as 16-bit numbers with eight fraction bits, so one
 * step of the pattern (a note with its rest, or a rest alone) has to stay
 * under 128 clocks: a longer gap is written as several rests of at most 96.
 */

#include "mpe.h"

#define STEP_CLOCKS 6
#define NOTE_CLOCKS 3              /* as stock's Rhythm 1: half the step at Gate 64 */
#define MAX_STEPS 32
#define MAX_SPAN 96                /* clocks in one event pair or one rest */
#define VELOCITY 100               /* percent of the key's velocity, stock's usual value */
#define DEFAULT_STEPS 16

#define A_PATTERN 8                /* arp state: pointer to the pattern's events */
#define A_COUNT 0x1D4              /* the number of events */
#define A_RHYTHM 0x1D8             /* the Rhythm number the pattern was loaded for */
#define PATCH_RHYTHM 0xF1

PATCH_NOINIT static uint8_t events[2 * (2 * MAX_STEPS + 6)];
static uint8_t made_k, made_n, made_r;       /* what events[] holds */

uint32_t euclid_steps(void)
{
    uint8_t v = globals[MPE_G_EUC_STEPS];
    return v == 0 || v > MAX_STEPS ? DEFAULT_STEPS : v;
}

/* 0 = Off: the patch's Rhythm plays. */
uint32_t euclid_pulses(void)
{
    uint8_t v = globals[MPE_G_EUC_PULSES];
    uint32_t n = euclid_steps();
    return v > MAX_STEPS ? 0 : v > n ? n : v;
}

uint32_t euclid_rotate(void)
{
    return globals[MPE_G_EUC_ROTATE] % euclid_steps();
}

/* Step i of n has a note: k of them, as even as whole steps allow. */
static uint32_t pulse_at(uint32_t i, uint32_t k, uint32_t n, uint32_t r)
{
    return ((i + n - r) % n) * k % n < k;
}

static uint8_t *put_rest(uint8_t *p, uint32_t clocks)
{
    while (clocks) {
        uint32_t t = clocks > MAX_SPAN ? MAX_SPAN : clocks;
        *p++ = 0;
        *p++ = (uint8_t)t;
        clocks -= t;
    }
    return p;
}

/* Writes the events of k notes in n steps; returns their number. */
static uint32_t build(uint32_t k, uint32_t n, uint32_t r)
{
    uint8_t *p = events;
    uint32_t i = 0;
    while (i < n && !pulse_at(i, k, n, r))
        i++;
    p = put_rest(p, i * STEP_CLOCKS);            /* the steps before the first note */
    while (i < n) {
        uint32_t empty = 0;
        for (i++; i < n && !pulse_at(i, k, n, r); i++)
            empty++;
        uint32_t rest = STEP_CLOCKS - NOTE_CLOCKS + empty * STEP_CLOCKS;
        uint32_t first = rest > MAX_SPAN - NOTE_CLOCKS ? MAX_SPAN - NOTE_CLOCKS : rest;
        *p++ = VELOCITY;
        *p++ = NOTE_CLOCKS;
        *p++ = 0;                                /* the note's own rest: Gate works on this one */
        *p++ = (uint8_t)first;
        p = put_rest(p, rest - first);
    }
    return (uint32_t)(p - events) / 2;
}

/* Replaces the call of arp_tick (0x08011956). */
void euclid_arp_tick(void)
{
    uint8_t *a = arp_state_ptr;
    uint8_t **pattern = (uint8_t **)(a + A_PATTERN);
    uint32_t k = euclid_pulses();
    if (k) {
        uint32_t n = euclid_steps(), r = euclid_rotate();
        if (*pattern != events || k != made_k || n != made_n || r != made_r) {
            a[A_COUNT] = (uint8_t)build(k, n, r);
            *pattern = events;
            made_k = (uint8_t)k;
            made_n = (uint8_t)n;
            made_r = (uint8_t)r;
            arp_pattern_reset();
        }
        a[A_RHYTHM] = patches[PATCH_RHYTHM];     /* nothing for stock to load */
    } else if (*pattern == events) {
        a[A_RHYTHM] = 0xFF;                      /* Off: stock loads the patch's Rhythm now */
    }
    arp_tick();
}
