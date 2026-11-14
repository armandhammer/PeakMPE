/* Peak MPE core: zone routing and the channel filter.
 *
 * Both of midi_parse_byte's calls of midi_channel_filter (0x0800F014,
 * 0x0800F074) come here. A message on a channel of a zone in use goes to the
 * patch's handlers; every other message goes to the stock filter unchanged,
 * so with MPE off the synth behaves as stock. Zone channels are checked
 * first, so the zone wins over the Peak's own MIDI channel.
 *
 * Zones, from the live layout (mpe_live), when the patch has MPE on:
 *   every configured zone plays the patch; none configured: the Lower Zone
 *   with 15 members. Both zones at once (RPN 6 for each, as a LinnStrument
 *   sends with both splits in MPE) share the 8 voices.
 *
 * In a zone, the master channel works as the Peak's normal channel: notes,
 * bend, pressure, CCs, program change go to the firmware's handlers. Member
 * channels play notes (bound to their channel, mpe_voice.c), take RPN, and
 * pass CC 120 and 123-127 (all sound / notes off, mode messages); bend,
 * pressure (channel or poly) and CC 74 are stored per channel for the
 * expression modules; everything else on a member channel is dropped.
 *
 * A note-off goes first to an active voice bound to its channel and note,
 * wherever the channel is routed now, so a layout or flag change while
 * notes are held leaves nothing stuck.
 *
 * The Peak has no Multi mode, so there are no part channels and no channel
 * clash to report (the Summit patch's mpe_clash).
 */

#include "mpe.h"

struct mpe_zone mpe_zones[2];
int16_t mpe_chan_bend[16];
int16_t mpe_master_bend[2];
uint8_t mpe_chan_pressure[16];
uint8_t mpe_chan_slide[16];
uint8_t mpe_rx_channel;

__attribute__((weak)) void mpe_member_message(const struct mpe_zone *z, uint8_t ch, const uint8_t *msg)
{
    (void)z, (void)ch, (void)msg;
}

int mpe_part_on(uint32_t part)
{
    (void)part;
    return mpe_patch()[MPE_FLAG_OFFSET] == 1;
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
    uint8_t part = MPE_NONE;
    if (mpe_part_on(0)) {
        if (!lower && !upper)
            lower = MPE_DEFAULT_MEMBERS;
        part = 0;
    }
    set_zone(MPE_LOWER, lower, part);
    set_zone(MPE_UPPER, upper, part);
}

const struct mpe_zone *mpe_zone_of(uint8_t ch)
{
    for (int k = 0; k < 2; k++)
        if (in_zone(&mpe_zones[k], ch))
            return &mpe_zones[k];
    return 0;
}

/* An active voice is bound to ch and plays note. */
static int bound(uint8_t ch, uint8_t note)
{
    for (uint32_t v = 0; v < MPE_VOICES; v++)
        if (voice_channel[v] == ch && voice_note[v] == note && VOICE_GATE(v))
            return 1;
    return 0;
}

/* Calls the handler as the stock filter does (0x0800EEEA: parts+0 = the
 * patch, then handler(msg + 1, src)), with mpe_rx_channel set. */
static void deliver(uint8_t ch, uint32_t src, midi_handler_fn *handler, const uint8_t *msg)
{
    *(uint8_t *volatile *)parts = patches;
    mpe_rx_channel = ch;
    handler(msg + 1, src, (uint32_t)patches, (uint32_t)parts);
    mpe_rx_channel = MPE_NONE;
}

/* Replaces midi_channel_filter (src, handler, msg) at both call sites. */
void mpe_channel_filter(uint32_t src, midi_handler_fn *handler, const uint8_t *msg)
{
    uint8_t status = msg[0];
    if (status >= 0xF0) {
        midi_channel_filter(src, handler, msg);
        return;
    }
    if (arp_echo_drop(msg))    /* the arp's own note coming back (arp_echo.c) */
        return;
    uint8_t ch = status & 0x0F, type = status & 0xF0;
    mpe_route_update();
    const struct mpe_zone *z = mpe_zone_of(ch);

    if (type == 0xB0 && mpe_rpn_cc(ch, msg[1], msg[2], z))
        return;
    if ((type == 0x80 || (type == 0x90 && msg[2] == 0)) && bound(ch, msg[1])) {
        deliver(ch, src, handler, msg);
        return;
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
        case 0xA0:
            /* Poly pressure on a member channel is that channel's note's
             * pressure (a LinnStrument with Z set to poly pressure). Peak
             * addition, not in the Summit patch. */
            mpe_chan_pressure[ch] = msg[2];
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
    if (type == 0xE0)   /* the zone's master: its bend also goes to the part, as stock */
        mpe_master_bend[z->master == 0 ? MPE_LOWER : MPE_UPPER] = (int16_t)(((msg[2] << 7) | msg[1]) - 8192);
    deliver(ch, src, handler, msg);
}
