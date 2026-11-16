/* Peak motion recording (docs/peak-features.md step 21, docs/peak-motion-morph.md).
 *
 * One lane: one control's movement over one loop of 32 steps, played back in
 * time with the tempo.
 *
 *   Hold Mod, press Animate 1   arm ("Move a control"); again: cancel or stop
 *   move a slider or knob       recording starts at that move, for one loop
 *   after one loop              the lane plays until stopped
 *   move the control again      its values replace the steps passed meanwhile
 *   stop (Mod + Animate 1)      the control goes back to its value from before
 *
 * Animate 1 is panel button 14 (button_table 0x20000AB8 entry 14: type 4,
 * action 6, argument 0; action 6 with argument 0 or 1 calls FUN_08016FCC, which
 * runs the Animate function and sends CC 114 + argument: observed). Its press
 * with Mod held, and the release that follows, are taken here and hidden from
 * stock, so Animate 1 itself does not fire.
 *
 * Time: stock's tempo clock (tempo_clock_step 0x0800FB80, in the 1 kHz
 * interrupt) counts MIDI clocks, 24 per quarter note, at the current tempo,
 * internal or external; the count is the high word of 0x20012268. A step is 3
 * clocks (a 1/32 note), so 32 steps are one 4/4 bar; Settings > MOTION > Length
 * makes a step 6 or 12 clocks (2 or 4 bars). The loop's "one" is the move that
 * started the recording. A jump of the count (more than 48 clocks between two
 * main-loop passes: stock reset it) restarts the loop.
 *
 * Playback is a ramp, not steps: at each step the value starts moving from
 * where it is to the step's recorded value and arrives 20 ms before the step
 * ends (the length of the step before, in 1 kHz ticks, less RAMP_MARGIN),
 * written every 16 ms, the rate at which stock applies parameter changes
 * anyway (param_groups_poll). So the jump from the loop's last value back to
 * its first takes about 40 ms at 120 BPM and 1 bar instead of landing at once. On v0.16 the lane
 * wrote each step's value in one go: a filter sweep clicked where the loop
 * started again (user, 2026-11-16).
 *
 * Values go in through stock's setter behind a received CC (param_put), as
 * EnvSync and undo do, so the sound chip, the screen and Pickup follow as for a
 * CC; nothing is sent to MIDI out. The recorded control's own Pickup is cleared
 * on each of its moves, so the hand always takes over at once. Controls without
 * a CC or NRPN number cannot be played back and are not taken. Not stored: a
 * patch load clears the lane.
 */

#include "mpe.h"

#define BUTTON_ANIMATE1 14
#define STEPS 32
#define CLOCK_POSITION (*(volatile uint32_t *)0x20012268)   /* MIDI clock count << 16 | fraction */
#define TOUCH_TICKS 250          /* the hand counts as on the control this long after its last move */
#define COUNT_JUMP 48
#define WRITE_TICKS 16           /* stock applies parameter changes every 16 ms */
#define MAX_RAMP 500             /* a step longer than this (the clock stood still) is not a ramp length */
#define RAMP_MARGIN 20           /* a ramp ends this long before its step does, so that its last value
                                    (written up to WRITE_TICKS late) is in before the next ramp starts */

enum { M_OFF, M_ARMED, M_REC, M_PLAY };

static uint8_t state;
static uint8_t swallow;          /* the Animate 1 press was taken: take its release too */
static uint8_t hires;            /* the control is a 9-bit one: values 0-255 over two patch bytes */
static uint8_t touched;
static uint8_t step;             /* the step the loop is in */
static uint8_t cur_val;          /* the control's last value from the hand */
static uint8_t written;          /* the value the patch has now, as far as the lane knows */
static uint8_t before_val;       /* the value before the recording */
static uint16_t id;              /* the control: its patch offset */
static uint16_t last_count;
static uint16_t phase;           /* clocks into the loop */
static uint32_t touch_tick;
static uint8_t ramp_from, ramp_to;   /* the ramp of the step that is playing */
static uint32_t ramp_tick, ramp_len;
static uint32_t step_tick;       /* when the current step began */
static uint32_t write_tick;
PATCH_NOINIT static uint8_t steps[STEPS];   /* written whole when a recording starts */

static uint32_t step_clocks(void)
{
    uint8_t n = globals[MPE_G_MOTION_LEN];
    return 3u << (n > 2 ? 0 : n);
}

static uint32_t value(void)
{
    return hires ? (uint32_t)(patches[id] * 2 + (patches[id + 1] >> 6)) & 0xFF : patches[id];
}

