/* Arp echo filter: the Peak ignores its own arp notes when they come back.
 *
 * With Arp>Midi On the arpeggiator sends every step out as a note on and a
 * note off (arp_midi_note_on / arp_midi_note_off). A DAW that routes the
 * Peak's MIDI out back to its MIDI in returns those notes, and the Peak
 * treats them as keys: a returned note off reaches arp_note_off
 * (0x08014E10), which removes the note from the arp's play map as if the
 * key had been let go. On the rig (2026-11-13, loopback_test.py) the arp
 * stopped after one pass over a held C E G: 6 note messages
 * (docs/findings/peak-2.2-build2108.md, "Arpeggiator and the MIDI loop").
 *
 * Here every note the arp sends is remembered for ECHO_WINDOW ticks. An
 * incoming note on or note off (a note on with velocity 0 counts as a note
 * off) with the same status and note number within that time is dropped
 * before any handler sees it, and it uses up that one entry, so each sent
 * message cancels at most one incoming message. Velocity isn't compared: a
 * DAW may rescale it.
 *
 * The cost: a key really released (or pressed) on the same channel and note
 * within ECHO_WINDOW of the arp sending that note is dropped too. With the
 * arp running, that leaves the note in the arp until it is pressed and
 * released again.
 *
 * Time comes from mod_tick (1 kHz, called through mpe_mod_update). Nothing
 * here runs unless the arp sends notes, so with the arp off, or Arp>Midi
 * Off, the synth behaves as stock.
 */

#include "mpe.h"

#define ECHO_SLOTS 32
#define ECHO_WINDOW 100   /* mod_tick ticks: about 100 ms */

struct echo {
    uint8_t status;       /* 0x90 / 0x80 | channel; 0 = free */
    uint8_t note;
    uint16_t sent;        /* arp_echo_now when sent */
};

static struct echo pending[ECHO_SLOTS];
static uint16_t arp_echo_now;

static int expired(const struct echo *e)
{
    return (uint16_t)(arp_echo_now - e->sent) > ECHO_WINDOW;
}

void arp_echo_tick(void)
{
    arp_echo_now++;
}

static void expect(uint8_t type, uint32_t note)
{
    uint32_t pick = 0;
    uint16_t oldest = 0;
    for (uint32_t i = 0; i < ECHO_SLOTS; i++) {
        struct echo *e = &pending[i];
        if (!e->status || expired(e)) {
            pick = i;
            break;
        }
        uint16_t age = (uint16_t)(arp_echo_now - e->sent);
        if (age >= oldest) {
            oldest = age;
            pick = i;
        }
    }
    pending[pick].status = (uint8_t)(type | (midi_global_channel & 0x0F));
    pending[pick].note = (uint8_t)note;
    pending[pick].sent = arp_echo_now;
}

/* Replaces arp_step's call of arp_midi_note_on (0x08015202). Remembered
 * before sending, so even an instant echo finds its entry. */
void arp_echo_note_on(uint32_t note, uint32_t velocity)
{
    expect(0x90, note);
    arp_midi_note_on(note, velocity);
}

/* Replaces arp_step_release's call of arp_midi_note_off (0x08014EE2). */
void arp_echo_note_off(uint32_t note, uint32_t velocity)
{
    expect(0x80, note);
    arp_midi_note_off(note, velocity);
}

/* From mpe_channel_filter, for every channel message: 1 = an echo of an arp
 * note, drop it. */
int arp_echo_drop(const uint8_t *msg)
{
    uint8_t status = msg[0] & 0xF0;
    if (status == 0x90 && msg[2] == 0)
        status = 0x80;
    if (status != 0x80 && status != 0x90)
        return 0;
    status |= msg[0] & 0x0F;
    for (uint32_t i = 0; i < ECHO_SLOTS; i++) {
        struct echo *e = &pending[i];
        if (e->status != status || e->note != msg[1])
            continue;
        int hit = !expired(e);
        e->status = 0;
        if (hit)
            return 1;
    }
    return 0;
}
