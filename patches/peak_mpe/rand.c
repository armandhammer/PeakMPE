/* Peak section randomiser (v0.26, band-pass and high-pass ranges v0.27; docs/peak-features.md, "Later": patch
 * randomiser by section).
 *
 * Settings > RANDOMISE: Section (Osc 1, Osc 2, Osc 3, Mixer, Filter, Amp Env,
 * Mod Env1, Mod Env2, LFO 1, LFO 2, FX, All), Amount (10-100 %, 50 % until
 * changed), Roll (turned up once: one roll). The guide has no randomise
 * function. A roll changes only the chosen section's controls, in the edit
 * buffer, through stock's setter (param_put, as section copy and undo), so
 * the sound chip, the screen and Pickup follow. Nothing is saved: the patch
 * slot changes only on Save. The patch as it was goes into the undo step
 * first, so Mod + Page left takes the roll back (one level, section.c).
 *
 * Per control (the table below):
 *   - a continuous control gets a fresh value r inside its safe range, and
 *     moves from where it is towards r by Amount: v + (r - v) * Amount. At
 *     100 % it is r; at 10 % a nudge.
 *   - a switch (wave, range, filter shape and slope, LFO wave, FX types) is
 *     picked afresh from its useful values with a chance of Amount.
 *   - the filter's cutoff, and for band-pass its resonance and amp envelope
 *     depth, take ranges of the shape (below); when the Shape changes they
 *     are rolled at 100 %: a high-pass keeping a low-pass cutoff goes thin.
 *
 * Safe ranges (raw values; the screen's units from format_value, the times
 * from docs/peak-units.md): the attack of the amp envelope at most 72 (a
 * full ramp of about 0.8 s), its release at most 96 (t20 about 1.8 s);
 * resonance at most 96 (127 self-oscillates, which the guide warns can
 * clip); drives, distortion, FX levels and feedbacks well below the top;
 * oscillator Fine within +-10 cents; Osc 2 and 3 Coarse only 0, +-5, +7 or
 * +-12 semitones (raw 74, 182, 203, 0, 255: the values the screen shows as
 * whole semitones), Osc 1 Coarse not touched, so the patch stays in its key;
 * WaveMore only the 60 factory tables (4-63: 64-73 are the user slots,
 * "*User 1" to "*User 10", which may be empty).
 * Not touched: pitch modulation depths, FixedNote, bend ranges, envelope
 * Repeats and triggers, LFO sync, phase and fade modes, the mod matrix, the
 * arp, the voice settings, VCA Gain and Patch Level. The amp Decay and
 * Release while EnvSync has them (as the morph).
 *
 * Checks (the processor never hears the audio, so these are rules):
 *   Mixer   the loudest oscillator at least 100 of 255 (or noise at least
 *           160), and the five levels together at most 420 (the guide: all
 *           sources at maximum can clip)
 *   Filter  low-pass cutoff at least 90 (fc about 200 Hz at key track 0,
 *           peak-units), or at least 40 with the amp envelope opening it
 *           (AenvFiltFreq at least +16); band-pass cutoff 64-150 with
 *           resonance at least 40 and AenvFiltFreq within -16..+16;
 *           high-pass cutoff at most 110; and resonance above 80 only with
 *           post drive at most 24. Band-pass and high-pass from the rig
 *           (v0.27, findings "Value scales for the randomiser"): at C4
 *           band-pass is loudest near cutoff 96 and was 20-30 dB down at
 *           v0.26's 100-220; resonance 0 to 96 lifts a saw through it
 *           about 21 dB; high-pass at 150 was 10 (saw) to 28 dB (sine)
 *           under its open level, at 110 5 to 10 dB.
 *   Amp     attack at most 80, and sustain at least 48 or decay at least 60
 *           (a note with no sustain still sounds for a while)
 *   FX      delay, reverb and chorus levels together at most 170,
 *           distortion at most 64, delay feedback at most 100
 * A roll at 100 % always ends inside the checks. Below 100 % a check is only
 * enforced when the patch passed it before the roll, so a nudge never
 * repairs (and so changes) what the user set on purpose.
 * The values are computed in a copy of the patch, checked there, and only
 * then written, the changed ones only.
 *
 * Random numbers: xorshift32, stirred with the tick count at each roll (the
 * moment of the press is the entropy).
 */

