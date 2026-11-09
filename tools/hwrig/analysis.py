"""Audio analysis for the hardware test rig: pitch, peaks, onset, silence.

Pure numpy, no audio I/O, so all of it is unit-tested on synthesized signals
(tests/test_hwrig_analysis.py). Signals are 1-D float arrays in full-scale
units (±1.0 = 0 dBFS); levels are dBFS.

The Summit's oscillators are digital NCOs, so a test patch with one sine
oscillator gives a clean partial whose frequency is exact to well under a
cent. The detectors lean on that:

- `peaks`: spectral peaks with a 4-term Blackman-Harris window (side lobes
  at -92 dB, so a quiet voice next to a loud one isn't hidden), parabolic
  interpolation on the log magnitude, then a golden-section search for the
  maximum of the windowed DTFT around each peak. That last step makes the
  estimate exact to a few hundredths of a cent on a clean tone.
- `fundamental`: the strongest peak, moved down to f/k when the spectrum has
  a strong partial there too (in case a patch isn't a pure sine).
- `onset`: the first sample above a threshold that stays above it, for the
  MIDI-to-audio latency.
- `tone_above_reference`: is there a partial in a segment that the reference
  (pre-roll) segment didn't have? Catches a stuck note far below the RMS
  noise floor while ignoring mains hum, which is in both.
"""
from dataclasses import dataclass

import numpy as np

A4_HZ = 440.0
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


# ------------------------------------------------------------------ units

def note_hz(note, a4=A4_HZ):
    """Equal-tempered frequency of MIDI note number `note` (69 = A4)."""
    return a4 * 2.0 ** ((note - 69) / 12.0)


def note_name(note):
    """'A3' for 57 (middle C = 60 = C4, as in Live and the Summit's display)."""
    return f"{NOTE_NAMES[note % 12]}{note // 12 - 1}"


def cents(f, ref):
    return 1200.0 * np.log2(f / ref)


def db(x, floor=1e-12):
    return 20.0 * np.log10(np.maximum(np.abs(x), floor))


def rms_db(x):
    x = np.asarray(x, dtype=np.float64)
    if x.size == 0:
        return -240.0
    return float(db(np.sqrt(np.mean(x * x))))


def peak_db(x):
    x = np.asarray(x, dtype=np.float64)
    return float(db(np.max(np.abs(x)))) if x.size else -240.0


# --------------------------------------------------------------- spectrum

def blackman_harris(n):
    a = (0.35875, 0.48829, 0.14128, 0.01168)
    k = np.arange(n) * (2.0 * np.pi / (n - 1))
    return a[0] - a[1] * np.cos(k) + a[2] * np.cos(2 * k) - a[3] * np.cos(3 * k)


@dataclass
class Peak:
    hz: float
    db: float  # amplitude of the partial in dBFS (a full-scale sine is 0 dB)

    def cents_from(self, ref_hz):
        return float(cents(self.hz, ref_hz))


class Spectrum:
    """Windowed spectrum of one segment, with DTFT refinement."""

    def __init__(self, x, sr, pad=4):
        x = np.asarray(x, dtype=np.float64)
        if x.size < 64:
            raise ValueError("segment too short for a spectrum")
        x = x - np.mean(x)
        self.sr = sr
        self.n = x.size
        self.w = blackman_harris(self.n)
        self.xw = x * self.w
        self.gain = np.sum(self.w) / 2.0  # |DTFT| of a unit sine at its frequency
        self.nfft = 1 << int(np.ceil(np.log2(self.n * pad)))
        self.mag = np.abs(np.fft.rfft(self.xw, self.nfft)) / self.gain
        self.hz_per_bin = sr / self.nfft
        self._t = np.arange(self.n) / sr

    def dtft(self, hz):
        """Amplitude of the windowed signal at `hz` (a unit sine reads 1.0)."""
        return abs(np.dot(self.xw, np.exp(-2j * np.pi * hz * self._t))) / self.gain

    def refine(self, hz, span):
        """Golden-section search for the DTFT maximum in hz ± span."""
        g = (np.sqrt(5.0) - 1.0) / 2.0
        lo, hi = hz - span, hz + span
        a, b = hi - g * (hi - lo), lo + g * (hi - lo)
        fa, fb = self.dtft(a), self.dtft(b)
        while hi - lo > 1e-5 * max(hz, 1.0) * 1e-2:  # well under 0.001 cent
            if fa < fb:
                lo, a, fa = a, b, fb
                b = lo + g * (hi - lo)
                fb = self.dtft(b)
            else:
                hi, b, fb = b, a, fa
                a = hi - g * (hi - lo)
                fa = self.dtft(a)
        f = (lo + hi) / 2.0
        return f, self.dtft(f)

    def floor_db(self, fmin=20.0, fmax=None):
        """Median spectral level per bin between fmin and fmax (dB re a sine)."""
        lo, hi = self._bins(fmin, fmax)
        return float(np.median(db(self.mag[lo:hi])))

    def _bins(self, fmin, fmax):
        fmax = self.sr / 2.0 if fmax is None else fmax
        lo = max(1, int(fmin / self.hz_per_bin))
        hi = min(self.mag.size - 1, int(np.ceil(fmax / self.hz_per_bin)) + 1)
        return lo, hi

    def peaks(self, fmin=20.0, fmax=None, min_db=-90.0, rel_db=-60.0,
              prominence_db=20.0, min_sep_cents=40.0, refine=True):
        """Spectral peaks, strongest first.

        A peak is kept if it is above `min_db`, within `rel_db` of the
        strongest peak, and `prominence_db` above the median floor. Peaks
        closer than `min_sep_cents` merge into the stronger one.
        """
        lo, hi = self._bins(fmin, fmax)
        m = db(self.mag)
        floor = float(np.median(m[lo:hi]))
        seg = m[lo:hi]
        idx = np.where((seg[1:-1] > seg[:-2]) & (seg[1:-1] >= seg[2:]))[0] + 1 + lo
        idx = idx[m[idx] > max(min_db, floor + prominence_db)]
        if idx.size == 0:
            return []
        top = m[idx].max()
        idx = idx[m[idx] >= top + rel_db]
        idx = idx[np.argsort(-m[idx])]
        found = []
        for i in idx:
            a, b, c = m[i - 1], m[i], m[i + 1]
            den = a - 2 * b + c
            off = 0.5 * (a - c) / den if den != 0 else 0.0
            hz = (i + off) * self.hz_per_bin
            if refine:
                hz, amp = self.refine(hz, 0.75 * self.hz_per_bin)
                level = float(db(amp))
            else:
                level = float(b - 0.25 * (a - c) * off)
            if hz <= 0:
                continue
            if any(abs(cents(hz, p.hz)) < min_sep_cents for p in found):
                continue
            found.append(Peak(float(hz), level))
        found.sort(key=lambda p: -p.db)
        return found


