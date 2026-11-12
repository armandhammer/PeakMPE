/* Peak MPE UI: the per-patch flag on the VOICE page and the Settings MPE
 * pages (the Summit patch's mpe_ui.c; docs/mpe-design.md, "UI").
 *
 * VOICE page 1, item 3 (patch.py adds it: kind 1, index 0x1A2). The
 * descriptor (patch_param_desc[0x1A2]: 0-1, Off/On, "MPE") shows the item;
 * editing it needs code on the Summit (ui_value_change's offset -> NRPN
 * table stops below 0x1A2), and the Peak's patch table has the same reserved
 * entry, so the same is assumed here (inferred; the simulator will check).
 * The four calls of ui_value_change come here, and this item is written
 * directly into the patch. No MIDI echo: the flag has no NRPN.
 *
 * Settings: two pages after MIDI CONTROL (where the Peak has its MIDI
 * channel), so Settings has 28 pages.
 *   MPE             Zone (Off/Lower/Upper), Members (1-15)
 *   MPE BEND RANGE  Note Bend, MasterBend (semitones, 1-96)
 * The Summit's read-only "Channels" item (CH CLASH) is left out: the Peak has
 * no Multi parts whose channels a zone could take.
 * The items are kind 3 (global settings) with records 0x30-0x33, which stock
 * global_param_desc doesn't have (0x22 records on the Peak). So the
 * descriptor table and the Settings menu move to patch RAM, filled at boot
 * from the stock RAM copies plus the new entries. The three literals of
 * global_param_desc point at the new table (patch.py); menus[8] is set when
 * the menu is built.
 *
 * The pages show what is in effect, mpe_live (the Settings layout plus what
 * RPN 6 and RPN 0 changed), through display types 0xE0-0xE4, which stock
 * format_value doesn't know (it ends at 0x60) and which the kind 3 drawer
 * passes to mpe_ui_format. A value that differs from the Settings value
 * (globals +0x30..+0x33, 0 = default) has a '*' after it: set by MIDI, and
 * stored only by Save. An edit first takes the live state into the
 * Settings, as Save would (mpe_live_to_globals), then changes the one
 * value, so RPN changes to the other items aren't lost. mpe_ui_poll redraws
 * the values when what they'd show changes (RPN, mode, flags), as long as
 * one of the pages is on screen.
 *
 * Stock code that acts on Settings page numbers (Save on tuning pages > 8,
 * Calibrate on 1, BACKUP on 9) asks ui_current_page_index; those calls come
 * to mpe_settings_page_index, which gives them the stock number (the MPE
 * pages count as MIDI CONTROL, which has no page action).
 */

#include "mpe.h"

/* --- Tables ------------------------------------------------------------- */

struct mpe_desc {
    uint8_t min, max, nrpn_msb, nrpn_lsb;
    uint32_t display;
    const char *name;
};

struct mpe_page {
    const char *title;
    uint8_t n_items, selected;
    struct { uint8_t kind, pad; uint16_t index; } item[4];
};

#define STOCK_DESCS 0x22           /* Peak global_param_desc: records 0x00-0x21, then other data */
#define MPE_DESCS (MPE_G_MASTER_RANGE + 1)
#define MPE_PAGE_AT 4              /* after MIDI CONTROL (stock page 3) */
#define MPE_PAGES 2
#define STOCK_PAGES PEAK_SETTINGS_PAGES
#define UI_MODE_SETTINGS PEAK_UI_SETTINGS
#define UI_MODE (ui_state[0])

enum { DISP_ZONE = 0xE0, DISP_MEMBERS, DISP_NOTE, DISP_MASTER, DISP_END };

#define FIELD 8                    /* value field: columns 11-18, the mark is at 19 */

/* Patch RAM copies; patch.py points the firmware at them. build_tables
 * writes all of them before their first use, so they aren't cleared at
 * startup (PATCH_NOINIT). */
