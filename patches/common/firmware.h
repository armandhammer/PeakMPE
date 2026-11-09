/* Firmware functions and globals that patch code may use: Summit 2.2, build 2121.
 *
 * The addresses come from docs/symbols/summit-2.2-2121.csv through the
 * generated fw_symbols.ld (functions as address | 1, Thumb). Only prototypes
 * we're confident about are here; each says how we know. Confidence labels
 * are the findings' (docs/findings/summit-2.2-build2121.md): observed = read
 * from the code, emulated = checked in emu/ tests, inferred = a reasoned
 * reading. A wrong prototype silently passes wrong arguments, so add new ones
 * only with evidence.
 *
 * The firmware is built for the hard-float ABI (findings, "Float ABI"), as
 * patch code is, so float/double arguments would go in s0/d0 both ways.
 * None of the functions below take floats.
 */
#ifndef SUMMIT_FIRMWARE_H
#define SUMMIT_FIRMWARE_H

#include <stdint.h>

/* Patch RAM that __patch_start doesn't clear (common/patch.ld): only for
 * variables written whole before their first use. */
#define PATCH_NOINIT __attribute__((section(".noinit")))

/* --- MIDI input -------------------------------------------------------- */

/* A channel-message handler, as called from midi_channel_filter: r0 points at
 * the data bytes (data[0], data[1]); r1-r3 carry the source and part
 * bookkeeping, which the handlers below don't read (observed for note_on and
 * cc). Wrappers should pass all four registers on unchanged. */
typedef void midi_handler_fn(const uint8_t *data, uint32_t r1, uint32_t r2, uint32_t r3);

/* One entry of midi_channel_handlers (8 bytes). observed */
struct midi_handler_entry {
    midi_handler_fn *handler;
    uint8_t len;     /* data bytes after the status */
    uint8_t flags;   /* bit 0: running status allowed; bit 2: system real-time */
    uint16_t pad;
};

/* RAM table 0x200002D0, indexed by (status >> 4) - 8; .data, initialised
 * from flash 0x0804C050. observed */
extern struct midi_handler_entry midi_channel_handlers[8];

/* Feed one byte to the parser of the selected input queue. observed, emulated
 * (tests/test_patch_toolchain.py). */
void midi_parse_byte(uint8_t byte);
/* Select input queue src (0 USB, 1 DIN) for midi_parse_byte. observed */
void midi_queue_select(uint32_t src);
/* (src, handler, msg): msg = [status, data...]; routes by channel and mode,
 * writes midi_current_part, then calls handler(msg + 1, ...). observed */
void midi_channel_filter(uint32_t src, midi_handler_fn *handler, const uint8_t *msg);

/* Channel handlers. note_on: data[0] note, data[1] velocity (0 = note off);
 * observed, emulated. cc: data[0] controller, data[1] value; emulated
 * (tests/test_cc_nrpn.py). The others take the same pointer; observed. */
midi_handler_fn note_on, note_off, poly_at, cc, program_change, chan_at, bend;

/* --- Voices ------------------------------------------------------------ */

/* (note, velocity, part): unison loop over voice_alloc. observed */
void voice_trigger(uint8_t note, uint8_t velocity, uint8_t part);
/* (note, velocity, part, voice, unison): voice >= 0 forces that voice index,
 * -1 lets the allocator choose. observed */
void voice_alloc(uint8_t note, uint8_t velocity, uint8_t part, int32_t voice, int8_t unison);
/* (note, part): releases the part's active voices playing note, all of them
 * in the mono modes (patch +0x22 < 3); with sustain held it only marks them
 * (voice_state+0x3B8+v). Compares voice_note[v] with note. observed */
void voice_release(uint8_t note, uint8_t part);
/* (part): glides voice_pitch_out toward voice_pitch for the voice in
 * voice_loop_index. voice_alloc calls it (0x08016F5C) after choosing the
 * voice and before its osc_pitch calls. observed */
void voice_glide(uint32_t part);
/* (part): reads every voice's envelope state and level from the FPGA into
 * voice_env_state / voice_env_level: both engines in Single mode (part
 * ignored), the part's engine in Multi. It waits for 2 (Single) or 3 (Multi)
 * EXTI15 edges since the last read first (voice_env_poll 0x08014D54).
 * voice_candidates calls it (0x0801562A) for every voice_alloc that lets the
 * allocator choose; nothing else does. observed */
void voice_env_read(uint32_t part);

/* --- Modulation and the FPGA queue --------------------------------------- */

/* (part_mask, target, param, value): appends one entry to the 128-entry
 * fpga_queue; the TIM6 interrupt sends up to 4 per 50 us. part_mask 0x80 =
 * engine A, 0x40 = engine B, 0 = by target (voices 0-7 A, 8-15 B). No
 * overflow check: the write index wraps. emulated (emu/fpga.py) */
void fpga_mod_write(uint8_t part_mask, uint8_t target, uint16_t param, int32_t value);
/* (target, param, value): one write straight to the FPGA under cpsid f, not
 * queued; target 0-15 is a voice (engine by voice). voice_alloc writes the
 * new voice's 0x000-0x002 with it (0x08016F8C). emulated (emu/fpga.py) */
void fpga_voice_write(uint8_t target, uint16_t param, int32_t value);
/* (part): one part's 1 kHz modulation update, called twice per tick by
 * mod_tick. Smooths the part bend and queues 0x68/0x69 (target 0x1A) and
 * 0x868/0x869 (0x19), the part sources and one voice's 0x61. observed */
