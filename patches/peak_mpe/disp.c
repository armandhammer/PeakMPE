/* Knob-turn display: units, value bars and pickup feedback (plan steps 9, 10).
 *
 * Stock draws the overlay in knob_overlay (0x08016B14): row 0 the parameter
 * name, row 1 "  current <value>", row 2 "saved val <value>", and while the
 * Pickup setting holds the value back, row 3 "   pickup <knob>"
 * (docs/findings/peak-2.2-build2108.md, "The knob overlay"). This module owns
 * that overlay:
 *
 *  - disp_knob_overlay replaces both calls of knob_overlay (knob_poll
 *    0x08016EF2, 0x08016F28). It records the parameter and calls stock, which
 *    prints rows 0-2 through three format_value calls;
 *  - disp_fmt_cur / disp_fmt_saved replace the calls for rows 1 and 2 (while
 *    pickup holds the knob back, "current" shows the knob's value)
 *    (0x08016C72, 0x08016C90) and print milliseconds or Hz for the envelope
 *    times, Hold and the filter cutoff (measured tables, docs/peak-units.md),
 *    stock's text for everything else;
 *  - disp_skip_puts drops stock's pickup label and row-3 clear (0x08016C2A,
 *    0x08016C48);
 *  - disp_fmt_pick replaces the knob value on the pickup row (0x08016C3C) with
 *    nothing: row 3 is redrawn whole below;
 *  - after stock has drawn, row 3 shows a value bar of the shown value (from the
 *    centre for bipolar parameters), or, while pickup holds the knob back, an
 *    arrow at the end of the knob's bar, pointing the way to the patch's value;
 *    it moves with the knob and goes when the value is reached.
 *
 * The bars use custom characters, which stock loads once at boot (box-frame
 * pieces, codes 0-7). The first overlay loads ours; disp_poll puts stock's
 * set back when the overlay's message time has run out (lcd_load_cgram), so
 * the pages that might use the frame characters are unchanged. All of it is
 * drawn at the end of the knob event that called stock, in the main loop,
 * never from an interrupt or mod_tick.
 *
 * The ms and Hz figures describe the amp envelope (attack: the whole ramp;
 * decay and release: time to -40 dB) and the filter with key tracking 0 at
 * resonance 127. The mod envelopes are assumed to be the same curves
 * (inferred; not measured).
 */

#include "mpe.h"
#include "disp_tables.h"

/* Display floors: settings below these were under the measuring chain's
 * resolution, so the text says "<Nms" (docs/peak-units.md). */
#define ATTACK_FLOOR 24
#define DECAY_FLOOR 28
#define RELEASE_FLOOR 12
#define CUTOFF_FLOOR 24   /* knob value (CC 12 = 24): below it the table is extrapolated */

#define GLOBAL_PICKUP 0x0C

/* Custom characters (slots chosen so that none is code 0, which would end a
 * string): left-aligned fills of 1-4 columns, full, right-aligned fills of
 * 2 and 4 columns. Rows 1-6 are drawn, rows 0 and 7 left blank. */
enum { G_L1 = 1, G_L2, G_L3, G_L4, G_FULL, G_R2, G_R4, GLYPHS };
#define CHAR_ARROW_RIGHT '>'    /* plain ASCII: the ROM arrows 0x10/0x11 were not seen on the synth */
#define CHAR_ARROW_LEFT '<'

static const uint8_t glyph_pattern[GLYPHS] = {
    0x00, 0x10, 0x18, 0x1C, 0x1E, 0x1F, 0x03, 0x0F,
};

#define COLS 20
#define CELL_PX 5

static uint8_t glyphs_loaded;
static uint8_t ov_id, ov_hires, ov_drawn;
static uint32_t ov_cur;

/* --- Text ---------------------------------------------------------------- */