# ------------------------------------------------------------- detectors

def peaks(x, sr, **kw):
    return Spectrum(x, sr).peaks(**kw)


def fundamental(x, sr, fmin=20.0, fmax=8000.0, sub_rel_db=-30.0):
    """The fundamental of one tone, as a Peak, or None if there is no tone."""
    spec = Spectrum(x, sr)
    found = spec.peaks(fmin=fmin, fmax=fmax, rel_db=-60.0)
    if not found:
        return None
    best = found[0]
    for k in (5, 4, 3, 2):  # lowest sub-harmonic first
        sub = best.hz / k
        if sub < fmin:
            continue
        for p in found:
            if abs(cents(p.hz, sub)) < 25 and p.db >= best.db + sub_rel_db:
                return p
    return best


def match_voices(found, expected_hz, tol_cents=50.0):
    """For each expected frequency, the nearest found Peak within tolerance
    (or None). Returns a list in the order of `expected_hz`."""
    out = []
    for f in expected_hz:
        near = [p for p in found if abs(cents(p.hz, f)) <= tol_cents]
        out.append(min(near, key=lambda p: abs(cents(p.hz, f))) if near else None)
    return out


def count_voices(x, sr, fmin=20.0, fmax=8000.0, rel_db=-30.0, min_sep_cents=40.0):
    """Number of distinct partials within `rel_db` of the loudest: the
    sounding voice count of a chord played with a pure-sine test patch."""
    return len(peaks(x, sr, fmin=fmin, fmax=fmax, rel_db=rel_db,
                     min_sep_cents=min_sep_cents))


def onset(x, sr, threshold_db=None, noise_db=None, above_noise_db=20.0,
          hold_s=0.005):
    """Index of the first sample of a note: the first sample whose |x| is
    above the threshold while the median |x| of the next `hold_s` stays
    above half of it (so a click doesn't count; a sine's median |x| is 0.7
    of its peak). The threshold is `threshold_db`
    (dBFS) or, by default, `noise_db + above_noise_db`, where noise_db is
    the RMS of the first 50 ms when not given. None if nothing crosses."""
    x = np.asarray(x, dtype=np.float64)
    if threshold_db is None:
        if noise_db is None:
            noise_db = rms_db(x[: max(1, int(0.05 * sr))])
        threshold_db = noise_db + above_noise_db
    thr = 10.0 ** (threshold_db / 20.0)
    hold = max(1, int(hold_s * sr))
    cand = np.flatnonzero(np.abs(x) > thr)
    ax = np.abs(x)
    for i in cand[:20000]:
        if i + hold > x.size:
            break
        if np.median(ax[i:i + hold]) > thr / 2.0:
            return int(i)
    return None


def tone_above_reference(x, ref, sr, margin_db=12.0, fmin=20.0, fmax=8000.0, min_db=-200.0):
    """Partials in `x` that `ref` doesn't have, as Peaks (empty = silent).

    `ref` is a stretch of the same input with nothing playing (the pre-roll),
    so hum and interface noise are in both and cancel out. A partial counts
    if it is `margin_db` above `ref`'s level at that frequency and above
    `ref`'s median spectral floor by the same margin, and at least `min_db`."""
    n = min(len(x), len(ref))
    sx, sr_ = Spectrum(x[:n], sr), Spectrum(ref[:n], sr)
    floor = sr_.floor_db(fmin, fmax)
    out = []
    for p in sx.peaks(fmin=fmin, fmax=fmax, min_db=min_db, rel_db=-200.0, prominence_db=margin_db):
        ref_level = float(db(sr_.dtft(p.hz)))
        if p.db >= max(ref_level, floor) + margin_db:
            out.append(p)
    return out


@dataclass
class SilenceResult:
    silent: bool
    rms_db: float
    floor_db: float
    tones: list


def silence(x, ref, sr, margin_db=12.0, rms_margin_db=6.0, min_db=-200.0):
    """Is `x` as quiet as the reference `ref`? Both its RMS (within
    `rms_margin_db`) and its spectrum (no new partial of at least `min_db`,
    see tone_above_reference).

    On the Summit a released voice keeps leaking its pitch at about -66 dB
    re the note (observed, 2026-11-07, docs/hw-test-rig.md), so callers that
    know the note's level pass `min_db` = that level - 40 dB: a stuck note
    sounds near full level, the leak doesn't count."""
    level, floor = rms_db(x), rms_db(ref)
    tones = tone_above_reference(x, ref, sr, margin_db=margin_db, min_db=min_db)
    return SilenceResult(level <= floor + rms_margin_db and not tones, level, floor, tones)
