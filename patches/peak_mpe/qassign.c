/* Peak quick-assign modulation (docs/peak-features.md, step 12).
 *
 * Hold Mod, move a control: the control's mod destination goes into the first
 * free matrix slot with the chosen source at depth +32. Turn the value
 * encoder (or press the value buttons) while holding Mod to choose the source;
 * the choice is shown on the OLED for the message time. Without Mod held
 * nothing here acts.
 *
 *  - qa_panel_read replaces panel_button_event's read of the button event
 *    (0x08016FF4, bl 0x0800DDFC) and tracks the Mod button: panel button 7
 *    (button_table 0x20000AB8 index 7: type 3, mode 5, the menu with the
 *    ":sA [Slot ss]" page), the event's low byte is +1 press / -1 release,
 *    the next byte the button index (observed in the disassembly). Stock
 *    still sees the event and opens the Mod menu as it always did.
 *  - qa_encoder is called first by mpe_ui_value_change: with Mod held it takes
 *    the encoder for the source and returns 1.
 *  - qa_knob is called by disp_knob_overlay, instead of stock's knob overlay,
 *    while Mod is held (the control then only selects: stock draws nothing and the
 *    control's value is not applied), with the control's patch offset: a table gives its mod
 *    destination (names matched to the matrix's destination list: inferred;
 *    the Peak's own offset-to-destination relation was not found in the
 *    firmware). A control moved with Mod held does not change its own value.
 *
 * A slot is free when Source A and B are Direct and Depth is 0 (64). A slot
 * that already has the same source and destination is reused (nothing
 * new is added). Values go in through the CC setter (param_set_by_id) with
 * the NRPN number of the slot's parameter, as an NRPN would.
 */

#include "mpe.h"

#define BUTTON_MOD 7
#define SLOTS 16
#define SLOT_BASE 0xFC             /* patch offset: SourceA, SourceB, Depth, Destin */
#define DEPTH_ZERO 64
#define ASSIGN_DEPTH (DEPTH_ZERO + 32)
#define SOURCES 24
#define DEST_NONE 0xFF
#define GLOBAL_MSG_TIME 0x1A

/* Names: the matrix's own tables. */
static const char *const *source_names = (const char *const *)0x08046480;
static const char *const *dest_names = (const char *const *)0x080464E0;

/* patch offset of a control (either byte of a 9-bit one) -> matrix destination */
static const struct { uint8_t offset, dest; } dest_of[] = {
    {0x31, 1}, {0x32, 1}, {0x46, 2}, {0x47, 2}, {0x5B, 3}, {0x5C, 3},       /* oscillator coarse: pitch */
    {0x3E, 4}, {0x53, 5}, {0x68, 6},                                          /* Vsync */
    {0x3B, 7}, {0x50, 8}, {0x65, 9},                                          /* shape */
    {0x6F, 10}, {0x70, 10}, {0x71, 11}, {0x72, 11}, {0x73, 12}, {0x74, 12},   /* oscillator levels */
    {0x77, 13}, {0x78, 13}, {0x75, 14}, {0x76, 14},                           /* noise, ring */
    {0x7D, 16}, {0x7E, 17}, {0x83, 18}, {0x84, 18}, {0x82, 19},               /* filter */
    {0xAC, 20}, {0xAD, 20}, {0xBA, 21}, {0xBB, 21},                           /* LFO rates */
    {0x92, 22}, {0x93, 23}, {0x95, 24},                                       /* amp envelope A D R */
    {0x9B, 25}, {0x9C, 26}, {0x9E, 27},                                       /* mod envelope 1 */
    {0xA3, 28}, {0xA4, 29}, {0xA6, 30},                                       /* mod envelope 2 */
    {0x8E, 38},                                                               /* pan */
    {0x98, 41}, {0x94, 42}, {0xA1, 44}, {0x9D, 45}, {0xA9, 47}, {0xA5, 48},   /* hold, sustain */
};

static uint8_t held;
static uint8_t source_sel;           /* 0 = the default, Lfo1+ (patch RAM is zero-initialised only) */
static uint8_t done_id1;             /* the control assigned in this hold, offset + 1 (0 = none) */
static uint8_t shown_id1;            /* the control the message was drawn for, offset + 1 */
static uint8_t done_slot;            /* ... and the slot it is in */

#define DEFAULT_SOURCE 7
#define source (source_sel ? source_sel : DEFAULT_SOURCE)

int qa_held(void)
{
    return held;
}

