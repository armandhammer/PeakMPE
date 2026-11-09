"""`probe`: play single notes, record them, report pitch, level, latency.

Hardware-free core: the MIDI port, the recorder and the confirmation are
passed in, so tests/test_hwrig_probe.py runs the whole flow against a fake
synth. Nothing is sent unless `confirm(plan_text)` returns True, and the port
is only opened after that.
"""
import json
import time
from dataclasses import asdict, dataclass, field

import numpy as np

from . import analysis as an
from .audio import write_wav
from .midi import check_message, note_msgs, note_off, program_msgs

PATCH_LOAD_S = 0.5   # wait after a program change before the first note
TUNE_TOL_CENTS = 5.0 # "ok" bound for the probe; real checks use ±1 (docs/hw-test-rig.md)
STUCK_REL_DB = 40.0  # a partial after the note-off within this of the note = sound after note-off


def plan(cfg):
    """(program messages, [(note, [note messages])]) for this config; each
    message already passed the port's check, so what is shown is sendable."""
    pre, notes = program_msgs(cfg), [(n, note_msgs(cfg, n)) for n in cfg.notes]
    for m in pre + [m for _, ms in notes for m in ms]:
        check_message(m.data)
    return pre, notes


def plan_text(cfg, port_name):
    pre, notes = plan(cfg)
    lines = [f"MIDI to port {port_name!r}, channel {cfg.channel}:"]
    k = 0
    for m in pre:
        k += 1
        lines.append(f"  {k:2}. {m.hex():<9} {m.what}")
    for note, msgs in notes:
        for m in msgs:
            k += 1
            lines.append(f"  {k:2}. {m.hex():<9} {m.what}  (at +{m.at_s:.2f} s in its take)")
    take = cfg.preroll_s + cfg.hold_s + cfg.tail_s
    lines.append(f"{k} messages, one take of {take:.1f} s per note "
                 f"({len(cfg.notes) * take:.0f} s in all). If interrupted, a note-off "
                 f"for the held note is sent too. Nothing else is sent.")
    return "\n".join(lines)


@dataclass
class ChannelResult:
    input: int
    noise_db: float
    latency_ms: float = None
    level_db: float = None
    hz: float = None
    cents: float = None
    tail_db: float = None
    tail_silent: bool = None
    tail_tones_hz: list = field(default_factory=list)
    other_db: float = None  # strongest other partial, dB re the fundamental (purity)
    leak_db: float = None   # the note's pitch in the tail, dB re the note (released-voice leak)


@dataclass
class NoteResult:
    note: int
    name: str
    expected_hz: float
    channels: list
    status: str = ""


def analyze_take(audio, sr, cfg, note, on_s, off_s, inputs):
    on_i, off_i = int(round(on_s * sr)), int(round(off_s * sr))
    exp = an.note_hz(note, cfg.a4_hz)
    chans = []
    for k, inp in enumerate(inputs):
        x = audio[:, k].astype(np.float64)
        pre = x[: max(64, on_i - int(0.01 * sr))]
        r = ChannelResult(input=inp, noise_db=round(an.rms_db(pre), 1))
        o = an.onset(x[on_i:off_i], sr, noise_db=r.noise_db)
        note_db, note_hz = None, None
        if o is not None:
            r.latency_ms = round(1000.0 * o / sr, 2)
            a = on_i + o + int(0.1 * sr)
            b = off_i - int(0.01 * sr)
            if b - a > int(0.05 * sr):
                seg = x[a:b]
                r.level_db = round(an.rms_db(seg), 1)
                p = an.fundamental(seg, sr)
                if p is not None:
                    note_db, note_hz = p.db, p.hz
                    r.hz = round(p.hz, 4)
                    r.cents = round(float(an.cents(p.hz, exp)), 3)
                    # partials the pre-roll doesn't have (so not hum), away from the
                    # note's window skirt (> 1 semitone), within the window's 85 dB range
                    others = [q.db for q in an.tone_above_reference(seg, pre, sr, fmax=20000,
                                                                    min_db=p.db - 85.0)
                              if abs(an.cents(q.hz, p.hz)) > 100]
                    r.other_db = round(max(others) - p.db, 1) if others else None
        t = off_i + int(min(0.5, (len(x) - off_i) / sr / 2) * sr)
        tail = x[t:]
        if tail.size >= 1024:
            min_db = note_db - STUCK_REL_DB if note_db is not None else -90.0
            s = an.silence(tail, pre, sr, min_db=min_db)
            r.tail_db, r.tail_silent = round(s.rms_db, 1), s.silent
            if note_hz is not None:
                r.leak_db = round(float(an.db(an.Spectrum(tail, sr).dtft(note_hz))) - note_db, 1)
            r.tail_tones_hz = [round(p.hz, 2) for p in s.tones[:5]]
        chans.append(r)
    res = NoteResult(note, an.note_name(note), round(exp, 4), chans)
    res.status = status(res)
    return res