PATCH_NOINIT struct mpe_desc mpe_global_desc[MPE_DESCS];
PATCH_NOINIT struct {
    uint8_t cur, n_pages;
    uint16_t pad;
    struct mpe_page *pages[STOCK_PAGES + MPE_PAGES];
} mpe_settings_menu;
PATCH_NOINIT struct mpe_page mpe_pages[MPE_PAGES];

static const char title_zone[] = "MPE";
static const char title_bend[] = "MPE BEND RANGE";

static const struct mpe_desc new_descs[] = {
    {0, 2, 0x40, 0x2E, DISP_ZONE, "Zone"},
    {1, 15, 0x40, 0x2F, DISP_MEMBERS, "Members"},
    {1, MPE_MAX_RANGE, 0x40, 0x30, DISP_NOTE, "Note Bend"},
    {1, MPE_MAX_RANGE, 0x40, 0x31, DISP_MASTER, "MasterBend"},
};

/* Last drawn per item. Only compared with what would be drawn now, so its
 * startup contents cost at most one redraw: not cleared (PATCH_NOINIT). */
PATCH_NOINIT static char drawn[DISP_END - DISP_ZONE][FIELD + 1];

static void page_init(struct mpe_page *p, const char *title)
{
    uint8_t *b = (uint8_t *)p;
    for (uint32_t i = 0; i < sizeof *p; i++)
        b[i] = 0;
    p->title = title;
}

static void page_item(struct mpe_page *p, uint16_t index)
{
    p->item[p->n_items].kind = 3;
    p->item[p->n_items++].index = index;
}

/* Builds the tables and points menus[8] at the new Settings menu. */
static void build_tables(void)
{
    const uint32_t *src = (const uint32_t *)global_param_desc;  /* word-aligned, 12-byte records */
    uint32_t *dst = (uint32_t *)mpe_global_desc;
    for (uint32_t i = 0; i < STOCK_DESCS * sizeof(struct mpe_desc) / 4; i++)
        dst[i] = src[i];
    for (uint32_t i = STOCK_DESCS * sizeof(struct mpe_desc) / 4; i < MPE_G_ZONE * sizeof(struct mpe_desc) / 4; i++)
        dst[i] = 0;  /* records 0x22-0x2F: no Settings item uses them */
    for (uint32_t i = 0; i <= MPE_G_MASTER_RANGE - MPE_G_ZONE; i++)
        mpe_global_desc[MPE_G_ZONE + i] = new_descs[i];

    page_init(&mpe_pages[0], title_zone);
    page_item(&mpe_pages[0], MPE_G_ZONE);
    page_item(&mpe_pages[0], MPE_G_MEMBERS);
    page_init(&mpe_pages[1], title_bend);
    page_item(&mpe_pages[1], MPE_G_NOTE_RANGE);
    page_item(&mpe_pages[1], MPE_G_MASTER_RANGE);

    struct mpe_page **stock = (struct mpe_page **)(settings_menu + 4);
    uint32_t n = 0;
    for (uint32_t i = 0; i < STOCK_PAGES; i++) {
        if (i == MPE_PAGE_AT)
            for (uint32_t k = 0; k < MPE_PAGES; k++)
                mpe_settings_menu.pages[n++] = &mpe_pages[k];
        mpe_settings_menu.pages[n++] = stock[i];
    }
    mpe_settings_menu.cur = settings_menu[0];
    mpe_settings_menu.n_pages = (uint8_t)n;
    mpe_settings_menu.pad = 0;
    menus[UI_MODE_SETTINGS] = (uint8_t *)&mpe_settings_menu;
}

/* Replaces main_loop's first settings_load call (0x0800D132): the tables
 * are complete before the main loop runs, so no button can reach Settings
 * before them. The
 * patch RAM they live in isn't cleared at startup (PATCH_NOINIT); this
 * writes all of it. */
void mpe_ui_boot(void)
{
    build_tables();
    settings_load();
}

/* --- Page numbers --------------------------------------------------------- */

/* Replaces ui_current_page_index where stock code acts on a Settings page
 * number (patch.py): the stock number of the page shown. */
