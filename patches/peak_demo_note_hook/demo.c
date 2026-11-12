/* Peak demo patch: count note-ons on their way through the firmware.
 *
 * demo_note_on replaces note_on in the MIDI channel-handler table (pointer
 * hook); demo_voice_dispatch replaces note_on's call to voice_dispatch (bl
 * hook). Both count, then call the original, so the synth behaves as stock.
 * Not meant for hardware.
 */

#include "peak.h"

#define DEMO_MAGIC 0x4D504530u  /* "MPE0" */

volatile uint32_t demo_magic;           /* set by patch_init */
volatile uint32_t demo_note_on_calls;
volatile uint32_t demo_voice_dispatch_calls;
volatile uint8_t demo_last_note;

void patch_init(void)
{
    demo_magic = DEMO_MAGIC;
}

void demo_note_on(const uint8_t *data, uint32_t r1, uint32_t r2, uint32_t r3)
{
    demo_note_on_calls++;
    note_on(data, r1, r2, r3);
}

void demo_voice_dispatch(uint8_t note, uint8_t velocity)
{
    demo_voice_dispatch_calls++;
    demo_last_note = note;
    voice_dispatch(note, velocity);
}
