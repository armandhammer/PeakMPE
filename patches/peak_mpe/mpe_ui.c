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
 * Settings: four pages after MIDI CONTROL (where the Peak has its MIDI
 * channel), so Settings has 30 pages.
 *   MPE             Zone (Off/Lower/Upper), Members (1-15)
 *   MPE BEND RANGE  Note Bend, MasterBend (semitones, 1-96)
 *   MPE EXTRAS      PressCurve (Squared/Linear), EnvSync (Off, 1/2-1/16),
 *                   Glide (Stock/LastNote/Legato)
 *   PARAM LOCK      Lock FX, Lock Arp, Lock Voice (Off/On)
 *   COPY SECTION, MIDI MONITOR (section.c, diag.c)
 *   MOTION          Length (1, 2, 4 bars); read-only: the recorder's state, LateTicks
 *   MORPH           Morph (Off/ModWheel); read-only: the position, the number of
 *                   controls that differ (morph.c)
 *   ARP EUCLID      Pulses (Off, 1-32), Steps (1-32), Rotate (euclid.c)
 *   ARP RATCHET     Ratchet (Off, x2, x3), Every (1-8) (euclid.c)
 *   RELEASE VEL     Source (Off, ExprPED1, BrthPED2) (relvel.c)
 *   RANDOMISE       Section, Amount (10-100 %), Roll (rand.c)
 *   PATCH DUMP      Send (Off, USB) (pdump.c)
 *   PATCH TIMING    Change at (Now, Beat, Bar, 2 Bars, 4 Bars) (ptime.c)
 * The Summit's read-only "Channels" item (CH CLASH) is left out: the Peak has
 * no Multi parts whose channels a zone could take.
 * The items are kind 3 (global settings) with records 0x30-0x38, which stock
 * global_param_desc doesn't have (0x22 records on the Peak). So the
 * descriptor table and the Settings menu move to patch RAM, filled at boot
 * from the stock RAM copies plus the new entries. The three literals of
 * global_param_desc point at the new table (patch.py); menus[8] is set when
 * the menu is built.
 *
 * The pages show what is in effect, mpe_live (the Settings layout plus what
 * RPN 6 and RPN 0 changed), through display types from 0xA0 (0xE0 until
 * v0.30, when 0xFE was the last free code below 0xFF), which stock
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
#define MPE_G_LAST (MPE_G_PFILTER + 5)  /* the last record of new_descs */
#define MPE_DESCS (MPE_G_LAST + 1)
#define MPE_PAGE_AT 4              /* after MIDI CONTROL (stock page 3) */
#define MPE_PAGES 16
#define STOCK_PAGES PEAK_SETTINGS_PAGES
#define UI_MODE_SETTINGS PEAK_UI_SETTINGS
#define UI_MODE (ui_state[0])

enum { DISP_ZONE = 0xA0, DISP_MEMBERS, DISP_NOTE, DISP_MASTER, DISP_CURVE, DISP_ENVSYNC, DISP_LOCK_FX, DISP_LOCK_ARP, DISP_LOCK_VOICE, DISP_SECT, DISP_DOIT, DISP_DLAST, DISP_DCOUNT, DISP_DOVF, DISP_GLIDE, DISP_MLEN, DISP_MSTATE, DISP_LATE, DISP_MORPH, DISP_MPOS, DISP_MDIFF, DISP_EPULSES, DISP_ESTEPS, DISP_EROTATE, DISP_ERATCHET, DISP_EEVERY, DISP_RELVEL, DISP_RSECT, DISP_RAMT, DISP_ROLL, DISP_PDUMP, DISP_PTIME, DISP_PF0, DISP_PF1, DISP_PF2, DISP_PF3, DISP_PF4, DISP_PF5, DISP_END };

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
static const char title_extra[] = "MPE EXTRAS";
static const char title_lock[] = "PARAM LOCK";
static const char title_sect[] = "COPY SECTION";
static const char title_mon[] = "MIDI MONITOR";
static const char title_motion[] = "MOTION";
static const char title_morph[] = "MORPH";
static const char title_euclid[] = "ARP EUCLID";
static const char title_ratchet[] = "ARP RATCHET";
static const char title_relvel[] = "RELEASE VEL";
static const char title_rand[] = "RANDOMISE";
static const char title_pdump[] = "PATCH DUMP";
static const char title_ptime[] = "PATCH TIMING";
static const char title_usb_in[] = "USB IN";
static const char title_din_in[] = "DIN IN";

