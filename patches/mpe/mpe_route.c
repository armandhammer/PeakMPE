/* MPE core: zone routing and the channel filter (docs/mpe-design.md).
 *
 * Both of midi_parse_byte's calls of midi_channel_filter (0x08010804,
 * 0x08010864) come here. A message on a channel of a zone in use goes to
 * that zone's part; every other message goes to the stock filter unchanged,
 * so parts with MPE off, and the whole synth with MPE off everywhere, behave
 * as stock. Zone channels are checked first, so the zone wins a channel
 * conflict (the design's rule): a Multi part whose channel lies in a zone,
 * or the Multi global channel, can't be reached there.
 *
 * Zone routing, from the live layout (mpe_live) and the flags:
 *   Single, MPE on      every configured zone plays Part A; none configured:
 *                       the Lower Zone with 15 members
 *   Multi, A and B on   A = Lower, B = Upper. Both zones configured (RPN 6):
 *                       as configured. Otherwise Lower n (the configured
 *                       Lower count, at most 13; 7 if Lower isn't
 *                       configured) and Upper 14 - n
 *   Multi, one part on  that part takes the configured zone (the Lower one
 *                       if both are); none configured: Lower, 15 members
 *
 * In a zone, the master channel works as a normal channel of its part: notes,
 * bend, pressure, CCs, program change go to the firmware's handlers. Member
 * channels play notes (bound to their channel, mpe_voice.c), take RPN, and
 * pass CC 120 and 123-127 (all sound / notes off, mode messages) to the part;
 * bend, pressure and CC 74 are stored per channel for the expression step;
 * everything else on a member channel is dropped.
 *
 * A note-off goes first to the part of an active voice bound to its channel
 * and note, wherever the channel is routed now, so a layout or flag change
 * while notes are held leaves nothing stuck.
 */

#include "mpe.h"

struct mpe_zone mpe_zones[2];
uint8_t mpe_clash;
int16_t mpe_chan_bend[16];
uint8_t mpe_chan_pressure[16];
uint8_t mpe_chan_slide[16];
uint8_t mpe_rx_channel;

__attribute__((weak)) void mpe_member_message(const struct mpe_zone *z, uint8_t ch, const uint8_t *msg)
{
    (void)z, (void)ch, (void)msg;
}

int mpe_part_on(uint32_t part)
{
    return mpe_patch(part)[MPE_FLAG_OFFSET] == 1;
}

static void set_zone(int kind, uint8_t members, uint8_t part)
{
    struct mpe_zone *z = &mpe_zones[kind];
    if (!members || part == MPE_NONE) {
        z->part = MPE_NONE;
        return;
    }
    z->part = part;
    if (kind == MPE_LOWER) {
        z->master = 0;
        z->first = 1;
        z->last = members;
    } else {
        z->master = 15;
        z->first = (uint8_t)(15 - members);
        z->last = 14;
    }
}

static int in_zone(const struct mpe_zone *z, uint8_t ch)
{
    return z->part != MPE_NONE && (ch == z->master || (ch >= z->first && ch <= z->last));
}

void mpe_route_update(void)
{
    uint8_t lower = mpe_live.members[MPE_LOWER], upper = mpe_live.members[MPE_UPPER];
    uint8_t lower_part = MPE_NONE, upper_part = MPE_NONE;

    if (!multi_mode) {
        if (mpe_part_on(0)) {
            if (!lower && !upper)
                lower = MPE_DEFAULT_MEMBERS;
            lower_part = upper_part = 0;
        }
    } else {
        int a = mpe_part_on(0), b = mpe_part_on(1);
        if (a && b) {
            if (!(lower && upper)) {
                lower = !lower ? 7 : lower > 13 ? 13 : lower;
                upper = (uint8_t)(14 - lower);
            }
            lower_part = 0;
            upper_part = 1;
        } else if (a || b) {
            uint8_t part = b;
            if (lower || !upper) {
                if (!lower)
                    lower = MPE_DEFAULT_MEMBERS;
                lower_part = part;
            } else {
                upper_part = part;
            }
        }
    }
    set_zone(MPE_LOWER, lower, lower_part);
    set_zone(MPE_UPPER, upper, upper_part);

    mpe_clash = 0;
    if (multi_mode) {
        if (!mpe_part_on(0) && mpe_zone_of(midi_part_a_channel))
            mpe_clash |= 1;
        if (!mpe_part_on(1) && mpe_zone_of(midi_part_b_channel))
            mpe_clash |= 2;
        if (mpe_zone_of(midi_global_channel))
            mpe_clash |= 4;
    }
}

const struct mpe_zone *mpe_zone_of(uint8_t ch)
{
    for (int k = 0; k < 2; k++)
        if (in_zone(&mpe_zones[k], ch))
            return &mpe_zones[k];
    return 0;
}

/* The part of an active voice bound to ch that plays note, or -1. */
static int bound_part(uint8_t ch, uint8_t note)
{
    for (uint32_t v = 0; v < 16; v++)
        if (voice_channel[v] == ch && voice_note[v] == note && voice_state[0x334 + v])
            return multi_mode && v >= 8 ? 1 : 0;
    return -1;
}

/* Calls the handler for part, as the stock filter does (it sets edit_part
 * only in Multi, and puts it back afterwards), with mpe_rx_channel set. */
static void deliver(uint32_t part, uint8_t ch, uint32_t src, midi_handler_fn *handler, const uint8_t *msg)
{
    uint8_t saved = edit_part;
    if (multi_mode)
        edit_part = (uint8_t)part;
    midi_current_part = (uint8_t)part;
    mpe_rx_channel = ch;
    handler(msg + 1, src, 0, 0);
    mpe_rx_channel = MPE_NONE;
    if (multi_mode)
        edit_part = saved;
}

/* Replaces midi_channel_filter (src, handler, msg) at both call sites. */
void mpe_channel_filter(uint32_t src, midi_handler_fn *handler, const uint8_t *msg)
{
    uint8_t status = msg[0];
    if (status >= 0xF0) {
        midi_channel_filter(src, handler, msg);
        return;
    }
    uint8_t ch = status & 0x0F, type = status & 0xF0;
    mpe_route_update();
    const struct mpe_zone *z = mpe_zone_of(ch);

    if (type == 0xB0 && mpe_rpn_cc(ch, msg[1], msg[2], z))
        return;
    if (type == 0x80 || (type == 0x90 && msg[2] == 0)) {
        int part = bound_part(ch, msg[1]);
        if (part >= 0) {
            deliver((uint32_t)part, ch, src, handler, msg);
            return;
        }
    }
    if (!z) {
        midi_channel_filter(src, handler, msg);
        return;
    }
    if (ch != z->master) {
        switch (type) {
        case 0x80:
        case 0x90:
            break;
        case 0xB0:
            if (msg[1] == 120 || msg[1] >= 123)
                break;
            if (msg[1] == 74)
                mpe_chan_slide[ch] = msg[2];
            mpe_member_message(z, ch, msg);
            return;
        case 0xD0:
            mpe_chan_pressure[ch] = msg[1];
            mpe_member_message(z, ch, msg);
            return;
        case 0xE0:
            mpe_chan_bend[ch] = (int16_t)(((msg[2] << 7) | msg[1]) - 8192);
            mpe_member_message(z, ch, msg);
            return;
        default:
            mpe_member_message(z, ch, msg);
            return;
        }
    }
    deliver(z->part, ch, src, handler, msg);
}
