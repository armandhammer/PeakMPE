/* Peak MPE patch: state and interfaces shared by its modules.
 *
 * The Peak port of patches/mpe (Summit). The design is the Summit patch's
 * (docs/mpe-design.md), cut down to what the Peak has: one part, 8 voices,
 * one FPGA engine, no Multi mode. Firmware interface: common/peak.h.
 *
 *   mpe_settings.c  global settings, live state, RPN 0 / RPN 6, Save
 *   mpe_route.c     zone routing and the channel filter
 *   mpe_voice.c     channel <-> voice binding, triggers, release
 *   mpe_ui.c        the VOICE page flag and the Settings MPE pages
 *   mpe_expr.c ...  per-note bend, pressure and Slide (mpe_expr.h)
 *
 * Channels are 0-15 here (MIDI channel 1 = 0). MPE_NONE marks "no channel"
 * and "no part". Part arguments are kept where the firmware passes one; on
 * the Peak it is 0 (voice_part_mode stays 0, inferred), and every part reads
 * the one patch.
 */
#ifndef MPE_H
#define MPE_H

#include "peak.h"

#define MPE_NONE 0xFF
#define MPE_VOICES PEAK_VOICES

/* Per-patch flag: MPE is on for the patch when this byte is exactly 1. */
#define MPE_FLAG_OFFSET 0x1A2

/* Global settings (globals[]), saved with the Settings. Out-of-range values
 * read as the default, so never-initialised units behave. Unused by the
 * Peak's stock code (static scan, docs/symbols/peak-2.2-2108.csv). */
#define MPE_G_ZONE 0x30          /* 0 Off, 1 Lower, 2 Upper; other = Off */
#define MPE_G_MEMBERS 0x31       /* member channels 1-15; 0 or > 15 = 15 */
#define MPE_G_NOTE_RANGE 0x32    /* note bend range, semitones 1-96; 0 or > 96 = 48 */
#define MPE_G_MASTER_RANGE 0x33  /* master bend range, 1-96; 0 or > 96 = 2 */
#define MPE_G_CURVE 0x34         /* pressure curve: 0 Squared (stock), 1 Linear */
#define MPE_G_ENVSYNC 0x35       /* tempo-synced Decay/Release: 0 Off, 1-4 = 1/2 1/4 1/8 1/16 */
#define MPE_G_SECT 0x39          /* Settings records, not stored in the globals: COPY SECTION choice, "Do it", */
#define MPE_G_DOIT 0x3A          /* and the three read-only MIDI MONITOR items */
#define MPE_G_DIAG 0x3B
#define MPE_G_LOCK_FX 0x36       /* parameter lock: FX, Arp, Voice at +0x36, +0x37, +0x38: 0 Off, 1 On */
#define MPE_G_GLIDE 0x3E         /* where a poly glide starts: 0 Stock (the voice's last pitch), 1 LastNote, 2 Legato */
#define MPE_G_MOTION_LEN 0x3F    /* motion recording loop: 0 = 1 bar, 1 = 2 bars, 2 = 4 bars */
#define MPE_G_MOTION_STATE 0x40  /* Settings records, not stored: the recorder's state, */
#define MPE_G_LATE 0x41          /* and the late-tick count (diag.c) */

#define MPE_DEFAULT_MEMBERS 15
#define MPE_DEFAULT_NOTE_RANGE 48
#define MPE_DEFAULT_MASTER_RANGE 2
#define MPE_MAX_RANGE 96

enum { MPE_LOWER, MPE_UPPER };

/* --- Settings and live state (mpe_settings.c) --------------------------- */

struct mpe_live {
    uint8_t members[2];       /* [MPE_LOWER], [MPE_UPPER]: 0 = zone not configured */
    uint8_t note_range[2];
    uint8_t master_range[2];
};
extern struct mpe_live mpe_live;

void mpe_live_to_globals(void);
void mpe_globals_to_live(void);

/* --- Routing (mpe_route.c) ---------------------------------------------- */

/* A zone in effect. part == MPE_NONE: the zone isn't in use. Both zones,
 * when configured (a LinnStrument with both splits in MPE), play the one
 * patch. */
struct mpe_zone {
    uint8_t part;
    uint8_t master;           /* 0 (Lower) or 15 (Upper) */
    uint8_t first, last;      /* member channels, first <= last */
};
extern struct mpe_zone mpe_zones[2];

