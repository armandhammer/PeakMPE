/* Peak MPE core: global settings, live state, RPN 0 and RPN 6 (docs/mpe-design.md).
 *
 * The Settings layout (globals +0x30..+0x33) is copied into mpe_live at boot
 * and whenever the globals change (a Settings edit, a globals SysEx). RPN 6
 * (MPE Configuration Message) and RPN 0 (pitch bend sensitivity) change
 * mpe_live only; Settings Save writes mpe_live back to the globals before
 * the firmware saves them. So RPN changes are applied live and persist only
 * when saved.
 *
 * The firmware has no RPN state: CC 6 always goes to the part's last NRPN
 * (findings, "CC, NRPN and RPN"). mpe_rpn_cc keeps an RPN/NRPN selection
 * per channel, on every channel, and only takes the CCs away from the
 * firmware on a zone channel: elsewhere the firmware still gets them, as
 * stock.
 *
 * Hooks (patch.py): globals_apply_poll in the main loop (0x0800D1B6) and
 * settings_save in settings_save_action (0x08018FFA). Peak port: unchanged
 * from the Summit patch apart from these addresses.
 */

#include "mpe.h"

struct mpe_live mpe_live;

/* Item name of the per-patch flag (patch_param_desc[0x1A2].name, patch.py). */
const char mpe_flag_name[] = "MPE";

static uint8_t seen[4];      /* globals +0x30..+0x33 as last applied */
static uint8_t seen_valid;

/* Per channel: the last parameter number selected and whether it was an
 * RPN (CC 101/100) or an NRPN (CC 99/98). */
static uint8_t rpn_msb[16], rpn_lsb[16], rpn_selected[16];

__attribute__((weak)) void mpe_live_changed(void) {}

void mpe_settings_init(void)
{
    for (int ch = 0; ch < 16; ch++)
        rpn_msb[ch] = rpn_lsb[ch] = 0x7F;  /* RPN null */
    for (int z = 0; z < 2; z++) {
        mpe_live.note_range[z] = MPE_DEFAULT_NOTE_RANGE;
        mpe_live.master_range[z] = MPE_DEFAULT_MASTER_RANGE;
    }
}

static uint8_t setting(uint32_t offset, uint8_t max, uint8_t fallback)
{
    uint8_t v = globals[offset];
    return v == 0 || v > max ? fallback : v;
}

static void reset_ranges(int z)
{
    mpe_live.note_range[z] = setting(MPE_G_NOTE_RANGE, MPE_MAX_RANGE, MPE_DEFAULT_NOTE_RANGE);
    mpe_live.master_range[z] = setting(MPE_G_MASTER_RANGE, MPE_MAX_RANGE, MPE_DEFAULT_MASTER_RANGE);
}

static void load_from_globals(void)
{
    uint8_t zone = globals[MPE_G_ZONE];
    uint8_t n = setting(MPE_G_MEMBERS, 15, MPE_DEFAULT_MEMBERS);
    mpe_live.members[MPE_LOWER] = zone == 1 ? n : 0;
    mpe_live.members[MPE_UPPER] = zone == 2 ? n : 0;
    reset_ranges(MPE_LOWER);
    reset_ranges(MPE_UPPER);
}

/* Takes over a changed Settings layout and refreshes the routing. Inlined
 * into the main-loop hook, so a pass costs what it did in step 1. */
static inline __attribute__((always_inline)) void take_globals(void)
{
    int changed = !seen_valid;
    for (int i = 0; i < 4; i++)
        if (globals[MPE_G_ZONE + i] != seen[i]) {
            seen[i] = globals[MPE_G_ZONE + i];
            changed = 1;
        }
    if (changed) {
        seen_valid = 1;
        load_from_globals();
    }
    mpe_route_update();  /* keeps mpe_zones current for the UI after flag and mode changes */
    if (changed)
        mpe_live_changed();
}

/* Replaces main_loop's globals_apply_poll call: runs it, then takes over a
 * changed Settings layout and refreshes the routing. */
void mpe_globals_apply_poll(void)
{
    globals_apply_poll();
    take_globals();
}

/* The same now, as the main loop would; the Settings page calls it after an
 * edit. */
void mpe_globals_to_live(void)
{
    take_globals();
}

