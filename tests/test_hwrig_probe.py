"""tools/hwrig probe flow, config, WAV and CLI against a fake synth: no hardware.

The fake port and recorder stand in for rtmidi and sounddevice: the
recorder runs the take's events, and renders what a one-sine test patch
would play for the notes the port received, with a set latency, detune,
hum and noise.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from hwrig import analysis as an  # noqa: E402
from hwrig import audio, cli, config, midi, probe  # noqa: E402

SR = 48000


class FakePort:
    def __init__(self, log):
        self.log, self.closed = log, False

    def send(self, data):
        self.log.append(bytes(data))

    def close(self):
        self.closed = True


class FakeSynth:
    """A recorder whose 'audio' is a synth reacting to the FakePort's log."""

    def __init__(self, latency_ms=6.5, detune_cents=0.0, stuck=False, inputs=(1, 2),
                 fail_after_note_on=False, level=0.25, h2_db=None, leak_db=None):
        self.sr, self.inputs = SR, list(inputs)
        self.latency, self.detune, self.stuck = latency_ms / 1000, detune_cents, stuck
        self.fail, self.level, self.h2_db, self.leak_db = fail_after_note_on, level, h2_db, leak_db
        self.log, self.opened = [], 0

    def open_port(self):
        self.opened += 1
        return FakePort(self.log)

    def record(self, duration_s, events):
        stamps, start = [], len(self.log)
        for at_s, fn in events:
            fn()
            stamps.append(at_s + 0.0003)  # the send lands just after its slot
            if self.fail:
                raise KeyboardInterrupt
        n = int(round(duration_s * SR))
        t = np.arange(n) / SR
        rng = np.random.default_rng(len(self.log))
        x = 0.002 * np.sin(2 * np.pi * 50 * t) + rng.normal(0, 3e-5, n)
        on = {}
        for msg, ts in zip(self.log[start:], stamps):
            if msg[0] & 0xF0 == 0x90:
                on[msg[1]] = ts
            elif msg[0] & 0xF0 == 0x80 and msg[1] in on:
                t0, t1 = on.pop(msg[1]) + self.latency, ts + self.latency
                t1 = duration_s if self.stuck else t1
                hz = an.note_hz(msg[1]) * 2 ** (self.detune / 1200)
                env = np.clip((t - t0) / 0.001, 0, 1) * np.clip((t1 + 0.01 - t) / 0.01, 0, 1)
                x += self.level * env * np.sin(2 * np.pi * hz * np.maximum(t - t0, 0))
                if self.leak_db is not None:  # the released voice keeps leaking its pitch
                    after = (t >= t1 + 0.01) * 10 ** (self.leak_db / 20)
                    x += self.level * after * np.sin(2 * np.pi * hz * np.maximum(t - t0, 0))
                if self.h2_db is not None:
                    x += self.level * 10 ** (self.h2_db / 20) * env * np.sin(4 * np.pi * hz * np.maximum(t - t0, 0))
        return np.stack([x] * len(self.inputs), axis=1).astype(np.float32), stamps


def cfg(**kw):
    c = config.Config(notes=[57, 69], hold_s=0.4, preroll_s=0.3, tail_s=0.6)
    for k, v in kw.items():
        setattr(c, k, v)
    return c.validate()


def run(tmp_path, synth, c=None, answer=True):
    said = []
    res = probe.run(c or cfg(), "Summit", synth.open_port, synth, lambda: answer,
                    tmp_path, say=said.append, sleep=lambda s: None)
    return res, "\n".join(said)


def test_nothing_sent_without_confirmation(tmp_path):
    synth = FakeSynth()
    res, out = run(tmp_path, synth, answer=False)
    assert res is None and synth.opened == 0 and synth.log == []
    assert "nothing sent" in out
    assert not any(tmp_path.iterdir())


def test_confirm_requires_the_word_play(monkeypatch):
    for typed, ok in [("play", True), (" play\n", True), ("y", False), ("PLAY", False), ("", False)]:
        monkeypatch.setattr("builtins.input", lambda prompt, t=typed: t)
        assert cli.confirm_play() is ok

    def eof(prompt):
        raise EOFError
    monkeypatch.setattr("builtins.input", eof)
    assert cli.confirm_play() is False


