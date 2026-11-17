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
  bl hook:      main_loop's globals_apply_poll -> Settings layout to live state
  bl hook:      settings_save_action's settings_save -> live state to globals
  bl hooks x4:  ui_value_change calls -> the VOICE item writes the flag itself
  byte patches: patch_param_desc[0x1A2] (the MPE flag: 0-1, Off/On, "MPE"),
                VOICE page 1 item 3 = the flag, version labels "MPEJ" (v0.19; "MPEI" = v0.18, "MPEH" = v0.17, "MPEG" = v0.16, "MPEF" = v0.15, "MPEE" = v0.14, "MPED" = v0.13, "MPEC" = v0.12, "MPEB" = v0.11, "MPEA" = v0.10, "MPE9" = v0.9, "MPE8" = v0.8, "MPE7" = v0.7, "MPE6" = v0.6, "MPE5" = v0.5, "MPE4" = v0.4, "MPE3" = v0.3, "MPE2" = v0.2, "MPE1" = v0.1)
UI (Settings MPE pages):
  bl hook:      main_loop's first settings_load -> builds the relocated tables
  bl hook:      main_loop's sysex_rx_poll -> redraws the MPE values on change
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
    # Version labels: boot screen "MPEJ Ver ...", Settings "MPEJVer".
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
    (0x080452FB, b" Version ", b"MPEJ Ver ", "boot screen label (.data initialiser of RAM 0x200000EB)"),
    (0x080445E8, b"Version\x00", b"MPEJVer\x00", "Settings 2/28 SYSTEM item name"),
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
           "morph.c"]

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
    ("bl", 0x08016C2A, LCD_PUTS, "disp_skip_puts", "knob_overlay: the pickup label on row 3"),
    ("bl", 0x08016C48, LCD_PUTS, "disp_skip_puts", "knob_overlay: the row-3 clear after a pickup"),
    ("bl", 0x08016C3C, FORMAT_VALUE, "disp_fmt_pick", "knob_overlay: the knob's value on the pickup row"),
    ("bl", 0x08016C72, FORMAT_VALUE, "disp_fmt_cur", "knob_overlay: the 'current' value"),
    ("bl", 0x08016C90, FORMAT_VALUE, "disp_fmt_saved", "knob_overlay: the 'saved val' value"),
]