static const struct mpe_desc new_descs[] = {
    {0, 2, 0x40, 0x2E, DISP_ZONE, "Zone"},
    {1, 15, 0x40, 0x2F, DISP_MEMBERS, "Members"},
    {1, MPE_MAX_RANGE, 0x40, 0x30, DISP_NOTE, "Note Bend"},
    {1, MPE_MAX_RANGE, 0x40, 0x31, DISP_MASTER, "MasterBend"},
    {0, 1, 0x40, 0x32, DISP_CURVE, "PressCurve"},
    {0, 4, 0x40, 0x33, DISP_ENVSYNC, "EnvSync"},
    {0, 1, 0x40, 0x34, DISP_LOCK_FX, "Lock FX"},
    {0, 1, 0x40, 0x35, DISP_LOCK_ARP, "Lock Arp"},
    {0, 1, 0x40, 0x36, DISP_LOCK_VOICE, "Lock Voice"},
    {0, 0, 0xFF, 0x00, DISP_SECT, "Section"},         /* records 0x39-0x3D follow the globals' numbers; not stored */
    {0, 0, 0xFF, 0x00, DISP_DOIT, "Do it"},
    {0, 0, 0xFF, 0x00, DISP_DLAST, "Last msg"},
    {0, 0, 0xFF, 0x00, DISP_DCOUNT, "Msg count"},
    {0, 0, 0xFF, 0x00, DISP_DOVF, "DIN ovfl"},
    {0, 2, 0x40, 0x37, DISP_GLIDE, "Glide"},          /* records 0x3E, 0x3F: stored in the globals again */
    {0, 2, 0x40, 0x38, DISP_MLEN, "Length"},
    {0, 1, 0x40, 0x39, DISP_MORPH, "Morph"},          /* record 0x40: the last one stored in the globals */
    {0, 0, 0xFF, 0x00, DISP_MSTATE, "Motion"},        /* records 0x41-0x44: read-only, not stored */
    {0, 0, 0xFF, 0x00, DISP_LATE, "LateTicks"},
    {0, 0, 0xFF, 0x00, DISP_MPOS, "Position"},
    {0, 0, 0xFF, 0x00, DISP_MDIFF, "Differ"},
    {0, 32, 0x40, 0x3A, DISP_EPULSES, "Pulses"},      /* records 0x45-0x47: stored in the globals */
    {1, 32, 0x40, 0x3B, DISP_ESTEPS, "Steps"},
    {0, 31, 0x40, 0x3C, DISP_EROTATE, "Rotate"},
    {0, 2, 0x40, 0x3D, DISP_ERATCHET, "Ratchet"},     /* records 0x48, 0x49: stored in the globals */
    {1, 8, 0x40, 0x3E, DISP_EEVERY, "Every"},
    {0, 2, 0x40, 0x3F, DISP_RELVEL, "Source"},        /* record 0x4A: stored in the globals */
    {0, 0, 0xFF, 0x00, DISP_RSECT, "Section"},        /* records 0x4B-0x4D: not stored (rand.c) */
    {0, 0, 0xFF, 0x00, DISP_RAMT, "Amount"},
    {0, 0, 0xFF, 0x00, DISP_ROLL, "Roll"},
    {0, 1, 0x40, 0x40, DISP_PDUMP, "Send"},           /* record 0x4E: stored in the globals */
    {0, 4, 0x40, 0x41, DISP_PTIME, "Change at"},      /* record 0x4F: stored in the globals */
    {0, 1, 0x40, 0x42, DISP_PF0, "Notes"},            /* records 0x50-0x55: stored in the globals (pfilter.c); */
    {0, 1, 0x40, 0x43, DISP_PF1, "CC"},               /* the value here is 1 On, 0 Off, the stored byte 0 On, 1 Off */
    {0, 1, 0x40, 0x44, DISP_PF2, "Patch"},
    {0, 1, 0x40, 0x45, DISP_PF3, "Notes"},
    {0, 1, 0x40, 0x46, DISP_PF4, "CC"},
    {0, 1, 0x40, 0x47, DISP_PF5, "Patch"},
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
    for (uint32_t i = 0; i <= MPE_G_LAST - MPE_G_ZONE; i++)
        mpe_global_desc[MPE_G_ZONE + i] = new_descs[i];

    page_init(&mpe_pages[0], title_zone);
    page_item(&mpe_pages[0], MPE_G_ZONE);
    page_item(&mpe_pages[0], MPE_G_MEMBERS);
    page_init(&mpe_pages[1], title_bend);
    page_item(&mpe_pages[1], MPE_G_NOTE_RANGE);
    page_item(&mpe_pages[1], MPE_G_MASTER_RANGE);
    page_init(&mpe_pages[2], title_extra);
    page_item(&mpe_pages[2], MPE_G_CURVE);
    page_item(&mpe_pages[2], MPE_G_ENVSYNC);
    page_item(&mpe_pages[2], MPE_G_GLIDE);
    page_init(&mpe_pages[3], title_lock);
    page_item(&mpe_pages[3], MPE_G_LOCK_FX);
    page_item(&mpe_pages[3], MPE_G_LOCK_FX + 1);
    page_item(&mpe_pages[3], MPE_G_LOCK_FX + 2);
    page_init(&mpe_pages[4], title_sect);
    page_item(&mpe_pages[4], MPE_G_SECT);
    page_item(&mpe_pages[4], MPE_G_DOIT);
    page_init(&mpe_pages[5], title_mon);
    page_item(&mpe_pages[5], MPE_G_DIAG);
    page_item(&mpe_pages[5], MPE_G_DIAG + 1);
    page_item(&mpe_pages[5], MPE_G_DIAG + 2);
    page_init(&mpe_pages[6], title_motion);
    page_item(&mpe_pages[6], MPE_G_MOTION_LEN);
    page_item(&mpe_pages[6], MPE_G_MOTION_STATE);
    page_item(&mpe_pages[6], MPE_G_LATE);
    page_init(&mpe_pages[7], title_morph);
    page_item(&mpe_pages[7], MPE_G_MORPH);
    page_item(&mpe_pages[7], MPE_G_MORPH_POS);
    page_item(&mpe_pages[7], MPE_G_MORPH_N);
    page_init(&mpe_pages[8], title_euclid);
    page_item(&mpe_pages[8], MPE_G_EUC_PULSES);
    page_item(&mpe_pages[8], MPE_G_EUC_STEPS);
    page_item(&mpe_pages[8], MPE_G_EUC_ROTATE);
    page_init(&mpe_pages[9], title_ratchet);
    page_item(&mpe_pages[9], MPE_G_EUC_RATCHET);
    page_item(&mpe_pages[9], MPE_G_EUC_EVERY);
    page_init(&mpe_pages[10], title_relvel);
    page_item(&mpe_pages[10], MPE_G_RELVEL);
    page_init(&mpe_pages[11], title_rand);
    page_item(&mpe_pages[11], MPE_G_RAND_SECT);
    page_item(&mpe_pages[11], MPE_G_RAND_AMT);
    page_item(&mpe_pages[11], MPE_G_RAND_ROLL);
    page_init(&mpe_pages[12], title_pdump);
    page_item(&mpe_pages[12], MPE_G_PDUMP);
    page_init(&mpe_pages[13], title_ptime);
    page_item(&mpe_pages[13], MPE_G_PTIME);
    page_init(&mpe_pages[14], title_usb_in);
    page_init(&mpe_pages[15], title_din_in);
    for (uint32_t i = 0; i < 3; i++) {
        page_item(&mpe_pages[14], (uint16_t)(MPE_G_PFILTER + i));
        page_item(&mpe_pages[15], (uint16_t)(MPE_G_PFILTER + 3 + i));
    }

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
    ptime_boot();
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
    case DISP_CURVE:
        put_str(&p, globals[MPE_G_CURVE] == 1 ? "Linear" : "Squared");
        break;
    case DISP_SECT:
        put_str(&p, section_name(section_op()));
        break;
    case DISP_DOIT:
        put_str(&p, "Off");        /* set to Yes: copies, shows a message, goes back to Off */
        break;
    case DISP_DLAST:
    case DISP_DCOUNT:
    case DISP_DOVF: {
        char buf[16];
        diag_text(display - DISP_DLAST, buf);
        put_str(&p, buf);
        break;
    }
    case DISP_LOCK_FX:
    case DISP_LOCK_ARP:
    case DISP_LOCK_VOICE:
        put_str(&p, globals[MPE_G_LOCK_FX + (display - DISP_LOCK_FX)] == 1 ? "On" : "Off");
        break;
    case DISP_ENVSYNC: {
        static const char *const names[] = {"Off", "1/2", "1/4", "1/8", "1/16"};
        uint8_t n = globals[MPE_G_ENVSYNC];
        put_str(&p, names[n > 4 ? 0 : n]);
        break;
    }
    case DISP_MLEN: {
        static const char *const names[] = {"1 bar", "2 bars", "4 bars"};
        uint8_t n = globals[MPE_G_MOTION_LEN];
        put_str(&p, names[n > 2 ? 0 : n]);
        break;
    }
    case DISP_MSTATE:
        put_str(&p, motion_state_name());
        break;
    case DISP_MORPH:
        put_str(&p, globals[MPE_G_MORPH] == 1 ? "ModWheel" : "Off");
        break;
    case DISP_MPOS:
        put_num3(&p, morph_position());
        break;
    case DISP_MDIFF:
        put_num3(&p, morph_differ());
        break;
    case DISP_EPULSES:
        if (euclid_pulses())
            put_num3(&p, euclid_pulses());
        else
            put_str(&p, "Off");
        break;
    case DISP_ESTEPS:
        put_num3(&p, euclid_steps());
        break;
    case DISP_EROTATE:
        put_num3(&p, euclid_rotate());
        break;
    case DISP_ERATCHET: {
        static const char *const names[] = {"Off", "x2", "x3"};
        put_str(&p, names[euclid_ratchet() - 1]);
        break;
    }
    case DISP_EEVERY:
        put_num3(&p, euclid_every());
        break;
    case DISP_LATE: {
        char buf[16];
        diag_late_text(buf);
        put_str(&p, buf);
        break;
    }
    case DISP_GLIDE: {
        static const char *const names[] = {"Stock", "LastNote", "Legato"};
        uint8_t n = globals[MPE_G_GLIDE];
        put_str(&p, names[n > 2 ? 0 : n]);
        break;
    }
    case DISP_RSECT:
        put_str(&p, rand_section_name());
        break;
    case DISP_RAMT:
        put_num3(&p, rand_amount() * 10);
        *p++ = '%';
        break;
    case DISP_ROLL:
        put_str(&p, "Off");        /* turned up: one roll, a message, back to Off */
        break;
    case DISP_RELVEL: {
        static const char *const names[] = {"Off", "ExprPED1", "BrthPED2"};   /* the guide's source names */
        uint8_t n = globals[MPE_G_RELVEL];
        put_str(&p, names[n > 2 ? 0 : n]);
        break;
    }
    case DISP_PDUMP:
        put_str(&p, pdump_on() ? "USB" : "Off");
        break;
    case DISP_PTIME: {
        static const char *const names[] = {"Now", "Beat", "Bar", "2 Bars", "4 Bars"};
        uint8_t n = globals[MPE_G_PTIME];
        put_str(&p, names[n > 4 ? 0 : n]);
        break;
    }
    case DISP_PF0:
    case DISP_PF1:
    case DISP_PF2:
    case DISP_PF3:
    case DISP_PF4:
    case DISP_PF5:
        put_str(&p, globals[MPE_G_PFILTER + (display - DISP_PF0)] == 1 ? "Off" : "On");
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
    if (display == DISP_LATE)      /* a reading is taken only when stock draws the page: see diag.c */
        diag_latch();
    render(display, field);
    lcd_puts(field);
}

