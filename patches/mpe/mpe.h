/* MPE patch: state and interfaces shared by its modules (docs/mpe-design.md).
 *
 * Step 1, the core, has three modules:
 *   mpe_settings.c  global settings, live state, RPN 0 / RPN 6, Save
 *   mpe_route.c     zone routing and the channel filter
 *   mpe_voice.c     channel <-> voice binding, triggers, release
 *
 * Later steps add modules that read this state; they don't change the
 * core's files:
 *   step 2 (expression): per-voice bend, pressure and Slide. They read
 *     voice_channel[] and the per-channel values below from their own hooks
 *     (osc_pitch, mod_update), and may define the weak event functions at
 *     the end of this file to react when a value arrives.
 *   step 3 (UI): the Settings page and the VOICE item. It edits the globals
 *     at MPE_G_*, and shows mpe_live, mpe_zones and mpe_clash.
 *
 * Channels are 0-15 here (MIDI channel 1 = 0). MPE_NONE marks "no channel"
 * and "no part".
 */
#ifndef MPE_H
#define MPE_H

#include "firmware.h"

#define MPE_NONE 0xFF

/* Per-patch flag: MPE is on for a patch when this byte is exactly 1. */
#define MPE_FLAG_OFFSET 0x1A2

/* Global settings (globals[]), saved with the Settings. Out-of-range values
 * read as the default, so never-initialised units behave. */
#define MPE_G_ZONE 0x30          /* 0 Off, 1 Lower, 2 Upper; other = Off */
#define MPE_G_MEMBERS 0x31       /* member channels 1-15; 0 or > 15 = 15 */
#define MPE_G_NOTE_RANGE 0x32    /* note bend range, semitones 1-96; 0 or > 96 = 48 */
#define MPE_G_MASTER_RANGE 0x33  /* master bend range, 1-96; 0 or > 96 = 2 */

#define MPE_DEFAULT_MEMBERS 15
#define MPE_DEFAULT_NOTE_RANGE 48
#define MPE_DEFAULT_MASTER_RANGE 2
#define MPE_MAX_RANGE 96

enum { MPE_LOWER, MPE_UPPER };

/* --- Settings and live state (mpe_settings.c) --------------------------- */

/* What the synth plays by: the Settings layout, then whatever RPN 6 and
 * RPN 0 changed. Stored to the globals only by Settings Save. */
struct mpe_live {
    uint8_t members[2];       /* [MPE_LOWER], [MPE_UPPER]: 0 = zone not configured */
    uint8_t note_range[2];    /* semitones, per zone kind */
    uint8_t master_range[2];
};
extern struct mpe_live mpe_live;

/* The live state into globals +0x30..+0x33, as Settings Save stores it
 * (without writing flash). */
void mpe_live_to_globals(void);
/* Take changed globals +0x30..+0x33 into mpe_live now, as the main loop
 * does within one pass, and refresh the routing. */
void mpe_globals_to_live(void);

/* --- Routing (mpe_route.c) ---------------------------------------------- */

/* A zone in effect: the configured layout resolved against Single/Multi and
 * the parts' flags. part == MPE_NONE: the zone isn't in use. */
struct mpe_zone {
    uint8_t part;
    uint8_t master;           /* 0 (Lower) or 15 (Upper) */
    uint8_t first, last;      /* member channels, first <= last */
};
extern struct mpe_zone mpe_zones[2];  /* [MPE_LOWER], [MPE_UPPER] */

/* Bit p: Part p (Multi, MPE off) can't be reached because its channel lies
 * in a zone; bit 2: the Multi global channel lies in a zone. */
extern uint8_t mpe_clash;

/* Recompute mpe_zones and mpe_clash. Cheap; the filter runs it per message. */
void mpe_route_update(void);
/* The zone a channel belongs to (master or member), or 0. */
const struct mpe_zone *mpe_zone_of(uint8_t ch);
/* MPE on for the patch a part plays. */
int mpe_part_on(uint32_t part);

/* Per-channel values from member channels, kept until the next message
 * (MPE senders send them just before the note-on). Bend -8192..8191. */
extern int16_t mpe_chan_bend[16];
extern uint8_t mpe_chan_pressure[16];
extern uint8_t mpe_chan_slide[16];       /* CC 74 */

/* Channel of the zone message being handled, MPE_NONE outside the filter's
 * zone path (other channels, the keybed, the arpeggiator). */
extern uint8_t mpe_rx_channel;

/* --- Voices (mpe_voice.c) ----------------------------------------------- */

/* The channel each voice plays for, MPE_NONE if it plays for none (MPE off,
 * the keybed). Set when the voice is allocated, before voice_alloc's
 * osc_pitch calls, and kept through the release until the voice is
 * allocated again. */
extern uint8_t voice_channel[16];

/* The channel the voice being allocated binds to, valid during voice_alloc. */
extern uint8_t mpe_alloc_channel;

/* First voice and voice count of a part: 16 voices in Single, 8 in Multi. */
static inline uint32_t mpe_first_voice(uint32_t part) { return multi_mode ? part * 8 : 0; }
static inline uint32_t mpe_voice_count(void) { return multi_mode ? 8 : 16; }
/* The patch a part plays: patches[multi + part]. */
static inline uint8_t *mpe_patch(uint32_t part) { return patches[(multi_mode ? 1 : 0) + part]; }

/* --- Events for later modules (weak, empty by default) ------------------ */

/* A message on a member channel that the core doesn't play itself: pitch
 * bend, channel pressure and CC 74 (after the core stored the value), poly
 * pressure, program change and other CCs. msg = [status, data...]. */
void mpe_member_message(const struct mpe_zone *z, uint8_t ch, const uint8_t *msg);
/* The live layout or a bend range changed (RPN 6, RPN 0, Settings). */
void mpe_live_changed(void);

/* Internal to the core. */
void mpe_settings_init(void);
void mpe_voice_init(void);
int mpe_rpn_cc(uint8_t ch, uint8_t cc, uint8_t value, const struct mpe_zone *z);

#endif