#include "mpe.h"

#define H 0x8000u        /* a 9-bit control: 0-255 over two patch bytes */
#define PICK 0x4000u     /* a switch: a value lo..hi */
#define LIST 0x2000u     /* a switch: lists[lo], hi values */
#define OFF 0x01FFu

#define WORK 0xF0        /* the copy covers offsets 0-0xEF */

struct entry { uint16_t e; uint8_t lo, hi; };

enum { L_RANGE1 = 0, L_RANGE = 4, L_COARSE = 10, L_SHAPE = 18 };
static const uint8_t lists[] = {
    63, 64, 64, 65,                       /* Osc 1 Range: 16', 8', 8', 4' */
    63, 64, 64, 65, 65, 66,               /* Osc 2, 3 Range: 16' to 2' */
    128, 128, 128, 203, 74, 255, 0, 182,  /* Coarse: 0, 0, 0, +7, -5, +12, -12, +5 semitones */
    0, 0, 0, 1, 2,                        /* filter Shape: LOW, LOW, LOW, BAND, HIGH */
};

#define OSC(b) \
    {((b) + 0x3) | H, 118, 138}, {((b) + 0x8) | PICK, 0, 4}, {((b) + 0x9) | PICK, 4, 63}, \
    {(b) + 0xB, 16, 112}, {(b) + 0xC, 40, 88}, {(b) + 0xD, 40, 88}, \
    {(b) + 0xE, 0, 64}, {(b) + 0xF, 0, 127}, {(b) + 0x10, 0, 127}
#define MODENV(b) \
    {(b) + 0, 0, 100}, {(b) + 1, 0, 110}, {(b) + 2, 0, 127}, {(b) + 3, 0, 110}, \
    {(b) + 4, 24, 104}, {(b) + 6, 0, 40}
#define LFO(b) \
    {(b) | H, 40, 220}, {((b) + 3) | PICK, 0, 3}, {(b) + 5, 0, 80}, {(b) + 6, 0, 80}

#define AMP_ATTACK 0x92
#define AMP_DECAY 0x93
#define AMP_SUSTAIN 0x94
#define AMP_RELEASE 0x95
#define F_POSTDRV 0x7E
#define F_SHAPE 0x80
#define F_RES 0x82
#define F_FREQ 0x83
#define F_AENV 0x89
#define X_DIST 0xC7
#define X_DELAY 0xCC
#define X_DELFB 0xD2
#define X_REVERB 0xD9
#define X_CHORUS 0xE5

static const struct entry table[] = {
    /* Osc 1: Range, Fine, Wave, WaveMore, Shape, ME1Shape, L1Shape, Vsync, SawDense, DenseDet */
    {0x30 | LIST, L_RANGE1, 4}, OSC(0x30),
    /* Osc 2, Osc 3: the same and Coarse */
    {0x45 | LIST, L_RANGE, 6}, {0x46 | H | LIST, L_COARSE, 8}, OSC(0x45),
    {0x5A | LIST, L_RANGE, 6}, {0x5B | H | LIST, L_COARSE, 8}, OSC(0x5A),
    /* Mixer: Osc 1-3, ring mod, noise */
    {0x6F | H, 0, 255}, {0x71 | H, 0, 255}, {0x73 | H, 0, 255}, {0x75 | H, 0, 160}, {0x77 | H, 0, 120},
    /* Filter: drives, slope, shape, key track, resonance, freq, LFO 1, Osc 3, amp env, mod env 1, diverge */
    {0x7D, 0, 64}, {F_POSTDRV, 0, 48}, {0x7F | PICK, 0, 1}, {F_SHAPE | LIST, L_SHAPE, 5},
    {0x81, 32, 127}, {F_RES, 0, 96}, {F_FREQ | H, 90, 255}, {0x85 | H, 88, 168},
    {0x87, 0, 40}, {F_AENV, 40, 110}, {0x8A, 40, 110}, {0x8B, 0, 64},
    /* Amp env: attack, decay, sustain, release, velocity */
    {AMP_ATTACK, 0, 72}, {AMP_DECAY, 20, 110}, {AMP_SUSTAIN, 0, 127}, {AMP_RELEASE, 10, 96}, {0x96, 64, 104},
    MODENV(0x9B),
    MODENV(0xA3),
    LFO(0xAC),
    LFO(0xBA),
    /* FX: distortion; delay level, time, width, feedback; reverb level, type, feedback, size;
     * chorus level, type, rate, depth, feedback, mode */
    {X_DIST, 0, 48}, {X_DELAY, 0, 80}, {0xCD, 20, 127}, {0xCF, 64, 127}, {X_DELFB, 0, 90},
    {X_REVERB, 0, 80}, {0xDA | PICK, 0, 2}, {0xDB, 40, 110}, {0xDE, 40, 127},
    {X_CHORUS, 0, 80}, {0xE6 | PICK, 0, 2}, {0xE7, 0, 90}, {0xE8, 20, 127}, {0xE9, 40, 88}, {0xEC | PICK, 0, 2},
};
#define ENTRIES (sizeof table / sizeof table[0])