static int on_mpe_page(const uint8_t *page)
{
    if (UI_MODE != UI_MODE_SETTINGS)
        return 0;
    for (uint32_t k = 0; k < MPE_PAGES; k++)
        if (page == (const uint8_t *)&mpe_pages[k])
            return 1;
    return 0;
}

/* Replaces main_loop's sysex_rx_poll call (0x0800D1C4), a call made once per
 * main-loop pass (the Peak has no mode_request_poll, which the Summit patch
 * wraps): redraws the MPE values when what they show changed (RPN, the
 * flag). */
static uint32_t polled;      /* the modulation tick the polls below last ran in */

void mpe_ui_poll(void)
{
    sysex_rx_poll();
    /* The main loop passes about 70 times a millisecond (emulated); nothing below
     * needs more than one look per 1 kHz tick, and each look costs the loop
     * (test_mpe_off_writes_as_stock; findings, "Main-loop pace in the simulator"). */
    uint32_t now = mpe_ticks();
    if (now == polled)
        return;
    polled = now;
    disp_poll();
    envsync_poll();
    ui_hold_poll();
    motion_poll();
    morph_poll();
    pdump_poll();
    ptime_poll();
    if (UI_MODE != UI_MODE_SETTINGS)   /* before ui_current_page: only a Settings page can be ours */
        return;
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
    if (index > MPE_G_LAST || delta == 0)   /* as stock, no reset for globals */
        return;
    if (index > MPE_G_MORPH && index < MPE_G_EUC_PULSES)   /* the records between are read-only */
        return;
    if (index >= MPE_G_SECT && index <= MPE_G_DIAG + 2) {  /* COPY SECTION (section.c); the monitor items are read-only */
        if (index <= MPE_G_DOIT) {
            section_edit(index, delta);
            if (index == MPE_G_SECT)   /* "Do it" draws its own message; a redraw would wipe it */
                ui_draw_values();
        }
        return;
    }
    if (index >= MPE_G_RAND_SECT && index <= MPE_G_RAND_ROLL) {   /* RANDOMISE (rand.c), not stored */
        rand_edit(index, delta);
        if (index != MPE_G_RAND_ROLL)  /* Roll draws its own message */
            ui_draw_values();
        return;
    }
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
    case MPE_G_CURVE:
        v = globals[MPE_G_CURVE] == 1;
        break;
    case MPE_G_ENVSYNC:
    case MPE_G_PTIME:
        v = globals[index] > 4 ? 0 : globals[index];
        break;
    case MPE_G_GLIDE:
        v = globals[MPE_G_GLIDE] > 2 ? 0 : globals[MPE_G_GLIDE];
        break;
    case MPE_G_MOTION_LEN:
    case MPE_G_RELVEL:
        v = globals[index] > 2 ? 0 : globals[index];
        break;
    case MPE_G_LOCK_FX:
    case MPE_G_LOCK_FX + 1:
    case MPE_G_LOCK_FX + 2:
    case MPE_G_MORPH:
    case MPE_G_PDUMP:
        v = globals[index] == 1;
        break;
    case MPE_G_EUC_PULSES:
        v = (int32_t)euclid_pulses();
        break;
    case MPE_G_EUC_STEPS:
        v = (int32_t)euclid_steps();
        break;
    case MPE_G_EUC_ROTATE:
        v = (int32_t)euclid_rotate();
        break;
    case MPE_G_EUC_RATCHET:
        v = (int32_t)euclid_ratchet() - 1;
        break;
    case MPE_G_EUC_EVERY:
        v = (int32_t)euclid_every();
        break;
    case MPE_G_PFILTER:
    case MPE_G_PFILTER + 1:
    case MPE_G_PFILTER + 2:
    case MPE_G_PFILTER + 3:
    case MPE_G_PFILTER + 4:
    case MPE_G_PFILTER + 5:
        v = globals[index] != 1;     /* shown and edited as 1 On, 0 Off */
        break;
    default:
        v = setting(MPE_G_MASTER_RANGE, MPE_MAX_RANGE, MPE_DEFAULT_MASTER_RANGE);
        break;
    }
    v += delta;
    v = v < d->min ? d->min : v > d->max ? d->max : v;
    if (index == MPE_G_EUC_PULSES && v > (int32_t)euclid_steps())
        v = (int32_t)euclid_steps();          /* no more notes than steps */
    if (index == MPE_G_EUC_ROTATE && v >= (int32_t)euclid_steps())
        v = (int32_t)euclid_steps() - 1;
    if (index >= MPE_G_PFILTER)
        v = !v;                      /* stored 0 On, 1 Off: stock behaviour is the default */
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
    if (qa_encoder(delta))    /* Mod held: the encoder chooses the quick-assign source */
        return;
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