/* The live state into globals +0x30..+0x33, as Save stores it. A two-zone
 * layout (only RPN 6 can make one) goes in as its Lower Zone. With no zone
 * the member count setting stays as it is. A range of 0 (RPN 0 can set it)
 * goes in as 0, which reads as the default. */
void mpe_live_to_globals(void)
{
    int z = mpe_live.members[MPE_LOWER] || !mpe_live.members[MPE_UPPER] ? MPE_LOWER : MPE_UPPER;
    uint8_t n = mpe_live.members[z];
    globals[MPE_G_ZONE] = n ? (uint8_t)(z + 1) : 0;
    if (n)
        globals[MPE_G_MEMBERS] = n;
    globals[MPE_G_NOTE_RANGE] = mpe_live.note_range[z];
    globals[MPE_G_MASTER_RANGE] = mpe_live.master_range[z];
    for (int i = 0; i < 4; i++)
        seen[i] = globals[MPE_G_ZONE + i];
}

/* Replaces settings_save_action's settings_save call: the live state is
 * what gets saved. */
void mpe_settings_save(void)
{
    mpe_live_to_globals();
    settings_save();
}

/* MPE Configuration Message on channel 1 (Lower) or 16 (Upper): n member
 * channels, 0 = no such zone. The other zone shrinks to what is left, as
 * the MPE spec has it, and the zone's bend ranges go back to the Settings
 * values (the defaults, ±48 and ±2, unless changed there). */
static void configure(int z, uint8_t n)
{
    if (n > 15)
        n = 15;
    mpe_live.members[z] = n;
    uint8_t *other = &mpe_live.members[!z];
    if (*other && n + *other > 14)
        *other = n >= 14 ? 0 : (uint8_t)(14 - n);
    reset_ranges(z);
}

/* The zone kind of ch for RPN 0: the zone in use (z), otherwise the
 * configured layout, so a range can be set before an MPE patch is chosen.
 * -1: neither. */
static int range_zone(uint8_t ch, const struct mpe_zone *z)
{
    if (z)
        return z->master == 0 ? MPE_LOWER : MPE_UPPER;
    if (mpe_live.members[MPE_LOWER] && ch <= mpe_live.members[MPE_LOWER])
        return MPE_LOWER;
    if (mpe_live.members[MPE_UPPER] && ch >= 15 - mpe_live.members[MPE_UPPER])
        return MPE_UPPER;
    return -1;
}

static void data_entry(uint8_t ch, uint8_t value, const struct mpe_zone *z)
{
    int kind;
    if (rpn_msb[ch] != 0)
        return;
    if (rpn_lsb[ch] == 0 && (kind = range_zone(ch, z)) >= 0) {  /* RPN 0: bend range */
        if (value > MPE_MAX_RANGE)
            value = MPE_MAX_RANGE;
        if (ch == 0 || ch == 15)
            mpe_live.master_range[kind] = value;
        else
            mpe_live.note_range[kind] = value;
    } else if (rpn_lsb[ch] == 6 && (ch == 0 || ch == 15)) {  /* RPN 6: MCM */
        configure(ch == 0 ? MPE_LOWER : MPE_UPPER, value);
        mpe_route_update();
    } else {
        return;
    }
    mpe_live_changed();
}

/* One CC on channel ch, zone z (0 when ch is in none). Tracks the RPN/NRPN
 * selection and applies RPN 0 and RPN 6. Returns 1 when the CC belongs to
 * the MPE patch and mustn't reach the firmware's cc: an RPN select or RPN
 * data on a zone channel. NRPN keeps working as stock. */
int mpe_rpn_cc(uint8_t ch, uint8_t cc, uint8_t value, const struct mpe_zone *z)
{
    switch (cc) {
    case 101:
    case 100:
        if (cc == 101)
            rpn_msb[ch] = value;
        else
            rpn_lsb[ch] = value;
        rpn_selected[ch] = !(rpn_msb[ch] == 0x7F && rpn_lsb[ch] == 0x7F);
        return z != 0;
    case 99:
    case 98:
        rpn_selected[ch] = 0;
        return 0;
    case 6:
        if (!rpn_selected[ch])
            return 0;
        data_entry(ch, value, z);
        return z != 0;
    case 38:  /* data LSB: cents of RPN 0, not used */
        return rpn_selected[ch] && z != 0;
    default:
        return 0;
    }
}
