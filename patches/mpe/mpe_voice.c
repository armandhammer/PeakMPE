/* MPE core: channel <-> voice binding (docs/mpe-design.md, "Voice binding").
 *
 * voice_channel[v] is the channel voice v plays for. It's written for every
 * allocation, from mpe_alloc_channel, in the hook on voice_alloc's
 * voice_glide call: after the voice is chosen, before its osc_pitch calls.
 * So every voice of a unison stack takes the note's channel, a stolen voice
 * drops its old channel as it takes the new one, and a voice allocated
 * outside an MPE note (MPE off, the keybed) binds to MPE_NONE. The binding
 * stays through the release.
 *
 * Triggers (the three voice_trigger calls) set mpe_alloc_channel:
 *   note_on        the channel of the message (mpe_rx_channel); it's
 *                  remembered per part and note for the two below
 *   note_off       mono/legato's fallback to a held note: that note's channel
 *   arpeggiator    the channel the arpeggiated note was played on
 * In a part with MPE off the channel is always MPE_NONE.
 *
 * Channel reuse (v1.1): in the poly modes, a note on a channel takes over
 * the voices still bound to it only while they sound or release, through
 * voice_alloc's forced-voice argument, one per unison voice; the allocator
 * picks the rest. A sender reusing a channel before the release has ended
 * so never doubles that channel. Bound voices that are idle are unbound and
 * the note goes to the stock allocator, so it rotates through the voices as
 * with MPE off (v1 took idle voices over too: the same voice every time,
 * hardware observation L5).
 *
 * Sounding or releasing ("live") is what the stock allocator itself reads
 * (voice_candidates 0x080155E4): the gate flag voice_state+0x334+v, and
 * voice_env_state / voice_env_level from the FPGA. A voice is live if its
 * gate is held, its envelope state isn't 3 (release or idle), or its level is
 * above 0x200, the level voice_candidates counts as still sounding. The FPGA
 * values are read for the decision (voice_env_read) unless every bound
 * voice is certain without: its gate is held, or the last read saw it idle
 * and it hasn't been allocated since (only an allocation wakes an idle
 * voice). That read stands in for the one the allocator would make next
 * (mpe_env_read). So a note-on waits for the FPGA at most as long as on
 * stock, and a take-over of a held voice costs what it did in v1.
 *
 * The mono modes have one voice and keep the allocator's choice; it follows
 * the channel of the sounding note.
 *
 * Release: in an MPE part's poly modes, note_off's voice_release(note, part)
 * releases only the voices bound to the message's channel (MPE_NONE for the
 * keybed and non-zone channels), not every voice playing that note number.
 * The other voices with that note are hidden from voice_release for the
 * call. Mono modes release as stock.
 */

#include "mpe.h"

uint8_t voice_channel[16];
uint8_t mpe_alloc_channel;

static uint8_t note_channel[2][128];   /* channel of the last note-on per part and note */
static uint16_t reuse;                 /* voices to take over in this trigger */
static uint8_t env_fresh;              /* voice_env_read just ran: the allocator's read may use it */
static uint16_t env_stale;             /* voices allocated since their last read */
static uint16_t idle_at_read;          /* voices the last read saw idle (gate off, state 3, level <= 0x200) */

#define MPE_LIVE_LEVEL 0x200           /* voice_candidates: above this a voice still sounds */

void mpe_voice_init(void)
{
    for (int v = 0; v < 16; v++)
        voice_channel[v] = MPE_NONE;
    for (int p = 0; p < 2; p++)
        for (int n = 0; n < 128; n++)
            note_channel[p][n] = MPE_NONE;
    mpe_alloc_channel = MPE_NONE;
    mpe_rx_channel = MPE_NONE;
    env_fresh = 0;
    env_stale = 0xFFFF;
    idle_at_read = 0;
}

void patch_init(void)
{
    mpe_voice_init();
    mpe_settings_init();
    for (int k = 0; k < 2; k++)
        mpe_zones[k].part = MPE_NONE;
}

static int poly(uint32_t part)
{
    return mpe_patch(part)[0x22] >= 3;  /* Mode: 0 Mono, 1 MonoLG, 2 Mono2, 3 Poly, 4 Poly2 */
}

static uint16_t gates(void)
{
    uint16_t g = 0;
    for (uint32_t v = 0; v < 16; v++)
        if (voice_state[0x334 + v])
            g |= (uint16_t)(1u << v);
    return g;
}

/* Index of voice v in voice_env_state / voice_env_level. */
static uint32_t env_index(uint32_t v)
{
    return multi_mode && v >= 8 ? v + 8 : v;
}

/* Voice v still sounds or releases (see the top of this file), by its gate
 * and the FPGA values voice_env_read left. */
static int live(uint32_t v)
{
    uint32_t i = env_index(v);
    return voice_state[0x334 + v] != 0 || voice_env_state[i] != 3 || voice_env_level[i] > MPE_LIVE_LEVEL;
}

