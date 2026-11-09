"""MPE for the Summit, step 1: the core (docs/mpe-design.md).

Settings and live state (RPN 0, RPN 6, Save), the per-patch flag, zone
routing in Single and Multi mode, and the channel <-> voice binding. The
expression (per-note bend, pressure, Slide) and the Settings page are later
steps; they add modules next to these (patches/mpe/mpe.h).

  bl hooks x2:  midi_parse_byte's midi_channel_filter calls -> mpe_channel_filter
  bl hooks x3:  voice_trigger calls (note_on, note_off's mono fallback, arp)
  bl hook:      voice_trigger's voice_alloc call -> forced-voice channel reuse
  bl hook:      voice_alloc's voice_glide call -> binds the chosen voice
  bl hook:      voice_candidates' voice_env_read -> reuses the FPGA read the
                reuse rule made (v1.1: idle voices rotate as stock)
  bl hooks x4:  note_off's voice_release calls -> release by channel
  bl hook:      main_loop's globals_apply_poll -> Settings layout to live state
  bl hook:      settings_save_action's settings_save -> live state to globals
  bl hooks x5:  ui_value_change calls -> the VOICE item writes the flag itself
  byte patches: patch_param_desc[0x1A2] (the MPE flag: 0-1, Off/On, "MPE"),
                VOICE page 1 item 3 = the flag, version labels "MPE3"

Step 3, the Settings MPE pages (mpe_ui.c):
  bl hook:      main_loop's first settings_load -> builds the relocated tables
                (and sets menus[10]) before the main loop runs
  bl hook:      main_loop's mode_request_poll -> redraws the MPE values on change
  bl hook:      ui_draw_values' kind 3 format_value -> the MPE value formatter
  bl hooks x5:  ui_current_page_index where stock acts on a Settings page number
  pointers x3:  global_param_desc's three literals

Emulated in tests/test_mpe_*.py. Hardware only from a tagged main commit.
"""

SOURCE = "summit-firmware-2.2-build2121.syx"
NAME = "mpe"

PATCH_PARAM_DESC = 0x0804E7CC  # flash initialiser of patch_param_desc (RAM 0x20002A4C), 12 B per patch offset
FLAG_DESC = PATCH_PARAM_DESC + 0x1A2 * 12  # 0x0804FB64: {min, max, nrpn msb, nrpn lsb, u32 display, char *name}
VOICE_PAGE_1 = 0x0804E43C  # flash initialiser of the VOICE menu's first page (RAM 0x200026BC)

PATCHES = [
    # Version labels: boot screen "MPE3 Ver 126.778", Settings "MPE3Ver".
    # MPE1 = v1 (hw/2026-11-02-mpe-v1); MPE2 = v1.1 (hw/2026-11-08-mpe-v1.1),
    # the channel-reuse rule that lets idle voices rotate; MPE3 = v1.2, Slide
    # written per voice directly instead of through a phase-guarded queue.
    (0x0804C3B7, b" Version ", b"MPE3 Ver ", "boot screen label (.data initialiser of RAM 0x20000637)"),
    (0x0804B3E4, b"Version\x00", b"MPE3Ver\x00", "Settings 2/33 SYSTEM item name"),
    # The flag's reserved descriptor: max 0 -> 1, display 0 -> 0x0F (Off/On).
    # NRPN stays 255:0 (no MIDI). The name pointer is the hook below.
    (FLAG_DESC + 1, b"\x00", b"\x01", "patch_param_desc[0x1A2].max: MPE flag 0-1"),
    (FLAG_DESC + 4, b"\x00\x00\x00\x00", b"\x0f\x00\x00\x00", "patch_param_desc[0x1A2].display: Off/On"),
    # VOICE page 1: Unison, UniDetune, and now MPE (kind 1 = patch_param_desc, index 0x1A2).
    (VOICE_PAGE_1 + 4, b"\x02", b"\x03", "VOICE page 1: 2 -> 3 items"),
    (VOICE_PAGE_1 + 14, b"\x00\x00\x00\x00", b"\x01\x00\xa2\x01", "VOICE page 1 item 3: kind 1, index 0x1A2"),
]

