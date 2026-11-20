/* Peak patch change timed to the clock (v0.31; docs/peak-features.md, Later).
 *
 * Settings PATCH TIMING > Change at = Beat, Bar, 2 Bars or 4 Bars: while an
 * external MIDI clock plays (a Start or Continue, no Stop since, and a clock
 * byte within the last 100 ms), a patch change by program change or by the
 * patch buttons (including a cued patch, Patch Cue) waits for the next beat
 * or bar line of that clock and loads on its clock byte, before the notes
 * that follow it are read. A change in the first two clocks of a step (just
 * after its line: a DAW sending it on the bar) loads at once. Without a
 * playing clock, or with `Now`, patch changes load at once, as stock. Bars
 * are 4/4: 96 clocks. Continue after Stop goes on from where Stop left the
 * count, unless a Song Position Pointer came between.
 *
 * Stock keeps no song position: its tempo clock (0x20012268) runs freely and
 * MIDI Start only sets a flag (0x08010E30), Continue, Stop and Song Position
 * Pointer are ignored (handlers that return). So this counts the clock itself:
 *  - Start: the next clock byte is position 0 (beat 1 of bar 1);
 *  - Song Position Pointer (in 16ths): the next clock after Continue is
 *    position 6 x SPP;
 *  - Stop: no clock plays; a waiting patch change loads now.
 * Clock bytes reach stock's handlers per port (0x0800FBD0, 0x0800FBE8, called
 * from the MIDI input loop 0x0800F084); both are hooked and counted alike.
 * Start, Continue and Stop are entries of stock's system-message table in RAM
 * (0x200001E0, 8 bytes each: handler, length, flags), set here at boot; Song
 * Position Pointer passes through mpe_channel_filter (mpe_route.c).
 *
 * The patch change itself is stock's patch_select_load (bank | number << 8,
 * bank 0x80+ = the current bank), hooked at its two calls: program_change
 * (0x0800F112) and the panel's patch apply (0x08018C9A; the power-up load in
 * settings_load stays as it is). A later change while one waits replaces it.
 * The panel's own program change out (Bank/Patch transmit) is still sent when
 * the patch is chosen.
 */

#include "mpe.h"

#define CLOCK_TIMEOUT_TICKS 100
/* A change that comes within the first two clocks of a step loads at once: a
 * DAW that puts a program change on the bar sends it with that tick's clock
 * byte, often just after it, and waiting would make it a whole step late
 * (review 2026-11-20). Two clocks: 42 ms at 120 BPM. */
#define GRACE_CLOCKS 2
#define SYS_HANDLER(status) ((uint32_t *)&midi_sys_handlers[((status) & 0x0F) * 8])

static const uint16_t unit_clocks[] = {0, 24, 96, 192, 384};   /* Now, Beat, Bar, 2 Bars, 4 Bars */

static uint32_t position;        /* MIDI clocks since Start, the one now playing */
static uint8_t playing;          /* Start or Continue seen, no Stop since */
static uint8_t first;            /* the next clock byte is `position` itself, not position + 1 */
static uint32_t clock_tick;      /* mpe_ticks() of the last clock byte */
static uint8_t waiting;
static uint16_t waiting_arg;

uint32_t ptime_unit(void)
{
    uint8_t v = globals[MPE_G_PTIME];
    return v < sizeof unit_clocks / sizeof unit_clocks[0] ? unit_clocks[v] : 0;
}

static int clock_playing(void)
{
    return playing && (uint32_t)(mpe_ticks() - clock_tick) < CLOCK_TIMEOUT_TICKS;
}

static void load_waiting(void)
{
    waiting = 0;
    patch_select_load(waiting_arg);
}

static void put3(char *p, uint32_t n)
{
    p[0] = (char)('0' + n / 100 % 10);
    p[1] = (char)('0' + n / 10 % 10);
    p[2] = (char)('0' + n % 10);
}

/* Replaces patch_select_load at program_change (0x0800F112) and the panel's
 * patch apply (0x08018C9A). */
void ptime_select(uint16_t arg)
{
    if (!(arg & 0x80) && (uint8_t)((arg & 0xFF) - 1) > 3) {
        patch_select_load(arg);      /* a bank stock refuses (CC 32 = 0 or above 4): it ignores the */
        return;                      /* change, and a waiting one stays (review 2026-11-20) */
    }
    uint32_t unit = ptime_unit();
    if (!unit || !clock_playing() || position % unit < GRACE_CLOCKS) {
        waiting = 0;
        patch_select_load(arg);
        return;
    }
    waiting_arg = arg;
    waiting = 1;
    uint8_t bank = (uint8_t)arg;
    if (bank & 0x80)
        bank = patch_select[4];        /* program change without a bank select: the current bank */
    char name[5] = {(char)('A' + (bank - 1) % 4), 0, 0, 0, 0};
    put3(name + 1, (uint32_t)(arg >> 8));
    static const char *const when[] = {"", "at the next beat", "at the next bar", "in 2-bar steps", "in 4-bar steps"};
    ui_say("PATCH TIMING", name, when[globals[MPE_G_PTIME]], "");
}

static void clock_byte(void)
{
    clock_tick = mpe_ticks();
    if (!playing)
        return;
    if (first)
        first = 0;
    else
        position++;
    if (!waiting)
        return;
    uint32_t unit = ptime_unit();
    if (!unit || position % unit == 0)
        load_waiting();
}

/* Replace the MIDI input loop's calls of stock's clock handlers (0x0800F0A0,
 * 0x0800F0A8). Stock's first: it measures the tempo from when clock bytes
 * arrive (0x0800F764 reads the ms counter), and a patch load takes 10-20 ms
 * on the synth, which would make this byte look late (review 2026-11-20).
 * The notes after the byte are read after the load either way. */
void ptime_clock_1(void)
{
    midi_clock_rx_1();
    clock_byte();
}

void ptime_clock_0(void)
{
    midi_clock_rx_0();
    clock_byte();
}

static void start(void)
{
    position = 0;
    first = 1;
    playing = 1;
    midi_start_rx();
}

static void cont(void)
{
    playing = 1;                     /* after a Song Position Pointer (first set), its position comes next; */
}                                    /* else the one after where Stop left it (v0.31 counted that one again) */

static void stop(void)
{
    playing = 0;
    if (waiting)
        load_waiting();
}

/* Song Position Pointer (msg: F2 lsb msb), from mpe_channel_filter. */
void ptime_spp(const uint8_t *msg)
{
    position = 6u * (uint32_t)(msg[1] | msg[2] << 7);
    first = 1;
}

/* Boot (mpe_ui_boot): Start, Continue and Stop into stock's system-message table. */
void ptime_boot(void)
{
    *SYS_HANDLER(0xFA) = (uint32_t)start;
    *SYS_HANDLER(0xFB) = (uint32_t)cont;
    *SYS_HANDLER(0xFC) = (uint32_t)stop;
}

/* Once per 1 kHz tick (mpe_ui_poll): a clock that stopped without a Stop
 * (unplugged, a DAW that just stops sending) lets a waiting change load. */
void ptime_poll(void)
{
    if (waiting && !clock_playing())
        load_waiting();
}
