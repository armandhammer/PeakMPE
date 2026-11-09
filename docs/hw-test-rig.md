# Hardware test rig

An unattended end-to-end test of the MPE firmware on the real Summit: a
script on the Mac sends MIDI, records the Summit's main outputs through an
audio interface, and checks the audio. It replaces most of the manual
listening of the first MPE hardware run with measurements: pitch in cents, voice counts, levels, silence.

The simulator (`emu/synth.py`, [SIMULATOR.md](SIMULATOR.md)) stays the
main test bed for firmware logic. The rig covers what it can't: the real
FPGA, USB and DIN timing, Live-like traffic, and the analog output.

**Status:** stage 1 (this document, `tools/hwrig list` and `probe`, the
analysis and its unit tests, the `hw` marker). Stages 2–4 are the plan
below.

## Setup

```
Mac ── USB ─────────────── Summit (MIDI port "Summit")
 │                            │ main out L/R
 ├─ USB-MIDI interface ─ DIN ─┘ (MIDI IN)
 └─ audio interface ◄─────────┘ inputs, line level
```

- **MIDI:** the Summit's USB port (`Summit`), and for the DIN path a USB-MIDI
  interface whose output is wired to the Summit's MIDI IN. Live's dense MPE
  output overruns DIN (L4 in the v1 run), so USB is the main path and DIN is
  tested on its own, at rates DIN can carry.
- **Audio:** the Summit's main outputs L and R into two line inputs. The
  Summit has no USB audio. Level: set the input gain so `probe` reads about
  −12 dBFS; nothing in the checks needs an absolute level.
- **Nothing else sends to the Summit during a run.** Live can stay open
  and keep monitoring the same inputs (Core Audio lets several apps read
  one input; the first run was recorded that way), but it must not send
  MIDI or clock to the Summit or the AF16Rig DIN port: no armed MPE track
  played, no transport start/stop (its bend reset burst), no MIDI clock
  sync to the Summit. CoreMIDI merges senders, so that traffic would land
  in the middle of a check. Live also must not switch the interface to
  another sample rate: the device has one rate for every app.
- **Monitors down.** Test patches are pure sines at a fixed level; through
  speakers they are loud and unpleasant.

### Configuration

Nothing about the interfaces is assumed. `tools/hwrig list` prints the
audio inputs (index, name, channel count) and the MIDI ports; put the
names into `work/hwrig.toml` (copy [`tools/hwrig/hwrig.example.toml`](../tools/hwrig/hwrig.example.toml);
`work/` is git-ignored), or pass them as flags:

| Key | Flag | Meaning |
|---|---|---|
| `midi.usb_port` | `--port` | MIDI output, exact name or a unique substring (default `Summit`) |
| `midi.din_port` | `--din` selects it | the USB-MIDI interface output wired to the Summit's DIN in |
| `midi.channel` | `--channel` | 1–16 |
| `audio.audio_device` | `--device` | input device: index or name substring; empty = system default |
| `audio.inputs` | `--inputs 1,2` | 1-based input channels with Summit L, R |
| `audio.samplerate` | `--samplerate` | 48000 by default |
| `probe.notes` | `--notes 57,45` | MIDI notes (57 = A3, middle C = 60 = C4) |
| `probe.slot` | `--slot D002` | select a slot first (CC 32 + program change); empty = don't |
| `patches.mpe_base`, `plain_base` | | base slots for `setup` (default D002, D003) |

## Test patches

Every check uses a sound that makes one property easy to measure. The rig
builds them itself (`hwrig setup`, below); each starts from the Init Patch:

- Osc 1 **sine**, Osc 2 and 3 level 0, noise and ring mod 0.
- Filter fully open (low-pass at maximum, resonance 0, no drive, no key or
  envelope amount), so a voice is one clean partial.
- FX off: distortion, chorus, delay, reverb levels 0.
- No LFO routing, oscillator drift/diverge 0, glide off, no unison.
- Amp envelope: attack 0, decay 0, sustain full, release 0, amp
  velocity 0 (64, bipolar), so the level is the same for every note.
