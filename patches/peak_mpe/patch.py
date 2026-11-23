"""MPE for the Novation Peak, firmware 2.2 (build 2108).

The Peak port of patches/mpe (Summit 2.2): the same design (docs/mpe-design.md)
for one part, 8 voices, one FPGA engine and no Multi mode. Every hook site
below was read side by side with the Summit's and checked against the Peak
image (decoded bl target or literal); addresses and evidence are in
docs/symbols/peak-2.2-2108.csv.

Core:
  bl hooks x2:  midi_parse_byte's midi_channel_filter calls -> mpe_channel_filter
  bl hooks x3:  voice_dispatch calls (note_on, note_off's mono fallback, arp)
  bl hook:      voice_trigger's voice_alloc call -> forced-voice channel reuse
  bl hook:      voice_alloc's voice_glide call -> binds the chosen voice
  bl hook:      voice_candidates' voice_env_read -> reuses the trigger's read
  bl hooks x3:  note_off's voice_release calls -> release by channel
  bl hook:      main_loop's globals_apply_poll -> Settings layout to live state (once per 1 kHz tick, v0.29)
  bl hook:      settings_save_action's settings_save -> live state to globals
  bl hooks x4:  ui_value_change calls -> the VOICE item writes the flag itself
  byte patches: patch_param_desc[0x1A2] (the MPE flag: 0-1, Off/On, "MPE"),
                VOICE page 1 item 3 = the flag, version labels "MPEb" (v0.37; "MPEa" = v0.36, "MPEZ" = v0.35, "MPEY" = v0.34, "MPEX" = v0.33, "MPEW" = v0.32, "MPEV" = v0.31, "MPEU" = v0.30, "MPET" = v0.29, "MPES" = v0.28, "MPER" = v0.27, "MPEQ" = v0.26, "MPEP" = v0.25, "MPEO" = v0.24, "MPEN" = v0.23, "MPEM" = v0.22, "MPEL" = v0.21, "MPEK" = v0.20, "MPEJ" = v0.19, "MPEI" = v0.18, "MPEH" = v0.17, "MPEG" = v0.16, "MPEF" = v0.15, "MPEE" = v0.14, "MPED" = v0.13, "MPEC" = v0.12, "MPEB" = v0.11, "MPEA" = v0.10, "MPE9" = v0.9, "MPE8" = v0.8, "MPE7" = v0.7, "MPE6" = v0.6, "MPE5" = v0.5, "MPE4" = v0.4, "MPE3" = v0.3, "MPE2" = v0.2, "MPE1" = v0.1)
UI (Settings MPE pages):
  bl hook:      main_loop's first settings_load -> builds the relocated tables
  bl hook:      main_loop's sysex_rx_poll -> the patch's polls, once per 1 kHz tick (v0.29), and the MPE values' redraw
  bl hook:      ui_draw_values' kind 3 format_value -> the MPE value formatter
  bl hooks x3:  ui_current_page_index where stock acts on a Settings page number
  pointers x3:  global_param_desc's three literals
Expression:
  pointer hook: osc_pitch's literal for part_bend_smoothed -> mpe_bend_in
  bl hooks x6:  osc_pitch calls in mod_tick and voice_alloc
  bl hook:      mod_update's broadcast 0x60 -> dropped while MPE is on
  bl hook:      mod_tick's mod_update() -> per-voice 0x60 (Slide + wheel)
Arp echo filter (arp_echo.c; v0.2):
  bl hooks x2:  arp_step's arp_midi_note_on, arp_step_release's
                arp_midi_note_off -> remember the notes the arp sends
  (in mpe_channel_filter) incoming notes matching one within ~100 ms are
                dropped, so a DAW routing loop can't stop the arp

Knob display (disp.c; v0.3):
  bl hooks x2:  knob_poll's knob_overlay calls -> disp_knob_overlay
  bl hooks x2:  knob_overlay's lcd_puts of the pickup label and the row-3 clear -> dropped
  bl hooks x3:  knob_overlay's format_value calls (pickup row, current, saved
                val) -> ms / Hz text, nothing, ms / Hz text
  (and mpe_ui_poll calls disp_poll, which puts stock's custom characters back)
                value bars on row 3; pickup arrow and distance bar

LCD cache (lcdcache.c; v0.23):
  bl hooks x2:  the escape layer's lcd_putc and lcd_cursor calls -> a character
                the display already shows isn't sent again
  bl hooks x2:  lcd_init (the copy becomes blank), the panel power-up after the
                screen saver (the copy is forgotten)

Release velocity (relvel.c; v0.24):
  bl hooks x2:  mod_update's broadcast ExprPED1 / BrthPED2 writes -> dropped for
                the source Settings RELEASE VEL names
  (in mpe_channel_filter and mpe_note_release) the note-off's velocity goes to
                that source of the voices about to be released

MIDI Tuning Standard (mts.c; v0.25):
  bl hook:      sysex_rx_byte's call of mts_single_note_rx -> stock's parser,
                then one that takes device ID 7F and any number of notes in
                a single-note change, and the bulk dump with device ID 7F

Per-port receive filters (pfilter.c; v0.34):
  no hook:      in mpe_channel_filter, Settings USB IN and DIN IN (Notes, CC,
                Patch) drop a port's channel messages; port 2, the synth's
                own output read back in, is never filtered

Just intonation (ji.c; v0.35):
  no hook:      in mpe_expr.c's osc_pitch wrapper, every voice gets a pitch
                offset, fixed to Settings JUST TUNE Root or following the
                chord (Mode Adapt)

Patch change timed to the clock (ptime.c; v0.31; v0.34 counts only the
Clock Source port):
  bl hooks x2:  program_change's and the panel's patch_select_load -> wait
                for the next beat or bar of a playing external clock
  bl hooks x2:  the MIDI input loop's clock handlers -> count the clock
  RAM table:    Start, Continue, Stop handlers (midi_sys_handlers, at boot)

Patch dump on patch change (pdump.c; v0.30):
  bl hook:      patch_select_load's patch_select_set -> with Settings PATCH
                DUMP > Send = USB, stock's current-patch answer (editor
                answer 00) goes out over USB after a stored patch loads

Front-panel panic (panic.c; v0.28):
  no hook:      Mod + Audition (qa_panel_read takes the press and its
                release) runs stock's CC 120, then clears the held keys,
                the arp's keys and play map, the MPE voice bindings and the
                stored per-channel bend, pressure and slide

Section randomiser (rand.c; v0.26, band-pass and high-pass ranges v0.27):
  no hook:      Settings RANDOMISE (mpe_ui.c's pages) rolls one section of
                the patch through param_put, as section copy does

9-bit CC pairs over MIDI (ccpair.c; v0.22):
  bl hook:      cc's call of param_set_by_id for a plain CC -> the coarse
                byte of a pair is held against half the pair's range, so Osc
                Fine CC 15/18/21 at 14-27 (Fine -100 to -73) is no longer dropped

Summit hooks with no Peak counterpart: note_off's arp-path release (the
Peak's arp calls its own note-off), ui_page_step's second branch, the tuning
NRPN page check (no such NRPN handler), POT CALIBRATE (no such page).

Built and hook-verified only. Not yet run in a simulator or on hardware.
"""