def test_yes_skips_the_prompt_only_when_given(monkeypatch):
    import argparse
    monkeypatch.setattr("builtins.input", lambda prompt: "no")
    assert cli.confirmer(argparse.Namespace(yes=True))() is True
    assert cli.confirmer(argparse.Namespace(yes=False))() is False
    assert cli.confirmer(argparse.Namespace())() is False


def test_plan_lists_exactly_what_is_sent(tmp_path):
    synth = FakeSynth()
    c = cfg(channel=3, slot="D005")
    text = probe.plan_text(c, "Summit")
    assert "channel 3" in text
    for line in ("B2 20 04", "C2 05", "92 39 64", "82 39 00", "92 45 64", "82 45 00"):
        assert line in text
    run(tmp_path, synth, c)
    assert [m.hex() for m in [midi.Msg(0, d, "") for d in synth.log]] == [
        "B2 20 04", "C2 05", "92 39 64", "82 39 00", "92 45 64", "82 45 00"]
    assert "6 messages" in text


def test_probe_measures_pitch_latency_and_silence(tmp_path):
    synth = FakeSynth(latency_ms=6.5, detune_cents=-3.2)
    res, out = run(tmp_path, synth)
    assert [r.note for r in res] == [57, 69]
    for r in res:
        assert r.status == "ok", r
        for c in r.channels:
            assert c.cents == pytest.approx(-3.2, abs=0.05)
            assert c.latency_ms == pytest.approx(6.5, abs=0.5)
            assert c.level_db == pytest.approx(an.rms_db(0.25 * np.sin(np.arange(4800))), abs=0.3)
            assert c.noise_db < -50 and c.tail_silent
    assert "| A3 (57)" in out and "| A4 (69)" in out
    rep = json.loads((tmp_path / "probe.json").read_text())
    assert rep["results"][0]["channels"][1]["input"] == 2
    a, sr = audio.read_wav(tmp_path / "probe-057-A3.wav")
    assert sr == SR and a.shape == (round(1.3 * SR), 2)


def test_probe_flags_detune_and_stuck_note(tmp_path):
    res, _ = run(tmp_path, FakeSynth(detune_cents=20.0))
    assert all("+20.00 c" in r.status for r in res)
    res, _ = run(tmp_path, FakeSynth(stuck=True))
    assert all("sound after note-off" in r.status for r in res)


def test_probe_no_audio_reports_no_note(tmp_path):
    res, _ = run(tmp_path, FakeSynth(level=0.0))
    assert all(r.status.startswith("in1: no note") for r in res)


def test_interrupted_take_releases_the_held_note(tmp_path):
    synth = FakeSynth(fail_after_note_on=True)
    with pytest.raises(KeyboardInterrupt):
        run(tmp_path, synth)
    assert synth.log == [bytes([0x90, 57, 100]), bytes([0x80, 57, 0])]


def test_config_file_and_flags(tmp_path):
    p = tmp_path / "hwrig.toml"
    p.write_text('[midi]\nusb_port = "Summit"\nchannel = 2\n[audio]\naudio_device = "Fireface"\n'
                 'inputs = [3, 4]\n[probe]\nnotes = [60]\n')
    c = config.load(p)
    assert (c.channel, c.audio_device, c.inputs, c.notes) == (2, "Fireface", [3, 4], [60])
    args = cli.argparse.Namespace(channel=5, device="2", inputs="7,8", samplerate=None,
                                  notes="57,45", slot=None, velocity=None, hold=None)
    c = cli.apply_flags(c, args)
    assert (c.channel, c.audio_device, c.inputs, c.notes) == (5, "2", [7, 8], [57, 45])
    p.write_text("[midi]\nchanel = 2\n")
    with pytest.raises(ValueError, match="unknown key"):
        config.load(p)
    with pytest.raises(FileNotFoundError):
        config.load(tmp_path / "missing.toml")
    with pytest.raises(ValueError):
        cfg(channel=17)


