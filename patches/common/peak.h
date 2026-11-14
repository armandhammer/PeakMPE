/* Firmware functions and globals that patch code may use: Peak 2.2, build 2108.
 *
 * The Peak counterpart of firmware.h (Summit 2.2). Addresses come from
 * docs/symbols/peak-2.2-2108.csv through the generated fw_symbols.ld
 * (functions as address | 1, Thumb). Each prototype says how we know it;
 * "as Summit" means the Peak function was read side by side with the
 * Summit's and does the same with the same arguments. A wrong prototype
 * silently passes wrong arguments, so add new ones only with evidence.
 *
 * What differs from the Summit, all observed in the Peak's code:
 *   - 8 voices, one FPGA engine (chip select PB6), one part in practice;
 *   - no FPGA write queue: every write is a direct SPI transaction;
 *   - mod_update takes no argument and runs before mod_tick's voice loop;
 *   - UI mode is ui_state[0]; Settings is mode 8; 11 menus.
 */
#ifndef PEAK_FIRMWARE_H
#define PEAK_FIRMWARE_H

#include <stdint.h>

/* Patch RAM that __patch_start doesn't clear (common/patch.ld): only for
 * variables written whole before their first use. */
#define PATCH_NOINIT __attribute__((section(".noinit")))

#define PEAK_VOICES 8

/* --- MIDI input -------------------------------------------------------- */

/* A channel-message handler, as called from midi_channel_filter: r0 points at
 * the data bytes; r1-r3 are passed on unchanged. As Summit. */
typedef void midi_handler_fn(const uint8_t *data, uint32_t r1, uint32_t r2, uint32_t r3);

struct midi_handler_entry {
    midi_handler_fn *handler;
    uint8_t len;
    uint8_t flags;
    uint16_t pad;
};

/* RAM 0x200001A8, .data (init 0x080453B8). observed */
extern struct midi_handler_entry midi_channel_handlers[8];

/* (src, handler, msg): msg = [status, data...]; calls handler(msg + 1, ...)
 * only when the channel is midi_global_channel. No Multi branch. observed */
void midi_channel_filter(uint32_t src, midi_handler_fn *handler, const uint8_t *msg);

/* Channel handlers (table order). observed */
midi_handler_fn note_on, note_off, poly_at, cc, program_change, chan_at, bend;

/* --- Arpeggiator MIDI out ---------------------------------------------- */

/* (note, velocity): midi_send3(0x90 / 0x80, note, velocity), the status
 * OR midi_global_channel. arp_step calls arp_midi_note_on at 0x08015202 with
 * the step's note and velocity; arp_step_release calls arp_midi_note_off at
 * 0x08014EE2 with velocity 0x40. Observed in the decompile (2026-11-13) and
 * on the rig (arp steps arrive as 90 nn vv / 80 nn 40). */
void arp_midi_note_on(uint32_t note, uint32_t velocity);
void arp_midi_note_off(uint32_t note, uint32_t velocity);

/* --- Voices ------------------------------------------------------------ */

/* (note, velocity): routes to voice_trigger by voice_part_mode (0: part 0;
 * 1: split at voice_split_point; 2: both parts). Callers pass r2 = 0, which
 * it ignores. note_on, note_off's mono fallback, the arpeggiator and a
 * panel button call it. observed */
void voice_dispatch(uint8_t note, uint8_t velocity);
/* (note, velocity, part): unison loop over voice_alloc(.., -1, unison).
 * As Summit voice_trigger. observed */
void voice_trigger(uint8_t note, uint8_t velocity, uint8_t part);
/* (note, velocity, part, voice, unison): voice >= 0 forces that voice, -1
 * lets the allocator choose. As Summit. observed */
void voice_alloc(uint8_t note, uint8_t velocity, uint8_t part, int32_t voice, int8_t unison);
/* (note, part): releases the part's voices playing note (by voice_part_mode
 * through voice_release_part). note_off passes part 0. observed */
void voice_release(uint8_t note, uint8_t part);
/* (part): glide for voice voice_loop_index; voice_alloc passes 0. observed */
void voice_glide(uint32_t part);
/* (part): reads all 8 voices' envelope state and level from the FPGA into
 * voice_env_state / voice_env_level. voice_candidates calls it (0x08011B8E).
 * The argument isn't read before the reads (inferred from the code). */
void voice_env_read(uint32_t part);

/* --- Modulation and the FPGA ------------------------------------------- */

/* (target, param, value): one direct SPI1 write (three 16-bit frames) with
 * chip select PB6; target 0-7 a voice, 8-15 the part/broadcast targets.
 * Not interrupt-masked. observed */
void fpga_write(uint8_t target, uint16_t param, int32_t value);
/* (target, n, value): fpga_write(target, 0x60 + n, value). n 0 ModWheel,
 * 1 AftTouch, 7 pitch; target 0xA = all voices. observed */
void voice_mod_write(uint8_t target, uint8_t n, int32_t value);
/* (): the part's 1 kHz modulation update: smooths the bend into
 * part_bend_smoothed and sends 0x68/0x69, the wheel (broadcast 0x60 at
 * 0x08010972), 0x62/0x63 and one voice's 0x61. mod_tick calls it first,
 * before its voice loop (0x08010E70). observed */
void mod_update(void);
/* (osc, part): one oscillator's pitch for voice voice_loop_index, sent as
 * param 0x000-0x002. Reads part_bend_smoothed through the literal at
 * 0x08010C24. As Summit. observed */
void osc_pitch(uint8_t *osc, uint32_t part);

/* Firmware main, called by Reset_Handler (and by __patch_start). observed */
void main_loop(void);

/* --- Settings ---------------------------------------------------------- */

