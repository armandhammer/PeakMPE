/* Per-port receive filters (v0.34; docs/peak-features.md).
 *
 * Settings USB IN and DIN IN, each with Notes, CC and Patch, On (as stock) or
 * Off. Stock reads three inputs, each with its own receive ring and parser
 * (0x200040B4 + port x 0x110), and hands every channel message to
 * midi_channel_filter with its port (findings, "MIDI input ports"):
 *   0 USB (0x0801D2F0), 1 DIN (emulated), 2 the synth's own output read back
 *   in (0x08017340: the panel's program change, the arp with Arp>MIDI).
 * Port 2 is never filtered, so the panel works whatever is set here. System
 * messages and SysEx (the editor, Components) are not filtered; the clock
 * follows stock's Clock Source (ptime.c).
 *
 * The groups:
 *   Notes: note-ons, bend, channel and poly pressure, and everything on an
 *     MPE zone's member channels (their CC 74 and RPNs are note expression),
 *     plus RPNs on any channel (bend range, the MPE Configuration Message);
 *   CC: every other controller, NRPNs included (stock's parameter NRPNs);
 *   Patch: program change and bank select (CC 0 and 32).
 * Always let through, whatever is set: note-offs (note-on with velocity 0
 * too), so a note held when its port's Notes is turned off doesn't stick; and
 * CC 120 and 123 (all sound off, all notes off), so panic works from any port.
 *
 * Data entry (CC 6, 38) and increment/decrement (96, 97) belong to whichever
 * of RPN or NRPN was selected last on that port and channel (CC 101/100 or
 * 99/98), tracked here whether or not the selection itself was let through.
 */

#include "mpe.h"

enum { NOTES, CCS, PATCH };

static uint8_t nrpn_selected[2][16];   /* per port (USB, DIN) and channel: 1 = NRPN, 0 = RPN */

/* Settings value of a port's group: stored 0 = On (the globals were 0 before
 * v0.34, so stock behaviour is the default), 1 = Off. */
static int off(uint32_t port, uint32_t group)
{
    return globals[MPE_G_PFILTER + 3 * port + group] == 1;
}

static uint32_t cc_group(uint32_t port, uint8_t ch, uint8_t cc, const struct mpe_zone *z)
{
    switch (cc) {
    case 99:
    case 98:
        nrpn_selected[port][ch] = 1;
        return CCS;
    case 101:
    case 100:
        nrpn_selected[port][ch] = 0;
        return NOTES;
    case 0:
    case 32:
        return PATCH;
    }
    if (z && ch != z->master)
        return NOTES;
    if (cc == 6 || cc == 38 || cc == 96 || cc == 97)
        return nrpn_selected[port][ch] ? CCS : NOTES;
    return CCS;
}

/* A channel message from port src that Settings USB IN / DIN IN turn off.
 * z: the zone of its channel, or 0 (mpe_channel_filter). */
int pfilter_drop(uint32_t src, const uint8_t *msg, const struct mpe_zone *z)
{
    if (src > 1)
        return 0;
    uint8_t type = msg[0] & 0xF0, ch = msg[0] & 0x0F;
    switch (type) {
    case 0x80:
        return 0;
    case 0x90:
        return msg[2] && off(src, NOTES);
    case 0xC0:
        return off(src, PATCH);
    case 0xB0:
        if (msg[1] == 120 || msg[1] == 123) {
            cc_group(src, ch, msg[1], z);
            return 0;
        }
        return off(src, cc_group(src, ch, msg[1], z));
    default:                             /* A0, D0, E0 */
        return off(src, NOTES);
    }
}