SOURCE = "peak-firmware-2.2-build2108.syx"
NAME = "mpe"

PATCH_PARAM_DESC = 0x080469DC  # flash initialiser of patch_param_desc (RAM 0x200017CC), 12 B per patch offset
FLAG_DESC = PATCH_PARAM_DESC + 0x1A2 * 12  # 0x08047D74: {min, max, nrpn msb, nrpn lsb, u32 display, char *name}
VOICE_PAGE_1 = 0x08048648  # flash initialiser of the VOICE menu's first page (RAM 0x20003438)

PATCHES = [
    # Version labels: boot screen "MPEb Ver ...", Settings "MPEbVer".
    # MPE1 = v0.1 (first hardware release); MPE2 = v0.2 (arp echo filter);
    # MPE3 = v0.3 (knob display: ms and Hz, bars, pickup arrow);
    # MPE4 = v0.4 (Settings MPE page: PressCurve Squared/Linear);
    # MPE5 = v0.5 (CC 11 on a member channel is pressure);
    # MPE6 = v0.6 (Settings MPE EXTRAS: EnvSync, tempo-synced Decay and Release);
    # MPE7 = v0.7 (EnvSync applies a changed setting after 1 s, so scrolling past a choice does nothing);
    # MPE8 = v0.8 (quick-assign modulation: hold Mod, move a control);
    # MPE9 = v0.9 (quick-assign message redrawn on every move: stock overwrote it);
    # MPEA = v0.10 (quick-assign: with Mod held a control only selects, stock draws and applies nothing);
    # MPEB = v0.11 (Settings PARAM LOCK: keep FX, Arp or Voice settings through a patch change);
    # MPEb = v0.37 (a Continue after power-up waits for a Start or Song Position Pointer,
    #        ptime.c; the patch dump is requested right before sysex_rx_poll, pdump.c).
    # MPEa = v0.36 (notes on a zone's master channel play chords: channel reuse for member
    #        channels only, mpe_voice.c; A-Z used up, lower case from here).
    # MPEZ = v0.35 (just intonation, ji.c: Settings JUST TUNE, Fixed or Adapt).
    # MPEY = v0.34 (per-port receive filters, pfilter.c; patch timing follows the Clock Source port).
    # MPEX = v0.33 (PATCH TIMING message: program_change passes stack garbage in bits 16-31; masked).
    # MPEW = v0.32 (review fixes: patch timing grace, Continue, bank check, clock order; patch dump Off).
    # MPEV = v0.31 (patch change timed to the clock, ptime.c).
    # MPEU = v0.30 (patch dump on patch change, pdump.c).
    # MPET = v0.29 (main-loop headroom: the per-pass polls once per 1 kHz tick).
    # MPES = v0.28 (front-panel panic: Mod + Audition, panic.c).
    # MPER = v0.27 (RANDOMISE: band-pass cutoff 64-150 with resonance, high-pass up to 110, from the rig).
    # MPEQ = v0.26 (Settings RANDOMISE: one section rolled inside safe ranges, rand.c; PARAM LOCK's chorus Mode and buffer).
    # MPEP = v0.25 (MIDI Tuning Standard: device ID 7F and several notes per single-note change, mts.c).
    # MPEO = v0.24 (release velocity into ExprPED1 or BrthPED2 per voice: Settings RELEASE VEL, relvel.c).
    # MPEN = v0.23 (LCD cache: a character the display already shows isn't sent again, lcdcache.c; the bar's characters load one per main-loop pass).
    # MPEM = v0.22 (Osc 1/2/3 Fine over MIDI reaches -100: the coarse byte of a 9-bit CC pair is held against half the pair's range, ccpair.c).
    # MPEL = v0.21 (arp ratchets: Settings ARP RATCHET, a note sounds two or three times in its step).
    # MPEK = v0.20 (Compare leaves the undo step and a motion lane alone: both stand still while it is held;
    #         Euclidean arp rhythms: Settings ARP EUCLID, euclid.c; the arp echo filter drops a note off only
    #         while a loop is known, so a key let go without a loop always stops its arp note).
    # MPEJ = v0.19 (morph: stands still while Compare is held, so the release finds the edit again; starts afresh after Save).
    # MPEI = v0.18 (patch morph: Settings MORPH page, the mod wheel blends the edited patch towards the stored one).
    # MPEH = v0.17 (motion playback as a ramp between steps; LateTicks a latched "count gap" reading; no page redraw from playback).
    # MPEG = v0.16 (motion recording: Mod + Animate 1; Settings MOTION page with Length, state, LateTicks).
    # MPEF = v0.15 (messages always clear and are held 3 s; Msg Time counts 22 ms, 127 = about 3 s).
    # MPEE = v0.14 (Glide start option on MPE EXTRAS; tick counts for the real 1 kHz tick; 2 s message hold by ticks).
    # MPED = v0.13 (v0.12 plus longer Do it message, 20-column undo text). MPEC = v0.12 (section copy, one-level undo, MIDI monitor).
    # Message time: stock takes one count off the message countdown when the ms counter
    # has advanced by more than 10 (cmp r3, #10 in ui_msg_countdown 0x08018ADC), so Msg
    # Time 127 lasts 1.45 s (about 1.5 s measured by the user, 2026-11-15) where the
    # guide says about 3 s. More than 21 makes a count 22 ms: 127 = 2.9 s, 64 = 1.5 s.
    (0x08018AEA, bytes.fromhex("0a2b"), bytes.fromhex("152b"), "ui_msg_countdown: one count per 22 ms instead of 11 (cmp r3, #21)"),
    (0x080452FB, b" Version ", b"MPEb Ver ", "boot screen label (.data initialiser of RAM 0x200000EB)"),
    (0x080445E8, b"Version\x00", b"MPEbVer\x00", "Settings 2/28 SYSTEM item name"),
    # The flag's reserved descriptor: max 0 -> 1, display 0 -> 0x0F (Off/On,
    # as KeySync/FadeSync/Common on the Peak). NRPN stays 255:0. The name
    # pointer is a hook below.
    (FLAG_DESC + 1, b"\x00", b"\x01", "patch_param_desc[0x1A2].max: MPE flag 0-1"),
    (FLAG_DESC + 4, b"\x00\x00\x00\x00", b"\x0f\x00\x00\x00", "patch_param_desc[0x1A2].display: Off/On"),
    # VOICE page 1: Unison, UniDetune, and now MPE (kind 1, index 0x1A2).
    (VOICE_PAGE_1 + 4, b"\x02", b"\x03", "VOICE page 1: 2 -> 3 items"),
    (VOICE_PAGE_1 + 14, b"\x00\x00\x00\x00", b"\x01\x00\xa2\x01", "VOICE page 1 item 3: kind 1, index 0x1A2"),
]