SOURCES = ["mpe_settings.c", "mpe_route.c", "mpe_voice.c", "mpe_ui.c"]

MIDI_CHANNEL_FILTER = 0x08010710
VOICE_TRIGGER = 0x08017244
VOICE_ALLOC = 0x08016B40
VOICE_GLIDE = 0x08013914
VOICE_ENV_READ = 0x08014E3C
VOICE_RELEASE = 0x080154F4
GLOBALS_APPLY_POLL = 0x0800EE70
SETTINGS_SAVE = 0x0800F4EC
UI_VALUE_CHANGE = 0x0801CDE0
SETTINGS_LOAD = 0x08011000
MODE_REQUEST_POLL = 0x0800EF34
FORMAT_VALUE = 0x0801B18C
UI_CURRENT_PAGE_INDEX = 0x0801C808
GLOBAL_PARAM_DESC = 0x20003DFC  # RAM; 0x30 records, no room after it

# (kind, site, expected original, patch symbol, why)
HOOKS = [
    ("bl", 0x08010804, MIDI_CHANNEL_FILTER, "mpe_channel_filter", "midi_parse_byte: channel message"),
    ("bl", 0x08010864, MIDI_CHANNEL_FILTER, "mpe_channel_filter", "midi_parse_byte: channel message, other path"),
    ("bl", 0x08010B0A, VOICE_TRIGGER, "mpe_trigger_note_on", "note_on -> voice_trigger"),
    ("bl", 0x08010A70, VOICE_TRIGGER, "mpe_trigger_held", "note_off: mono fallback to a held note"),
    ("bl", 0x0800D0F2, VOICE_TRIGGER, "mpe_trigger_held", "arpeggiator -> voice_trigger"),
    ("bl", 0x080172DE, VOICE_ALLOC, "mpe_voice_alloc", "voice_trigger's unison loop -> voice_alloc"),
    ("bl", 0x08016F5C, VOICE_GLIDE, "mpe_alloc_glide", "voice_alloc: voice chosen, before osc_pitch"),
    ("bl", 0x0801562A, VOICE_ENV_READ, "mpe_env_read", "voice_candidates: FPGA envelope read (v1.1 reuse rule)"),
    ("bl", 0x08010A08, VOICE_RELEASE, "mpe_note_release", "note_off: arp path"),
    ("bl", 0x08010A3A, VOICE_RELEASE, "mpe_note_release", "note_off: poly modes"),
    ("bl", 0x08010A4E, VOICE_RELEASE, "mpe_note_release", "note_off: mono, no last note"),
    ("bl", 0x08010A8E, VOICE_RELEASE, "mpe_note_release", "note_off: mono, no held note left"),
    ("bl", 0x0801C62C, GLOBALS_APPLY_POLL, "mpe_globals_apply_poll", "main_loop: apply globals"),
    ("bl", 0x0800F5CA, SETTINGS_SAVE, "mpe_settings_save", "settings_save_action: Settings Save"),
    ("bl", 0x0801AC3A, UI_VALUE_CHANGE, "mpe_ui_value_change", "ui_encoder_event: encoder"),
    ("bl", 0x0801ADA0, UI_VALUE_CHANGE, "mpe_ui_value_change", "ui_button_event: value reset"),
    ("bl", 0x0801ADA8, UI_VALUE_CHANGE, "mpe_ui_value_change", "ui_button_event: value inc/dec"),
    ("bl", 0x0801D256, UI_VALUE_CHANGE, "mpe_ui_value_change", "ui_page_step: value change"),
    ("bl", 0x0801D27C, UI_VALUE_CHANGE, "mpe_ui_value_change", "ui_page_step: value change"),
    ("pointer", FLAG_DESC + 8, 0x00000000, "mpe_flag_name", "patch_param_desc[0x1A2].name"),
    # Step 3: the Settings MPE pages.
    ("bl", 0x0801C57A, SETTINGS_LOAD, "mpe_ui_boot", "main_loop: first settings_load, before the main loop runs"),
    ("bl", 0x0801C642, MODE_REQUEST_POLL, "mpe_ui_poll", "main_loop: redraw the MPE values when they change"),
    ("bl", 0x0801CBF4, FORMAT_VALUE, "mpe_ui_format", "ui_draw_values: kind 3 (global) value"),
    ("bl", 0x0800F5A6, UI_CURRENT_PAGE_INDEX, "mpe_settings_page_index", "settings_save_action: tuning page > 16"),
    ("bl", 0x0801812A, UI_CURRENT_PAGE_INDEX, "mpe_settings_page_index", "tuning NRPN: Settings page > 16"),
    ("bl", 0x0801D460, UI_CURRENT_PAGE_INDEX, "mpe_settings_page_index", "item action: Settings page 1 (Calibrate)"),
    ("bl", 0x0801D47A, UI_CURRENT_PAGE_INDEX, "mpe_settings_page_index", "item action: Settings page 15"),
    ("bl", 0x0801D4C2, UI_CURRENT_PAGE_INDEX, "mpe_settings_page_index", "item action: Settings page 9"),
    ("pointer", 0x0801C9E8, GLOBAL_PARAM_DESC, "mpe_global_desc", "ui_draw_page: kind 3 item name"),
    ("pointer", 0x0801CC9C, GLOBAL_PARAM_DESC, "mpe_global_desc", "ui_draw_values: kind 3 display type"),
    ("pointer", 0x0801D220, GLOBAL_PARAM_DESC, "mpe_global_desc", "ui_value_change: kind 3 min/max"),
]

