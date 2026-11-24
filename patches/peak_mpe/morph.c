/* Peak patch morph (docs/peak-features.md step 22, docs/peak-motion-morph.md).
 *
 * Settings > MORPH > Morph = ModWheel: the mod wheel (CC 1 on the zone's
 * master channel with MPE on, on the synth's channel without) blends the
 * patch as it stands ("B", wheel at 0) towards the patch as it is stored
 * ("A", wheel at 127). Load a patch, turn some knobs, and the wheel takes the
 * changes back out and in again.
 *
 *   wheel 0     the patch as edited: nothing is touched
 *   wheel 127   every morphed control at its stored value
 *   between     each control at b + (a - b) * wheel / 127
 *
 * A is read from the patch memory, the same bytes stock's "saved val" row
 * shows: saved_value_read 0x080190F8 reads record (bank - 1) * 128 + number
 * (patch_select +4, +5) at 512 bytes per record, byte k of a record being
 * patch offset k (observed; patch load copies the record into the patch).
 * It is read, and B taken from the patch, whenever the wheel leaves 0; back
 * at 0 with every value restored the morph lets go of the patch again.
 *
 * Only continuous controls are morphed (the table below): levels, amounts,
 * times, rates, the filter, FX amounts, and the depths of the mod matrix.
 * Switches, waves, ranges, sync settings, the arp and the matrix's sources
 * and destinations are left as they are in B. A matrix slot whose sources or
 * destination differ between A and B is taken as absent in A: its depth
 * morphs to zero (64), so a routing added by hand fades out and in.
 * Not morphed either: amp Decay and Release while EnvSync has them, and the
 * groups PARAM LOCK holds (they are not the stored patch's on purpose).
 *
 * Values go in through stock's setter behind a received CC (param_put), as
 * motion playback does, at most MAX_PUTS a slot of 16 ms, the rate at which
 * stock applies parameter changes; the redraw request the setter makes is
 * taken back. On the synth a lane writing at this rate cost no modulation
 * ticks (v0.17, LateTicks). The wheel position is followed at most POS_STEP
 * a slot, so a jump of the wheel is a ramp of about 130 ms.
 *
 * Edits while the wheel is up:
 *   - a knob or slider is taken in "blend space": its position is B, and
 *     what stock's overlay draws and tests for Pickup is the blend of it
 *     (morph_knob, from disp_knob_overlay), so the overlay shows the sounding
 *     value and Pickup compares like with like. Stock's caller would then
 *     write the control's own position into the patch (knob_poll applies
 *     the move when the overlay returns 1), so the hook returns 0 and the
 *     blend is written here instead (morph_applied). Such a move therefore
 *     sends no CC to MIDI out. At 127 a control does nothing audible until
 *     the wheel comes down: it is still setting B.
 *   - any other change of a morphed value (a menu, a received CC, a motion
 *     lane) is seen in the next slot and becomes B as it stands.
 * Save stores what sounds, the blend, and from then on that is the patch:
 * the morph starts afresh with stored and edited the same (morph_patch_save),
 * as after any stock Save. A patch load starts afresh too.
 *
 * Compare (hold to hear the stored patch): stock keeps the patch aside, loads
 * the stored one and copies the patch back at the release. While the button
 * is held the morph stands still and keeps what it knows, so the release
 * finds the blend it left and goes on from there. (Taking the load as a new
 * patch, as v0.18 did, made the blend the edit at the release: the edit was
 * lost; emulated, tests/test_peak_morph.py.)
 */

#include "mpe.h"

#define HIRES 0x8000u            /* a 9-bit control: 0-255 over two patch bytes, as motion.c */
#define MATRIX 0x4000u           /* a mod matrix depth: sources at -2, -1, destination at +1 */
#define OFFSET 0x01FFu
#define H(o) ((o) | HIRES)
#define M(k) ((0xFE + 4 * (k)) | MATRIX)

