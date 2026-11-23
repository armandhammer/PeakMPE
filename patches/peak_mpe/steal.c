/* Voice stealing: with every voice still in its attack, the oldest note goes
 * (v0.39; findings, "Voice allocation and stealing").
 *
 * Stock's voice_candidates (0x08011B70) ranks the voices by what the sound
 * chip reports: of those in release the quietest (voice_alloc's first
 * choice), then of the held ones the quietest, then of those in their attack
 * (envelope state 0) the one with the largest start stamp (voice_state+0x218+4v,
 * a note counter stored at each envelope start), so the newest note. On a pad
 * with a slow attack a new note cut the note played just before it (observed
 * on the synth, 2026-11-15). The user guide, of Unison: when voices run out
 * "the first note played will be cancelled".
 *
 * This hook replaces voice_alloc's voice_candidates call (0x08012392): it
 * runs stock's ranking, then sets the attack candidate (cand_attack) to the
 * voice in state 0 with the smallest start stamp, first in stock's scan
 * order on a tie. The release and held candidates, and the mask candidate the
 * mono modes and Poly2 use, are stock's.
 */

#include "mpe.h"

/* Past the 0x200 bytes peak.h declares for voice_state (as sostenuto.c's flags). */
#define VOICE_START_STAMP(v) (*(volatile uint32_t *)((uintptr_t)voice_state + 0x218 + 4 * (v)))

void steal_candidates(uint32_t start, uint32_t mask, uint32_t unison)
{
    voice_candidates(start, mask, unison);
    if (cand_attack == 0x0F)
        return;
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