- VOICE `MPE` **On** (except P5).

| Patch | Extra | Used by |
|---|---|---|
| **P1 sine** | none | probe, per-note bend, ±48, voice counts, stuck notes, global channel |
| **P2 pressure → pitch** | matrix: AftTouch → Osc 1 pitch, a few semitones | pressure on the right note |
| **P3 slide → pitch** | matrix: ModWheel → Osc 1 pitch (Slide arrives as the voice's mod wheel, [mpe-design.md](mpe-design.md)) | slide on the right note |
| **P4 pressure → level** | Osc 1 level about half; matrix: AftTouch → Osc 1 level | level response, the one level check |
| **P5 sine, MPE off** | `MPE` Off | the normal part in Multi mode |
| **P6 sine mono legato** | voice mode mono legato | mono/legato |
| **P7 sine, Diverge 127** | Diverge 127 (NRPN 0:9), AmpRelease 64 | voice rotation (stage 4): each voice plays a note at its own fixed offset, so the pitch says which voice it is |
| **M1 Multi** | part A = P1 (MPE), part B = P5 on a channel outside the zone | Multi mode |

Pitch is measured far more precisely than level (hundredths of a cent
against tenths of a dB), so pressure and slide route to pitch, with one
level patch for the level path. The checks don't rely on the matrix depth
values: each one first measures the response on a single note, then expects
the same response on the target note of a chord and none on the others.

### Building the sounds over MIDI (`hwrig setup`)

The Summit takes almost every patch parameter as an NRPN or a CC
([findings](findings/summit-2.2-build2121.md#cc-nrpn-and-rpn-cc-0x080102c0)),
so the rig builds each sound in the **edit buffer** and never saves it:

1. **Base slot:** CC 32 (bank) and a program change select the recipe's
   base slot. It supplies the one setting MIDI can't reach, the VOICE `MPE`
   flag (patch byte `0x1A2`): `mpe_base` (default **D002**, MPE on) or
   `plain_base` (**D003**, MPE off) in `work/hwrig.toml` `[patches]`. D001
   is the user's and isn't used; D004 is reserved.
2. **Init values:** the Init Patch value of every settable sound parameter
   (325 of them, `0x022`–`0x18C`), so the result doesn't depend on what
   the base slot sounds like.
3. **The recipe's values:** sine, envelope, matrix slots
   ([`tools/hwrig/recipes.py`](../tools/hwrig/recipes.py)).

About 800 messages, 2,400 bytes, 1.3 s, paced 25 % below the DIN rate so
either path keeps up. Selecting the base slot again restores it.

The parameter table (names, ranges, NRPN/CC numbers), the Init Patch and
the matrix, wave and voice-mode names are read at run time from the local
firmware image (`tools/hwrig/params.py`, addresses there); recipes name
their parameters, and a name that doesn't match the table stops the plan
before anything is sent. `hwrig patches` lists the recipes and both matrix
lists; it sends nothing.

**What MIDI can't set** (emulated), so it stays as in the base slot:
LevelComp, two delay entries (`0x0D7`, `0x0D8`), ClockRate (`0x0ED`,
`0x0EE`), and the **FX-matrix slots 5–8** (NRPN MSB 21–24, which `cc`
rejects). All are inaudible with the recipes' FX levels at 0 and the
arpeggiator off, except an FX-matrix slot that raises an FX level: **keep
FX-matrix slots 5–8 empty in D002 and D003.** RevType follows RevSize
when RevSize is set over NRPN, so the Init Patch's pair can't be rebuilt;
the reverb level is 0.

**Needs on the Summit** (globals can't be set over MIDI): Settings → MIDI
CONTROL, **CC/NRPN receive on** and **Bank/Patch receive on**.

**Checked in the simulator** (`tests/test_hwrig_setup.py`): the exact
bytes, at the rig's pacing, over USB for every recipe and over DIN on
channel 5, starting from a sound with every parameter at a random value;
the edit buffer then matches the recipe byte for byte, and the MPE flag is
untouched. CC 32 = 4 then program change 2 shows `4-002`. CC 0 isn't a bank
select in this firmware (it reaches the patch parameters), so it's never
sent.

`hwrig setup p1 --check` builds P1 and then plays A3: the probe's table
then also shows the strongest other partial against the fundamental (a
clean sine: well below −50 dB; D001's filter gave −25 dB).

Patches as SysEx dumps remain an option for stage 5 (they could set the
MPE flag too); until that is confirmed, the rig sends no SysEx.

## Latency

`probe` time-stamps each MIDI send on the audio stream's clock and knows the
ADC time of the first sample, so latency = onset time − send time. That
includes USB MIDI, the Summit's handling, its DAC and the interface's ADC,
and depends on the interface reporting its input latency correctly.

**Calibration (stage 2):** a cable from an interface output to an input, a
click played through the same stream, and the measured round trip gives the
interface's real input latency; it goes into the config as an offset. Until
then, latency numbers are comparable between runs on the same interface but
not absolute.

Each check cuts its analysis windows relative to the measured onset, with
margins (pre-roll ends 10 ms before the send, the sustain window starts
100 ms after onset), so a few ms of jitter don't matter. Latency is also a
result in itself: USB against DIN, and under dense traffic. Stage 2 repeats
it and reports median and 95th percentile.

## Checks

The analysis is in [`tools/hwrig/analysis.py`](../tools/hwrig/analysis.py):
spectral peaks with a 4-term Blackman-Harris window (side lobes −92 dB, so a
quiet voice next to a loud one shows), parabolic interpolation, then a
golden-section search for the maximum of the windowed DTFT. On a clean sine
that is exact to a few hundredths of a cent; the unit tests require ±1 cent
from A0 to A7 in 0.5 s, and from A3 in 0.1 s. Chord notes are always at
least a semitone apart, so their partials separate.

The Summit's oscillators are digital NCOs, so a note's pitch should be exact.
The bend path is smoothed (`part_bend_smoothed`), so pitch is measured after
it has settled (stage 2 measures the settling time once and uses it).

| Check | Stimulus | Analysis | Pass |
|---|---|---|---|
| **Per-note bend** | P1, Lower Zone; chord C4 E4 G4 on members 2–4; bend member 3 to several values | partial of each note | bent note at the expected cents (bend × range / 8192) ±1 c; the others at their baseline ±0.5 c |
| **Pressure / slide, right note** | P2 / P3; same chord; pressure or CC 74 on one member | response measured on a single note first, then on the chord | target note moves by that response ±2 c; the others don't move (±0.5 c); P4 the same in dB |
| **Voice count after an MCM zone change (bug B1)** | MCM (RPN 6 on the master channel) to change the zone or member count, a delay (0, 1, 5, 20 ms, and in the same burst as the chord, as the Hapax does), then a chord of k notes | count partials within 30 dB of the loudest; match them to the expected notes | all k notes present, nothing extra. Stress-repeated: a few hundred takes with random zone sizes, chords and delays; every failing take kept |
| **Silence after the last note-off (stuck notes)** | the end of every check, plus a dense random MPE stream (Live-like bursts, or a replayed capture) then all note-offs | tail against the pre-roll: RMS within 6 dB, and no partial 12 dB above the pre-roll's spectrum at that frequency and within 40 dB of the note | silent. The spectral test ignores mains hum (it is in the pre-roll too) and the released-voice leak (about −66 dB, see First run); a stuck note sounds near full level. The leak is reported per note, so a voice that closes less than before shows up |
| **±48 bend range** | P1, note bend range RPN 0 = 48; one note (C5, so −48 is 33 Hz and +48 8.4 kHz); bend from 0 to 16383 in steps | pitch per step | each step at the expected cents ±1 c, monotonic, no jump or wrap. The first run is exploratory: it records where the FPGA's accepted range for params `0x000`–`0x002` ends (the one untested number of the MPE v1 run), and the patch's clamp near the extremes is reported, not failed |
| **Global channel as zone master** | Summit global channel inside the zone (channel 1 = Lower Zone master); chord on members; pitch bend and CC 1 on channel 1 | every partial | all notes move by the master bend (±2 by default), together |
| **Multi mode** | M1; zone notes on members, normal notes on part B's channel (another octave); per-note bend on a member, channel bend on part B | partials by octave | the bent member note moves alone; part B moves as a whole and isn't touched by the zone's expression, and vice versa |
| **Mono / legato** | P6; note on member 2 bent, a legato note on member 3, release it | one partial over time (frames of 50 ms) | voice count 1 throughout; the pitch takes member 3's bend at once, then returns to note 1 with member 2's current bend ([mpe-design.md](mpe-design.md#voice-binding)) |
| **USB vs DIN** | the checks above over each path | the same | both pass at DIN-safe rates; latency per path reported. The dense-stream test over DIN is informational: DIN can't carry Live's bursts (3,125 bytes/s) |

### Stage 2: `hwrig run`

The checks built so far ([`tools/hwrig/checks.py`](../tools/hwrig/checks.py)),
in run order:

| Check | Sound | Stimulus | Rows (pass bounds) |
|---|---|---|---|
| `bend_one_note` | P1 | C4 E4 G4 on members 2–4; member 3 bent +683, −1365, +2048, 0 (+400, −800, +1200, 0 c; never onto another chord note) | bent note ±1 c of the expected cents re its own unbent pitch; the others ±0.5 c of theirs; silence |
| `bend_range_48` | P1 | C5 on member 2; bend 0, −2048 … −8192, +2048 … +8191, 0 | each step ±1 c; within ±24 semitones a miss fails, beyond it is **info** (exploratory: the FPGA range, the patch's clamp), with the measured pitch; monotonic (a plateau is a clamp, a step back fails); the range that was in tolerance (info); silence |
| `stuck_notes_stress` | P1 | 3 s of random notes, bends, pressure and Slide on members 2–16 (300 messages/s, under 60 % of DIN), then every note off and the channels reset | sound during the stream; silence |
| `pressure_right_note` | P2 | E4 alone on member 3 at pressure 0 and 127 (the response), then G3 E4 C5 on members 2–4, pressure 127 and 0 on member 3 | response ≥ 5 c; E4 moves by the response ±2 c and comes back ±1 c; G3 and C5 ±0.5 c; silence |
| `slide_right_note` | P3 | the same with CC 74 | the same |
| `pressure_level_right_note` | P4 | the same, pressure → level | response ≥ 1 dB; E4 ±0.5 dB of it, back ±0.3 dB; the others ±0.2 dB; silence |

Every measurement is relative to the same voice earlier in the same take, so
the interface's clock offset and the Summit's tuning cancel. Each window
starts 0.35 s after the change (bend and pressure are smoothed in the
firmware) and lasts 0.3 s.

Before the first check the run sends RPN 0 = 48 on member 2 (the note bend
range) and RPN 0 = 2 on channel 1 (master), and centres bend, pressure and
Slide on channels 2–16. It assumes the Lower Zone with master channel 1:
the Summit's own fallback for an MPE patch with Settings Zone Off, or Zone
Lower 15. It sends no MCM.

```bash
.venv/bin/python -I tools/hwrig run
```

```bash
.venv/bin/python -I tools/hwrig run --checks bend_one_note,bend_range_48
```

`--din` runs the same over `midi.din_port`. The plan lists every check,
its sound and what it sends (by type and channel), the total (about 4,300
messages, 45 s), and the cleanup; every byte is in `messages.txt` next to
the report. One `play`, then it runs unattended.

**How it is tested without hardware** (`tests/test_hwrig_run.py`):
- a fake MPE Summit ([`tests/hwrig_fake.py`](../tests/hwrig_fake.py)) that
  renders the run's MIDI as sines with per-note bend, pressure and Slide
  (and the −66 dB leak): every check passes on it, and each catches its
  injected fault (a broadcast bend, a ±24 range, pressure on every note,
  a stuck voice); a ±30 semitone clamp is reported as info, not failed;
- the exact timelines in the simulator with the MPE patch (emulated): the
  bend moves only its voice's oscillator pitch, by exactly the expected
  amount (4096 units per octave), from −48 to +48 semitones; the pressure
  reaches only its voice (`0x61`); the stress stream leaves no voice
  active.

### Stage 3: `hwrig run --stage 3`

[`tools/hwrig/checks3.py`](../tools/hwrig/checks3.py), in run order:

| Check | Sound | Stimulus | Rows (pass bounds) |
|---|---|---|---|
| `master_channel` | P1 | Single mode, global channel 1 = Lower master: G3, E4 on members 2–3, C5 **on the master**; master bend +4096, then member 2 +683, master back, member back | master bend moves all three by +100 c (±2 range), the master's own note included; the member bend moves only G3 (+400 c); ±1 c moved, ±0.5 c unchanged; silence |
| `mono_legato` | P6 (MonoLG, no glide) | C4 on member 2, bent +400 c; legato E4 on member 3 (bent −200 c before); member 2 bent to +800 c while E4 holds; E4 released | one partial in every phase; E4 at +200 c re C4; member 2's bend changes nothing while E4 sounds; back to C4 at +800 c (the channel's current bend); ±1 c |
| `b1_zone_change` | P1 | `--b1-trials` per delay (default 60 × 5 = 300): an MCM pair (the other zone to 0, then this zone to n, each after CC 121, as the Hapax sends it), the delay (`burst`: same scheduler pass, no RPN nulls; 0, 1, 5, 20 ms), a chord of 3–6 notes (≥ 3 semitones apart) on random members of the new zone; layouts from Lower/Upper 3–15, never the same twice in a row; seeded and interleaved over the delays; 10 takes of 30 | per delay: chords with every note and no extra partial, `x / N (%)`; 0 passes; a B1 row (info) saying reproduced or not; every failing trial's WAV clip and MIDI; silence after each take. **0 % is a result** (B1 not reproduced), not a reason to tune the check |
| `multi_m1` | M1 | Multi, Part A on Upper 9–15 (master 16), Part B (P5 an octave up) on its Part channel: G3, E4 on members 9–10, C4 on Part B (sounds C5); member 9 bend, Part B channel bend +4096, master 16 bend +4096 | member bend moves G3 only; Part B's bend moves C5 only, by +600 c (Init BendRange ±12, emulated) ±2 c; master 16 moves G3, E4 only; no C4 (Part B doubled on Part A); silence |
| `global_master_multi` (F5) | F5 | Multi, Part A on Lower 2–4 whose master is the global channel 1: G3 **on channel 1**, E4 on member 2, C4 on Part B; master 1 bend, Part B bend | G3 plays on Part A only (no G4 from Part B); master 1 moves G3, E4 only; Part B's bend C5 only; info row: CH CLASH (emulated: shown, `mpe_clash` bit 2; the rig can't see the screen) |

**Part channels:** the Multi checks need the Summit's Settings Part A/B
channels in `work/hwrig.toml` `[patches]` (`part_a_channel`,
`part_b_channel`; MIDI can't read or set them). The plan prints them and
asks to check them before `play`. A check whose Part channels fall inside
its zone (F5's Lower 1–4, e.g. the Summit defaults 2/3) is **skipped**,
with the reason in the plan and the report.

**Global channel and outputs:** the Summit's Settings global channel
must be `midi.channel` (1): it is the Lower Zone's master, the channel
`setup` sends its NRPNs on, and the one that switches Single/Multi. With
global 16 and Zone Off, 16 is a member of the fallback Lower 15, and M1's
Upper master. If Multi sends Part B to its own output pair, record both
pairs (`audio.inputs = [9, 10, 11, 12]` on the user's rig): every check
analyses the mean of all recorded inputs, so both parts are in it and a
single-pair signal keeps its relative levels.

**Restore:** after each check that moves the zone or switches to Multi
(`b1_zone_change`, `multi_m1`, `global_master_multi`), and again whenever
the run ends or stops (Ctrl-C, an error): NRPN 62:0 = 0 on both Part
channels and the global channel (Single mode; in Multi only a Part channel
switches), then MCM for `mpe.zone` (default `"off"`: no zone, so an MPE
patch plays Lower 15 as with Settings Zone Off; or `"lower N"`/`"upper
N"`), then bend, pressure and CC 74 centred on all 16 channels, then the
bend ranges again.

**Tested without hardware** (`tests/test_hwrig_run3.py`): on the fake
Summit every stage-3 check passes, each catches its injected fault (master
bend ignored, Part B following the zone, the global note layered onto Part
B, Part B doubled, a stale mono fallback bend, a broadcast bend, and a
B1-like drop within 1.5 ms of the MCM, which fails `burst`, 0 and 1 ms and
passes 5 and 20 ms), and an abort in the middle of M1 leaves Single mode,
no zone and no voice. In the simulator with the MPE patch (emulated): the
master channel, mono legato, M1 and F5 timelines move exactly the expected
voices by the expected amounts; ten B1 trials over all delays sound every
note; F5 sets `mpe_clash` bit 2, M1 doesn't; the restore leaves Single
mode and the Lower 15 fallback.

```bash
.venv/bin/python -I tools/hwrig run --stage 3
```

```bash
.venv/bin/python -I tools/hwrig run --stage 3 --din
```

```bash
.venv/bin/python -I tools/hwrig run --checks b1_zone_change --b1-trials 200
```

### Stage 4: `hwrig run --stage 4` (voice rotation, F1)

[`tools/hwrig/checks4.py`](../tools/hwrig/checks4.py): MPE v1.1's channel
reuse ([mpe-design.md](mpe-design.md#channel-reuse-v11)). Built 2026-11-08;
run on v1.1 the same day: every rotation row passes over USB and DIN, the
tail row failed on P7's release, which outlasted the shared 0.5–1.0 s tail
window (a rig bound). Since
2026-11-08 (v1.2 branch) the check has its own window, 1.5–2.0 s after the
last note-off (`VoiceRotation.TAIL_FROM_S`, `TAIL_S`): P7's release takes
about 0.9 s to the floor, and 2 s is the gap the "silent before each
note-on" row already shows is enough. The fake Summit's `slow_release`
fault plays releases as long as the synth's (`tests/test_hwrig_run4.py`:
the old window fails on it, the new one passes, a stuck note still fails).

**How the rig tells voices apart.** The voices play a note identically,
except for the patch's Diverge: `osc_pitch` adds `Diverge × s8 >> 5`
(8.8 semitones) from a fixed table per voice and oscillator at
`0x200007CC` (`.data`, initialiser `0x0804C54C`; observed in the image).
For Osc 1 the eight values are +1 −8 +4 −2 +6 −6 +9 −11, for voices 0–7
and again for 8–15. At Diverge 127 that's −17.2 to +13.7 cents, at least
2.7 cents between any two (emulated: the simulator's oscillator pitch per
voice matches the table). The rig measures hundredths of a cent, so a
note's pitch re its nominal frequency names its voice modulo 8.

| Check | Sound | Stimulus | Rows (pass bounds) |
|---|---|---|---|
| `voice_rotation` | P7 | a chord A3 A4 A5 E4 on members 2–5; then A4 6 × on member 2, each note-on 2 s after the previous note-off (the release has ended); then A4/C5 4 × on member 3, each 5 ms after the previous note-off (still releasing) | chord: four notes, each ≥ 1 c from the others (Diverge works; else the rest can't tell voices apart); after the release: silent before each note-on (≤ −50 dB at the note: the release had ended) and **each note ≥ 1 c from the one before** (another voice; v1 gives the same voice each time, L5), plus an info row with the number of voices used; during the release: **all four at one deviation, ±0.5 c** (the voice is taken over); silence |

The stock allocator rotates through idle voices and never takes the voice
it took last (`voice_alloc` compares with its last pick, `0x20000B14`), so consecutive notes on
idle voices always differ (inferred from the code; emulated: voices 4–9 in
turn). The ±1 c bound sits well inside the 2.7 c minimum spacing and well
outside the rig's noise.

**Tested without hardware** (`tests/test_hwrig_run4.py`): the fake
Summit's Diverge table is the firmware's (read from the image); on the
fake the check passes when idle voices rotate and a releasing one is taken
over; it fails "each note on another voice" with v1's rule
(`pinned_voice`), "during the release" when the allocator rotates there too
(`rotate_in_release`), and the chord row without Diverge. In the simulator
with the MPE patch (emulated, the release modelled as 60 ms): the
timeline's notes after the release take voices 4, 5, 6, 7, 8, 9; the four
notes during the release all take voice 10; consecutive notes differ in
oscillator pitch by the table's Diverge offsets.

```bash
.venv/bin/python -I tools/hwrig run --stage 4
```

### What stage 3 showed on the synth (2026-11-08, observed)

- **Every check passes over USB.** B1 was not reproduced in 600 trials,
  over USB and DIN.
- **Multi needs both Part channels in 4–8.** A stored Multi can have MPE on
  in both parts; the firmware then splits the channels between the parts
  itself, Part channels inside a zone become members, and their program
  change and CCs are dropped (as designed). The Multi setup therefore
  switches to Multi first, sets both zones explicitly (Lower 2 = members
  2–3, Upper 7 = 9–15) so channels 4–8 are in no zone, sets up both parts,
  and only then sets the check's layout.
- **After an MCM, a zone's member bend range is the Settings `Note Bend`**
  (default 48). A synth with `Note Bend 49` bent members ±49. The rig sends
  RPN 0 = 48 after every MCM it sends, so its results don't depend on that
  setting.
- **DIN loses messages now and then** (inferred: the interface's DIN
  output): once a preamble RPN, once two note-offs, the same way as the v1
  run's L4 stuck note. The run sends its preamble before every check, and
  the B1 check reports notes left on in their own row.

### M1: Multi

`hwrig setup m1` (the `multi_m1` check uses it): NRPN 62:0 = 1 on the
global channel (Multi), the setup layout (MCM 2 on 1, MCM 7 on 16: channels
4–8 free), then Part A on its Part channel: D002 and P1; Part B: D003 and
P5o (P5 an octave up, so its notes are told apart from Part A's); then MCM
0 on channel 1 and MCM 7 on 16 (Upper Zone 9–15 for Part A). `hwrig setup f5` is the same with
a Lower Zone 2–4 (master 1, the global channel). The Part channels are
Settings (`patches.part_a_channel`/`part_b_channel`, Summit defaults 2 and
3); MIDI can't set them. Checked in the simulator: Multi, the Upper Zone
on Part A with no clash, both parts byte for byte, a note on 9 plays Part
A, one on 3 Part B. The zone and the mode stay until a power cycle, another
MCM, or the Summit's Patch button.

## Report

Every run writes `work/hw-runs/<yyyy-mm-dd_hhmmss>/`:

- `report.md`: a pass/fail table, one row per check and variant (path,
  patch, notes, parameters, expected, measured, tolerance, result), plus the
  config, the git commit and the firmware the user says is on the synth
  (until the rig may ask for the identity, which is SysEx).
- `report.json`: the same, machine-readable.
- WAVs of the failing takes only (24-bit, all recorded inputs), each with
  the MIDI it sent and the actual send times, so a failure can be listened
  to, analysed again, and replayed in the simulator.

`probe` writes the same kind of folder (`…/probe/`), with every take's WAV,
`probe.md` and `probe.json`.

`work/` is never committed, so the WAVs and reports stay local; findings
from a run go into the docs as text.

## Running under pytest

Hardware tests carry the marker **`hw`** (`tests/test_hw_*.py`, with
`pytestmark = pytest.mark.hw`). [`tests/hwmark.py`](../tests/hwmark.py)
deselects them unless pytest gets `--hw`, whatever `-m` says, so the normal
suite, `-n auto`, `scripts/check` and CI never send MIDI.
`tests/test_hwmark.py` checks that.

```bash
.venv/bin/python -m pytest --hw -s -m hw
```

`-s` because each test prints what it sends and asks for `play`; without
`-s` (or with `-n`) they skip. `tests/test_hw_run.py` is the stage-2 run
as one test: one plan, one `play`, then unattended, failing if any row
fails (`info` rows don't).

## Safety model

- **The user starts every hardware run,** in their own terminal, and types
  `play` after reading the plan. Claude never runs `probe` or `--hw` tests
  against real ports and never types the confirmation. Without a terminal
  (no stdin), nothing is sent.
- **Plan first:** `probe` prints every message (hex bytes, meaning, time in
  its take) before asking; the only extra a run can send is the note-off
  for a note it is holding when interrupted (Ctrl-C, an error). Stage 2's
  session plan lists message types and channels rather than every byte, and
  its cleanup is note-offs, bend centre and pressure 0 on the channels it
  used.
- **Channel voice messages only:** the port wrapper (`midi.check_message`)
  refuses anything but note off/on, poly and channel pressure, CC (RPN 0,
  RPN 6/MCM and CC 74 are CCs), program change and pitch bend, and
  malformed messages. No SysEx, no system messages. So the rig can't reach
  the updater, the bootloader or the patch memory.
- **No bootloader port:** a port whose name contains "Bootloader" is
  refused.
- **Never flashes, never writes patches or Settings.** `setup` changes the
  edit buffer only and never sends a save; reselecting the slot restores
  it. `setup` prints its plan (base slot, the count, every recipe value
  with its bytes; all 800 messages in a file next to the run) before
  asking for `play`. MCM changes the zone live
  (the Settings page shows `*`) and is not saved; at the end of a run that
  sent MCM, the rig sends the MCM for the zone in `work/hwrig.toml` so the
  synth is left as configured.
- **Rates:** on DIN the rig stays below the line rate except in the test
  that is about overrunning it.
- **Volume:** see Setup: monitors down, input gain for −12 dBFS.
- The firmware rules in [CLAUDE.md](../CLAUDE.md) apply: only a build
  prepared by `scripts/build-image.sh` (checked, verified, hashed) is
  flashed, by the user, with `tools/flash.py`
  ([hardware.md](hardware.md)).

## What the first runs showed (2026-11-07, observed)

- **Pitch:** every note read +0.13 c on both paths, one constant ratio
  (76 ppm): the clock difference between the Summit's DAC and the
  interface's ADC, not the Summit's tuning. Checks compare notes against
  each other or a baseline from the same take, so it cancels out.
- **Latency:** about 3–4 ms over USB; DIN adds about 1.2 ms (a 3-byte
  message takes 0.96 ms on the wire).
- **A released voice leaks its pitch:** 0.5–1 s after the note-off the
  note's frequency is still there at −63 to −74 dB re the note, while the
  RMS stays at the noise floor. Presumably the VCA doesn't close fully
  (inferred). The probe reports it as `leak dB`; the stuck-note check only
  counts partials within 40 dB of the note.
- **The FPGA plays the full ±48 per-note range:** stage 2 measured every
  step within 0.02 c from −4800 c to +4800 c (oscillator pitch offsets of
  ±16,384, 4,096 per octave), monotonic, no clamp or wrap. The patch's clamp
  at ±43,690 isn't reached.
- **The analysis is precise:** results match the expected values to
  hundredths of a cent, so the tolerances (±1 c bent, ±0.5 c unbent) have a
  wide margin.
- **Pressure and Slide reach the same scale:** through the matrix at depth
  +16 they gave +197 c and +200 c, so `0x61` (pressure) and the per-voice
  `0x60` (Slide) both reach full scale at 127.

## Status and open items

Stages 1–4 are built and pass on the synth: interfaces and probe, test
sounds over MIDI (`hwrig setup`), the core checks (`hwrig run`), the bugs
and modes (`--stage 3`) and voice rotation (`--stage 4`). Open:

- latency calibration with a loopback cable;
- a dense stream replayed from a capture (`tools/mmon.py` logs), and
  replaying failing takes in the simulator;
- test patches sent as SysEx dumps, the identity request in the report,
  recording the Summit's MIDI out, a scheduled overnight run.