static const uint16_t table[] = {
    0x24, 0x25, 0x27, 0x2B, 0x2C, 0x2D, 0x2E,                       /* UniDetune Spread GlideTime Diverge Drift Noise LPF/HPF */
    H(0x33), 0x35, H(0x36), 0x3B, 0x3C, 0x3D, 0x3E, 0x3F, 0x40,     /* Osc 1: Fine ME2Pitch L2Pitch Shape ME1Shape L1Shape Vsync SawDense DenseDet */
    H(0x48), 0x4A, H(0x4B), 0x50, 0x51, 0x52, 0x53, 0x54, 0x55,     /* Osc 2 */
    H(0x5D), 0x5F, H(0x60), 0x65, 0x66, 0x67, 0x68, 0x69, 0x6A,     /* Osc 3 */
    H(0x6F), H(0x71), H(0x73), H(0x75), H(0x77),                    /* Osc1-3, ring mod, noise level */
    0x79, 0x7A, 0x7B, 0x7C,                                         /* PatchLevel VCA Gain DryLevel WetLevel */
    0x7D, 0x7E, 0x81, 0x82, H(0x83), H(0x85), 0x87, 0x89, 0x8A, 0x8B,  /* filter: drives KeyTrack Resonance Freq and its mod amounts, FltDiverge */
    0x8E,                                                           /* PanPosn */
    0x92, 0x93, 0x94, 0x95, 0x96, 0x98,                             /* amp env: A D S R Velocity HoldTime */
    0x9B, 0x9C, 0x9D, 0x9E, 0x9F, 0xA1,                             /* mod env 1 */
    0xA3, 0xA4, 0xA5, 0xA6, 0xA7, 0xA9,                             /* mod env 2 */
    H(0xAC), 0xB1, 0xB2, H(0xBA), 0xBF, 0xC0,                       /* LFO 1, 2: Rate Slew FadeTime */
    0xC7,                                                           /* Distortion */
    0xCC, 0xCD, 0xCF, 0xD2, 0xD3, 0xD4, 0xD5,                       /* delay: Level Time Width Fback LP HP SlewRate */
    0xD9, 0xDB, 0xDC, 0xDD, 0xDE, 0xDF, 0xE0, 0xE1, 0xE2, 0xE3,     /* reverb: Level Fback damps Size Mod LoPass HiPass PreDelay */
    0xE5, 0xE7, 0xE8, 0xE9, 0xEA, 0xEB,                             /* chorus: Level Rate Depth Feedback LoPass HiPass */
    M(0), M(1), M(2), M(3), M(4), M(5), M(6), M(7),                 /* mod matrix depths, slots 1-16 */
    M(8), M(9), M(10), M(11), M(12), M(13), M(14), M(15),
    M(16), M(17), M(18), M(19), M(20), M(21), M(22), M(23),         /* FX matrix depths */
};
#define N (sizeof table / sizeof table[0])

#define SLOT_TICKS 16            /* stock applies parameter changes every 16 ms */
#define MAX_PUTS 16u             /* setter calls a slot */
#define POS_STEP 16u             /* the position follows the wheel by at most this a slot */
#define AMP_DECAY 0x93
#define AMP_RELEASE 0x95
#define DEPTH_ZERO 64

/* patch_select 0x20002D14: +4 the bank (1-4), +5 the number (0-127) of the
 * patch that is loaded (what saved_value_read uses). */
#define PATCH_BANK (*(volatile uint8_t *)(0x20002D14 + 4))
#define PATCH_NUMBER (*(volatile uint8_t *)(0x20002D14 + 5))

static uint8_t wheel;            /* CC 1 as last received */
static uint8_t pos;              /* the position in effect, following the wheel */
static uint8_t running;          /* a, b and seen are valid for the patch that is loaded */
static uint8_t cursor;           /* where the next slot's pass starts */
static uint8_t differ;           /* controls whose A and B differ, as of the last full pass */
static uint8_t counting;
static uint8_t clean;            /* controls in a row that needed no write: N = the patch is the blend */
static uint32_t slot_tick;
/* All written by start() before they are read. */
PATCH_NOINIT static uint8_t a[N], b[N], seen[N];   /* seen: the patch's value as last read or written here */
PATCH_NOINIT static uint8_t stored[0x200];

static uint32_t value(const uint8_t *p, uint32_t e)
{
    uint32_t o = e & OFFSET;
    return e & HIRES ? (uint32_t)(p[o] * 2 + (p[o + 1] >> 6)) & 0xFF : p[o];
}

static uint32_t blend(uint32_t av, uint32_t bv)
{
    return (bv * (127u - pos) + av * pos + 63u) / 127u;
}

static void put(uint32_t e, uint32_t v)
{
    uint32_t o = e & OFFSET;
    uint8_t flags = ui_msg_state[1];
    if (e & HIRES) {
        if (patches[o] != v >> 1)
            param_put(o, v >> 1);
        if (patches[o + 1] != (v & 1) << 6)
            param_put(o + 1, (v & 1) << 6);
    } else {
        param_put(o, v);
    }
    ui_msg_state[1] = flags;     /* no page redraw for a morphed value: a redraw costs about 5 ms */
}

/* Controls the morph leaves at B for now: amp Decay and Release while EnvSync
 * sets them, and the FX and Voice ranges while PARAM LOCK holds them
 * (paramlock.c). Asked on every pass, so a setting changed during a morph
 * takes effect at once. */
static int held(uint32_t o)
{
    if ((o == AMP_DECAY || o == AMP_RELEASE) && globals[MPE_G_ENVSYNC] >= 1 && globals[MPE_G_ENVSYNC] <= 4)
        return 1;
    if (o >= 0xC7 && o <= 0xEB && globals[MPE_G_LOCK_FX] == 1)
        return 1;
    return o >= 0x22 && o <= 0x2F && globals[MPE_G_LOCK_FX + 2] == 1;
}

