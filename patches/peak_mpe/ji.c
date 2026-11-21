/* Just intonation, fixed or adaptive (v0.35; docs/peak-features.md, Later).
 *
 * Settings JUST TUNE > Mode: Off (as stock), Fixed or Adapt; Root: C to B.
 * Each voice gets its own pitch offset, added to osc_pitch's result after the
 * MPE bend (4,096 per octave, about 0.3 cents a step), so it works with or
 * without MPE and on top of the patch's tuning table (meant for the equal
 * table, Init's). Static just tunings are stock already (the guide: tuning
 * tables loaded from Scala files through Components); what this adds is
 * choosing the root on the panel, and following the chord.
 *
 * Intervals above the root, 5-limit (cents from equal temperament):
 *   1/1 0, 16/15 +11.7, 9/8 +3.9, 6/5 +15.6, 5/4 -13.7, 4/3 -2.0,
 *   45/32 -9.8, 3/2 +2.0, 8/5 +13.7, 5/3 -15.6, 9/5 +17.6, 15/8 -11.7
 * (9/5 for the minor seventh: a pure minor third above the fifth in a
 * dominant seventh, and a pure fifth above the third in a minor seventh).
 *
 * Fixed: every note is tuned to Root.
 *
 * Adapt: at each note-on the root is chosen from the notes sounding (gated
 * voices; with the arp on, its held keys too): each sounding pitch class is
 * scored by how many of the others are its fifth (3 points), thirds (2), or
 * sixth, seventh or ninth (1); the bass note gets 2 more and the last root 1
 * more, so ties go to the bass. A held note keeps its pitch: the new root's
 * pitch is worked out from a held note (the one the root fits best), and the
 * new notes are tuned to it. A note within 30 ms of the newest one is tuned
 * again with it, so a chord played at once is tuned as one. With nothing held
 * the root sits at its equal-tempered pitch, so a note played alone is equal
 * tempered and the tuning doesn't drift between phrases; while notes are held
 * across chord changes it can drift by a comma (21.5 cents) a time, clamped
 * to a semitone.
 */

#include "mpe_expr.h"

#define JI_WINDOW_TICKS 30
#define ARP_KEYS 0x168
#define PATCH_ARP_ON 0xF5
#define OSC_MIN (-43691)
#define OSC_MAX 43689
#define SEMITONE 341

static const int8_t ratio_units[12] = {0, 40, 13, 53, -47, -7, -33, 7, 47, -53, 60, -40};
static const uint8_t fit[12] = {0, 0, 1, 2, 2, 0, 0, 3, 0, 1, 1, 1};

static uint8_t key[MPE_VOICES];
static uint32_t started[MPE_VOICES];
static int16_t offset[MPE_VOICES];
static uint8_t keyed;            /* voices with a key here */
static uint8_t last_root;        /* + 1; 0 none */
static int16_t last_ref;

uint32_t ji_mode(void)
{
    uint8_t m = globals[MPE_G_JI];
    return m <= 2 ? m : 0;
}

static uint32_t interval(uint32_t note, uint32_t root)
{
    return (note + 12 - root % 12) % 12;
}

static int arp_on(void)
{
    return (patches[PATCH_ARP_ON] & 1) && arp_state_ptr;
}

/* v: the voice starting now (its gate isn't set yet at voice_alloc's call). */
static void adapt(uint32_t v)
{
    uint32_t now = mpe_ticks();
    uint32_t pcs = 0, bass = 0xFF;
    uint8_t sounding = 0, recent = 0;
    for (uint32_t u = 0; u < MPE_VOICES; u++) {
        uint8_t bit = (uint8_t)(1u << u);
        if (!(keyed & bit) || (!VOICE_GATE(u) && u != v))
            continue;
        sounding |= bit;
        if (now - started[u] < JI_WINDOW_TICKS)
            recent |= bit;
        pcs |= 1u << (key[u] % 12);
        if (key[u] < bass)
            bass = key[u];
    }
    if (arp_on()) {
        const uint8_t *held = arp_state_ptr + ARP_KEYS;
        for (uint32_t n = 0; n < 128; n++)
            if (held[n >> 3] & (1u << (n & 7))) {
                pcs |= 1u << (n % 12);
                if (n < bass)
                    bass = n;
            }
    }
    if (!pcs)
        return;
    uint32_t root = 0;
    int32_t best = -1;
    for (uint32_t r = 0; r < 12; r++) {
        if (!(pcs & (1u << r)))
            continue;
        int32_t score = 0;
        for (uint32_t q = 0; q < 12; q++)
            if (q != r && (pcs & (1u << q)))
                score += fit[(q + 12 - r) % 12];
        if (bass != 0xFF && bass % 12 == r)
            score += 2;
        if (last_root == r + 1)
            score += 1;
        if (score > best) {
            best = score;
            root = r;
        }
    }
    int32_t ref = 0;
    int32_t anchor_fit = -1;
    uint8_t settled = (uint8_t)(sounding & ~recent);
    for (uint32_t u = 0; u < MPE_VOICES; u++) {
        if (!(settled & (1u << u)))
            continue;
        uint32_t iv = interval(key[u], root);
        int32_t f = iv == 0 ? 4 : fit[iv];
        if (f > anchor_fit) {
            anchor_fit = f;
            ref = offset[u] - ratio_units[iv];
        }
    }
    if (anchor_fit < 0 && arp_on() && last_root == root + 1)
        ref = last_ref;              /* the arp on the same chord: no settled voice, keep its tuning */
    ref = ref < -SEMITONE ? -SEMITONE : ref > SEMITONE ? SEMITONE : ref;
    for (uint32_t u = 0; u < MPE_VOICES; u++)
        if (recent & (1u << u))
            offset[u] = (int16_t)(ref + ratio_units[interval(key[u], root)]);
    last_root = (uint8_t)(root + 1);
    last_ref = (int16_t)ref;
}

static void begin(uint32_t v, uint8_t note)
{
    key[v] = note;
    started[v] = mpe_ticks();
    keyed |= (uint8_t)(1u << v);
    if (ji_mode() == 1) {
        uint8_t r = globals[MPE_G_JI + 1];
        offset[v] = ratio_units[interval(note, r < 12 ? r : 0)];
    } else {
        offset[v] = 0;
        adapt(v);
    }
}

/* Once per voice (mpe_expr.c, before Osc 1's osc_pitch): note_on from
 * voice_alloc; otherwise every tick, where a gated voice whose note changed
 * (a mono or legato voice moving on) starts again. voice_note 0xFF is a
 * voice hidden from stock's note-off match (mpe_voice.c): no change. */
void ji_voice(uint32_t v, int note_on)
{
    if (!ji_mode())
        return;
    uint8_t n = voice_note[v];
    if (n == 0xFF)
        return;
    if (note_on || (VOICE_GATE(v) && (!(keyed & (1u << v)) || n != key[v])))
        begin(v, n);
}

void ji_add(uint8_t *osc, uint32_t v)
{
    if (!ji_mode() || !(keyed & (1u << v)))
        return;
    int32_t *out = OSC_RESULT(osc, v);
    int32_t pitch = *out + offset[v];
    *out = pitch < OSC_MIN ? OSC_MIN : pitch > OSC_MAX ? OSC_MAX : pitch;
}

/* For tests and the MIDI monitor: voice v's offset in osc units. */
int32_t ji_offset(uint32_t v)
{
    return ji_mode() && (keyed & (1u << v)) ? offset[v] : 0;
}