/* voice_env_read, noting which voices it refreshed (both engines in Single,
 * the part's in Multi) and which of them it saw idle. */
static void env_read(uint32_t part)
{
    voice_env_read(part);
    uint16_t mask = !multi_mode ? 0xFFFF : part ? 0xFF00 : 0x00FF, idle = 0;
    for (uint32_t v = 0; v < 16; v++)
        if (mask & (1u << v) && !live(v))
            idle |= (uint16_t)(1u << v);
    env_stale &= (uint16_t)~mask;
    idle_at_read = (uint16_t)((idle_at_read & ~mask) | idle);
}

static void trigger(uint8_t note, uint8_t velocity, uint8_t part, uint8_t ch)
{
    if (part > 1 || !mpe_part_on(part))
        ch = MPE_NONE;
    reuse = 0;
    if (ch != MPE_NONE && poly(part)) {
        uint32_t first = mpe_first_voice(part), n = mpe_voice_count();
        uint16_t bound = 0;
        for (uint32_t v = first; v < first + n; v++)
            if (voice_channel[v] == ch)
                bound |= (uint16_t)(1u << v);
        if (bound) {
            /* A held gate needs no read, nor a voice the last read saw idle
             * that hasn't been allocated since. A voice read as releasing
             * may have ended since: read again. */
            uint16_t sure = (uint16_t)(gates() | (idle_at_read & ~env_stale));
            uint16_t need = (uint16_t)(bound & ~sure);
            if (need) {
                env_read(part);
                env_fresh = 1;
            }
            for (uint32_t v = first; v < first + n; v++)
                if (bound & (1u << v)) {
                    if (live(v))
                        reuse |= (uint16_t)(1u << v);
                    else
                        voice_channel[v] = MPE_NONE;  /* idle: back to the allocator's rotation */
                }
        }
    }
    mpe_alloc_channel = ch;
    voice_trigger(note, velocity, part);
    mpe_alloc_channel = MPE_NONE;
    reuse = 0;
    env_fresh = 0;
}

/* Replaces note_on's voice_trigger call (0x08010B0A). */
void mpe_trigger_note_on(uint8_t note, uint8_t velocity, uint8_t part)
{
    if (part < 2)
        note_channel[part][note & 0x7F] = mpe_rx_channel;
    trigger(note, velocity, part, mpe_rx_channel);
}

/* Replaces the voice_trigger calls of note_off's mono fallback (0x08010A70)
 * and of the arpeggiator (0x0800D0F2): the held note's channel. */
void mpe_trigger_held(uint8_t note, uint8_t velocity, uint8_t part)
{
    trigger(note, velocity, part, part < 2 ? note_channel[part][note & 0x7F] : MPE_NONE);
}

/* Replaces voice_trigger's voice_alloc call (0x080172DE): forces the next
 * voice to take over, if any. */
void mpe_voice_alloc(uint8_t note, uint8_t velocity, uint8_t part, int32_t voice, int8_t unison)
{
    if (voice < 0 && reuse) {
        uint32_t v = (uint32_t)__builtin_ctz(reuse);
        reuse &= (uint16_t)~(1u << v);
        voice = (int32_t)(v - mpe_first_voice(part));
    }
    voice_alloc(note, velocity, part, voice, unison);
    env_fresh = 0;  /* the next unison voice reads the FPGA again, as stock */
}

/* Replaces voice_candidates' voice_env_read call (0x0801562A): when
 * trigger() has just read the FPGA for its reuse decision, the allocator
 * uses that read instead of waiting for another. */
void mpe_env_read(uint32_t part)
{
    if (env_fresh) {
        env_fresh = 0;
        return;
    }
    env_read(part);
}

/* Replaces voice_alloc's voice_glide call (0x08016F5C): binds the chosen
 * voice. */
void mpe_alloc_glide(uint32_t part)
{
    env_stale |= (uint16_t)(1u << (voice_loop_index & 0x0F));
    voice_channel[voice_loop_index & 0x0F] = mpe_alloc_channel;
    voice_glide(part);
}

/* Replaces note_off's voice_release calls (0x08010A08, 0x08010A3A,
 * 0x08010A4E, 0x08010A8E). */
void mpe_note_release(uint8_t note, uint8_t part)
{
    uint8_t ch = mpe_rx_channel;
    uint16_t hidden = 0;
    if (part < 2 && (ch != MPE_NONE || mpe_part_on(part)) && poly(part)) {
        uint32_t first = mpe_first_voice(part), n = mpe_voice_count();
        for (uint32_t v = first; v < first + n; v++)
            if (voice_note[v] == note && voice_channel[v] != ch) {
                voice_note[v] = 0xFF;
                hidden |= (uint16_t)(1u << v);
            }
    }
    voice_release(note, part);
    for (uint32_t v = 0; v < 16; v++)
        if (hidden & (1u << v) && voice_note[v] == 0xFF)
            voice_note[v] = note;
}
