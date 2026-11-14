# Peak units: envelope times and filter cutoff, measured

Step 6 of [peak-features.md](peak-features.md). The FPGA applies the curves;
the firmware only sends 0–255 (here 0–127 over MIDI), so the value → ms and
value → Hz tables for the on-screen units and for tempo-synced envelopes have to
be measured. Done 2026-11-13 on the user's Peak (firmware 2.2 build 2108 with
the MPE v0.2 patch, image `a7015456…`; the patch doesn't touch envelopes or the
filter, inferred), with the [test rig](hw-test-rig.md).

Labels: **observed** = measured on the synth in these runs; **inferred** =
derived from observed numbers by an assumption stated next to it; **emulated**
= not used here (nothing in this step runs in the simulator).

Script: [`work/measure_units.py`](../work/measure_units.py) (git-ignored, like
all of `work/`; plans `env`, `filter-explore`, `filter`, `midnote`, `zipper`,
`hold`, and an offline `selftest` of the analysis on synthetic signals) and
`work/make_unit_tables.py` (turns the saved JSON into the tables below). Raw
results, envelopes and the WAVs of the mid-note and zipper takes are in
`work/hw-runs/units-2026-11-13_*` on the user's machine.

## Method

**Sound and signal path.** Edit buffer only, nothing saved. The rig's `p5`
recipe (sine, MPE off, filter open, no FX or LFO, amp velocity 0) built on D003
with the Init value of every settable parameter, then the plan's own values on
top. MIDI channel 1, over USB. The Peak's L and R go to Scarlett inputs 1 and 2
at 48 kHz; the level used is the mean of the two (power), RMS over an 8 ms
window with a 1 ms hop. The note is A5 (880 Hz) so a short window is smooth.
Rig noise floor about −78 dBFS, so a fall can be followed about 45–50 dB below
a note at about −18 dBFS.

**Amp envelope, one take per setting** (`env`, 0–127 in steps of 4 and 127,
then midpoints wherever neighbouring times differ by more than 1.35× and the
time is above 30 ms; two rounds, 3 extra points for attack, none for decay, 4 for release here):

| Stage | Settings of the others | Measured |
|---|---|---|
| Attack | decay 0, sustain 127, release 0 | linear amplitude relative to the level held before the note-off: **t10, t50, t90, t99** = time after note-on to reach 10/50/90/99 % |
| Decay | attack 0, sustain 0, release 0 | **t6, t20, t40** = time after note-on for the level to fall 6/20/40 dB below its peak (first 0.3 s) and stay below for 30 ms |
| Release | attack 0, decay 0, sustain 127, note held 1 s | **t6, t20, t40** = time after note-off to fall 6/20/40 dB below the held level |