/* A's value for one control. */
static uint32_t stored_value(uint32_t e)
{
    uint32_t o = e & OFFSET;
    if (e & MATRIX) {
        if (stored[o - 2] != patches[o - 2] || stored[o - 1] != patches[o - 1] || stored[o + 1] != patches[o + 1])
            return DEPTH_ZERO;   /* another routing in A: this one is not there */
    }
    const struct param_desc *d = &patch_param_desc[o];
    uint32_t v = value(stored, e);
    return v < d->min ? d->min : v > d->max ? d->max : v;   /* a record that was never written */
}

/* Reads A and takes the patch as it stands as B. */
static void start(void)
{
    uint32_t record = (uint32_t)PATCH_NUMBER + ((uint32_t)PATCH_BANK - 1u) * 0x80u;
    ext_flash_read((record & 0x1FF) << 9, stored, sizeof stored);
    for (uint32_t i = 0; i < N; i++) {
        b[i] = seen[i] = (uint8_t)value(patches, table[i]);
        a[i] = (uint8_t)stored_value(table[i]);
    }
    cursor = 0;
    differ = counting = clean = 0;
    running = 1;
}

/* CC 1 on the channel that counts (mpe_channel_filter). */
void morph_cc(uint32_t v)
{
    wheel = (uint8_t)(v & 0x7F);
}

/* A patch load: B is the new patch. (Not called for the load Compare makes,
 * plock_copy: that patch is only listened to, and stock puts the other back.) */
void morph_clear(void)
{
    running = 0;
}

/* The Save button's write of the patch (settings_save_action 0x0801903E):
 * what is stored is now what sounds, so A and B are taken anew. */
void morph_patch_save(uint32_t number, uint32_t bank)
{
    patch_save(number, bank);
    running = 0;
}

uint32_t morph_position(void)
{
    return pos;
}

uint32_t morph_differ(void)
{
    return differ;
}

static int find(uint32_t id)
{
    for (uint32_t i = 0; i < N; i++)
        if ((table[i] & OFFSET) == id)
            return (int)i;
    return -1;
}

/* A control moved (disp_knob_overlay, before stock's overlay): with the wheel
 * up, its positions become the blended values stock is to show and apply.
 * Returns the control's index for morph_applied, or -1. */
int morph_knob(uint32_t id, uint32_t *prev, uint32_t *cur)
{
    if (!running || !pos || compare_held)
        return -1;
    int i = find(id);
    if (i < 0 || held(id))
        return -1;
    *prev = blend(a[i], *prev);
    *cur = blend(a[i], *cur);
    return i;
}

/* Stock's overlay took the move (Pickup allows it): the control's position is
 * B, and the patch gets the blend of it. */
void morph_applied(int i, uint32_t raw, uint32_t blended)
{
    uint32_t e = table[i];
    b[i] = (uint8_t)raw;
    if (value(patches, e) != blended)
        put(e, blended);
    if ((e & OFFSET) < sizeof pickup_state)
        pickup_state[e & OFFSET] = 0;        /* the setter armed it; the hand is on this control */
    seen[i] = (uint8_t)value(patches, e);
}

/* Main-loop pass (mpe_ui_poll). */
void morph_poll(void)
{
    if (compare_held)
        return;                  /* the stored patch is being listened to: nothing to blend, nothing to start */
    uint32_t want = globals[MPE_G_MORPH] == 1 ? wheel : 0;   /* switched off: back to B, then let go */
    if (!running && !want) {
        pos = 0;
        return;
    }
    uint32_t now = mpe_ticks();
    if (now - slot_tick < SLOT_TICKS)
        return;
    slot_tick = now;
    if (!running)
        start();                 /* the wheel left 0, or a patch was loaded with it up */
    if (pos != want) {
        uint32_t next = want;
        if (want > pos + POS_STEP)
            next = pos + POS_STEP;
        else if (want + POS_STEP < pos)
            next = pos - POS_STEP;
        pos = (uint8_t)next;
        clean = 0;
    }
    uint32_t puts = 0;
    for (uint32_t n = 0; n < N; n++) {
        uint32_t i = cursor;
        uint32_t e = table[i];
        uint32_t cur = value(patches, e);
        if (cur != seen[i])
            b[i] = (uint8_t)cur;             /* changed by someone else: that is B now */
        int fixed = held(e & OFFSET);
        uint32_t v = fixed ? b[i] : blend(a[i], b[i]);
        if (v != cur) {
            if (puts >= MAX_PUTS)
                return;                      /* the rest in the next slot, from here */
            put(e, v);
            puts++;
            clean = 0;
            cur = value(patches, e);
        } else if (clean < N) {
            clean++;
        }
        seen[i] = (uint8_t)cur;
        if (a[i] != b[i] && !fixed)
            counting++;
        if (++cursor >= N) {
            cursor = 0;
            differ = counting;
            counting = 0;
        }
    }
    if (!pos && !want && clean >= N)
        running = 0;             /* the patch is B again: edits are stock's own from here */
}