/* Main loop: applies globals (as Summit 0x0800EE70). No arguments. observed */
void globals_apply_poll(void);
/* globals -> ext flash 0x300000 (0x200 bytes). observed */
void settings_save(void);
/* ext flash 0x300000 -> globals. observed */
void settings_load(void);
/* Main loop, every pass: the SysEx receive state machine. No arguments.
 * The MPE UI wraps it as its per-pass hook (the Peak has no mode request
 * poll). inferred (void, reads only memory) */
void sysex_rx_poll(void);

/* --- Menus ------------------------------------------------------------- */

/* As Summit: the current page record {char *title; u8 n_items; u8 selected;
 * 4 x {u8 kind; u8 pad; u16 index}}. observed */
const uint8_t *ui_current_page(void);
/* (delta): change the selected item's value. As Summit. observed */
void ui_value_change(int32_t delta);
/* Set the changed flag (0x20011208 + 1, bit 0). As Summit. observed */
void mark_changed(void);
/* menus[ui_state[0]]->cur. observed */
uint8_t ui_current_page_index(void);
/* (display, value): print value in display type display. As Summit. observed */
void format_value(uint32_t display, uint32_t value);
/* Print a string at the LCD cursor; returns its length. As Summit. observed */
uint32_t lcd_puts(const char *s);
/* Draw the current page's values and cursor mark. observed (as Summit by
 * structure: kind 3 reads global_param_desc) */
void ui_draw_values(void);
/* Nonzero while a message covers the page. As Summit. observed */
uint32_t ui_message_active(void);

/* A menu: {u8 cur; u8 n_pages; u16 pad; page *pages[n_pages]}. As Summit. */
extern uint8_t *menus[11];                  /* by UI mode; [6] VOICE, [8] Settings */
extern uint8_t settings_menu[4 + 26 * 4];
extern uint8_t global_param_desc[0x30 * 12];
extern volatile uint8_t ui_state[4];        /* [0] = UI mode (8 = Settings) */

#define PEAK_UI_SETTINGS 8
#define PEAK_SETTINGS_PAGES 26

/* --- Globals (observed) ------------------------------------------------ */

extern volatile uint8_t midi_global_channel;  /* 0-15 */
extern volatile uint8_t voice_part_mode;      /* 0 one part; no direct store found (inferred: stays 0) */
extern volatile uint8_t voice_note[PEAK_VOICES];
extern volatile int16_t part_bend_smoothed;   /* mod_update's smoothed bend, +/-0x4000 */
extern uint8_t parts[0xA8];                   /* +4 bend, +6 wheel, +8 expression, +9 breath */
extern uint8_t patches[0x201];                /* the current patch; +0x22 voice mode, +0x23 unison */
extern uint8_t globals[0x200];                /* global settings, ext flash 0x300000 */
/* SoA: +9 voice loop index, +0x36 smoothed wheel (s16), +0x44+2v aftertouch
 * slot, +0x54+4v smoothed aftertouch, +0x1E6 last allocated voice,
 * +0x1F4+v gate. observed */
extern volatile uint8_t voice_state[0x200];
extern volatile uint8_t voice_env_state[PEAK_VOICES];   /* 3 = release or idle */
extern volatile uint16_t voice_env_level[PEAK_VOICES];  /* above 0x200 = still sounding */

#define voice_loop_index (voice_state[9])
#define VOICE_GATE(v) (voice_state[0x1F4 + (v)])
#define VOICE_AT_SLOT(v) (*(volatile uint16_t *)&voice_state[0x44 + 2 * (v)])
#define VOICE_AT_SMOOTH(v) (*(volatile int32_t *)&voice_state[0x54 + 4 * (v)])
#define PART_WHEEL (*(volatile int16_t *)&voice_state[0x36])

/* --- Knob overlay and the LCD (observed, docs/findings/peak-2.2-build2108.md) */

/* (id, prev, cur, saved, hires): the knob-turn overlay and pickup test.
 * id = patch offset; prev/cur the knob's previous and current value (0-127,
 * 0-255 when hires); saved = the compare buffer's value; hires 0 or 1 (a
 * stack word). Returns 1 = apply cur, 0 = pickup pending. Draws rows 0-2 (and
 * the pickup label on row 3) and calls format_value three times, at
 * 0x08016C3C (cur on the pickup row), 0x08016C72 (current), 0x08016C90 (saved
 * val). Callers: knob_poll at 0x08016EF2 and 0x08016F28. */
int knob_overlay(uint32_t id, uint32_t prev, uint32_t cur, uint32_t saved, uint32_t hires);
/* (col, row): DDRAM address 0x80 | col + row * 32. */
void lcd_cursor(uint32_t col, uint32_t row);
/* (cmd), (byte): the LCD's serial command and data writes. */
void lcd_write_cmd(uint32_t cmd);
void lcd_write_data(uint32_t byte);
/* (): CGRAM address 0 and the 64 bytes at 0x20000A78: stock's box frame. */
void lcd_load_cgram(void);
/* (code): one character through the escape state machine (9 = cursor). */
void lcd_putc_esc(uint32_t code);

/* patch_param_desc: 12-byte records by patch offset (RAM 0x200017CC). */
struct param_desc {
    uint8_t min, max, nrpn_msb, nrpn_lsb;
    uint32_t display;       /* low byte: the format_value type */
    const char *name;
};
extern const struct param_desc patch_param_desc[0x1A3];
/* One byte per patch offset (0xFB): 0 = picked up, nonzero = the knob has
 * not yet passed the patch value. */
extern volatile uint8_t pickup_state[0xFB];
/* 0x20011208: +1 flags, +2 message countdown (nonzero: a message is shown). */
extern volatile uint8_t ui_msg_state[8];

#endif