enum { S_OSC1, S_OSC2, S_OSC3, S_MIXER, S_FILTER, S_AMP, S_ENV1, S_ENV2, S_LFO1, S_LFO2, S_FX, S_ALL, SECTIONS };
static const struct { const char *name; uint8_t first, n; } sections[SECTIONS] = {
    {"Osc 1", 0, 10}, {"Osc 2", 10, 11}, {"Osc 3", 21, 11}, {"Mixer", 32, 5}, {"Filter", 37, 12},
    {"Amp Env", 49, 5}, {"Mod Env1", 54, 6}, {"Mod Env2", 60, 6}, {"LFO 1", 66, 4}, {"LFO 2", 70, 4},
    {"FX", 74, 15}, {"All", 0, ENTRIES},
};
_Static_assert(ENTRIES == 89, "the sections' first and n follow the table");

static uint8_t section;          /* zero-initialised: Osc 1 */
static uint8_t amount;           /* 1-10 = 10-100 %; 0 = not set yet, 50 % */
uint32_t rand_seed;              /* tests read and set it */
static uint8_t work[WORK];
static char msg_row[21];

uint32_t rand_amount(void)
{
    return amount ? amount : 5;
}

const char *rand_section_name(void)
{
    return sections[section < SECTIONS ? section : 0].name;
}

static uint32_t rnd(uint32_t n)
{
    rand_seed ^= rand_seed << 13;
    rand_seed ^= rand_seed >> 17;
    rand_seed ^= rand_seed << 5;
    return n ? rand_seed % n : 0;
}

static uint32_t get(const uint8_t *p, uint32_t e)
{
    uint32_t o = e & OFF;
    return e & H ? ((uint32_t)p[o] * 2 + (p[o + 1] >> 6)) & 0xFF : p[o];
}

static void set(uint8_t *p, uint32_t e, uint32_t v)
{
    uint32_t o = e & OFF;
    if (e & H) {
        p[o] = (uint8_t)(v >> 1);
        p[o + 1] = (uint8_t)((v & 1) << 6);
    } else {
        p[o] = (uint8_t)v;
    }
}

static int envsync_owns(uint32_t o)
{
    return (o == AMP_DECAY || o == AMP_RELEASE) && globals[MPE_G_ENVSYNC] >= 1 && globals[MPE_G_ENVSYNC] <= 4;
}

/* The cutoff range of a filter shape (0 LOW, 1 BAND, 2 HIGH). */
static void cutoff_range(uint32_t shape, uint32_t *lo, uint32_t *hi)
{
    *lo = shape == 2 ? 0 : shape == 1 ? 64 : 90;
    *hi = shape == 2 ? 110 : shape == 1 ? 150 : 255;
}

#define BP_RES_LO 40
#define BP_AENV_LO (64 - 16)
#define BP_AENV_HI (64 + 16)

/* Controls whose range follows the filter shape: 1 and the range, or 0. */
static int shape_range(uint32_t o, uint32_t shape, uint32_t *lo, uint32_t *hi)
{
    if (o == F_FREQ) {
        cutoff_range(shape, lo, hi);
        return 1;
    }
    if (shape != 1)
        return 0;
    if (o == F_RES) {
        *lo = BP_RES_LO;
        *hi = 96;
        return 1;
    }
    if (o == F_AENV) {
        *lo = BP_AENV_LO;
        *hi = BP_AENV_HI;
        return 1;
    }
    return 0;
}