void mpe_route_update(void);
const struct mpe_zone *mpe_zone_of(uint8_t ch);
/* MPE on for the patch (the Peak has one; part is ignored). */
int mpe_part_on(uint32_t part);

/* Per-channel values from member channels. Bend -8192..8191. */
extern int16_t mpe_chan_bend[16];
extern uint8_t mpe_chan_pressure[16];
extern uint8_t mpe_chan_slide[16];       /* CC 74 */

/* Each zone's master-channel bend, -8192..8191, [MPE_LOWER] and [MPE_UPPER].
 * Both zones play the Peak's one part, so the stock part bend can't tell the
 * two masters apart; MPE voices take their own zone's master bend from here
 * (found on hardware 2026-11-12: a master bend moved both zones). */
extern int16_t mpe_master_bend[2];

/* Channel of the zone message being handled, MPE_NONE outside it. */
extern uint8_t mpe_rx_channel;

/* --- Voices (mpe_voice.c) ----------------------------------------------- */

/* The channel each voice plays for, MPE_NONE if none. */
extern uint8_t voice_channel[MPE_VOICES];
extern uint8_t mpe_alloc_channel;

/* The patch. */
static inline uint8_t *mpe_patch(void) { return patches; }

/* --- Events for later modules (weak, empty by default) ------------------ */

void mpe_member_message(const struct mpe_zone *z, uint8_t ch, const uint8_t *msg);
void mpe_live_changed(void);

/* --- Arp echo filter (arp_echo.c) --------------------------------------- */

/* 1 = msg is the echo of a note the arp just sent: drop it. */
int arp_echo_drop(const uint8_t *msg);
/* Once per mod_tick (1 kHz). */
void arp_echo_tick(void);

/* --- Knob display (disp.c) ----------------------------------------------- */

/* Once per main-loop pass: restores stock's custom characters once the
 * overlay's message time has run out. */
void disp_poll(void);

/* --- Tempo-synced envelope times (envsync.c) ---------------------------- */
void envsync_tick(void);   /* 1 kHz, from mpe_mod_update */
void envsync_poll(void);   /* main loop, from mpe_ui_poll */

/* --- Quick-assign modulation (qassign.c) -------------------------------- */
uint32_t qa_panel_read(void);   /* panel_button_event's button read */
void qa_button(uint32_t ev);
int qa_held(void);
int qa_encoder(int32_t delta);  /* 1 = taken (Mod held: chooses the source) */
void qa_knob(uint32_t id);
void ui_say(const char *l0, const char *l1, const char *l2, const char *l3);  /* four rows for the message time */
void ui_say_hold(void);   /* keep that message up for 2 s */
void ui_hold_poll(void);  /* main loop, from mpe_ui_poll */

/* --- Section copy and undo (section.c), MIDI monitor (diag.c) ---------- */
uint32_t mpe_ticks(void);        /* envsync.c: modulation ticks since power-up, 1000 per second */
void undo_capture(void);
void undo_clear(void);
void undo_knob(uint32_t id);
int edit_button(uint32_t ev);    /* Mod held: Page left/right = undo/redo; 1 = taken */
const char *section_name(uint32_t i);
uint32_t section_op(void);
void section_edit(uint32_t index, int32_t delta);
uint32_t param_id_of(uint32_t offset);            /* the setter's id for a patch offset, 0 = not settable */
void param_put(uint32_t offset, uint32_t value);  /* set a patch byte through stock's setter, if it has an id */
void diag_tick(void);            /* once per modulation tick */
uint32_t diag_late_ticks(void);

/* --- Motion recording (motion.c) --------------------------------------- */
int motion_button(uint32_t ev, int mod_held);     /* 1 = taken (Mod + Animate 1 and its release) */
void motion_knob(uint32_t id, uint32_t cur, uint32_t hires);
void motion_poll(void);          /* main loop, from mpe_ui_poll */
void motion_clear(void);         /* a patch load */
const char *motion_state_name(void);
void diag_note(const uint8_t *msg);
void diag_text(uint32_t which, char *out);

/* Internal to the core. */
void mpe_settings_init(void);
void mpe_voice_init(void);
int mpe_rpn_cc(uint8_t ch, uint8_t cc, uint8_t value, const struct mpe_zone *z);

#endif
