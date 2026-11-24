/* Peak MIDI Tuning Standard: the messages stock drops (docs/peak-features.md,
 * "MTS real-time retuning"; findings, "MIDI Tuning Standard in stock").
 *
 * Stock has two tuning parsers among the seven that sysex_rx_byte
 * (0x0801AE0C) feeds each received SysEx byte (observed):
 *
 *   mts_single_note_rx 0x08019548: F0 7F 00 08 02 tt ll kk xx yy zz F7,
 *     exactly 11 bytes after F0, so one note per message, device ID 00 only;
 *     calls tuning_note_set and mark_changed.
 *   mts_bulk_rx 0x08019B40: F0 7E 00 08 01 tt <16-character name>
 *     <128 x xx yy zz> <checksum> F7, device ID 00 only; calls
 *     tuning_note_set for all 128 keys (no checksum test, no mark_changed).
 *
 * tuning_note_set (0x08012CCC: table, key, xx, yy, zz) writes the table entry
 * and, when the table is the patch's (patch +0x162), retunes the sounding
 * voices on that key; 7F 7F 7F means no change.
 *
 * This parser runs after stock's on every byte (the hook replaces
 * sysex_rx_byte's call of mts_single_note_rx and calls it first) and
 * applies what stock doesn't:
 *
 *   - the single-note change (real time, 7F .. 08 02) with device ID 7F (all
 *     devices) or 00, and any number of notes (ll 0 to 127); the one case stock
 *     already applies (device 00 with one note) is left to stock;
 *   - the bulk dump (7E 7F 08 01) with device ID 7F, the same as stock's
 *     device 00 one.
 *
 * As stock: a message is applied at its F7 and only at its exact length, the
 * table number must be 0 to 16, and while a message is being received, bytes
 * from another port are ignored. Unlike stock, a real-time byte (F8-FF) in
 * the middle doesn't end the message (MIDI allows them anywhere). Not taken:
 * the bank-select forms (sub-ID 07), the scale/octave forms (08 08, 08 09)
 * and the dump request with device 7F.
 */

#include "mpe.h"

void mts_single_note_rx(const uint8_t *byte, uint32_t port);
void tuning_note_set(uint32_t table, uint32_t key, uint32_t xx, uint32_t yy, uint32_t zz);

#define TABLES 17
#define BULK_LEN (5 + 16 + 128 * 3 + 1)   /* 7E dev 08 01 tt, name, data, checksum */
#define MAX_LEN (6 + 127 * 4)             /* the longest single-note message (bulk: 406) */

static uint8_t buf[MAX_LEN];
static uint16_t len;
static uint8_t active, active_port;

static void apply(void)
{
    if (len < 6 || buf[2] != 0x08)
        return;
    uint8_t dev = buf[1], tt = buf[4];
    if (tt >= TABLES)
        return;
    if (buf[0] == 0x7F && buf[3] == 0x02 && (dev == 0x00 || dev == 0x7F)) {
        uint32_t n = buf[5];
        if (len != 6 + 4 * n || (dev == 0x00 && n == 1))
            return;
        for (uint32_t i = 0; i < n; i++) {
            const uint8_t *q = &buf[6 + 4 * i];
            tuning_note_set(tt, q[0], q[1], q[2], q[3]);
        }
        if (n)
            mark_changed();
    } else if (buf[0] == 0x7E && buf[3] == 0x01 && dev == 0x7F && len == BULK_LEN) {
        for (uint32_t k = 0; k < 128; k++) {
            const uint8_t *q = &buf[5 + 16 + 3 * k];
            tuning_note_set(tt, k, q[0], q[1], q[2]);
        }
    }
}

/* Replaces sysex_rx_byte's call of mts_single_note_rx (0x0801AE42). */
void mts_rx(const uint8_t *byte, uint32_t port)
{
    mts_single_note_rx(byte, port);
    uint8_t b = *byte;
    if (b >= 0xF8)
        return;                              /* real time: not part of the message */
    if (active && (uint8_t)port != active_port)
        return;                              /* as stock: one port at a time */
    if (b == 0xF0) {
        active = 1;
        active_port = (uint8_t)port;
        len = 0;
        return;
    }
    if (!active)
        return;
    if (b == 0xF7) {
        active = 0;
        apply();
    } else if (b & 0x80) {
        active = 0;                          /* another status byte ends it */
    } else if (len < MAX_LEN) {
        buf[len++] = b;
    } else {
        active = 0;                          /* too long for any message taken here */
    }
}
