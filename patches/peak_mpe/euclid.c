/* Peak Euclidean arp rhythms and ratchets (docs/peak-features.md step 17).
 *
 * Settings > ARP EUCLID (globals +0x45 .. +0x47): Pulses (Off, 1-32), Steps
 * (1-32) and Rotate (0-31); a byte out of range, as one never written may
 * be, reads as Off, 16 and 0. With Pulses on, the arpeggiator plays that many
 * notes spread as evenly as possible over Steps steps (5 in 8: x.x.xx.x) in
 * place of the patch's Rhythm; Rotate starts the pattern that many steps
 * later. Everything else stays stock's: SyncRate sets how long a step is,
 * and Type, Octaves, Gate, Swing, Latch and KeySync work as before.
 *
 * Stock's rhythms (findings, "Arp rhythm patterns"): the arp state
 * (arp_state_ptr) holds a pointer to the pattern's events at +8 and their
 * number at +0x1D4; an event is two bytes, the velocity the step is played
 * at (0 = a rest; the key's own velocity is not used) and a length in arp
 * clocks, six clocks to a step, and a note event
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
 * Ratchets (Settings > ARP RATCHET, globals +0x48 and +0x49): Ratchet (Off,
 * x2, x3) plays a note two or three times within its step, Every (1-8) says
 * which notes: every one, every second one, and so on (the last of each
 * group). A ratchet is written into the pattern as that many short note
 * events. Stock moves on to the next note of the chord at every note event
 * (arp_step_select, called at 0x0801574E), so the repeats carry bit 7 in
 * their velocity: the hook on that call takes the bit off and puts the
 * arp's choice (played-order index, last note, direction, octave, random
 * seed) back to what it was before the note's first sounding, and stock
 * then picks the same note again. With Pulses Off a ratchet plays over a
 * plain rhythm of one note a step, not over the patch's Rhythm: stock's
 * own patterns are not rewritten. In the poly modes every repeat takes the
 * next voice, in the mono modes it retriggers the one voice (emulated).
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
#define VELOCITY 100               /* stock's usual value; the arp does not use the key's velocity */
#define DEFAULT_STEPS 16

#define A_PATTERN 8                /* arp state: pointer to the pattern's events */
#define A_COUNT 0x1D4              /* the number of events */
#define A_RHYTHM 0x1D8             /* the Rhythm number the pattern was loaded for */
#define A_VELOCITY 0x1D9           /* the velocity of the note event just read */
#define PATCH_RHYTHM 0xF1
#define REPEAT 0x80                /* in an event's velocity: a ratchet's repeat of the note before */
#define MAX_RATCHET 3
#define MAX_EVERY 8

PATCH_NOINIT static uint8_t events[2 * (2 * MAX_RATCHET * MAX_STEPS + 6)];
static uint8_t made[5];                      /* what events[] holds: pulses, steps, rotate, ratchet, every */

/* What stock's choice of the next note reads and writes (arp state offsets),
 * as it was before the last note that was not a repeat. */
static const uint16_t choice_at[] = {0x1CC, 0x1DB, 0x1DC, 0x1DD, 0x1E0};
static uint8_t choice[sizeof choice_at / sizeof choice_at[0]];
static uint32_t choice_seed;

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
    uint8_t v = globals[MPE_G_EUC_ROTATE];
    return v >= MAX_STEPS ? 0 : v % euclid_steps();   /* a byte never written (255) is 0 */
}

/* How often a ratcheted note sounds: 1 = no ratchet. */
uint32_t euclid_ratchet(void)
{
    uint8_t v = globals[MPE_G_EUC_RATCHET];
    return v >= MAX_RATCHET ? 1 : v + 1u;
}

/* Which notes ratchet: every one, every second one, ... */
uint32_t euclid_every(void)
{
    uint8_t v = globals[MPE_G_EUC_EVERY];
    return v == 0 || v > MAX_EVERY ? 1 : v;
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

/* Writes the events of k notes in n steps, every `every`th of them sounding
 * `ratchet` times; returns their number. */
static uint32_t build(uint32_t k, uint32_t n, uint32_t r, uint32_t ratchet, uint32_t every)
{
    uint8_t *p = events;
    uint32_t i = 0, pulse = 0;
    while (i < n && !pulse_at(i, k, n, r))
        i++;
    p = put_rest(p, i * STEP_CLOCKS);            /* the steps before the first note */
    while (i < n) {
        uint32_t empty = 0;
        for (i++; i < n && !pulse_at(i, k, n, r); i++)
            empty++;
        uint32_t times = ++pulse % every == 0 ? ratchet : 1;
        uint32_t span = STEP_CLOCKS / times;     /* 6, 3 or 2 clocks for each sounding */
        uint32_t note = (span + 1) / 2;          /* 3, 2 or 1 of them the note */
        for (uint32_t t = 0; t < times; t++) {
            uint32_t rest = span - note + (t + 1 == times ? empty * STEP_CLOCKS : 0);
            uint32_t first = rest > MAX_SPAN - note ? MAX_SPAN - note : rest;
            *p++ = (uint8_t)(t ? VELOCITY | REPEAT : VELOCITY);
            *p++ = (uint8_t)note;
            *p++ = 0;                            /* the note's own rest: Gate works on this one */
            *p++ = (uint8_t)first;
            p = put_rest(p, rest - first);
        }
    }
    return (uint32_t)(p - events) / 2;
}

/* Replaces the call of arp_tick (0x08011956). */
void euclid_arp_tick(void)
{
    uint8_t *a = arp_state_ptr;
    uint8_t **pattern = (uint8_t **)(a + A_PATTERN);
    uint32_t k = euclid_pulses(), ratchet = euclid_ratchet();
    if (k || ratchet > 1) {
        uint32_t every = euclid_every();
        uint32_t n = k ? euclid_steps() : every; /* no Euclid rhythm: a note on every step */
        uint32_t r = k ? euclid_rotate() : 0;
        if (!k)
            k = n;
        const uint8_t want[5] = {(uint8_t)k, (uint8_t)n, (uint8_t)r, (uint8_t)ratchet, (uint8_t)every};
        int same = *pattern == events;
        for (uint32_t i = 0; i < sizeof want; i++)
            same &= want[i] == made[i];
        if (!same) {
            a[A_COUNT] = (uint8_t)build(k, n, r, ratchet, every);
            *pattern = events;
            for (uint32_t i = 0; i < sizeof want; i++)
                made[i] = want[i];
            arp_pattern_reset();
        }
        a[A_RHYTHM] = patches[PATCH_RHYTHM];     /* nothing for stock to load */
    } else if (*pattern == events) {
        a[A_RHYTHM] = 0xFF;                      /* Off: stock loads the patch's Rhythm now */
    }
    arp_tick();
}

/* Replaces arp_tick's call of arp_step_select (0x0801574E), made for every
 * note event while the arp is on. */
void euclid_step_select(void)
{
    uint8_t *a = arp_state_ptr;
    if (a[A_VELOCITY] & REPEAT) {                /* a ratchet: the same note again */
        a[A_VELOCITY] &= (uint8_t)~REPEAT;
        for (uint32_t i = 0; i < sizeof choice; i++)
            a[choice_at[i]] = choice[i];
        arp_random_seed = choice_seed;
    } else {
        for (uint32_t i = 0; i < sizeof choice; i++)
            choice[i] = a[choice_at[i]];
        choice_seed = arp_random_seed;
    }
    arp_step_select();
}