/* Sets the control. Stock's setter also asks for the page to be redrawn
 * (mark_changed), and drawing the screen keeps the main loop from its
 * modulation ticks (diag.c, LateTicks), so a lane playing 16 steps a second
 * would cost ticks all the time: the redraw request is taken back. A page
 * that shows the control keeps its old number while the lane plays. */
static void write(uint32_t v)
{
    uint8_t flags = ui_msg_state[1];
    if (hires) {
        param_put(id, v >> 1);
        param_put(id + 1u, (v & 1) << 6);
    } else {
        param_put(id, v);
    }
    ui_msg_state[1] = flags;
    written = (uint8_t)v;
}

const char *motion_state_name(void)
{
    static const char *const names[] = {"Off", "Armed", "Rec", "Play"};
    return names[state];
}

/* A patch load: the lane belongs to the patch that was there. */
void motion_clear(void)
{
    state = M_OFF;
}

static void stop(void)
{
    if (state >= M_REC) {
        write(before_val);
        const char *name = patch_param_desc[id].name;
        ui_say("MOTION", "Stopped", name ? name : "", "");
    } else {
        ui_say("MOTION", "Off", "", "");
    }
    state = M_OFF;
}

/* One panel button event (as qa_panel_read reads it). 1 = taken. */
int motion_button(uint32_t ev, int mod_held)
{
    if (!(ev & 0xFF) || ((ev >> 8) & 0xFF) != BUTTON_ANIMATE1)
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
    if (state == M_OFF) {
        state = M_ARMED;
        ui_say("MOTION", "Move a control", "to record it", "Mod+Animate1: cancel");
    } else {
        stop();
    }
    return 1;
}

/* A control moved (disp_knob_overlay, before stock handles the move). */
void motion_knob(uint32_t kid, uint32_t cur, uint32_t is_hires)
{
    if (state == M_OFF)
        return;
    if (state == M_ARMED) {
        if (kid >= 0xFB || !param_id_of(kid))
            return;                          /* not playable: stay armed for another control */
        id = (uint16_t)kid;
        hires = is_hires & 1;
        before_val = (uint8_t)value();
        for (uint32_t i = 0; i < STEPS; i++)
            steps[i] = (uint8_t)cur;
        phase = 0;
        step = 0;
        last_count = (uint16_t)(CLOCK_POSITION >> 16);
        step_tick = mpe_ticks();
        touched = 0;
        state = M_REC;
    }
    if (kid != id)
        return;
    pickup_state[id] = 0;                    /* the hand takes over at once */
    cur_val = (uint8_t)cur;
    written = (uint8_t)cur;                  /* stock applies this move itself */
    steps[step] = (uint8_t)cur;
    if (state == M_PLAY) {
        touched = 1;
        touch_tick = mpe_ticks();
    }
}

/* A new step began. */
static void next_step(uint8_t s, uint32_t now)
{
    int wrapped = s < step;
    uint32_t len = now - step_tick;          /* how long the step before took */
    step = s;
    step_tick = now;
    if (state == M_REC) {
        if (!wrapped) {
            steps[s] = cur_val;              /* held until the hand moves again */
            return;
        }
        state = M_PLAY;                      /* one loop recorded */
    }
    if (touched && now - touch_tick < TOUCH_TICKS) {
        steps[s] = cur_val;                  /* the hand is on the control: replace */
        return;
    }
    touched = 0;
    ramp_from = written;
    ramp_to = steps[s];
    ramp_tick = now;
    if (len > MAX_RAMP)
        len = MAX_RAMP;
    ramp_len = len > 2 * RAMP_MARGIN ? len - RAMP_MARGIN : len / 2 + 1;
}

/* Main-loop pass (mpe_ui_poll). */
void motion_poll(void)
{
    if (state < M_REC)
        return;
    uint32_t now = mpe_ticks();
    uint16_t count = (uint16_t)(CLOCK_POSITION >> 16);
    uint16_t d = (uint16_t)(count - last_count);
    if (d) {
        last_count = count;
        uint32_t per = step_clocks();
        phase = d > COUNT_JUMP ? 0 : (uint16_t)((phase + d) % (STEPS * per));
        uint8_t s = (uint8_t)(phase / per);
        if (s != step)
            next_step(s, now);
    }
    if (state != M_PLAY || touched || now - write_tick < WRITE_TICKS)
        return;
    uint32_t e = now - ramp_tick;
    int32_t v = e >= ramp_len ? ramp_to
              : ramp_from + ((int32_t)ramp_to - ramp_from) * (int32_t)e / (int32_t)ramp_len;
    if ((uint8_t)v != written) {
        write((uint32_t)v);
        write_tick = now;
    }
}
