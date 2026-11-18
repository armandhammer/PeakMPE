/* Peak release velocity as a per-voice mod source (docs/peak-features.md
 * step 8).
 *
 * Stock has no release-velocity source (guide, appendix: the matrix sources
 * end at Noise), and note_off ignores the message's velocity (0x0800F4B0
 * reads only the note, observed). The matrix itself runs in the sound chip,
 * which takes each source as a parameter: 0x60 + n, written per voice or to
 * every voice (target 0xA) by voice_mod_write. mod_update sends n = 2 and
 * n = 3 to every voice on every tick, from the part's values at parts+8 and
 * parts+9 (0x080109C0, 0x08010A0E, observed). That n = 2 is ExprPED1 and
 * n = 3 BrthPED2 is inferred: the guide lists them right after ModWheel
 * (0x60) and AftTouch (0x61), and on the Summit 0x62/0x63 are expression and
 * breath. The first hardware check confirms it.
 *
 * Settings > RELEASE VEL > Source (globals +0x4A): Off, ExprPED1 or
 * BrthPED2. While it names a pedal source, that source's broadcast isn't
 * sent, and at each note-off the voices about to be released get the
 * message's velocity in that source, written just before stock's release
 * command (both are direct SPI writes, in that order). Route the source to
 * AmpEnv R (or ModEnv1R, ModEnv2R) in the matrix: the chip takes the release
 * time when the release starts (peak-units.md: a Release change reaches a
 * note only at its note-off, observed), so the note's own lift speed sets
 * its release. A note-on with velocity 0 counts as release velocity 64,
 * the MIDI default. The value stays in the voice until its next note-off,
 * so other destinations of that source would see it during the next note:
 * use the source only for release destinations while this is on.
 *
 * Whether the chip has already applied the new source value to the release
 * time when the release command arrives a few microseconds later is the
 * open question (first hardware check). The pedal or CC that normally drives
 * the source does nothing while this is on; back at Off, the broadcast
 * resumes on the next tick and sets every voice again.
 */

#include "mpe_expr.h"

static uint8_t off_velocity;   /* set by every note-off message before note_off runs */

static uint32_t source_n(void)
{
    uint8_t g = globals[MPE_G_RELVEL];
    return g == 1 ? RELVEL_EXPR_N : g == 2 ? RELVEL_BREATH_N : 0;
}

/* Every channel message, from mpe_channel_filter, before it is routed. */
void relvel_note(const uint8_t *msg)
{
    uint8_t type = msg[0] & 0xF0;
    if (type == 0x80)
        off_velocity = msg[2];
    else if (type == 0x90 && msg[2] == 0)
        off_velocity = 64;
}

/* note_off is about to release note: from mpe_note_release, after it has
 * hidden the voices of other channels (voice_note 0xFF). */
void relvel_release(uint8_t note)
{
    uint32_t n = source_n();
    if (!n)
        return;
    int32_t value = off_velocity == 127 ? 0x7FFF : off_velocity << 8;
    for (uint32_t v = 0; v < MPE_VOICES; v++)
        if (voice_note[v] == note && VOICE_GATE(v))
            voice_mod_write((uint8_t)v, (uint8_t)n, value);
}

/* Replaces mod_update's broadcast ExprPED1 and BrthPED2 writes (0x080109C0,
 * 0x08010A0E). */
void relvel_pedal_write(uint8_t target, uint8_t n, int32_t value)
{
    if (n == source_n())
        return;
    voice_mod_write(target, n, value);
}