static uint32_t towards(uint32_t v, uint32_t r, uint32_t a)
{
    return (uint32_t)((int32_t)v + ((int32_t)r - (int32_t)v) * (int32_t)a / 10);
}

static void roll_entry(const struct entry *t, uint32_t a, int shape_changed)
{
    uint32_t e = t->e, o = e & OFF;
    if (envsync_owns(o))
        return;
    if (e & (PICK | LIST)) {
        if (rnd(10) >= a)
            return;
        uint32_t v = e & LIST ? lists[t->lo + rnd(t->hi)] : t->lo + rnd((uint32_t)t->hi - t->lo + 1u);
        set(work, e, v);
        return;
    }
    uint32_t lo = t->lo, hi = t->hi;
    if (shape_range(o, work[F_SHAPE], &lo, &hi) && shape_changed)
        a = 10;
    set(work, e, towards(get(work, e), lo + rnd(hi - lo + 1u), a));
}

/* --- Checks: 1 = passes ---------------------------------------------------- */

static uint32_t level(const uint8_t *p, uint32_t o)
{
    return get(p, o | H);
}

static int mixer_ok(const uint8_t *p)
{
    uint32_t o1 = level(p, 0x6F), o2 = level(p, 0x71), o3 = level(p, 0x73);
    uint32_t top = o1 > o2 ? o1 : o2;
    top = top > o3 ? top : o3;
    uint32_t sum = o1 + o2 + o3 + level(p, 0x75) + level(p, 0x77);
    return (top >= 100 || level(p, 0x77) >= 160) && sum <= 420;
}

static void mixer_fix(uint8_t *p)
{
    static const uint16_t lv[5] = {0x6F, 0x71, 0x73, 0x75, 0x77};
    uint32_t best = 0;
    for (uint32_t k = 1; k < 3; k++)
        if (level(p, lv[k]) > level(p, lv[best]))
            best = k;
    if (level(p, lv[best]) < 100)
        set(p, lv[best] | H, 128 + rnd(128));
    uint32_t sum = 0;
    for (uint32_t k = 0; k < 5; k++)
        sum += level(p, lv[k]);
    if (sum > 420)
        for (uint32_t k = 0; k < 5; k++)
            set(p, lv[k] | H, level(p, lv[k]) * 420 / sum);
}

static int filter_ok(const uint8_t *p)
{
    uint32_t c = get(p, F_FREQ | H), lo, hi;
    if (p[F_RES] > 80 && p[F_POSTDRV] > 24)
        return 0;
    if (p[F_SHAPE] == 0)
        return c >= 90 || (c >= 40 && p[F_AENV] >= 64 + 16);
    if (p[F_SHAPE] == 1 && (p[F_RES] < BP_RES_LO || p[F_AENV] < BP_AENV_LO || p[F_AENV] > BP_AENV_HI))
        return 0;
    cutoff_range(p[F_SHAPE], &lo, &hi);
    return c >= lo && c <= hi;
}

static void filter_fix(uint8_t *p)
{
    uint32_t lo, hi;
    if (p[F_SHAPE] == 1) {
        if (p[F_RES] < BP_RES_LO)
            p[F_RES] = (uint8_t)(BP_RES_LO + rnd(41));
        if (p[F_AENV] < BP_AENV_LO || p[F_AENV] > BP_AENV_HI)
            p[F_AENV] = (uint8_t)(BP_AENV_LO + rnd(BP_AENV_HI - BP_AENV_LO + 1));
    }
    if (p[F_RES] > 80 && p[F_POSTDRV] > 24)
        p[F_POSTDRV] = 24;
    if (!filter_ok(p)) {
        cutoff_range(p[F_SHAPE] > 2 ? 0 : p[F_SHAPE], &lo, &hi);
        set(p, F_FREQ | H, lo + rnd(hi - lo + 1u));
    }
}

static int amp_ok(const uint8_t *p)
{
    return p[AMP_ATTACK] <= 80 && (p[AMP_SUSTAIN] >= 48 || p[AMP_DECAY] >= 60);
}

static void amp_fix(uint8_t *p)
{
    if (p[AMP_ATTACK] > 80)
        p[AMP_ATTACK] = 72;
    if (p[AMP_SUSTAIN] < 48 && p[AMP_DECAY] < 60) {
        if (envsync_owns(AMP_DECAY))
            p[AMP_SUSTAIN] = (uint8_t)(48 + rnd(80));
        else
            p[AMP_DECAY] = (uint8_t)(60 + rnd(51));
    }
}