def test_example_config_parses():
    c = config.load(Path(config.__file__).with_name("hwrig.example.toml"))
    assert c.validate().usb_port == "Summit"


def test_find_port():
    names = ["Summit", "Summit MIDI 2", "UM-ONE"]
    assert midi.find_port(names, "Summit") == "Summit"
    assert midi.find_port(names, "um-one") == "UM-ONE"
    with pytest.raises(LookupError, match="several"):
        midi.find_port(["Summit A", "Summit B"], "Summit")
    with pytest.raises(LookupError, match="no MIDI"):
        midi.find_port(names, "Peak")


def test_wav_round_trip(tmp_path):
    x = np.stack([np.linspace(-1, 1, 1000), np.sin(np.arange(1000) * 0.1) * 0.5], axis=1)
    audio.write_wav(tmp_path / "a.wav", x, 44100)
    y, sr = audio.read_wav(tmp_path / "a.wav")
    assert sr == 44100 and y.shape == x.shape
    assert np.max(np.abs(y - x)) < 2.0 / 8388608


def test_port_refuses_sysex_system_messages_and_bootloader():
    for ok in (midi.note_on(1, 60, 100), midi.note_off(16, 60), midi.cc(2, 101, 0),
               midi.program_change(1, 5), bytes([0xD1, 64]), bytes([0xE1, 0, 0x40])):
        assert midi.check_message(ok) == ok
    for bad in (bytes([0xF0, 0x00, 0x20, 0x29, 0xF7]), bytes([0xFF]), bytes([0xF8]), b"",
                bytes([0x90, 60]), bytes([0x90, 0x80, 1]), bytes([0xC0, 1, 2])):
        with pytest.raises(ValueError, match="refused"):
            midi.check_message(bad)
    with pytest.raises(ValueError, match="bootloader"):
        midi.check_port_name("Summit Bootloader")
    assert midi.check_port_name("Summit") == "Summit"


def test_planned_messages_pass_the_port_check():
    pre, notes = probe.plan(cfg(slot="A127", channel=16))
    for m in pre + [m for _, ms in notes for m in ms]:
        midi.check_message(m.data)


def test_wav_of_a_column_slice(tmp_path):
    # Inputs 9 and 10 of a 34-channel interface: a non-contiguous slice.
    x = np.random.default_rng(0).uniform(-0.5, 0.5, (2000, 10)).astype(np.float32)[:, [8, 9]]
    audio.write_wav(tmp_path / "b.wav", x, 48000)
    y, _ = audio.read_wav(tmp_path / "b.wav")
    assert np.max(np.abs(y - x)) < 2.0 / 8388608


def test_parse_slot():
    assert config.parse_slot("D002") == (4, 2)
    assert config.parse_slot("a0") == (1, 0)
    assert config.parse_slot("B127") == (2, 127)
    for bad in ("E001", "D128", "D", "002", "Dx1"):
        with pytest.raises(ValueError):
            config.parse_slot(bad)
    with pytest.raises(ValueError):
        cfg(mpe_base="H001")


def test_probe_reports_the_strongest_other_partial(tmp_path):
    res, _ = run(tmp_path, FakeSynth(h2_db=-58.0))
    assert all(c.other_db == pytest.approx(-58.0, abs=0.3) for r in res for c in r.channels)
    res, _ = run(tmp_path, FakeSynth())  # a pure sine: nothing above the noise
    assert all(c.other_db is None for r in res for c in r.channels)


def test_released_voice_leak_is_not_a_stuck_note(tmp_path):
    # As on the Summit: the note's pitch stays at -66 dB re the note after release.
    res, _ = run(tmp_path, FakeSynth(leak_db=-66.0))
    for r in res:
        assert r.status == "ok"
        assert all(c.tail_silent and c.leak_db == pytest.approx(-66.0, abs=1.0) for c in r.channels)
    res, _ = run(tmp_path, FakeSynth(leak_db=-20.0))  # a voice that didn't close
    assert all("sound after note-off" in r.status for r in res)