static char *put_uint(char *p, uint32_t v)
{
    char tmp[10];
    uint32_t n = 0;
    do {
        tmp[n++] = (char)('0' + v % 10);
        v /= 10;
    } while (v);
    while (n)
        *p++ = tmp[--n];
    return p;
}

/* t in ms: "35ms", "1.23s", "12.3s". */
static char *put_ms(char *p, uint32_t t)
{
    if (t < 1000) {
        p = put_uint(p, t);
        *p++ = 'm';
        *p++ = 's';
    } else if (t < 10000) {
        t = (t + 5) / 10;                 /* centiseconds */
        p = put_uint(p, t / 100);
        *p++ = '.';
        *p++ = (char)('0' + t / 10 % 10);
        *p++ = (char)('0' + t % 10);
        *p++ = 's';
    } else {
        t = (t + 50) / 100;               /* deciseconds */
        p = put_uint(p, t / 10);
        *p++ = '.';
        *p++ = (char)('0' + t % 10);
        *p++ = 's';
    }
    return p;
}

/* f in Hz: "533Hz", "5.32kHz", "23.7kHz". */
static char *put_hz(char *p, uint32_t f)
{
    if (f < 1000) {
        p = put_uint(p, f);
    } else if (f < 10000) {
        f = (f + 5) / 10;                 /* tens of Hz */
        p = put_uint(p, f / 100);
        *p++ = '.';
        *p++ = (char)('0' + f / 10 % 10);
        *p++ = (char)('0' + f % 10);
        *p++ = 'k';
    } else {
        f = (f + 50) / 100;
        p = put_uint(p, f / 10);
        *p++ = '.';
        *p++ = (char)('0' + f % 10);
        *p++ = 'k';
    }
    *p++ = 'H';
    *p++ = 'z';
    return p;
}

enum { U_NONE, U_ATTACK, U_DECAY, U_RELEASE, U_HOLD, U_CUTOFF };

/* The unit of a patch offset (ids from the findings: Amp 146-149, Mod Env 1
 * 155-158, Mod Env 2 163-166, Hold 152 161 169, FiltFreq 131). */
static uint32_t unit_of(uint32_t id)
{
    /* A table, not a switch: a compiled switch leaves a long run of zero
     * bytes (a jump table) that the web descriptor's no-firmware-bytes check
     * would match in the official image. */
    static const struct { uint8_t id, unit; } units[] = {
        {146, U_ATTACK}, {155, U_ATTACK}, {163, U_ATTACK},
        {147, U_DECAY}, {156, U_DECAY}, {164, U_DECAY},
        {149, U_RELEASE}, {158, U_RELEASE}, {166, U_RELEASE},
        {152, U_HOLD}, {161, U_HOLD}, {169, U_HOLD},
        {131, U_CUTOFF},
    };
    for (uint32_t i = 0; i < sizeof units / sizeof units[0]; i++)
        if (units[i].id == id)
            return units[i].unit;
    return U_NONE;
}

/* Formats value in the parameter's unit into buf (NUL-terminated); returns
 * the length, 0 if the parameter has no unit. */
static uint32_t unit_text(uint32_t id, uint32_t v, char *buf)
{
    uint32_t unit = unit_of(id);
    char *p = buf;
    if (unit == U_NONE)
        return 0;
    if (unit == U_HOLD)
        v = v > 127 ? 127 : v;
    else if (unit == U_CUTOFF)
        v = v > 255 ? 255 : v;
    else if (v > 127)
        v = 127;
    uint32_t floor = 0, t = 0;
    switch (unit) {
    case U_ATTACK: floor = ATTACK_FLOOR; t = disp_attack_ms[v]; break;
    case U_DECAY: floor = DECAY_FLOOR; t = disp_decay_ms[v]; break;
    case U_RELEASE: floor = RELEASE_FLOOR; t = disp_release_ms[v]; break;
    case U_HOLD: t = (v * 53 + 5) / 10; break;     /* 5.3 ms per step (peak-units.md) */
    case U_CUTOFF: floor = CUTOFF_FLOOR; t = disp_cutoff_hz[v]; break;
    }
    if (v < floor) {
        *p++ = '<';
        if (unit == U_CUTOFF)
            p = put_hz(p, disp_cutoff_hz[CUTOFF_FLOOR]);
        else
            p = put_ms(p, t);
    } else if (unit == U_CUTOFF) {
        p = put_hz(p, t);
    } else {
        p = put_ms(p, t);
    }
    *p = 0;
    return (uint32_t)(p - buf);
}