void mod_update(uint32_t part);

/* (osc, part): one oscillator's pitch for voice voice_loop_index, stored as
 * s32 at osc + 0xC + 4 * voice (4,096 per octave) and sent as param
 * 0x000-0x002. osc is osc1_pitch/osc2_pitch/osc3_pitch. Reads the part bend
 * from part_bend_smoothed[part] through the literal at 0x08013AD4. No return
 * value; uses r0-r7 only. observed (disassembly), emulated */
void osc_pitch(uint8_t *osc, uint32_t part);

/* Firmware main, called by Reset_Handler (and by __patch_start). inferred */
void main_loop(void);

/* --- Settings ---------------------------------------------------------- */

/* Main loop, every pass: applies globals to the running state (channels,
 * mode). No arguments. observed */
void globals_apply_poll(void);
/* globals -> ext flash 0x300000 (0x200 bytes). No arguments. observed */
void settings_save(void);

/* --- Menus ------------------------------------------------------------- */

/* The current menu page record: {char *title; u8 n_items; u8 selected;
 * 4 x {u8 kind; u8 pad; u16 index}}. observed */
const uint8_t *ui_current_page(void);
/* (delta): change the selected item's value by delta and store it through
 * param_write; delta 0 = the Init Patch value. observed */
void ui_value_change(int32_t delta);
/* Set the "changed" flag (0x20004B21 bit 0) that param_write sets. observed */
void mark_changed(void);

/* The current menu page's index: menu->cur of menus[ui_state[2]]. observed */
uint8_t ui_current_page_index(void);
/* (display, value): print value at the LCD cursor in display type display
 * (1-0x60; other types print nothing). The page drawers set the cursor to
 * column 11 of the item's row first. observed */
void format_value(uint32_t display, uint32_t value);
/* Print a 0-terminated string at the LCD cursor; returns its length. observed */
uint32_t lcd_puts(const char *s);
/* Draw the current page's item values and the cursor mark (0x10 after the
 * selected item), as after a value change. observed, emulated */
void ui_draw_values(void);
/* Nonzero while a message ("Settings Saved With ...") covers the page; the
 * page redraws skip drawing then. observed */
uint32_t ui_message_active(void);
/* Main loop: switch UI mode when one was requested. No arguments. observed */
void mode_request_poll(void);
/* boot: ext flash 0x300000 -> globals. No arguments. observed */
void settings_load(void);

/* A menu: {u8 cur; u8 n_pages; u16 pad; page *pages[n_pages]}; a page:
 * {char *title; u8 n_items; u8 selected; 4 x {u8 kind; u8 pad; u16 index}};
 * a descriptor (12 bytes): {u8 min, max, nrpn_msb, nrpn_lsb; u32 display;
 * char *name}. Kind 3 items take the value at globals[index] and the
 * descriptor global_param_desc[index] (0x30 records). observed */
extern uint8_t *menus[15];                  /* by UI mode; [10] = Settings */
extern uint8_t settings_menu[4 + 33 * 4];
extern uint8_t global_param_desc[0x30 * 12];
extern volatile uint8_t ui_state[4];        /* [2] = UI mode (10 = Settings) */

/* --- Globals (observed) ------------------------------------------------ */

extern volatile uint8_t multi_mode;           /* nonzero = Multi */
extern volatile uint8_t midi_global_channel;  /* 0-15 */
extern volatile uint8_t midi_part_a_channel;
extern volatile uint8_t midi_part_b_channel;
extern volatile uint8_t midi_current_part;    /* part of the message being handled */
extern volatile uint8_t edit_part;            /* part param_locate addresses; set per message in Multi */
extern volatile uint8_t voice_note[16];
extern volatile uint16_t voice_pitch[16];     /* 8.8 semitones */
extern volatile uint8_t voice_last_alloc;     /* voice_state+0x312, set by voice_alloc */
extern volatile uint8_t voice_loop_index;     /* voice_state+10, the voice osc_pitch works on */
extern volatile int16_t part_bend_smoothed[2]; /* mod_update's smoothed part bend, +/-0x4000 */
extern uint8_t parts[2][0x288];               /* +4 bend, +0x126 last note */
extern uint8_t patches[3][0x201];             /* [multi + part]: Single, Part A, Part B; +0x22 voice mode */
extern uint8_t globals[0x200];                /* global settings, ext flash 0x300000 */
extern volatile uint8_t voice_state[0x400];   /* SoA; +0x334 + v active (gate held) */
/* +0x4A8: 100 us steps since the last modulation tick request, 0-9
 * (tim6_isr 0x08011F90 counts every second 20 kHz IRQ; the request at 10).
 * +0x4AC ms counter, +0x4B4 EXTI15 edge count. observed */
extern volatile uint8_t timer_state[0x4C0];
/* Per (engine * 16 + voice in engine), as voice_env_read last read them: the
 * index is the voice in Single mode, part * 16 + (voice - part * 8) in Multi.
 * State 0 attack, 1/2 decay/sustain, 3 release or idle; the level tells the
 * last two apart (voice_candidates takes a voice as still sounding above
 * 0x200, set at 0x08015694). observed (the FPGA side inferred) */
extern volatile uint8_t voice_env_state[32];
extern volatile uint16_t voice_env_level[32];

#endif