static int fx_ok(const uint8_t *p)
{
    return p[X_DELAY] + p[X_REVERB] + p[X_CHORUS] <= 170 && p[X_DIST] <= 64 && p[X_DELFB] <= 100;
}

static void fx_fix(uint8_t *p)
{
    uint32_t sum = (uint32_t)p[X_DELAY] + p[X_REVERB] + p[X_CHORUS];
    if (sum > 170) {
        p[X_DELAY] = (uint8_t)(p[X_DELAY] * 170u / sum);
        p[X_REVERB] = (uint8_t)(p[X_REVERB] * 170u / sum);
        p[X_CHORUS] = (uint8_t)(p[X_CHORUS] * 170u / sum);
    }
    if (p[X_DIST] > 64)
        p[X_DIST] = 48;
    if (p[X_DELFB] > 100)
        p[X_DELFB] = 90;
}

static const struct {
    uint8_t section;
    int (*ok)(const uint8_t *);
    void (*fix)(uint8_t *);
} checks[] = {
    {S_MIXER, mixer_ok, mixer_fix}, {S_FILTER, filter_ok, filter_fix},
    {S_AMP, amp_ok, amp_fix}, {S_FX, fx_ok, fx_fix},
};

/* --- The roll -------------------------------------------------------------- */

static void put_num(char **p, uint32_t n)
{
    if (n >= 10)
        put_num(p, n / 10);
    *(*p)++ = (char)('0' + n % 10);
}

/* Rolls section s at amount a (1-10) into the patch; returns the number of
 * controls written. */
uint32_t rand_roll(uint32_t s, uint32_t a)
{
    if (s >= SECTIONS)
        return 0;
    rand_seed ^= mpe_ticks() * 2654435761u + 0x9E3779B9u;
    if (!rand_seed)
        rand_seed = 1;
    for (uint32_t o = 0; o < WORK; o++)
        work[o] = patches[o];
    uint32_t first = sections[s].first, n = sections[s].n;
    for (uint32_t i = first; i < first + n; i++) {
        roll_entry(&table[i], a, work[F_SHAPE] != patches[F_SHAPE]);
    }
    for (uint32_t k = 0; k < sizeof checks / sizeof checks[0]; k++) {
        if (s != S_ALL && s != checks[k].section)
            continue;
        if (!checks[k].ok(work) && (a >= 10 || checks[k].ok(patches)))
            checks[k].fix(work);
    }
    uint32_t written = 0;
    for (uint32_t i = 0; i < ENTRIES; i++) {
        uint32_t e = table[i].e, o = e & OFF;
        if (get(work, e) == get(patches, e))
            continue;
        if (e & H) {
            if (patches[o] != work[o])
                param_put(o, work[o]);
            if (patches[o + 1] != work[o + 1])
                param_put(o + 1, work[o + 1]);
        } else {
            param_put(o, work[o]);
        }
        written++;
    }
    return written;
}

/* Settings > RANDOMISE edits (records MPE_G_RAND_SECT, _AMT, _ROLL). */
void rand_edit(uint32_t index, int32_t delta)
{
    if (index == MPE_G_RAND_SECT) {
        int32_t v = (int32_t)section + delta;
        section = (uint8_t)(v < 0 ? 0 : v >= SECTIONS ? SECTIONS - 1 : v);
        return;
    }
    if (index == MPE_G_RAND_AMT) {
        int32_t v = (int32_t)rand_amount() + delta;
        amount = (uint8_t)(v < 1 ? 1 : v > 10 ? 10 : v);
        return;
    }
    if (delta <= 0)
        return;
    if (compare_held) {
        ui_say("RANDOMISE", "Not during Compare", "", "");
        return;
    }
    undo_capture();
    uint32_t n = rand_roll(section, rand_amount());
    char *p = msg_row;
    put_num(&p, n);
    const char *t = n == 1 ? " control changed" : " controls changed";
    while (*t && p < msg_row + 20)
        *p++ = *t++;
    *p = 0;
    ui_say("RANDOMISE", rand_section_name(), msg_row, "Undo: Mod+Page left");
    ui_say_hold();
}