static void put_str(const char *s)
{
    while (*s)
        lcd_putc_esc((uint8_t)*s++);
}

/* Prints the value of the parameter being drawn, padded to width columns so a
 * shorter text covers a longer one drawn earlier. */
static void print_value(uint32_t type, uint32_t value, uint32_t width)
{
    char buf[16];
    uint32_t n = unit_text(ov_id, value, buf);
    if (!n) {
        format_value(type, value);
        return;
    }
    put_str(buf);
    for (; n < width; n++)
        lcd_putc_esc(' ');
}

/* --- Hooks inside knob_overlay ------------------------------------------- */

/* 0x08016C3C: the knob's value on the pickup row. Row 3 is drawn in full after
 * stock returns, so nothing here. */
void disp_fmt_pick(uint32_t type, uint32_t value)
{
    (void)type;
    (void)value;
}

/* 0x08016C2A and 0x08016C48: knob_overlay's lcd_puts of the pickup label and
 * of the row-3 clear. Row 3 is drawn whole below, so stock's label would only
 * flash on it first (seen on the synth, 2026-11-13: "pickup" over the bar). */
uint32_t disp_skip_puts(const char *s)
{
    (void)s;
    return 0;
}

/* 0x08016C72: "  current " (10 columns), so up to 10 for the value. */
void disp_fmt_cur(uint32_t type, uint32_t value)
{
    ov_drawn = 1;
    /* While Pickup holds the knob back stock shows the patch's value here;
     * show what the knob is sending instead, as it moves. */
    if (globals[GLOBAL_PICKUP] && ov_id < sizeof pickup_state && pickup_state[ov_id])
        value = ov_cur;
    print_value(type, value, 10);
}

/* 0x08016C90: "saved val ". */
void disp_fmt_saved(uint32_t type, uint32_t value)
{
    print_value(type, value, 10);
}

/* --- Custom characters --------------------------------------------------- */

static void load_glyphs(void)
{
    if (glyphs_loaded)
        return;
    lcd_write_cmd(0x40 + 8);                    /* CGRAM address 8: character 1 */
    for (uint32_t g = 1; g < GLYPHS; g++)
        for (uint32_t row = 0; row < 8; row++)
            lcd_write_data(row == 0 || row == 7 ? 0 : glyph_pattern[g]);
    glyphs_loaded = 1;
}

/* --- Bars ---------------------------------------------------------------- */

/* The character for cells [lo, hi) of pixel space (5 pixels per cell, left
 * pixel first), 0x20 for none. Left fills 1-4 and full; right fills of 2 and
 * 4 pixels (1 and 3 round up). */
static uint8_t cell_char(uint32_t cell, uint32_t lo, uint32_t hi)
{
    uint32_t a = cell * CELL_PX, b = a + CELL_PX;
    uint32_t from = lo > a ? lo : a;
    uint32_t to = hi < b ? hi : b;
    if (to <= from)
        return ' ';
    uint32_t n = to - from;
    if (n >= CELL_PX)
        return G_FULL;
    if (from == a)
        return (uint8_t)(G_L1 + n - 1);
    return n <= 2 ? G_R2 : G_R4;                 /* ends at the cell's right edge */
}

#define SCREEN_PX (COLS * CELL_PX)