Take lengths grow with the setting (the previous result sets the next guess;
a threshold that wasn't reached gets one longer retry). Sustain is 0 for decay,
so the fall is measured from the peak all the way down and not to a sustain
level; whether a non-zero sustain changes the decay *rate* was not tested
(it is exponential in dB, below, so the rate is a property of the setting).

**Time offset.** The recorded audio is shifted by `input_delay_ms = 120`
(work/hwrig.toml). Attack 0 shows the 50 % point at −0.018 s from the MIDI
send, so the audio is 18 ms earlier than the shift assumes: the true
send-to-sound latency is about 102 ms **plus** the few ms the rig does not
resolve, not 120 ms (inferred; the latency is not otherwise measured). This
offset is subtracted from the attack times; decay and release are given as
measured (the offset is below 2 % of every value above 0.9 s and in the noise of
the 8 ms window below that; the release at 100 matches the decay at 100 to
0.1 %).

**Filter cutoff** (`filter-explore`, `filter`): low-pass, 24 dB slope
(`FiltSlope` 1), key track 0, no envelope or LFO routing, note 60, patch
oscillators off.

- *Self-oscillation:* resonance 127, a 0.25 s noise kick (noise level 20, then
  0) to start it, strongest partial over 0.9 s of the held note (a spectrum
  with a Blackman-Harris window and a refined peak, as the rig's pitch
  analysis).
- *Noise:* noise level 127, oscillators off; PSD of the filtered noise divided
  by the PSD with the filter wide open (cutoff 127, resonance 0), 1/3-octave
  smoothed. Two readings: the **−3 dB point** at resonance 0 and the **peak of
  the resonance bump** at resonance 90.
- *Key track meaning* (`filter-explore`, resonance 127, cutoff 64): note 45 and
  note 81, 36 semitones apart, at key track 0, 64, 127.

Not measured: cutoff fine byte (CC 61), other slopes or shapes, other
resonances than 0, 90 and 127, drive, Osc 3 / modulation amounts.

## Results

### Amp envelope

All three curves are smooth and monotonic in the setting. Attack (observed): a
**linear amplitude ramp** (t10 : t50 : t90 = 0.10 : 0.49 : 0.90 of the total at
every setting from 80 up, within 0.01; at 127, t50 is 8.84 s of a full ramp of
(t90 − t10)/0.8 = 17.9 s). Decay and release (observed) are **linear in dB**,
that is exponential in amplitude: t40/t20 is 1.97–2.01 (decay from 36 up; release from 64 up, 2.05–2.4 below that, where the fall is within a few windows of the noise), so the slope in dB/s is constant over the fall (the table gives it). Decay
and release are **the same curve**: from setting 60 up the two t20 agree
within 1 % (within 20 % below, where the offset matters). Time is roughly exponential in the
setting (about ×2 per 11–12 steps), but a single exponential misses by 10–17 %,
so the display and any tempo table should use the measured table, not a fit:

| Fit over settings ≥ 40 (≥ 48 for attack) | max error |
|---|---|
| attack full ramp ≈ 0.0132 s · e^(0.0573 v) | 9 % |
| decay t20 ≈ 0.00732 s · e^(0.0578 v) | 10 % |
| release t20 ≈ 0.00604 s · e^(0.0596 v) | 17 % |

(observed values, inferred fits.)

**Resolution limits (observed):** decay and release below about 12 and attack
below about 24 are shorter than the measuring chain resolves (window 8 ms): the
release is 0 within the window up to 8, and the decay t40 below 28 is not
monotonic (that column is below the window's resolution, not real). Treat
those settings as "under 10 ms" for display.

### Tables

Values are the setting sent as CC (0–127); times in seconds.

Offset subtracted from attack times: -0.018 s (attack 0, t50).

#### Attack (observed)

| Value | t10 s | t50 s | t90 s | t99 s | full ramp s (t90−t10)/0.8 |
|--:|--:|--:|--:|--:|--:|
| 0 | -0.002 | 0.000 | 0.005 | 0.006 | 0.009 |
| 4 | 0.006 | 0.009 | 0.013 | 0.016 | 0.009 |
| 8 | 0.009 | 0.013 | 0.018 | 0.021 | 0.011 |
| 12 | 0.008 | 0.014 | 0.020 | 0.024 | 0.015 |
| 16 | 0.009 | 0.016 | 0.024 | 0.028 | 0.019 |
| 20 | 0.002 | 0.013 | 0.023 | 0.028 | 0.026 |
| 24 | 0.013 | 0.027 | 0.041 | 0.047 | 0.035 |
| 28 | 0.005 | 0.023 | 0.042 | 0.049 | 0.046 |
| 29 | 0.014 | 0.034 | 0.055 | 0.062 | 0.051 |
| 30 | 0.014 | 0.036 | 0.058 | 0.064 | 0.055 |
| 32 | 0.016 | 0.040 | 0.067 | 0.073 | 0.064 |
| 36 | 0.012 | 0.045 | 0.080 | 0.089 | 0.085 |
| 38 | 0.018 | 0.056 | 0.096 | 0.106 | 0.097 |
| 40 | 0.021 | 0.065 | 0.110 | 0.121 | 0.111 |
| 44 | 0.024 | 0.082 | 0.142 | 0.156 | 0.147 |
| 48 | 0.020 | 0.096 | 0.172 | 0.191 | 0.190 |
| 52 | 0.025 | 0.122 | 0.222 | 0.245 | 0.246 |
| 56 | 0.040 | 0.165 | 0.293 | 0.324 | 0.316 |
| 60 | 0.049 | 0.208 | 0.374 | 0.411 | 0.406 |
| 64 | 0.062 | 0.267 | 0.477 | 0.526 | 0.519 |
| 68 | 0.063 | 0.325 | 0.592 | 0.654 | 0.661 |
| 72 | 0.092 | 0.425 | 0.767 | 0.846 | 0.844 |
| 76 | 0.104 | 0.525 | 0.955 | 1.055 | 1.064 |
| 80 | 0.141 | 0.675 | 1.228 | 1.353 | 1.359 |
| 84 | 0.174 | 0.840 | 1.527 | 1.682 | 1.691 |
| 88 | 0.215 | 1.055 | 1.922 | 2.122 | 2.134 |
| 92 | 0.264 | 1.338 | 2.438 | 2.689 | 2.717 |
| 96 | 0.332 | 1.645 | 2.987 | 3.295 | 3.319 |
| 100 | 0.415 | 2.096 | 3.825 | 4.221 | 4.263 |
| 104 | 0.509 | 2.592 | 4.726 | 5.214 | 5.271 |
| 108 | 0.623 | 3.149 | 5.741 | 6.333 | 6.397 |
| 112 | 0.800 | 4.018 | 7.323 | 8.082 | 8.154 |
| 116 | 0.979 | 4.909 | 8.944 | 9.865 | 9.956 |
| 120 | 1.250 | 6.293 | 11.495 | 12.683 | 12.806 |
| 124 | 1.451 | 7.341 | 13.398 | 14.786 | 14.934 |
| 127 | 1.760 | 8.842 | 16.095 | 17.767 | 17.919 |

#### Decay (observed)

| Value | t6 s | t20 s | t40 s | slope dB/s (20/t20) |
|--:|--:|--:|--:|--:|
| 0 | 0.009 | 0.066 | — | 303.0 |
| 4 | 0.023 | 0.087 | — | 229.9 |
| 8 | 0.004 | 0.039 | — | 512.8 |
| 12 | 0.004 | 0.011 | 0.097 | 1818.2 |
| 16 | 0.005 | 0.014 | 0.058 | 1428.6 |
| 20 | 0.006 | 0.017 | 0.035 | 1176.5 |
| 24 | 0.008 | 0.023 | 0.093 | 869.6 |
| 28 | 0.010 | 0.029 | 0.061 | 689.7 |
| 32 | 0.013 | 0.039 | 0.078 | 512.8 |
| 36 | 0.017 | 0.051 | 0.101 | 392.2 |
| 40 | 0.021 | 0.067 | 0.133 | 298.5 |
| 44 | 0.027 | 0.087 | 0.172 | 229.9 |
| 48 | 0.035 | 0.112 | 0.222 | 178.6 |
| 52 | 0.045 | 0.145 | 0.292 | 137.9 |
| 56 | 0.057 | 0.186 | 0.370 | 107.5 |
| 60 | 0.073 | 0.238 | 0.470 | 84.0 |
| 64 | 0.093 | 0.304 | 0.601 | 65.8 |
| 68 | 0.118 | 0.386 | 0.761 | 51.8 |
| 72 | 0.151 | 0.493 | 0.969 | 40.6 |
| 76 | 0.189 | 0.619 | 1.223 | 32.3 |
| 80 | 0.242 | 0.789 | 1.559 | 25.3 |
| 84 | 0.298 | 0.981 | 1.940 | 20.4 |
| 88 | 0.380 | 1.242 | 2.457 | 16.1 |
| 92 | 0.479 | 1.579 | 3.122 | 12.7 |
| 96 | 0.589 | 1.927 | 3.819 | 10.4 |
| 100 | 0.751 | 2.480 | 4.906 | 8.1 |
| 104 | 0.929 | 3.063 | 6.056 | 6.5 |
| 108 | 1.129 | 3.722 | 7.361 | 5.4 |
| 112 | 1.436 | 4.729 | 9.352 | 4.2 |
| 116 | 1.756 | 5.787 | 11.444 | 3.5 |
| 120 | 2.259 | 7.432 | 14.715 | 2.7 |
| 124 | 2.628 | 8.668 | 17.159 | 2.3 |
| 127 | 3.172 | 10.430 | 20.626 | 1.9 |

#### Release (observed)

| Value | t6 s | t20 s | t40 s | slope dB/s (20/t20) |
|--:|--:|--:|--:|--:|
| 0 | 0.000 | 0.000 | 0.000 | — |
| 4 | 0.000 | 0.000 | 0.000 | — |
| 8 | 0.000 | 0.000 | 0.005 | — |
| 12 | 0.000 | 0.001 | 0.010 | 20000.0 |
| 16 | 0.000 | 0.003 | 0.014 | 6666.7 |
| 20 | 0.000 | 0.006 | 0.022 | 3333.3 |
| 24 | 0.000 | 0.012 | 0.033 | 1666.7 |
| 28 | 0.000 | 0.020 | 0.048 | 1000.0 |
| 32 | 0.001 | 0.027 | 0.065 | 740.7 |
| 34 | 0.005 | 0.035 | 0.078 | 571.4 |
| 36 | 0.006 | 0.040 | 0.092 | 500.0 |
| 38 | 0.002 | 0.041 | 0.099 | 487.8 |
| 39 | 0.005 | 0.047 | 0.107 | 425.5 |
| 40 | 0.011 | 0.056 | 0.121 | 357.1 |
| 42 | 0.013 | 0.065 | 0.138 | 307.7 |
| 44 | 0.022 | 0.082 | 0.165 | 243.9 |
| 48 | 0.023 | 0.100 | 0.208 | 200.0 |
| 52 | 0.029 | 0.129 | 0.270 | 155.0 |
| 56 | 0.041 | 0.169 | 0.348 | 118.3 |
| 60 | 0.056 | 0.220 | 0.451 | 90.9 |
| 64 | 0.082 | 0.293 | 0.593 | 68.3 |
| 68 | 0.109 | 0.378 | 0.753 | 52.9 |
| 72 | 0.141 | 0.482 | 0.962 | 41.5 |
| 76 | 0.177 | 0.609 | 1.215 | 32.8 |
| 80 | 0.231 | 0.777 | 1.553 | 25.7 |
| 84 | 0.286 | 0.967 | 1.934 | 20.7 |
| 88 | 0.369 | 1.231 | 2.449 | 16.2 |
| 92 | 0.471 | 1.568 | 3.114 | 12.8 |
| 96 | 0.579 | 1.925 | 3.805 | 10.4 |
| 100 | 0.745 | 2.478 | 4.905 | 8.1 |
| 104 | 0.923 | 3.057 | 6.050 | 6.5 |
| 108 | 1.122 | 3.707 | 7.337 | 5.4 |
| 112 | 1.429 | 4.722 | 9.357 | 4.2 |
| 116 | 1.751 | 5.786 | 11.434 | 3.5 |
| 120 | 2.250 | 7.431 | 14.693 | 2.7 |
| 124 | 2.629 | 8.682 | 17.165 | 2.3 |
| 127 | 3.160 | 10.396 | 20.600 | 1.9 |


### Filter cutoff (CC 29, fine byte 0)

- **Self-oscillation works** (observed): at resonance 127 the filter rings as a
  clean sine from CC 29 ≈ 12 up (prominence 100–119 dB over the spectrum floor,
  about −8 dBFS, falling to −16.5 dB at the top because the tone approaches
  the 24 kHz Nyquist limit), a usable pitch for a calibrated estimate. At 0, 4
  and 8 the ring is weak (−33 dB) and the frequencies do not follow the trend:
  below about CC 12 (≈ 30 Hz) the table is **not measured**.
- The frequency is exponential in CC 29: ×1.62 per 8 steps near the middle,
  about 0.7 octave per 8 steps, slowing a little at the extremes (observed).
  Top: CC 124 ≈ 20.4 kHz and 127 ≈ 23.7 kHz are at the measurement limit (the
  filter itself may go higher; the recording cannot show it).
- **Key track** (observed): 0 → no tracking (pitch 686 Hz vs 675 Hz for two
  notes 36 semitones apart, 1 % apart); 64 → ×2.79 (about 49 %); 127 → ×7.83
  (about 99 %, 36 semitones = ×8 at 100 %). So 127 is 100 % tracking, 64 is
  about half, and the Init Patch's 127 means the filter follows the keyboard
  fully. The tables are for key track 0; at 127 the frequency scales by
  2^((note − 60)/12) (inferred from the two notes).
- **Cross-check** (observed): the resonance peak of noise at resonance 90 sits
  within 8 % of the self-oscillation frequency from CC 28 to CC 116 (e.g.
  CC 64: 668 vs 672 Hz; CC 100: 5244 vs 5322 Hz). The −3 dB point at resonance 0
  is 0.52–0.67 of that frequency (CC 40–116), as expected for a 24 dB
  low-pass whose −3 dB point sits below its natural frequency (inferred). So
  **the self-oscillation frequency is the filter's fc**, and the figure the
  display should show if it shows one number; "−3 dB point" is lower and
  depends on resonance.

#### Filter table (observed)

| CC 29 | self-osc Hz | level dB | −3 dB Hz, res 0 | noise peak Hz, res 90 |
|--:|--:|--:|--:|--:|
| 0 | 48.9 | -33.3 | 64 | 41 |
| 4 | 62.3 | -33.1 | 64 | 41 |
| 8 | 80.6 | -33.6 | 64 | 41 |
| 12 | 33.4 | -8.1 | 65 | 41 |
| 16 | 42.6 | -8.2 | 65 | 41 |
| 20 | 53.4 | -7.8 | 67 | 53 |
| 24 | 67.3 | -7.9 | 66 | 64 |
| 28 | 83.9 | -8.1 | 73 | 82 |
| 32 | 106.1 | -8.1 | 76 | 106 |
| 36 | 134.0 | -8.1 | 91 | 123 |
| 40 | 172.2 | -8.0 | 113 | 170 |
| 44 | 212.9 | -7.8 | 137 | 205 |
| 48 | 271.7 | -8.0 | 165 | 252 |
| 52 | 338.5 | -7.7 | 207 | 316 |
| 56 | 430.2 | -7.8 | 254 | 422 |
| 60 | 533.7 | -8.1 | 289 | 522 |
| 64 | 672.0 | -8.0 | 424 | 668 |
| 68 | 850.0 | -8.0 | 506 | 809 |
| 72 | 1091.1 | -8.0 | 590 | 1020 |
| 76 | 1349.8 | -7.8 | 823 | 1336 |
| 80 | 1717.5 | -8.0 | 1048 | 1606 |
| 84 | 2141.6 | -7.7 | 1111 | 1986 |
| 88 | 2712.7 | -7.9 | 1687 | 2607 |
| 92 | 3361.9 | -8.2 | 2021 | 3270 |
| 96 | 4224.8 | -8.3 | 2412 | 4125 |
| 100 | 5322.2 | -8.4 | 3400 | 5244 |
| 104 | 6801.3 | -8.6 | 4020 | 6762 |
| 108 | 8412.5 | -8.8 | 4575 | 8408 |
| 112 | 10607.9 | -9.5 | 6268 | 10459 |
| 116 | 13203.0 | -10.0 | 8787 | 13201 |
| 120 | 16575.4 | -11.4 | 10722 | 17039 |
| 124 | 20407.0 | -13.2 | — | 19998 |
| 127 | 23718.2 | -16.5 | — | 19998 |

Status of the filter table: a calibrated estimate for these conditions
(low-pass, 24 dB, key track 0, resonance 127 for the tone, fine byte 0), not an
exact frequency. With resonance 0 the audible "cutoff" is 0.5–0.67 of it.

### Mid-note changes (observed, `midnote`, 2026-11-13)

A held A5 sine; the envelope time is changed with one CC while the note
sounds. Control takes set the old or the new value from the start; the "after"
slope of the changed take is compared with both controls.

| Change | Before the change | After (changed take) | Control, old value | Control, new value | Reading |
|---|---|---|---|---|---|
| **Decay** 110 → 90 at 1.0 s into the fall | −4.56 dB/s | **−14.34 dB/s** | −4.61 | −14.43 | the *sounding* note takes the new rate immediately |
| **Attack** 116 → 100 at 1.0 s into the rise (linear amplitude, fraction of full scale per second) | 0.104/s | **0.2385/s** | 0.108 | 0.237 | the sounding note takes the new rate immediately |
| **Release** 110 → 90 at 1.0 s of hold, note-off at 2.0 s | — | fall after note-off **−14.23 dB/s** | −4.54 | −14.21 | the release uses the value present at the note-off |

So the sound chip reads envelope times **continuously**, not at note-on
(observed for attack and decay; release is read at note-off, consistent with
that). Consequences for [tempo-synced envelopes](peak-features.md): a
recalculated value reaches notes that are already sounding, so the first
version must recalculate only on deliberate tempo changes (as step 11 already
says), and a tempo ramp would audibly bend held envelopes. Not tested: the
"time-to-new-value" for a change at the very start of a stage, or the mod
envelopes (inferred identical because they share the parameter layout).

### Parameter-change smoothness (observed, `zipper`)

- **Level** (Osc 1 level, CC 23): a single jump 30 → 100 (+10.4 dB) rises
  10–90 % in **9 ms**, which is the 3 ms window plus at most a few ms of
  smoothing, so the control path has essentially no slew. A 70-step ramp, one
  CC every 5 ms, moves 0.15 dB per step: below the envelope estimator's own
  ripple (±0.2 dB), so no staircase is visible, and the energy away from the
  tone during the ramp is −49 dB re the tone, no worse than steady (−45 dB;
  that figure is the noise floor). **No zipper noise measured at 1 CC step per
  5 ms.** Not listened to by the user yet, and steps of several dB at once
  were not tested.
- **Cutoff** (CC 29 on noise, 20 → 100): the 3–9 kHz band rises 10–90 %
  in **21 ms** (the analysis frame is 10.7 ms, so about 10 ms of that is the
  measurement) and by +53 dB. So a cutoff jump is smoothed over roughly
  10–20 ms, not instantaneous (inferred: the frame limits the estimate). The 40-step ramp
  (one CC every 10 ms) was recorded (`zipper-cutoff.wav`) but not analysed
  further for steps.

Budget implication for steps 21–22 (motion recording, morph): one CC per
millisecond is not needed; 5–10 ms per update is smooth for level and cutoff
(inferred; envelope times were not tested for stepping).

## Cross-check against the user guide

| Guide reference | Measured (observed unless noted) | Agrees? |
|---|---|---|
| Attack maximum over 18 s | 127: full ramp 17.9 s; t99 17.77 s | within 1 %: the setting reaches 18 s only if "attack time" means the whole ramp (inferred 17.9–18 s) |
| Decay about 22 s | 127: t40 20.6 s, 2.0 × t20 steady, so −44 dB at 22 s (inferred) | consistent if the guide's time is to about −44 dB |
| Release over 24 s | 127: t40 20.6 s, −48 dB (1/256) at 24.8 s (inferred) | consistent if the guide's time is to about −48 dB |
| Hold 127 = 500 ms | 127: **0.68 s** (t6 with hold 127 0.696 s minus hold 0 0.021 s; hold is linear in the setting, 5.3 ms per step, observed) | **does not agree: 35 % longer** |
| Env Delay 85 ≈ 1 s, 127 = 10 s | **not measured**: the Delay byte (patch `0x090/0x091`) is reserved in the parameter table, so MIDI can't set it; it is only a mod destination | open |

Glide and the LFO rate (the guide's other references) were not measured here.
Decay/release "times" in the guide are not defined (to what level?), so those
two rows agree only under the stated assumption; the Hold row is a real
discrepancy (maybe the guide's 500 ms is nominal, or the hold ends at a
different point of the envelope than the level starting to fall: not
investigated).

## Definition of the displayed time

For the OLED, the least confusing single number per stage:

- **Attack:** the full ramp, 0 → 100 % (listed as "full ramp" above).
- **Decay and release:** the time to −40 dB (1 %), a figure the measurement
  covers directly at every setting from 12 up. Other levels scale by dB/s
  (linear in dB: the table's slope column).
- A table in flash would hold one 16-bit entry per setting (128 × 3 × 2 =
  768 bytes), plus a 128-entry filter table.

## Reproducing

```bash
.venv/Scripts/python.exe -I work/measure_units.py selftest
.venv/Scripts/python.exe -I work/measure_units.py env
.venv/Scripts/python.exe -I work/measure_units.py filter
.venv/Scripts/python.exe -I work/measure_units.py midnote --param decay --a 110 --b 90
.venv/Scripts/python.exe -I work/measure_units.py zipper
.venv/Scripts/python.exe -I work/measure_units.py hold
```

Each sends channel voice messages only to the edit buffer and needs the same
synth state as [the rig](hw-test-rig.md#building-the-sounds-over-midi-hwrig-setup).
`--dry-run` validates the messages without sending. The runs took about
8 minutes (`env`), 8 (`filter`) and 1–2 each for the others.

## Open items

- Env Delay (not settable over MIDI) and the mod envelopes; Glide and LFO rate.
- Cutoff below CC 12, the fine byte, other resonances, slopes and shapes.
- Hold: why 0.68 s and not 500 ms.
- Listening check for zipper noise with larger steps (user's ears).