uint8_t mpe_settings_page_index(void)
{
    uint8_t i = ui_current_page_index();
    if (UI_MODE != UI_MODE_SETTINGS || i < MPE_PAGE_AT)
        return i;
    if (i < MPE_PAGE_AT + MPE_PAGES)
        return MPE_PAGE_AT - 1;
    return (uint8_t)(i - MPE_PAGES);
}

/* --- Values --------------------------------------------------------------- */

static uint8_t setting(uint32_t offset, uint8_t max, uint8_t fallback)
{
    uint8_t v = globals[offset];
    return v == 0 || v > max ? fallback : v;
}

/* What the Settings alone would put in effect (as mpe_settings.c loads it). */
static void settings_view(struct mpe_live *v)
{
    uint8_t zone = globals[MPE_G_ZONE];
    uint8_t n = setting(MPE_G_MEMBERS, 15, MPE_DEFAULT_MEMBERS);
    v->members[MPE_LOWER] = zone == 1 ? n : 0;
    v->members[MPE_UPPER] = zone == 2 ? n : 0;
    for (int z = 0; z < 2; z++) {
        v->note_range[z] = setting(MPE_G_NOTE_RANGE, MPE_MAX_RANGE, MPE_DEFAULT_NOTE_RANGE);
        v->master_range[z] = setting(MPE_G_MASTER_RANGE, MPE_MAX_RANGE, MPE_DEFAULT_MASTER_RANGE);
    }
}

static void put_str(char **p, const char *s)
{
    while (*s)
        *(*p)++ = *s++;
}

static void put_num(char **p, uint32_t n)
{
    if (n >= 10)
        put_num(p, n / 10);
    *(*p)++ = (char)('0' + n % 10);
}

/* A number right-aligned in three columns, as stock prints them. */
static void put_num3(char **p, uint32_t n)
{
    for (uint32_t w = n >= 100 ? 3 : n >= 10 ? 2 : 1; w < 3; w++)
        *(*p)++ = ' ';
    put_num(p, n);
}

/* Lower and Upper value of a two-zone layout (only RPN 6 makes one): "7+7". */
static void put_pair(char **p, uint32_t lower, uint32_t upper)
{
    put_num(p, lower);
    *(*p)++ = '+';
    put_num(p, upper);
}

/* One item's value as the view has it, unpadded. With one zone (or none:
 * the Settings values) the ranges are that zone's. */
static void render_view(const struct mpe_live *v, uint32_t display, char *out)
{
    char *p = out;
    uint8_t lo = v->members[MPE_LOWER], up = v->members[MPE_UPPER];
    int z = lo || !up ? MPE_LOWER : MPE_UPPER;
    switch (display) {
    case DISP_ZONE:
        put_str(&p, lo && up ? "Lo+Up" : lo ? "Lower" : up ? "Upper" : "Off");
        break;
    case DISP_MEMBERS:
        if (lo && up)
            put_pair(&p, lo, up);
        else
            put_num3(&p, lo ? lo : up ? up : setting(MPE_G_MEMBERS, 15, MPE_DEFAULT_MEMBERS));
        break;
    case DISP_NOTE:
        if (lo && up)
            put_pair(&p, v->note_range[MPE_LOWER], v->note_range[MPE_UPPER]);
        else
            put_num3(&p, v->note_range[z]);
        break;
    case DISP_MASTER:
        if (lo && up)
            put_pair(&p, v->master_range[MPE_LOWER], v->master_range[MPE_UPPER]);
        else
            put_num3(&p, v->master_range[z]);
        break;
    }
    *p = 0;
}

/* The value field (FIELD characters, padded): the live value, '*' when it
 * differs from the Settings value. */
static void render(uint32_t display, char *out)
{
    struct mpe_live saved;
    char other[FIELD + 1];
    settings_view(&saved);
    render_view(&mpe_live, display, out);
    render_view(&saved, display, other);
    uint32_t n = 0;
    while (out[n])
        n++;
    int differs = 0;
    for (uint32_t i = 0; i <= n; i++)
        differs |= out[i] != other[i];
    if (differs && n < FIELD)
        out[n++] = '*';
    while (n < FIELD)
        out[n++] = ' ';
    out[n] = 0;
}

