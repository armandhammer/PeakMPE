/* Voice stealing (findings, "Voice allocation and stealing").
 *
 * Stock's voice_candidates (0x08011B70) ranks the voices by what the sound
 * chip reports: of those in release the quietest (voice_alloc's first
 * choice), then of the held ones (envelope state 1 or 2) the quietest, then
 * of those in their attack (state 0) the one with the largest start stamp
 * (voice_state+0x218+4v, a note counter stored at each envelope start). Ties
 * go to the first voice in its scan order, which starts at the voice after
 * the last pick. The user guide, of Unison: when voices run out "the first
 * note played will be cancelled".
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
 * A tie that remains goes to the first in stock's scan order. The release
 * candidate and the mask candidate (mono modes, Poly2) are stock's.
 */

#include "mpe.h"

/* Past the 0x200 bytes peak.h declares for voice_state (as sostenuto.c's flags). */
#define VOICE_START_STAMP(v) (*(volatile uint32_t *)((uintptr_t)voice_state + 0x218 + 4 * (v)))

void steal_candidates(uint32_t start, uint32_t mask, uint32_t unison)
{
    voice_candidates(start, mask, unison);
    if (cand_attack != 0x0F) {
        uint32_t oldest = 0xFFFFFFFFu;
        uint8_t pick = cand_attack;
        for (uint32_t i = 0; i < MPE_VOICES; i++) {
            uint32_t v = (start + i) & (MPE_VOICES - 1);
            if (voice_env_state[v] == 0 && VOICE_START_STAMP(v) < oldest) {
                oldest = VOICE_START_STAMP(v);
                pick = (uint8_t)v;
            }
        }
        cand_attack = pick;
    }
    if (cand_held != 0x0F) {
        uint16_t level = voice_env_level[cand_held & (MPE_VOICES - 1)];   /* the quietest held level */
        uint8_t up = pedal_keys_up();
        int best_up = -1;
        uint32_t oldest = 0xFFFFFFFFu;
        uint8_t pick = cand_held;
        for (uint32_t i = 0; i < MPE_VOICES; i++) {
            uint32_t v = (start + i) & (MPE_VOICES - 1);
            uint8_t st = voice_env_state[v];
            if ((st != 1 && st != 2) || voice_env_level[v] != level)
                continue;
            int is_up = (up >> v) & 1;
            uint32_t stamp = VOICE_START_STAMP(v);
            if (is_up > best_up || (is_up == best_up && stamp < oldest)) {
                best_up = is_up;
                oldest = stamp;
                pick = (uint8_t)v;
            }
        }
        cand_held = pick;
    }
}
