/* Peak MIDI monitor and diagnostics (docs/peak-features.md, step 16).
 *
 * Settings > MIDI MONITOR (read-only): the last channel message that arrived (status
 * and data bytes in hex), how many have arrived since power-up, and the DIN receive
 * overflow count (the DIN ring is 256 bytes; the count is at +0x204 of the ring
 * 0x20003EAC: observed in the earlier DIN tests, inferred from the Summit's layout
 * for the counter). The MPE zone in effect is on the Settings MPE page.
 *
 * mpe_channel_filter calls diag_note for every channel message (not system
 * messages) before it routes it.
 */

#include "mpe.h"

#define DIN_RING 0x20003EAC
#define DIN_OVERFLOWS (*(volatile uint8_t *)(DIN_RING + 0x204))

#define MS_COUNTER (*(volatile uint32_t *)(0x20003AD0 + 0x1C0))   /* tim6_isr: +1 per millisecond */

static uint8_t last[3];
static uint32_t count;
static uint32_t late, last_ms;
static uint8_t ticked;

/* Late ticks: the interrupt asks for a modulation tick every millisecond, and the
 * main loop runs one per pass without catching up, so a pass longer than 1 ms loses
 * ticks. Each tick here counts the milliseconds that went by without one. It is the
 * measure of how much main-loop work (parameter updates, the screen) the synth has
 * room for: docs/peak-motion-morph.md, "Risks". Shown on Settings > MOTION. */
void diag_tick(void)
{
    uint32_t ms = MS_COUNTER;
    if (ticked && ms - last_ms > 1)
        late += ms - last_ms - 1;
    last_ms = ms;
    ticked = 1;
}

uint32_t diag_late_ticks(void)
{
    return late;
}

void diag_note(const uint8_t *msg)
{
    uint8_t status = msg[0];
    uint32_t n = (status & 0xF0) == 0xC0 || (status & 0xF0) == 0xD0 ? 2 : 3;
    last[0] = status;
    last[1] = msg[1];
    last[2] = n == 3 ? msg[2] : 0xFF;     /* 0xFF = a two-byte message */
    count++;
}

static char hex(uint32_t v)
{
    return (char)(v < 10 ? '0' + v : 'A' + v - 10);
}

static void put_hex(char **p, uint32_t b)
{
    *(*p)++ = hex(b >> 4);
    *(*p)++ = hex(b & 15);
}

static void put_dec(char **p, uint32_t n)
{
    if (n >= 10)
        put_dec(p, n / 10);
    *(*p)++ = (char)('0' + n % 10);
}

/* The value text of the three items (display types 0..2), unpadded, at most 8 characters. */
void diag_text(uint32_t which, char *out)
{
    char *p = out;
    if (which == 0) {
        if (!count) {
            *p++ = '-';
        } else {
            put_hex(&p, last[0]);
            *p++ = ' ';
            put_hex(&p, last[1]);
            if (last[2] != 0xFF) {
                *p++ = ' ';
                put_hex(&p, last[2]);
            }
        }
    } else if (which == 1) {
        put_dec(&p, count);
    } else {
        put_dec(&p, DIN_OVERFLOWS);
    }
    *p = 0;
}