def status(res):
    problems = []
    for c in res.channels:
        if c.latency_ms is None:
            problems.append(f"in{c.input}: no note")
        elif c.cents is None:
            problems.append(f"in{c.input}: no pitch")
        elif abs(c.cents) > TUNE_TOL_CENTS:
            problems.append(f"in{c.input}: {c.cents:+.2f} c")
        if c.tail_silent is False:
            problems.append(f"in{c.input}: sound after note-off")
    return "ok" if not problems else "; ".join(problems)


def table(results):
    head = ("note", "input", "expected Hz", "measured Hz", "cents", "level dB",
            "latency ms", "noise dB", "tail dB", "other partials dB", "leak dB", "status")
    rows = []
    for r in results:
        for c in r.channels:
            f = lambda v, fmt: "-" if v is None else format(v, fmt)
            rows.append((f"{r.name} ({r.note})", f"in{c.input}", f"{r.expected_hz:.3f}",
                         f(c.hz, ".3f"), f(c.cents, "+.2f"), f(c.level_db, ".1f"),
                         f(c.latency_ms, ".1f"), f"{c.noise_db:.1f}", f(c.tail_db, ".1f"),
                         f(c.other_db, ".1f"), f(c.leak_db, ".1f"), r.status))
    w = [max(len(h), *(len(row[i]) for row in rows)) for i, h in enumerate(head)] if rows else [len(h) for h in head]
    line = lambda cells: "| " + " | ".join(c.ljust(w[i]) for i, c in enumerate(cells)) + " |"
    return "\n".join([line(head), "|" + "|".join("-" * (x + 2) for x in w) + "|"] + [line(r) for r in rows])


def run(cfg, port_name, open_port, recorder, confirm, out_dir, say=print, sleep=time.sleep,
        show_plan=True):
    """Run the probe. Returns the NoteResults, or None if not confirmed
    (and then nothing was opened or sent). show_plan=False: the caller
    already showed plan_text and had it confirmed."""
    if show_plan:
        say(plan_text(cfg, port_name))
    if not confirm():
        say("Not confirmed: nothing sent.")
        return None
    pre, notes = plan(cfg)
    port = open_port()
    results, held = [], set()
    try:
        for m in pre:
            port.send(m.data)
        if pre:
            sleep(PATCH_LOAD_S)
        for note, msgs in notes:
            def send(m=None, note=note):
                def fn():
                    port.send(m.data)
                    (held.add if m.data[0] & 0xF0 == 0x90 else held.discard)(note)
                return fn
            events = [(m.at_s, send(m)) for m in msgs]
            take_s = cfg.preroll_s + cfg.hold_s + cfg.tail_s
            audio, stamps = recorder.record(take_s, events)
            res = analyze_take(audio, recorder.sr, cfg, note, stamps[0], stamps[1], recorder.inputs)
            results.append(res)
            write_wav(out_dir / f"probe-{note:03d}-{res.name.replace('#', 's')}.wav", audio, recorder.sr)
            say(f"{res.name}: {res.status}")
    finally:
        for note in sorted(held):
            port.send(note_off(cfg.channel, note))
        port.close()
    say(table(results))
    write_report(out_dir, cfg, port_name, recorder, results)
    return results


def write_report(out_dir, cfg, port_name, recorder, results):
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "probe.json").write_text(json.dumps({
        "port": port_name, "channel": cfg.channel, "samplerate": recorder.sr,
        "inputs": recorder.inputs, "a4_hz": cfg.a4_hz,
        "results": [asdict(r) for r in results]}, indent=2))
    (out_dir / "probe.md").write_text(f"# hwrig probe\n\nport `{port_name}`, channel {cfg.channel}, "
                                      f"{recorder.sr} Hz, inputs {recorder.inputs}\n\n{table(results)}\n")