# --- Step 2: per-note expression (patches/mpe/mpe_expr.h) ---------------------
#
#   pointer hook: osc_pitch's literal for part_bend_smoothed -> mpe_bend_in
#                 (0 for MPE voices: their bend is an offset after osc_pitch)
#   bl hooks x6:  osc_pitch calls in mod_tick and voice_alloc -> per-voice
#                 bend offset, pressure slot, Slide target
#   bl hook:      mod_update's broadcast 0x60 -> dropped for MPE engines
#   bl hook:      mod_tick's mod_update(1) -> per-voice 0x60 (Slide + wheel)

SOURCES += ["mpe_expr.c", "mpe_bend.c", "mpe_pressure.c", "mpe_slide.c"]

OSC_PITCH = 0x08013A2C
PART_BEND_SMOOTHED = 0x2001389C
FPGA_MOD_WRITE = 0x08013FCC
MOD_UPDATE = 0x080140C4

HOOKS += [
    ("pointer", 0x08013AD4, PART_BEND_SMOOTHED, "mpe_bend_in", "osc_pitch: literal for the part bend"),
    ("bl", 0x08014526, OSC_PITCH, "mpe_osc_pitch_tick", "mod_tick: osc_pitch(osc1)"),
    ("bl", 0x08014530, OSC_PITCH, "mpe_osc_pitch_tick", "mod_tick: osc_pitch(osc2)"),
    ("bl", 0x0801453A, OSC_PITCH, "mpe_osc_pitch_tick", "mod_tick: osc_pitch(osc3)"),
    ("bl", 0x08016F66, OSC_PITCH, "mpe_osc_pitch_alloc", "voice_alloc: osc_pitch(osc1)"),
    ("bl", 0x08016F72, OSC_PITCH, "mpe_osc_pitch_alloc", "voice_alloc: osc_pitch(osc2)"),
    ("bl", 0x08016F7C, OSC_PITCH, "mpe_osc_pitch_alloc", "voice_alloc: osc_pitch(osc3)"),
    ("bl", 0x08014248, FPGA_MOD_WRITE, "mpe_wheel_write", "mod_update: broadcast 0x60 to 0x1A"),
    ("bl", 0x0801457E, MOD_UPDATE, "mpe_mod_update", "mod_tick -> mod_update(1), last part update of the tick"),
]