SOURCES = ["mpe_settings.c", "mpe_route.c", "mpe_voice.c", "mpe_ui.c",
           "mpe_expr.c", "mpe_bend.c", "mpe_pressure.c", "mpe_slide.c",
           "arp_echo.c", "disp.c", "envsync.c", "qassign.c", "paramlock.c", "section.c", "diag.c", "motion.c",
           "morph.c", "euclid.c", "ccpair.c", "lcdcache.c", "relvel.c", "mts.c", "rand.c", "panic.c", "pdump.c", "ptime.c", "pfilter.c", "ji.c"]

MIDI_CHANNEL_FILTER = 0x0800EED0
VOICE_DISPATCH = 0x08012984
VOICE_ALLOC = 0x080122B0
VOICE_GLIDE = 0x08010A9C
VOICE_ENV_READ = 0x0801162C
VOICE_RELEASE = 0x08011CC8
GLOBALS_APPLY_POLL = 0x08018C24
SETTINGS_SAVE = 0x08018F2C
UI_VALUE_CHANGE = 0x08018448
SETTINGS_LOAD = 0x0801AFD8
SYSEX_RX_POLL = 0x0801A47C
FORMAT_VALUE = 0x08017604
UI_CURRENT_PAGE_INDEX = 0x08017EEC
GLOBAL_PARAM_DESC = 0x20002B7C  # RAM; 0x22 records, other data after them
OSC_PITCH = 0x08010B60
PART_BEND_SMOOTHED = 0x2001233E
VOICE_MOD_WRITE = 0x08010850
MOD_UPDATE = 0x0801088C
PART_MOD_WRITE = 0x0801086C
ARP_MIDI_NOTE_ON = 0x08014EA4
ARP_MIDI_NOTE_OFF = 0x08014EB4
KNOB_OVERLAY = 0x08016B14
PANEL_EVENT_READ = 0x0800DDFC
FW_MEMCPY = 0x0801D736
LCD_PUTS = 0x0800D260
PATCH_SAVE = 0x08018F10
ARP_TICK = 0x08015554
ARP_STEP_SELECT = 0x08015408
PARAM_SET_BY_ID = 0x0800F6AC
LCD_PUTC = 0x080168C8
LCD_CURSOR = 0x080168B4
LCD_INIT = 0x080169E4
LCD_POWER_ON = 0x08016804
MTS_SINGLE_NOTE_RX = 0x08019548
PATCH_SELECT_SET = 0x08018C58
PATCH_SELECT_LOAD = 0x0801AF78
MIDI_CLOCK_RX_0 = 0x0800FBD0
MIDI_CLOCK_RX_1 = 0x0800FBE8

