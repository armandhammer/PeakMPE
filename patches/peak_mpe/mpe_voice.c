/* Peak MPE core: channel <-> voice binding (docs/mpe-design.md, "Voice
 * binding"; the Summit patch's mpe_voice.c for 8 voices and one part).
 *
 * voice_channel[v] is the channel voice v plays for, written for every
 * allocation from mpe_alloc_channel in the hook on voice_alloc's
 * voice_glide call (0x08012640): after the voice is chosen, before its
 * osc_pitch calls. A voice allocated outside an MPE note (MPE off, the panel
 * audition button) binds to MPE_NONE. The binding stays through the release.
 *
 * Triggers: the three calls of voice_dispatch (note, vel) set
 * mpe_alloc_channel:
 *   note_on        0x0800F570  the message's channel (mpe_rx_channel),
 *                              remembered per note for the two below
 *   note_off       0x0800F51A  mono/legato's fallback to a held note
 *   arpeggiator    0x08015216  the channel the arpeggiated note came on
 *
 * Channel reuse (as Summit v1.1): in the poly modes a note on a channel takes
 * over the voices still bound to it only while they sound or release, through
 * voice_alloc's forced-voice argument; idle bound voices are unbound and the
 * note goes to the stock allocator, so voices rotate as with MPE off. "Live"
 * is what voice_candidates reads: the gate (voice_state+0x1F4+v), and
 * voice_env_state / voice_env_level from the FPGA (state != 3 or level >
 * 0x200).
 *
 * Release: in the poly modes, note_off's voice_release(note, 0) releases
 * only the voices bound to the message's channel; the other voices with that
 * note are hidden from voice_release for the call. Mono modes release as
 * stock.
 */

#include "mpe.h"

uint8_t voice_channel[MPE_VOICES];
uint8_t mpe_alloc_channel;

static uint8_t note_channel[128];      /* channel of the last note-on per note */
static uint8_t reuse;                  /* voices to take over in this trigger */
static uint8_t env_fresh;              /* voice_env_read just ran: the allocator's read may use it */
static uint8_t env_stale;              /* voices allocated since their last read */
static uint8_t idle_at_read;           /* voices the last read saw idle */

#define MPE_LIVE_LEVEL 0x200

void mpe_voice_init(void)
{
    for (int v = 0; v < MPE_VOICES; v++)
        voice_channel[v] = MPE_NONE;
    for (int n = 0; n < 128; n++)
        note_channel[n] = MPE_NONE;
    mpe_alloc_channel = MPE_NONE;
    mpe_rx_channel = MPE_NONE;
    env_fresh = 0;
    env_stale = 0xFF;
    idle_at_read = 0;
}

void patch_init(void)
{
    mpe_voice_init();
    mpe_settings_init();
    for (int k = 0; k < 2; k++)
        mpe_zones[k].part = MPE_NONE;
}

static int poly(void)
{
    return mpe_patch()[0x22] >= 3;  /* Mode: 0 Mono, 1 MonoLG, 2 Mono2, 3 Poly, 4 Poly2 */
}

static uint8_t gates(void)
{
    uint8_t g = 0;
    for (uint32_t v = 0; v < MPE_VOICES; v++)
        if (VOICE_GATE(v))
            g |= (uint8_t)(1u << v);
    return g;
}

static int live(uint32_t v)
{
    return VOICE_GATE(v) != 0 || voice_env_state[v] != 3 || voice_env_level[v] > MPE_LIVE_LEVEL;
}

/* voice_env_read (all 8 voices), noting which it saw idle. */
static void env_read(uint32_t part)
{
    voice_env_read(part);
    uint8_t idle = 0;
    for (uint32_t v = 0; v < MPE_VOICES; v++)
        if (!live(v))
            idle |= (uint8_t)(1u << v);
    env_stale = 0;
    idle_at_read = idle;
}

static void trigger(uint8_t note, uint8_t velocity, uint8_t ch)
{
    if (!mpe_part_on(0))
        ch = MPE_NONE;
    reuse = 0;
    if (ch != MPE_NONE && poly()) {
        uint8_t bound = 0;
        for (uint32_t v = 0; v < MPE_VOICES; v++)
            if (voice_channel[v] == ch)
                bound |= (uint8_t)(1u << v);
        if (bound) {
            uint8_t sure = (uint8_t)(gates() | (idle_at_read & ~env_stale));
            if (bound & ~sure) {
                env_read(0);
                env_fresh = 1;
            }
            for (uint32_t v = 0; v < MPE_VOICES; v++)
                if (bound & (1u << v)) {
                    if (live(v))
                        reuse |= (uint8_t)(1u << v);
                    else
                        voice_channel[v] = MPE_NONE;
                }
        }
    }
    mpe_alloc_channel = ch;
    voice_dispatch(note, velocity);
    mpe_alloc_channel = MPE_NONE;
    reuse = 0;
    env_fresh = 0;
}

/* Replaces note_on's voice_dispatch call (0x0800F570). The callers pass
 * part 0 in r2, which voice_dispatch ignores. */
void mpe_trigger_note_on(uint8_t note, uint8_t velocity, uint8_t part)
{
    (void)part;
    note_channel[note & 0x7F] = mpe_rx_channel;
    trigger(note, velocity, mpe_rx_channel);
}

/* Replaces the voice_dispatch calls of note_off's mono fallback (0x0800F51A)
 * and of the arpeggiator (0x08015216): the held note's channel. */
void mpe_trigger_held(uint8_t note, uint8_t velocity, uint8_t part)
{
    (void)part;
    trigger(note, velocity, note_channel[note & 0x7F]);
}

/* Replaces voice_trigger's voice_alloc call (0x08012942): forces the next
 * voice to take over, if any. */
void mpe_voice_alloc(uint8_t note, uint8_t velocity, uint8_t part, int32_t voice, int8_t unison)
{
    if (voice < 0 && reuse) {
        uint32_t v = (uint32_t)__builtin_ctz(reuse);
        reuse &= (uint8_t)~(1u << v);
        voice = (int32_t)v;
    }
    voice_alloc(note, velocity, part, voice, unison);
    env_fresh = 0;
}

/* Replaces voice_candidates' voice_env_read call (0x08011B8E). */
void mpe_env_read(uint32_t part)
{
    if (env_fresh) {
        env_fresh = 0;
        return;
    }
    env_read(part);
}

/* Replaces voice_alloc's voice_glide call (0x08012640): binds the chosen
 * voice. */
void mpe_alloc_glide(uint32_t part)
{
    uint32_t v = voice_loop_index & (MPE_VOICES - 1);
    env_stale |= (uint8_t)(1u << v);
    voice_channel[v] = mpe_alloc_channel;
    voice_glide(part);
}

/* Replaces note_off's voice_release calls (0x0800F4E0, 0x0800F4F8,
 * 0x0800F52C). */
void mpe_note_release(uint8_t note, uint8_t part)
{
    uint8_t ch = mpe_rx_channel;
    uint8_t hidden = 0;
    if ((ch != MPE_NONE || mpe_part_on(0)) && poly()) {
        for (uint32_t v = 0; v < MPE_VOICES; v++)
            if (voice_note[v] == note && voice_channel[v] != ch) {
                voice_note[v] = 0xFF;
                hidden |= (uint8_t)(1u << v);
            }
    }
    voice_release(note, part);
    for (uint32_t v = 0; v < MPE_VOICES; v++)
        if (hidden & (1u << v) && voice_note[v] == 0xFF)
            voice_note[v] = note;
}