static uint32_t is_bipolar(uint32_t type, uint32_t *centre)
{
    switch (type) {
    case 0x03: case 0x0B: case 0x0C: case 0x30:
        *centre = 0x40;
        return 1;
    case 0x04: case 0x05:
        *centre = 0x80;
        return 1;
    default:
        return 0;
    }
}

/* Position of v in the parameter's range, in pixels 0..width. */
static uint32_t pos(uint32_t v, uint32_t lo, uint32_t hi, uint32_t width)
{
    if (hi <= lo)
        return 0;
    if (v < lo)
        v = lo;
    if (v > hi)
        v = hi;
    return (v - lo) * width / (hi - lo);
}

/* The bottom line for v: a bar from the left or, for bipolar parameters, from
 * the centre. *end is the cell where the bar ends at v. */
static void bar_cells(const struct param_desc *d, uint32_t v, uint8_t *row, uint32_t *end)
{
    uint32_t lo = d->min, hi = d->max, centre = 0;
    uint32_t type = d->display & 0xFF;
    uint32_t from = 0, to = pos(v, lo, hi, SCREEN_PX);
    uint32_t at = to;
    if (is_bipolar(type, &centre)) {
        uint32_t c = pos(centre, lo, hi, SCREEN_PX);
        from = to < c ? to : c;
        to = to < c ? c : to;
    }
    for (uint32_t cell = 0; cell < COLS; cell++)
        row[cell] = cell_char(cell, from, to);
    *end = at >= SCREEN_PX ? COLS - 1 : at / CELL_PX;
}

static void put_row(const uint8_t *row)
{
    lcd_cursor(0, 3);
    for (uint32_t cell = 0; cell < COLS; cell++)
        lcd_putc_esc(row[cell]);
}

/* No pickup pending: the bar of v. */
static void draw_value_bar(const struct param_desc *d, uint32_t v)
{
    uint8_t row[COLS];
    uint32_t end;
    bar_cells(d, v, row, &end);
    put_row(row);
}

/* Pickup pending: the bar of the knob's position with an arrow at its end,
 * pointing the way the knob has to go to reach the patch's value. The arrow
 * moves with the knob and is gone once the value is reached. */
static void draw_pickup(const struct param_desc *d, uint32_t knob, uint32_t target)
{
    uint8_t row[COLS];
    uint32_t end;
    bar_cells(d, knob, row, &end);
    row[end] = knob < target ? CHAR_ARROW_RIGHT : CHAR_ARROW_LEFT;
    put_row(row);
}

/* --- The overlay --------------------------------------------------------- */

static uint32_t patch_value(uint32_t id, uint32_t hires)
{
    uint32_t v = patches[id];
    if (hires)
        v = v * 2 + (patches[id + 1] >> 6);
    return v;
}

/* Replaces knob_poll's two calls of knob_overlay (0x08016EF2, 0x08016F28). */
int disp_knob_overlay(uint32_t id, uint32_t prev, uint32_t cur, uint32_t saved, uint32_t hires)
{
    ov_id = (uint8_t)id;
    ov_hires = (uint8_t)(hires & 0xFF);
    ov_drawn = 0;
    ov_cur = cur;
    int applied = knob_overlay(id, prev, cur, saved, hires & 0xFF);
    if (ov_drawn && id < 0x1A3) {
        const struct param_desc *d = &patch_param_desc[id];
        load_glyphs();
        if (!applied && globals[GLOBAL_PICKUP])
            draw_pickup(d, cur, patch_value(id, ov_hires));
        else
            draw_value_bar(d, cur);
    }
    return applied;
}

/* Once per main-loop pass (from mpe_ui_poll). Puts stock's characters back
 * when no message is on the display any more. */
void disp_poll(void)
{
    if (glyphs_loaded && !ui_msg_state[2]) {
        glyphs_loaded = 0;
        lcd_load_cgram();
        lcd_write_cmd(0x80);                    /* back to DDRAM, as lcd_init leaves it */
    }
}