/* Replaces format_value in ui_draw_values' kind 3 case (0x080181D8). */
void mpe_ui_format(uint32_t display, uint32_t value)
{
    if (display < DISP_ZONE || display >= DISP_END) {
        format_value(display, value);
        return;
    }
    char *field = drawn[display - DISP_ZONE];
    render(display, field);
    lcd_puts(field);
}

static int on_mpe_page(const uint8_t *page)
{
    return UI_MODE == UI_MODE_SETTINGS &&
           (page == (const uint8_t *)&mpe_pages[0] || page == (const uint8_t *)&mpe_pages[1]);
}

/* Replaces main_loop's sysex_rx_poll call (0x0800D1C4), a call made once per
 * main-loop pass (the Peak has no mode_request_poll, which the Summit patch
 * wraps): redraws the MPE values when what they show changed (RPN, the
 * flag). */
void mpe_ui_poll(void)
{
    sysex_rx_poll();
    const uint8_t *page = ui_current_page();
    if (!on_mpe_page(page) || ui_message_active())
        return;
    const struct mpe_page *p = (const struct mpe_page *)page;
    for (uint32_t i = 0; i < p->n_items; i++) {
        uint32_t display = mpe_global_desc[p->item[i].index].display;
        char now[FIELD + 1];
        render(display, now);
        const char *was = drawn[display - DISP_ZONE];
        for (uint32_t k = 0; k < FIELD; k++)
            if (now[k] != was[k]) {
                ui_draw_values();
                return;
            }
    }
}

/* --- Editing -------------------------------------------------------------- */

static void edit_setting(uint16_t index, int32_t delta)
{
    if (index > MPE_G_MASTER_RANGE || delta == 0)  /* as stock, no reset for globals */
        return;
    mpe_live_to_globals();
    const struct mpe_desc *d = &mpe_global_desc[index];
    int32_t v;
    switch (index) {
    case MPE_G_ZONE:
        v = globals[MPE_G_ZONE];
        break;
    case MPE_G_MEMBERS:
        v = setting(MPE_G_MEMBERS, 15, MPE_DEFAULT_MEMBERS);
        break;
    case MPE_G_NOTE_RANGE:
        v = setting(MPE_G_NOTE_RANGE, MPE_MAX_RANGE, MPE_DEFAULT_NOTE_RANGE);
        break;
    default:
        v = setting(MPE_G_MASTER_RANGE, MPE_MAX_RANGE, MPE_DEFAULT_MASTER_RANGE);
        break;
    }
    v += delta;
    v = v < d->min ? d->min : v > d->max ? d->max : v;
    globals[index] = (uint8_t)v;
    mark_changed();  /* as param_write does for stock Settings edits */
    mpe_globals_to_live();
    ui_draw_values();
}

/* Replaces ui_value_change at 0x08016FC2 (encoder), 0x080170F2/0x080170FA
 * (value buttons) and 0x08018708 (ui_page_step). delta 0: back to the Init
 * Patch value, which is 0 for the flag. */
void mpe_ui_value_change(int32_t delta)
{
    const uint8_t *page = ui_current_page();
    const uint8_t *item = page + 6 + 4 * page[5];
    uint16_t index = (uint16_t)(item[2] | item[3] << 8);
    if (item[0] == 3 && on_mpe_page(page)) {
        edit_setting(index, delta);
        return;
    }
    if (item[0] != 1 || index != MPE_FLAG_OFFSET) {
        ui_value_change(delta);
        return;
    }
    uint8_t *flag = &mpe_patch()[MPE_FLAG_OFFSET];
    int32_t v = delta ? *flag + delta : 0;
    v = v < 0 ? 0 : v > 1 ? 1 : v;
    if (v != *flag) {
        *flag = (uint8_t)v;
        mark_changed();
    }
}
