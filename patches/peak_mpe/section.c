/* Peak section copy/paste and one-level undo (docs/peak-features.md, steps 15 and 13).
 *
 * Copy: Settings > COPY SECTION. "Section" picks one of 14 copies (Osc 1>2, LFO 1>2,
 * Amp>Env 1, ...), "Do it" set to Yes performs it. A section is a block of patch
 * offsets (from the parameter table); the source block's values are written to the
 * destination block through the CC setter (param_set_by_id), so the patch, the
 * sound chip and Pickup follow as for a received CC. A parameter that cannot be set
 * that way (no NRPN/CC number in its descriptor) is skipped.
 *
 * Undo: one level. The patch's parameters (0x1A2 bytes) are saved before a paste, a
 * quick-assign, and the first move of a control after it has been still for about
 * 2 s (one gesture is one undo step). Hold Mod and press Page left to undo, Page
 * right to redo (both swap the saved copy with the patch, written back through the
 * same setter, for the parameters that differ). Editing with the value buttons or
 * the encoder is not recorded. A patch load clears it.
 *
 * The id for param_set_by_id comes from the parameter's own descriptor
 * (patch_param_desc: NRPN msb 252-254 = a CC whose number is the lsb, 255 = not
 * settable, otherwise NRPN id = lsb + 128 * msb + 128), the numbers the CC and NRPN
 * handler in the firmware uses (observed in the simulator for the amp envelope CCs
 * and the mod matrix NRPNs; the others by the same rule: inferred).
 */

#include "mpe.h"

#define PARAMS 0x1A2
#define TICKS_PER_GESTURE 4000   /* about 2 s at the 2 kHz tick envsync.c measured in the simulator */

static const struct { const char *name; uint8_t src, dst, len; } ops[] = {
    {"-", 0, 0, 0},
    {"Osc1>2", 0x30, 0x45, 0x13}, {"Osc1>3", 0x30, 0x5A, 0x13},
    {"Osc2>1", 0x45, 0x30, 0x13}, {"Osc2>3", 0x45, 0x5A, 0x13},
    {"Osc3>1", 0x5A, 0x30, 0x13}, {"Osc3>2", 0x5A, 0x45, 0x13},
    {"Amp>E1", 0x92, 0x9B, 8}, {"E1>Amp", 0x9B, 0x92, 8},
    {"Amp>E2", 0x92, 0xA3, 8}, {"E2>Amp", 0xA3, 0x92, 8},
    {"E1>E2", 0x9B, 0xA3, 8}, {"E2>E1", 0xA3, 0x9B, 8},
    {"LFO1>2", 0xAC, 0xBA, 12}, {"LFO2>1", 0xBA, 0xAC, 12},
};
#define OPS (sizeof ops / sizeof ops[0])

static uint8_t op;                       /* the chosen copy; 0 = none (patch RAM is zero-initialised) */
static uint8_t undo_buf[PARAMS];
static uint8_t undo_valid, undone;
static uint32_t last_move, last_id1;     /* the last control event: tick, offset + 1 */

/* The setter's id for a patch offset, or 0 if it cannot be set that way. */
static uint32_t id_of(uint32_t offset)
{
    const struct param_desc *d = &patch_param_desc[offset];
    if (d->max == 0 && d->min == 0)
        return 0;
    if (d->nrpn_msb == 255)
        return 0;
    if (d->nrpn_msb >= 252)           /* 252 a CC, 254 the coarse and 253 the fine byte of a 9-bit CC pair */
        return d->nrpn_lsb;
    return d->nrpn_lsb + 128u * d->nrpn_msb + 128u;
}

static void put(uint32_t offset, uint32_t value)
{
    uint32_t id = id_of(offset);
    if (id)
        param_set_by_id(value, id);
}

const char *section_name(uint32_t i)
{
    return ops[i < OPS ? i : 0].name;
}

uint32_t section_op(void)
{
    return op;
}

void undo_capture(void)
{
    for (uint32_t o = 0; o < PARAMS; o++)
        undo_buf[o] = patches[o];
    undo_valid = 1;
    undone = 0;
}

void undo_clear(void)
{
    undo_valid = 0;
    undone = 0;
}

/* A control moved (not while Mod is held): the first move after a still period, or
 * a different control, starts a new gesture and saves the patch as it is now. */
void undo_knob(uint32_t id)
{
    uint32_t now = mpe_ticks();
    if (last_id1 != id + 1 || now - last_move > TICKS_PER_GESTURE)
        undo_capture();
    last_id1 = id + 1;
    last_move = now;
}

/* Swaps the saved copy with the patch; returns the number of parameters that changed. */
static uint32_t swap(void)
{
    uint32_t n = 0;
    for (uint32_t o = 0; o < PARAMS; o++) {
        uint8_t a = patches[o], b = undo_buf[o];
        if (a == b || !id_of(o))
            continue;
        put(o, b);
        undo_buf[o] = a;
        n++;
    }
    return n;
}

/* Mod held and a Page button: undo (Page left) or redo (Page right). Returns 1 when
 * the button was taken. ev is the panel event (low byte +1 press / -1 release, next
 * byte the button index: 33 = Page right, 34 = Page left). */
int edit_button(uint32_t ev)
{
    uint32_t idx = (ev >> 8) & 0xFF;
    if (!(ev & 0xFF) || (idx != 33 && idx != 34))
        return 0;
    if ((int8_t)(ev & 0xFF) < 0)
        return 1;                              /* the release: nothing to do */
    int back = idx == 34;
    if (!undo_valid || (back && undone) || (!back && !undone)) {
        ui_say("UNDO", back ? "Nothing to undo" : "Nothing to redo", "", "");
        return 1;
    }
    swap();
    undone = (uint8_t)back;
    ui_say(back ? "UNDO" : "REDO", back ? "Back one change" : "Change restored", "Mod + Page left: undo", "Mod + Page right: redo");
    return 1;
}

/* Settings > COPY SECTION edits (records MPE_G_SECT and MPE_G_DOIT). */
void section_edit(uint32_t index, int32_t delta)
{
    if (index == MPE_G_SECT) {
        int32_t v = (int32_t)op + delta;
        op = (uint8_t)(v < 0 ? 0 : v >= (int32_t)OPS ? (int32_t)OPS - 1 : v);
        return;
    }
    if (delta <= 0)
        return;
    if (op == 0) {
        ui_say("COPY SECTION", "Choose a copy first", "", "");
        return;
    }
    undo_capture();
    for (uint32_t k = 0; k < ops[op].len; k++)
        put(ops[op].dst + k, patches[ops[op].src + k]);
    ui_say("COPY SECTION", "Done:", ops[op].name, "Undo: Mod + Page left");
}