# (kind, site, expected original, patch symbol, why)
HOOKS = [
    ("bl", 0x0800F014, MIDI_CHANNEL_FILTER, "mpe_channel_filter", "midi_parse_byte: channel message"),
    ("bl", 0x0800F074, MIDI_CHANNEL_FILTER, "mpe_channel_filter", "midi_parse_byte: channel message, other path"),
    ("bl", 0x0800F570, VOICE_DISPATCH, "mpe_trigger_note_on", "note_on -> voice_dispatch"),
    ("bl", 0x0800F51A, VOICE_DISPATCH, "mpe_trigger_held", "note_off: mono fallback to a held note"),
    ("bl", 0x08015216, VOICE_DISPATCH, "mpe_trigger_held", "arpeggiator -> voice_dispatch"),
    ("bl", 0x08012942, VOICE_ALLOC, "mpe_voice_alloc", "voice_trigger's unison loop -> voice_alloc"),
    ("bl", 0x08012640, VOICE_GLIDE, "mpe_alloc_glide", "voice_alloc: voice chosen, before osc_pitch"),
    ("bl", 0x08011B8E, VOICE_ENV_READ, "mpe_env_read", "voice_candidates: FPGA envelope read"),
    ("bl", 0x0800F4E0, VOICE_RELEASE, "mpe_note_release", "note_off: poly modes"),
    ("bl", 0x0800F4F8, VOICE_RELEASE, "mpe_note_release", "note_off: mono, no last note"),
    ("bl", 0x0800F52C, VOICE_RELEASE, "mpe_note_release", "note_off: mono, no held note left"),
    ("bl", 0x0800D1B6, GLOBALS_APPLY_POLL, "mpe_globals_apply_poll", "main_loop: apply globals"),
    ("bl", 0x08018FFA, SETTINGS_SAVE, "mpe_settings_save", "settings_save_action: Settings Save"),
    ("bl", 0x08016FC2, UI_VALUE_CHANGE, "mpe_ui_value_change", "ui_encoder_event: encoder"),
    ("bl", 0x080170F2, UI_VALUE_CHANGE, "mpe_ui_value_change", "panel_button_event: value reset"),
    ("bl", 0x080170FA, UI_VALUE_CHANGE, "mpe_ui_value_change", "panel_button_event: value inc/dec"),
    ("bl", 0x08018708, UI_VALUE_CHANGE, "mpe_ui_value_change", "ui_page_step: value change"),
    ("pointer", FLAG_DESC + 8, 0x00000000, "mpe_flag_name", "patch_param_desc[0x1A2].name"),
    # Settings MPE pages.
    ("bl", 0x0800D132, SETTINGS_LOAD, "mpe_ui_boot", "main_loop: first settings_load, before the main loop runs"),
    ("bl", 0x0800D1C4, SYSEX_RX_POLL, "mpe_ui_poll", "main_loop: per-pass call, redraw the MPE values"),
    ("bl", 0x080181D8, FORMAT_VALUE, "mpe_ui_format", "ui_draw_values: kind 3 (global) value"),
    ("bl", 0x08018FD6, UI_CURRENT_PAGE_INDEX, "mpe_settings_page_index", "settings_save_action: tuning page > 8"),
    ("bl", 0x0801838C, UI_CURRENT_PAGE_INDEX, "mpe_settings_page_index", "item action: Settings page 1 (Calibrate)"),
    ("bl", 0x080183A4, UI_CURRENT_PAGE_INDEX, "mpe_settings_page_index", "item action: Settings page 9 (BACKUP)"),
    ("pointer", 0x0801806C, GLOBAL_PARAM_DESC, "mpe_global_desc", "ui_draw_page: kind 3 item name"),
    ("pointer", 0x080182B8, GLOBAL_PARAM_DESC, "mpe_global_desc", "ui_draw_values: kind 3 display type"),
    ("pointer", 0x080186E4, GLOBAL_PARAM_DESC, "mpe_global_desc", "ui_value_change: kind 3 min/max"),
    # Expression.
    ("pointer", 0x08010C24, PART_BEND_SMOOTHED, "mpe_bend_in", "osc_pitch: literal for the part bend"),
    ("bl", 0x08010EB8, OSC_PITCH, "mpe_osc_pitch_tick", "mod_tick: osc_pitch(osc1)"),
    ("bl", 0x08010EC2, OSC_PITCH, "mpe_osc_pitch_tick", "mod_tick: osc_pitch(osc2)"),
    ("bl", 0x08010ECC, OSC_PITCH, "mpe_osc_pitch_tick", "mod_tick: osc_pitch(osc3)"),
    ("bl", 0x0801264A, OSC_PITCH, "mpe_osc_pitch_alloc", "voice_alloc: osc_pitch(osc1)"),
    ("bl", 0x08012654, OSC_PITCH, "mpe_osc_pitch_alloc", "voice_alloc: osc_pitch(osc2)"),
    ("bl", 0x0801265E, OSC_PITCH, "mpe_osc_pitch_alloc", "voice_alloc: osc_pitch(osc3)"),
    ("bl", 0x08010972, VOICE_MOD_WRITE, "mpe_wheel_write", "mod_update: broadcast 0x60 to all voices"),
    ("bl", 0x08010A7C, VOICE_MOD_WRITE, "mpe_pressure_write_voice", "mod_update: voice pressure (AftTouch) write, Linear curve"),
    ("bl", 0x08010A84, PART_MOD_WRITE, "mpe_pressure_write_part", "mod_update: part pressure write, same value"),
    ("bl", 0x080109C0, VOICE_MOD_WRITE, "relvel_pedal_write", "mod_update: broadcast ExprPED1 (0x62) to all voices"),
    ("bl", 0x08010A0E, VOICE_MOD_WRITE, "relvel_pedal_write", "mod_update: broadcast BrthPED2 (0x63) to all voices"),
    ("bl", 0x08010E70, MOD_UPDATE, "mpe_mod_update", "mod_tick -> mod_update(), before the voice loop"),
    # Arp echo filter.
    ("bl", 0x08015202, ARP_MIDI_NOTE_ON, "arp_echo_note_on", "arp_step: arp step note on to MIDI"),
    ("bl", 0x08014EE2, ARP_MIDI_NOTE_OFF, "arp_echo_note_off", "arp_step_release: arp step note off to MIDI"),
    # Knob-turn display (disp.c).
    ("bl", 0x08016EF2, KNOB_OVERLAY, "disp_knob_overlay", "knob_poll: 7-bit knob"),
    ("bl", 0x08016F28, KNOB_OVERLAY, "disp_knob_overlay", "knob_poll: 9-bit knob"),
    ("bl", 0x0801AECC, FW_MEMCPY, "plock_copy", "patch load: the copy into the patch (parameter lock)"),
    ("bl", 0x08016FF4, PANEL_EVENT_READ, "qa_panel_read", "panel_button_event: the button event read (Mod held)"),
    ("bl", 0x0801903E, PATCH_SAVE, "morph_patch_save", "settings_save_action: the Save button's write of the patch (morph)"),
    ("bl", 0x08011956, ARP_TICK, "euclid_arp_tick", "tick work 0x0801192C: the call of arp_tick (Euclidean rhythm)"),
    ("bl", 0x0801574E, ARP_STEP_SELECT, "euclid_step_select", "arp_tick: the choice of the next note (ratchet repeats)"),
    ("bl", 0x08016C2A, LCD_PUTS, "disp_skip_puts", "knob_overlay: the pickup label on row 3"),
    ("bl", 0x08016C48, LCD_PUTS, "disp_skip_puts", "knob_overlay: the row-3 clear after a pickup"),
    ("bl", 0x08016C3C, FORMAT_VALUE, "disp_fmt_pick", "knob_overlay: the knob's value on the pickup row"),
    ("bl", 0x08016C72, FORMAT_VALUE, "disp_fmt_cur", "knob_overlay: the 'current' value"),
    ("bl", 0x08016C90, FORMAT_VALUE, "disp_fmt_saved", "knob_overlay: the 'saved val' value"),
    ("bl", 0x0800F318, PARAM_SET_BY_ID, "ccpair_param_set", "cc: a plain CC to the setter (Osc Fine's coarse byte, ccpair.c)"),
    # LCD cache (lcdcache.c).
    ("bl", 0x0800D1FA, LCD_PUTC, "lcd_cache_putc", "escape layer: the only call of lcd_putc for text"),
    ("bl", 0x0800D216, LCD_CURSOR, "lcd_cache_cursor", "escape layer: the only call of lcd_cursor"),
    ("bl", 0x0800D202, LCD_INIT, "lcd_cache_init", "boot: lcd_init (ends with a clear)"),
    ("bl", 0x08016932, LCD_POWER_ON, "lcd_cache_power_on", "lcd_display_on: the panel's power-up after the screen saver"),
    # MIDI Tuning Standard (mts.c).
    ("bl", 0x0800F112, PATCH_SELECT_LOAD, "ptime_select", "program_change: the patch load (timed to the clock)"),
    ("bl", 0x08018C9A, PATCH_SELECT_LOAD, "ptime_select", "panel_patch_apply: the patch load (timed to the clock)"),
    ("bl", 0x0800F0A0, MIDI_CLOCK_RX_1, "ptime_clock_1", "MIDI input loop: a clock byte on port 1"),
    ("bl", 0x0800F0A8, MIDI_CLOCK_RX_0, "ptime_clock_0", "MIDI input loop: a clock byte on port 0"),
    ("bl", 0x0801AFC2, PATCH_SELECT_SET, "pdump_patch_selected", "patch_select_load: after the stored patch loaded (patch dump)"),
    ("bl", 0x0801AE42, MTS_SINGLE_NOTE_RX, "mts_rx", "sysex_rx_byte: the single-note tuning parser, then the patch's"),
]