/* One button event as panel_button_event reads it (low byte +1 press, -1 release;
 * next byte the button index). Separate from qa_panel_read so a test can feed it. */
void qa_button(uint32_t ev)
{
    if ((ev & 0xFF) && ((ev >> 8) & 0xFF) == BUTTON_MOD) {
        held = (int8_t)(ev & 0xFF) > 0;
        done_id1 = 0;
        shown_id1 = 0;
    }
}

/* panel_button_event's read of the next button event (0x08016FF4). */
uint32_t qa_panel_read(void)
{
    uint32_t ev = panel_event_read();
    qa_button(ev);
    return ev;
}

/* Four rows on the page for the message time. */
static void say(const char *l0, const char *l1, const char *l2, const char *l3)
{
    const char *rows[4] = {l0, l1, l2, l3};
    for (uint32_t r = 0; r < 4; r++) {
        lcd_cursor(0, r);
        uint32_t n = 0;
        for (const char *s = rows[r]; *s && n < 20; s++, n++)
            lcd_putc_esc((uint8_t)*s);
        for (; n < 20; n++)
            lcd_putc_esc(' ');
    }
    ui_msg_state[2] = (uint8_t)(globals[GLOBAL_MSG_TIME] + 5);
}

static void text(char *out, const char *a, const char *b)
{
    while (*a)
        *out++ = *a++;
    while (*b)
        *out++ = *b++;
    *out = 0;
}

/* Source choice. delta from the encoder or a value button. Returns 1 when taken. */
int qa_encoder(int32_t delta)
{
    if (!held)
        return 0;
    int32_t s = (int32_t)source + delta;
    source_sel = (uint8_t)(s < 1 ? SOURCES - 1 : s >= SOURCES ? 1 : s);
    char l1[24];
    text(l1, "Source ", source_names[source]);
    say("QUICK ASSIGN", l1, "Hold Mod and move a", "slider or knob");
    return 1;
}

static void set_slot(uint32_t slot, uint32_t k, uint32_t value)
{
    param_set_by_id(value, 128 * (slot + 2) + k);   /* NRPN (slot+1):k -> lsb + 128 * msb + 128 */
}

static void show(int32_t slot, uint32_t dest)
{
    char l1[8] = "Slot ";
    l1[5] = (char)('0' + (slot + 1) / 10);
    l1[6] = (char)('0' + (slot + 1) % 10);
    l1[7] = 0;
    say("QUICK ASSIGN", l1, source_names[source], dest_names[dest]);
}

/* A control with patch offset id moved while Mod is held. Called after stock drew. */
void qa_knob(uint32_t id)
{
    if (!held)
        return;
    if (shown_id1 == id + 1) {     /* already on the screen: keep it there, no redraw (flicker) */
        ui_msg_state[2] = (uint8_t)(globals[GLOBAL_MSG_TIME] + 5);
        return;
    }
    shown_id1 = (uint8_t)(id + 1);
    uint32_t dest = DEST_NONE;
    for (uint32_t i = 0; i < sizeof dest_of / sizeof dest_of[0]; i++)
        if (dest_of[i].offset == id)
            dest = dest_of[i].dest;
    if (dest == DEST_NONE) {
        say("QUICK ASSIGN", "No mod destination", "for this control", "");
        return;
    }
    if (done_id1 == id + 1) {      /* the control moved again after another one in this hold */
        show((int32_t)done_slot, dest);
        return;
    }
    int32_t slot = -1, free_slot = -1;
    for (uint32_t s = 0; s < SLOTS; s++) {
        const uint8_t *p = &patches[SLOT_BASE + 4 * s];
        if (p[0] == source && p[1] == 0 && p[3] == dest && p[2] != DEPTH_ZERO) {
            slot = (int32_t)s;
            break;
        }
        if (free_slot < 0 && p[0] == 0 && p[1] == 0 && p[2] == DEPTH_ZERO)
            free_slot = (int32_t)s;
    }
    done_id1 = (uint8_t)(id + 1);
    if (slot < 0) {
        if (free_slot < 0) {
            say("QUICK ASSIGN", "No free slot", "", "");
            return;
        }
        slot = free_slot;
        set_slot((uint32_t)slot, 0, source);
        set_slot((uint32_t)slot, 1, 0);
        set_slot((uint32_t)slot, 2, ASSIGN_DEPTH);
        set_slot((uint32_t)slot, 3, dest);
    }
    done_slot = (uint8_t)slot;
    show(slot, dest);
}
