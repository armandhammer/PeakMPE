/* Voice stealing (findings, "Voice allocation and stealing").
 *
 * Stock's voice_candidates (0x08011B70) ranks the voices by what the sound
 * chip reports: of those in release the quietest (voice_alloc's first
 * choice), then of the held ones (envelope state 1 or 2) the quietest, then
 * of those in their attack (state 0) the one with the largest start stamp
 * (voice_state+0x218+4v, a note counter stored at each envelope start). Ties
 * go to the first voice in its scan order, which starts at the voice after
 * the last pick. With none of the three voice_alloc takes voice 0. The user
 * guide, of Unison: when voices run out "the first note played will be
 * cancelled".
 *
 * This hook replaces voice_alloc's voice_candidates call (0x08012392): it
 * runs stock's ranking, then changes two of its picks.
 *  - v0.39, attack (cand_attack): the voice with the smallest start stamp,
 *    so the oldest note. Stock took the newest: on a pad with a slow attack
 *    a new note cut the note played just before it (observed, 2026-11-15).
 *  - v0.40, held (cand_held): still the quietest, but among the held voices
 *    at that level first one a pedal holds with its key up (sostenuto.c's
 *    pedal_keys_up), then the oldest. Held voices at full sustain tie on
 *    the synth (A4), so stock's rotation order decided: after a pick in the
 *    middle it cut a newer note than an older one, and under the sustain
 *    pedal it could cut a key still held down.
 *  - v0.41, Settings VOICE STEAL > Keep Low = On (Poly and Poly2): neither
 *    pick is a voice playing the lowest note that sounds (the lowest
 *    voice_note among the gated voices, so a key held down or a note a
 *    pedal holds). Oldest first would otherwise cut a bass note played
 *    before the chord first; the user guide, of Poly2, names the case: the
 *    voice stolen "may be the lowest A". A note in its release is not kept
 *    (its gate is off), and the release candidate stays first. If keeping
 *    the lowest note would leave voice_alloc no candidate at all (Unison 8,
 *    one note), the picks are made as with Keep Low Off.
 * A tie that remains goes to the first in stock's scan order. The release
 * candidate and the mask candidate (mono modes, Poly2's same note) are
 * stock's.
 */

#include "mpe.h"

/* Past the 0x200 bytes peak.h declares for voice_state (as sostenuto.c's flags). */
#define VOICE_START_STAMP(v) (*(volatile uint32_t *)((uintptr_t)voice_state + 0x218 + 4 * (v)))
#define MODE_POLY 3                 /* patch +0x22: 3 Poly, 4 Poly2 */

/* The voices playing the lowest note that sounds, when Keep Low is on. */
static uint8_t kept_voices(void)
{
    if (globals[MPE_G_KEEP_LOW] != 1 || mpe_patch()[0x22] < MODE_POLY)
        return 0;
    uint8_t low = 0xFF;
    for (uint32_t v = 0; v < MPE_VOICES; v++)
        if (VOICE_GATE(v) && voice_note[v] < low)
            low = voice_note[v];
    uint8_t m = 0;
    for (uint32_t v = 0; v < MPE_VOICES; v++)
        if (VOICE_GATE(v) && voice_note[v] == low)
            m |= (uint8_t)(1u << v);
    return m;
}

/* Of the voices in their attack and not kept, the oldest; 0x0F = none. */
static uint8_t pick_attack(uint32_t start, uint8_t kept)
{
    uint32_t oldest = 0xFFFFFFFFu;
    uint8_t pick = 0x0F;
    for (uint32_t i = 0; i < MPE_VOICES; i++) {
        uint32_t v = (start + i) & (MPE_VOICES - 1);
        if (voice_env_state[v] == 0 && !((kept >> v) & 1) && VOICE_START_STAMP(v) < oldest) {
            oldest = VOICE_START_STAMP(v);
            pick = (uint8_t)v;
        }
    }
    return pick;
}

/* Of the held voices not kept, the quietest; on a tie one a pedal holds with
 * its key up, then the oldest; 0x0F = none. */
static uint8_t pick_held(uint32_t start, uint8_t kept)
{
    uint32_t level = 0x10000u;
    for (uint32_t v = 0; v < MPE_VOICES; v++) {
        uint8_t st = voice_env_state[v];
        if ((st == 1 || st == 2) && !((kept >> v) & 1) && voice_env_level[v] < level)
            level = voice_env_level[v];
    }
    uint8_t up = pedal_keys_up();
    int best_up = -1;
    uint32_t oldest = 0xFFFFFFFFu;
    uint8_t pick = 0x0F;
    for (uint32_t i = 0; i < MPE_VOICES; i++) {
        uint32_t v = (start + i) & (MPE_VOICES - 1);
        uint8_t st = voice_env_state[v];
        if ((st != 1 && st != 2) || ((kept >> v) & 1) || voice_env_level[v] != level)
            continue;
        int is_up = (up >> v) & 1;
        uint32_t stamp = VOICE_START_STAMP(v);
        if (is_up > best_up || (is_up == best_up && stamp < oldest)) {
            best_up = is_up;
            oldest = stamp;
            pick = (uint8_t)v;
        }
    }
    return pick;
}

void steal_candidates(uint32_t start, uint32_t mask, uint32_t unison)
{
    voice_candidates(start, mask, unison);
    uint8_t kept = kept_voices();
    uint8_t held = cand_held != 0x0F ? pick_held(start, kept) : 0x0F;
    uint8_t attack = cand_attack != 0x0F ? pick_attack(start, kept) : 0x0F;
    if (kept && held == 0x0F && attack == 0x0F && cand_release == 0x0F) {
        held = cand_held != 0x0F ? pick_held(start, 0) : 0x0F;     /* nothing else to take */
        attack = cand_attack != 0x0F ? pick_attack(start, 0) : 0x0F;
    }
    cand_held = held;
    cand_attack = attack;
}
