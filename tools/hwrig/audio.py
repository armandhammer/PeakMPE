"""Audio in for the rig: device listing, timed takes, WAV files.

A take records the chosen inputs while events (MIDI sends) fire at set
offsets. Every send is time-stamped on the audio stream's clock, and the
first sample's ADC time is known, so a send converts to a sample index: that
is what the latency and the pre-roll/hold/tail windows are cut from.
"""
import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np


def input_devices():
    """[(index, name, host API, max input channels, default samplerate)]."""
    import sounddevice as sd
    apis = sd.query_hostapis()
    out = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            out.append((i, d["name"], apis[d["hostapi"]]["name"],
                        d["max_input_channels"], d["default_samplerate"]))
    return out


def default_input():
    import sounddevice as sd
    return sd.default.device[0]


def resolve_device(spec):
    """Device index from '' (default), an index, or a unique name substring."""
    devs = input_devices()
    if spec in ("", None):
        i = default_input()
        if i is None or i < 0 or not any(d[0] == i for d in devs):
            raise LookupError("no default audio input; set audio_device (see `list`)")
        return next(d for d in devs if d[0] == i)
    s = str(spec)
    if s.isdigit():
        for d in devs:
            if d[0] == int(s):
                return d
        raise LookupError(f"no audio input device with index {s}")
    hits = [d for d in devs if s.lower() in d[1].lower()]
    exact = [d for d in hits if d[1] == s]
    if exact:
        return exact[0]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise LookupError(f"no audio input device matches {s!r}; inputs: {[d[1] for d in devs]}")
    raise LookupError(f"several audio inputs match {s!r}: {[d[1] for d in hits]}; use the index")


class SoundDeviceRecorder:
    """Records input channels `inputs` (1-based) of `device` (an index)."""

    def __init__(self, device, inputs, samplerate, frame_clock=None, input_delay_s=0.0):
        self.device, self.inputs, self.sr = device, list(inputs), samplerate
        #: Constant delay of the input path (audio reaches the stream this much
        #: after it was played; ~1.54 s on a Scarlett 6i6 under Windows,
        #: 2026-11-12). Each take records it extra and drops it from the start.
        self.delay = max(0.0, float(input_delay_s))
        #: Time events by the samples received instead of the driver's clocks
        #: (default on Windows, where those disagree).
        self.frame_clock = sys.platform == "win32" if frame_clock is None else frame_clock

    def record(self, duration_s, events):
        """Record `duration_s`, calling each `(at_s, fn)` in `events` at
        `at_s` after the first sample. Returns (audio[n, len(inputs)],
        [seconds after the first sample at which each fn ran])."""
        import sounddevice as sd
        blocks, first = [], {}
        started = threading.Event()
        seen = [0]  # frames received so far

        def callback(indata, frames, t, status):
            seen[0] += frames
            if not first:
                adc = t.inputBufferAdcTime or (t.currentTime - frames / self.sr)
                first["adc"] = adc
                started.set()
            blocks.append(indata.copy())

        nch = max(self.inputs)
        with sd.InputStream(device=self.device, channels=nch, samplerate=self.sr,
                            dtype="float32", callback=callback, latency="low") as stream:
            if not started.wait(5.0):
                raise RuntimeError("audio input did not start within 5 s")
            t0 = first["adc"]
            if self.frame_clock:
                # Windows (MME, WASAPI): the ADC timestamps and stream.time
                # aren't on one clock (2026-11-12: takes 1.5 s late on WASAPI,
                # 13 ms long on MME), so the received samples are the clock.
                def now():
                    return seen[0] / self.sr
                t0 = 0.0
            else:
                def now():
                    return stream.time
            stamps = []
            for at_s, fn in sorted(events, key=lambda e: e[0]):
                while now() < t0 + at_s:
                    time.sleep(min(0.0005, max(0.0, t0 + at_s - now())))
                fn()
                stamps.append(now() - t0)
            while now() < t0 + duration_s + self.delay:
                time.sleep(0.005)
        audio = np.concatenate(blocks) if blocks else np.zeros((0, nch), np.float32)
        skip = int(round(self.delay * self.sr))
        audio = audio[skip: skip + int(round(duration_s * self.sr))]
        cols = [c - 1 for c in self.inputs]
        return np.ascontiguousarray(audio[:, cols]), stamps


def write_wav(path, audio, sr):
    """24-bit PCM WAV of a float array [n] or [n, channels]."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    a = np.asarray(audio, dtype=np.float64)
    if a.ndim == 1:
        a = a[:, None]
    ints = np.ascontiguousarray(np.clip(np.round(a * 8388607.0), -8388608, 8388607).astype("<i4"))
    raw = ints.view(np.uint8).reshape(-1, 4)[:, :3].tobytes()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(a.shape[1])
        w.setsampwidth(3)
        w.setframerate(int(sr))
        w.writeframes(raw)


def read_wav(path):
    """(float array [n, channels], samplerate) of a 16/24/32-bit PCM WAV."""
    with wave.open(str(path), "rb") as w:
        nch, width, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = np.frombuffer(w.readframes(n), dtype=np.uint8)
    if width == 3:
        b = raw.reshape(-1, 3)
        ints = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8)
                | (b[:, 2].astype(np.int32) << 16))
        ints = np.where(ints & 0x800000, ints - 0x1000000, ints)
        a = ints / 8388608.0
    elif width == 2:
        a = raw.view("<i2") / 32768.0
    elif width == 4:
        a = raw.view("<i4") / 2147483648.0
    else:
        raise ValueError(f"{width * 8}-bit WAV not supported")
    return a.reshape(-1, nch), sr
