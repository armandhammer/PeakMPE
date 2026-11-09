"""tools/hwrig/analysis.py on synthesized signals: no hardware."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from hwrig import analysis as an  # noqa: E402

SR = 48000


def tone(hz, dur=0.5, amp=0.3, phase=0.7, sr=SR, start=0.0, total=None):
    n = int((total or dur) * sr)
    t = np.arange(n) / sr
    x = amp * np.sin(2 * np.pi * hz * t + phase)
    if start or total:
        x[(t < start) | (t >= start + dur)] = 0.0
    return x


def noise(n, rms_db, seed=0):
    return np.random.default_rng(seed).normal(0.0, 10 ** (rms_db / 20), n)


def test_note_helpers():
    assert an.note_hz(69) == 440.0
    assert an.note_hz(57) == pytest.approx(220.0)
    assert an.note_name(57) == "A3" and an.note_name(60) == "C4" and an.note_name(61) == "C#4"
    assert an.cents(an.note_hz(70), an.note_hz(69)) == pytest.approx(100.0)


@pytest.mark.parametrize("note", [21, 33, 45, 57, 64, 69, 81, 93, 105])
@pytest.mark.parametrize("detune", [0.0, -37.3, 12.5])
def test_single_tone_within_one_cent(note, detune):
    hz = an.note_hz(note) * 2 ** (detune / 1200)
    x = tone(hz, phase=note * 0.1) + noise(int(0.5 * SR), -70, seed=note)
    p = an.fundamental(x, SR)
    assert abs(an.cents(p.hz, an.note_hz(note)) - detune) < 1.0
    assert abs(p.db - an.db(0.3)) < 0.5


def test_single_tone_short_window_and_44k1():
    # 100 ms is enough on A3 (22 periods), at either rate.
    for sr in (44100, 48000, 96000):
        x = tone(220.0, dur=0.1, sr=sr) + noise(int(0.1 * sr), -60)
        assert abs(an.cents(an.fundamental(x, sr).hz, 220.0)) < 1.0


def test_fundamental_with_harmonics_picks_the_root():
    hz = 110.0
    x = tone(hz, amp=0.1) + tone(2 * hz, amp=0.3) + tone(3 * hz, amp=0.2)
    assert abs(an.cents(an.fundamental(x, SR).hz, hz)) < 1.0


def test_no_tone_in_noise():
    assert an.fundamental(noise(SR // 2, -60), SR) is None


@pytest.mark.parametrize("notes", [[57, 60, 64, 67], [48, 55, 64, 71, 76], [60, 61], list(range(52, 68))])
def test_chord_voice_count_and_pitches(notes):
    x = sum(tone(an.note_hz(n), amp=0.05, phase=n) for n in notes) + noise(SR // 2, -80)
    assert an.count_voices(x, SR) == len(notes)
    got = an.match_voices(an.peaks(x, SR, rel_db=-30), [an.note_hz(n) for n in notes])
    assert all(p is not None for p in got)
    assert max(abs(p.cents_from(an.note_hz(n))) for p, n in zip(got, notes)) < 1.0


def test_chord_with_one_voice_missing():
    notes = [57, 60, 64, 67]
    x = sum(tone(an.note_hz(n), amp=0.05, phase=n) for n in notes if n != 64) + noise(SR // 2, -80)
    assert an.count_voices(x, SR) == 3
    got = an.match_voices(an.peaks(x, SR, rel_db=-30), [an.note_hz(n) for n in notes])
    assert [p is not None for p in got] == [True, True, False, True]


def test_bend_on_one_note_of_a_chord():
    # Per-note bend check: one voice of a held chord bent +150 c, the others unchanged.
    notes = [57, 60, 64]
    bent = an.note_hz(60) * 2 ** (150 / 1200)
    x = tone(an.note_hz(57), amp=0.1) + tone(bent, amp=0.1) + tone(an.note_hz(64), amp=0.1)
    found = an.peaks(x, SR, rel_db=-30)
    got = an.match_voices(found, [an.note_hz(57), bent, an.note_hz(64)], tol_cents=10)
    assert abs(got[1].cents_from(an.note_hz(60)) - 150) < 1.0
    assert abs(got[0].cents_from(an.note_hz(57))) < 1.0 and abs(got[2].cents_from(an.note_hz(64))) < 1.0


def test_level_difference_between_voices():
    # Pressure-to-level check: one voice 6 dB louder than its neighbours.
    x = tone(220.0, amp=0.1) + tone(330.0, amp=0.2) + tone(440.0, amp=0.1)
    lv = {round(p.hz): p.db for p in an.peaks(x, SR)}
    assert lv[330] - lv[220] == pytest.approx(6.02, abs=0.1)
    assert lv[440] - lv[220] == pytest.approx(0.0, abs=0.1)


@pytest.mark.parametrize("start_ms", [3.0, 7.25, 123.4])
@pytest.mark.parametrize("hz", [55.0, 220.0, 1760.0])
def test_onset_latency(start_ms, hz):
    total = 0.4
    x = tone(hz, dur=0.2, start=start_ms / 1000, total=total, phase=0.0)
    ramp = int(0.001 * SR)  # 1 ms attack, like the fast test-patch envelope
    i0 = int(start_ms / 1000 * SR)
    x[i0:i0 + ramp] *= np.linspace(0, 1, ramp)
    x += noise(x.size, -75)
    x[: int(0.002 * SR)] = noise(int(0.002 * SR), -75, seed=9)
    o = an.onset(x, SR, noise_db=-75)
    assert abs(o / SR * 1000 - start_ms) < 1.0


def test_onset_ignores_a_single_click():
    x = noise(int(0.3 * SR), -80)
    x[1000] = 0.5  # one-sample click, e.g. a USB glitch
    x += tone(440.0, dur=0.1, start=0.15, total=0.3)
    assert abs(an.onset(x, SR, noise_db=-80) / SR - 0.15) < 0.001


def test_onset_none_without_a_note():
    assert an.onset(noise(SR // 4, -70), SR) is None


def test_silence_with_hum_in_reference_and_tail():
    n = SR // 2
    hum = tone(50.0, amp=0.003, dur=0.5) + tone(150.0, amp=0.001, dur=0.5)
    ref = hum + noise(n, -70, seed=1)
    tail = hum + noise(n, -70, seed=2)
    s = an.silence(tail, ref, SR)
    assert s.silent and not s.tones


def test_stuck_note_far_below_noise_rms_is_found():
    # A stuck voice 5 dB *below* the broadband noise RMS: the total RMS rises
    # only about 1.2 dB, inside the RMS margin; the spectral check finds it.
    n = SR // 2
    ref = noise(n, -70, seed=1)
    tail = noise(n, -70, seed=2) + tone(220.0, amp=10 ** (-75 / 20) * np.sqrt(2), dur=0.5)
    s = an.silence(tail, ref, SR)
    assert not s.silent
    assert abs(s.rms_db - s.floor_db) < 1.5
    assert abs(an.cents(s.tones[0].hz, 220.0)) < 5


def test_loud_tail_is_not_silent():
    n = SR // 2
    s = an.silence(tone(440.0, amp=0.1) + noise(n, -70), noise(n, -70, seed=3), SR)
    assert not s.silent and s.rms_db > s.floor_db + 40


def test_rms_and_peak_db():
    assert an.rms_db(tone(1000.0, amp=1.0)) == pytest.approx(-3.01, abs=0.01)
    assert an.peak_db(tone(1000.0, amp=0.5)) == pytest.approx(-6.02, abs=0.01)
    assert an.rms_db(np.zeros(0)) == -240.0
