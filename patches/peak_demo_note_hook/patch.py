"""Peak demo C patch: shift MIDI notes per hook kind, so the hooks are audible.

The Peak counterpart of patches/demo_note_hook, made for hardware: it proves
on the synth that the startup hook, pointer hooks and bl hooks run (demo.c
has the table of shifts: +19 semitones = all ran). Boot screen and Settings
show "DEMO Ver" so the image is recognisable. Addresses (observed):
docs/symbols/peak-2.2-2108.csv.

  pointer hooks: channel-handler table (RAM 0x200001A8, .data initialiser at
                 flash 0x080453B8), entry 8x note_off and entry 9x note_on.
  bl hooks:      note_on -> voice_dispatch 0x0800F570; note_off's mono
                 retrigger -> voice_dispatch 0x0800F51A; note_off ->
                 voice_release at 0x0800F4E0 (poly), 0x0800F4F8 and
                 0x0800F52C (mono). Every dispatch and release reached from
                 MIDI is hooked, so note on and off get the same shift.
  not hooked:    the arpeggiator (0x08015216) and the panel's audition
                 button (0x08017040, note 60): it plays unshifted.
"""

SOURCE = "peak-firmware-2.2-build2108.syx"
NAME = "peak-demo-note-hook"

# (flash address, original bytes, new bytes, why)
PATCHES = [
    (0x080452FB, b" Version ", b"DEMO Ver ",
     "boot screen label; .data initialiser of RAM 0x200000EB"),
    (0x080445E8, b"Version\x00", b"DEMOVer\x00",
     "item name on Settings page 2/26 SYSTEM"),
]

SOURCES = ["demo.c"]

VOICE_DISPATCH, VOICE_RELEASE = 0x08012984, 0x08011CC8

HOOKS = [
    ("pointer", 0x080453B8, 0x0800F4B1, "demo_note_off",
     "channel-handler table entry 8x (note off), .data initialiser of RAM 0x200001A8"),
    ("pointer", 0x080453C0, 0x0800F53D, "demo_note_on",
     "channel-handler table entry 9x (note on), .data initialiser of RAM 0x200001B0"),
    ("bl", 0x0800F570, VOICE_DISPATCH, "demo_voice_dispatch",
     "note_on -> voice_dispatch(note, vel)"),
    ("bl", 0x0800F51A, VOICE_DISPATCH, "demo_voice_dispatch",
     "note_off, mono: retrigger the held note -> voice_dispatch"),
    ("bl", 0x0800F4E0, VOICE_RELEASE, "demo_voice_release",
     "note_off, poly -> voice_release(note, 0)"),
    ("bl", 0x0800F4F8, VOICE_RELEASE, "demo_voice_release",
     "note_off, mono (last note 0xFF) -> voice_release(note, 0)"),
    ("bl", 0x0800F52C, VOICE_RELEASE, "demo_voice_release",
     "note_off, mono (no held note left) -> voice_release(note, 0)"),
]
