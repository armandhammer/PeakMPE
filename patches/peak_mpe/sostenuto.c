/* Peak sostenuto pedal: let go only of keys that are up (v0.38).
 *
 * Stock (findings, "Voice allocation"): sostenuto_pedal 0x08011FEC marks every
 * gated voice sostenuto-held at pedal down (sostenuto_down 0x08011F6C,
 * voice_state+0x244+v) and at pedal up (sostenuto_up 0x08011F90) releases
 * every marked voice that the sustain pedal doesn't hold (+0x23C+v), without
 * looking at the key. A key's note-off under the pedal does nothing to the
 * voice (voice_release_part 0x08011A80 skips it), so the MCU keeps no record
 * of which held keys are up: a key held down through the pedal's release
 * stopped sounding (emulated, 2026-11-15).
 *
 * The patch keeps that record. key_up has a bit per voice:
 *  - at pedal down, a marked voice's key is up only if the sustain pedal
 *    holds it (pedal-held is set only for a key let go under sustain);
 *  - a note-off (mpe_note_release, all of note_off's voice_release calls)
 *    sets the bit of each marked, gated voice it would release: in the poly
 *    modes the voices with that note (voice_note, other MPE channels'
 *    voices hidden as 0xFF during the call), in the mono modes all of them
 *    (they release only when no key is held at all);
 *  - at pedal up, a marked voice whose key is still down loses its mark
 *    first, so stock's sostenuto_up skips it; its own note-off releases it
 *    later, as stock does any key (or hands it to the sustain pedal).
 * voice_alloc (0x080122B0) clears both pedal flags of the voice it starts a
 * note on, just before its gate is set, so a stale bit only matters on a
 * marked voice, and every pedal down sets all bits afresh.
 */

#include "mpe.h"

#define PEDAL_HELD(v) (*(volatile uint8_t *)((uintptr_t)voice_state + 0x23C + (v)))
#define SOSTENUTO_HELD(v) (*(volatile uint8_t *)((uintptr_t)voice_state + 0x244 + (v)))

static uint8_t key_up;

/* Replaces sostenuto_pedal's call of sostenuto_down (0x08012010). */
void sost_down(void)
{
    sostenuto_down();
    uint8_t up = 0;
    for (uint32_t v = 0; v < MPE_VOICES; v++)
        if (PEDAL_HELD(v))
            up |= (uint8_t)(1u << v);
    key_up = up;
}

/* Replaces sostenuto_pedal's call of sostenuto_up (0x08012016). */
void sost_up(void)
{
    for (uint32_t v = 0; v < MPE_VOICES; v++)
        if (SOSTENUTO_HELD(v) && VOICE_GATE(v) && !(key_up & (1u << v)))
            SOSTENUTO_HELD(v) = 0;          /* key still down: keeps sounding */
    sostenuto_up();
}

/* From mpe_note_release, after voice_release(note, part), with the other
 * channels' voices still hidden. poly: the patch's voice mode is a poly one. */
void sost_note_off(uint8_t note, int poly)
{
    for (uint32_t v = 0; v < MPE_VOICES; v++)
        if (SOSTENUTO_HELD(v) && VOICE_GATE(v) && (!poly || voice_note[v] == note))
            key_up |= (uint8_t)(1u << v);
}
