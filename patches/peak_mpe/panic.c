/* Peak front-panel panic (v0.28; docs/peak-features.md step 5).
 *
 * Hold Mod and press Audition: every note stops, whatever left it sounding (a
 * lost note-off, a stuck key on a controller, a latched arp). The guide has
 * no panic and no button combinations; Audition alone plays middle C (button
 * 18, action 0). Its press with Mod held, and the release that follows, are
 * taken here (as motion.c takes Animate 1), so the note does not sound.
 *
 * A panic is, in order:
 *   - what stock does for CC 120 (all_sound_off 0x08011E90): every voice
 *     released at once, gates and the sustain and sostenuto holds cleared,
 *     the sound chip's part values reset;
 *   - the held keys stock keeps for the mono modes and phrase starts (bitmap
 *     note_state+0xD8, last note +0x1D3): a key whose note-off never came
 *     would otherwise come back when another key is let go;
 *   - the arp's keys-held map (+0x168) and play map (arp_clear, as a patch
 *     load): a key whose note-off never came, or a latched chord, would
 *     otherwise keep the arp playing;
 *   - the MPE patch's voice bindings and per-note channels (mpe_voice_init),
 *     and the stored bend, pressure and slide of every channel, so the next
 *     note starts from rest.
 * The delay and reverb tails ring out: CC 120 does not cut them either (the
 * rig, v0.27 randomiser run), and the effects are not voices. Settings, the
 * patch and a motion lane are not touched.
 */

#include "mpe.h"

#define BUTTON_AUDITION 18
#define ARP_KEYS 0x168

static uint8_t swallow;          /* the Audition press was taken: take its release too */

void panic(void)
{
    all_sound_off();
    for (uint32_t i = 0; i < 16; i++)
        HELD_KEYS[i] = 0;
    LAST_NOTE = 0xFF;
    uint8_t *arp = arp_state_ptr;
    for (uint32_t i = 0; i < 16; i++)
        arp[ARP_KEYS + i] = 0;
    arp_clear();
    mpe_voice_init();
    for (uint32_t ch = 0; ch < 16; ch++) {
        mpe_chan_bend[ch] = 0;
        mpe_chan_pressure[ch] = 0;
        mpe_chan_slide[ch] = 0;
    }
    mpe_master_bend[0] = 0;
    mpe_master_bend[1] = 0;
    ui_say("PANIC", "All notes off", "", "");
    ui_say_hold();
}

/* One panel button event (as qa_panel_read reads it). 1 = taken. */
int panic_button(uint32_t ev, int mod_held)
{
    if (!(ev & 0xFF) || ((ev >> 8) & 0xFF) != BUTTON_AUDITION)
        return 0;
    if ((int8_t)(ev & 0xFF) < 0) {
        if (!swallow)
            return 0;
        swallow = 0;
        return 1;
    }
    if (!mod_held)
        return 0;
    swallow = 1;
    panic();
    return 1;
}
