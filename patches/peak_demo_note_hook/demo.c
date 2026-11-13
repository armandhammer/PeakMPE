/* Peak demo patch: make the C hooks audible.
 *
 * Every MIDI note is shifted on its way through the firmware, by a different
 * interval per hook kind, so one played note tells which links ran:
 *
 *   pointer hooks (channel-handler table, note on and note off): +12
 *   bl hooks (note_on/note_off -> voice_dispatch / voice_release):  +7
 *   both only after patch_init (the startup hook) has armed them.
 *
 *   heard shift   meaning
 *   +19           startup, pointer and bl hooks all ran
 *   +12           pointer hooks only
 *    +7           bl hooks only
 *     0           not armed: patch_init did not run (or no hook ran)
 *
 * Note on and note off get the same shift, so notes still end. The panel's
 * audition button (note 60, through voice_dispatch from panel_button_event,
 * not hooked) stays unshifted: a built-in reference. Not handled: the
 * arpeggiator (its triggers aren't hooked), so test with the arp off.
 */

#include "peak.h"

#define DEMO_MAGIC 0x4D504530u  /* "MPE0" */
#define POINTER_SHIFT 12
#define BL_SHIFT 7

volatile uint32_t demo_magic;           /* set by patch_init */
volatile uint32_t demo_note_on_calls;
volatile uint32_t demo_note_off_calls;
volatile uint32_t demo_dispatch_calls;
volatile uint32_t demo_release_calls;
volatile uint8_t demo_last_note;

void patch_init(void)
{
    demo_magic = DEMO_MAGIC;
}

static int armed(void)
{
    return demo_magic == DEMO_MAGIC;
}

/* Shift a note up, or leave it if the result would leave 0-127; the same
 * input always gives the same output, so on and off stay paired. */
static uint8_t shift(uint8_t note, uint8_t by)
{
    return note + by <= 127 ? note + by : note;
}

/* data = [note, velocity]; the firmware's buffer is passed on as a copy. */
void demo_note_on(const uint8_t *data, uint32_t r1, uint32_t r2, uint32_t r3)
{
    uint8_t msg[2] = { data[0], data[1] };
    demo_note_on_calls++;
    if (armed())
        msg[0] = shift(msg[0], POINTER_SHIFT);
    note_on(msg, r1, r2, r3);
}

void demo_note_off(const uint8_t *data, uint32_t r1, uint32_t r2, uint32_t r3)
{
    uint8_t msg[2] = { data[0], data[1] };
    demo_note_off_calls++;
    if (armed())
        msg[0] = shift(msg[0], POINTER_SHIFT);
    note_off(msg, r1, r2, r3);
}

void demo_voice_dispatch(uint8_t note, uint8_t velocity)
{
    demo_dispatch_calls++;
    if (armed())
        note = shift(note, BL_SHIFT);
    demo_last_note = note;
    voice_dispatch(note, velocity);
}

void demo_voice_release(uint8_t note, uint8_t part)
{
    demo_release_calls++;
    if (armed())
        note = shift(note, BL_SHIFT);
    voice_release(note, part);
}
