"""`hwrig run`: the stage-2 checks, unattended after one confirmation.

Order: the plan is printed (every check, its sound, what it sends, how long)
and the full byte listing is written next to the report; nothing is opened
or sent until `confirm()` says yes. Then:

1. bend ranges: RPN 0 = 48 on member 2 (note range), 2 on the master;
   member channels reset (bend centre, pressure 0, Slide 0);
2. for each check: `setup` of its recipe when it differs from the last
   one (edit buffer only), then one take while its timeline plays;
3. report.md / report.json, and the WAV and sent-MIDI log of every take
   with a failing row, under work/hw-runs/<timestamp>/.

If anything stops the run (Ctrl-C, an error), the cleanup sends a note-off
for every note still held, and bend centre / pressure 0 / Slide 0 on the
member channels; the plan says so. Nothing is ever saved.
"""
import json
import time
from collections import Counter
from dataclasses import asdict

from . import setup as setup_mod
from .audio import write_wav
from .checks import MASTER, NOTE_RANGE
from .midi import check_message
from .recipes import RECIPES
from .config import parse_zone
from .setup import nrpn_mode
from .stimulus import Take, bend, cc, note_off, pressure, rpn

MEMBERS = range(2, 17)
PORT_SETTLE_S = 0.3  # after opening the MIDI port, before the first message
ALL = range(1, 17)


def preamble(cfg):
    msgs = rpn(2, 0, 0, NOTE_RANGE) + rpn(MASTER, 0, 0, 2)
    for ch in MEMBERS:
        msgs += [bend(ch, 0), pressure(ch, 0), cc(ch, 74, 0)]
    return msgs


def centre(chans=ALL):
    out = []
    for ch in chans:
        out += [bend(ch, 0), pressure(ch, 0), cc(ch, 74, 0)]
    return out


def cleanup_msgs(held):
    return [note_off(ch, n) for ch, n in sorted(held)] + centre()


def restore_msgs(cfg):
    """Single mode, the config's MPE layout, centred channels.

    NRPN 62:0 = 0 on the Part channels first (in Multi the global channel
    doesn't switch modes), then on the global channel (a no-op in Single);
    then MCM for `mpe.zone` ("off": no zone, so an MPE patch plays Lower 15
    as with Settings Zone Off)."""
    out = []
    for ch in dict.fromkeys([cfg.part_a_channel, cfg.part_b_channel, cfg.channel]):
        out += nrpn_mode(ch, 0)
    kind, n = parse_zone(cfg.zone)
    if kind == "upper":
        out += rpn(1, 0, 6, 0) + rpn(16, 0, 6, n)
    else:
        out += rpn(16, 0, 6, 0) + rpn(1, 0, 6, n if kind == "lower" else 0)
    return out + centre()


def describe(msgs):
    """'12 note on, 3 pitch bend on ch 2-4' style summary."""
    kinds = {0x80: "note off", 0x90: "note on", 0xA0: "poly pressure", 0xB0: "CC", 0xC0: "program change",
             0xD0: "pressure", 0xE0: "pitch bend"}
    count, chans = Counter(), {}
    for d in msgs:
        k = kinds[d[0] & 0xF0]
        count[k] += 1
        chans.setdefault(k, set()).add((d[0] & 0x0F) + 1)

    def span(cs):
        cs = sorted(cs)
        return f"ch {cs[0]}" if len(cs) == 1 else f"ch {cs[0]}-{cs[-1]}" if cs == list(range(cs[0], cs[-1] + 1)) \
            else "ch " + ",".join(map(str, cs))
    return ", ".join(f"{n} {k} ({span(chans[k])})" for k, n in count.most_common())


class Item:
    def __init__(self, check, steps, timelines, skip=""):
        self.check, self.steps, self.timelines, self.skip = check, steps, timelines, skip

    @property
    def duration(self):
        return sum(tl.duration for tl in self.timelines)

    def messages(self):
        return [e.data for tl in self.timelines for e in tl.messages()]


class Plan:
    def __init__(self, cfg, table, checks):
        self.cfg, self.table, self.checks = cfg, table, checks
        self.pre = preamble(cfg)
        self.restore = restore_msgs(cfg)
        self.items = []
        last = None
        for c in checks:
            try:
                steps = None
                if c.recipe != last:
                    steps = setup_mod.plan(table, RECIPES[c.recipe], cfg)
                tls = c.timelines(cfg)
            except ValueError as e:  # e.g. Part channels inside the zone: skip, say why
                self.items.append(Item(c, None, [], skip=str(e)))
                continue
            last = None if c.changes_layout else c.recipe
            for tl in tls:
                if tl.held_at_end():
                    raise ValueError(f"{c.name}: notes left on at the end of its timeline: {tl.held_at_end()}")
                for e in tl.messages():
                    check_message(e.data)
            self.items.append(Item(c, steps, tls))
        for d in self.restore:
            check_message(d)

    @property
    def changes_layout(self):
        return any(i.check.changes_layout and not i.skip for i in self.items)

    def seconds(self):
        s = 0.2
        for it in self.items:
            if it.steps:
                s += sum(st.wait_s for st in it.steps) + setup_mod.SETTLE_S
            s += it.duration + 0.3 * len(it.timelines)
            if it.check.changes_layout and not it.skip:
                s += 0.5
        return s

    def text(self, port_name, listing_path=None):
        cfg = self.cfg
        lines = [f"hwrig run: {len(self.items)} checks, MIDI to {port_name!r}; audio inputs {cfg.inputs}.",
                 f"Assumes: an MPE patch on the Lower Zone (Settings Zone Off or Lower 15), master channel 1 "
                 f"= the global channel {cfg.channel}; MPE layout to restore: {cfg.zone!r}.",
                 f"  0. bend ranges and a clean start, at the start and again before every check: "
                 f"{describe(self.pre)}\n"
                 f"      [RPN 0 = {NOTE_RANGE} on ch 2, RPN 0 = 2 on ch 1; bend centre, pressure 0, CC 74 0 on ch 2-16]"]
        if any(getattr(RECIPES.get(i.check.recipe), "base", "") == "multi" for i in self.items):
            lines.append(f"  Part channels from work/hwrig.toml: Part A = {cfg.part_a_channel}, Part B = "
                         f"{cfg.part_b_channel}. CHECK they match the Summit's Settings > MIDI CHANNEL before "
                         "typing play (MIDI can't set them).")
        for k, it in enumerate(self.items, 1):
            c = it.check
            if it.skip:
                lines.append(f"  {k}. check {c.name}: SKIPPED, {it.skip}")
                continue
            if it.steps:
                r = RECIPES[c.recipe]
                if getattr(r, "base", "") == "multi":
                    first = "; ".join(s.what for s in it.steps[:3])
                    last = "; ".join(s.what for s in it.steps[-3:])
                    lines.append(f"  {k}. setup {c.recipe} ({r.about}): {first}; then both parts; then {last}; "
                                 f"{sum(len(s.data) for s in it.steps)} messages")
                else:
                    base = cfg.mpe_base if r.base == "mpe" else cfg.plain_base
                    lines.append(f"  {k}. setup {c.recipe} ({r.about}): select {base.upper()}, "
                                 f"{sum(len(s.data) for s in it.steps)} NRPN/CC messages, edit buffer only")
                lines.append(f"     check {c.name}: {c.about}")
            else:
                lines.append(f"  {k}. check {c.name}: {c.about}")
            lines.append(f"     {describe(it.messages())}; {it.duration:.1f} s recorded"
                         + (f" in {len(it.timelines)} takes" if len(it.timelines) > 1 else ""))
            if c.changes_layout:
                lines.append(f"     then restore: Single mode (NRPN 62:0 = 0), MCM for {cfg.zone!r}, "
                             "centred channels")
        n = len(self.pre) * (1 + sum(not it.skip for it in self.items)) + sum(sum(len(s.data) for s in it.steps) if it.steps else 0 for it in self.items) + \
            sum(len(it.messages()) for it in self.items) + \
            sum(len(self.restore) for it in self.items if it.check.changes_layout and not it.skip)
        lines.append(f"{n} messages, about {self.seconds():.0f} s. Nothing is saved; the last test sound stays "
                     "in the edit buffer (select a slot to leave it).")
        stop = "note-offs for held notes, then bend centre, pressure 0 and CC 74 0 on ch 1-16"
        if self.changes_layout:
            stop += f", Single mode and the MCM for {cfg.zone!r}"
        lines.append(f"Whenever the run ends or stops: {stop}. No SysEx, no other messages.")
        if listing_path:
            lines.append(f"Every message: {listing_path}")
        return "\n".join(lines)

    def listing(self):
        out = ["# preamble"] + [d.hex(" ").upper() for d in self.pre]
        for it in self.items:
            if it.skip:
                out.append(f"# check {it.check.name}: skipped, {it.skip}")
                continue
            if it.steps:
                out += [f"# setup {it.check.recipe}", setup_mod.listing(it.steps)]
            for k, tl in enumerate(it.timelines):
                out.append(f"# check {it.check.name} take {k + 1} (seconds into the take)")
                out += [f"{e.t:8.4f} {e.data.hex(' ').upper():<9} {e.label}" for e in tl.messages()]
            if it.check.changes_layout:
                out += ["# restore"] + [d.hex(" ").upper() for d in self.restore]
        out += ["# at the end, if any check changed the layout: restore"]
        return "\n".join(out) + "\n"


def record_take(port, recorder, tl, held):
    """Play `tl` while recording; returns a Take and the sent log."""
    def fire(e):
        def fn():
            if e.data:
                port.send(e.data)
                kind = e.data[0] & 0xF0
                key = ((e.data[0] & 0x0F) + 1, e.data[1])
                if kind == 0x90 and e.data[2]:
                    held.add(key)
                elif kind in (0x80, 0x90):
                    held.discard(key)
        return fn
    events = tl.sorted()
    audio, stamps = recorder.record(tl.duration, [(e.t, fire(e)) for e in events])
    times = {}
    for e, s in zip(events, stamps):
        if e.label and e.label not in times:
            times[e.label] = s
    return Take(audio, recorder.sr, times), list(zip(events, stamps))


def send_all(port, msgs, sleep, gap=0.002):
    for d in msgs:
        port.send(d)
        sleep(gap)


def run(plan, port_name, open_port, recorder, confirm, out_dir, say=print, sleep=time.sleep):
    """Run the plan. Returns the rows, or None if not confirmed (nothing
    opened or sent)."""
    from .checks import Row
    out_dir.mkdir(parents=True, exist_ok=True)
    listing = out_dir / "messages.txt"
    listing.write_text(plan.listing())
    say(plan.text(port_name, listing))
    if not confirm():
        say("Not confirmed: nothing sent.")
        return None
    port = open_port()
    sleep(PORT_SETTLE_S)
    rows, held, failed_takes = [], set(), []
    started = time.strftime("%Y-%m-%d %H:%M:%S")
    completed = False
    try:
        send_all(port, plan.pre, sleep)
        sleep(0.1)
        for it in plan.items:
            c = it.check
            if it.skip:
                say(f"check {c.name}: skipped ({it.skip})")
                rows.append(Row(c.name, "skipped", "", it.skip, "", "info"))
                continue
            if it.steps:
                say(f"setup {c.recipe} ...")
                setup_mod.send(it.steps, port, sleep=sleep)
            # the bend ranges and centred channels again before every check, so a check never
            # depends on one message sent minutes earlier (a DIN run on 2026-11-08 lost the
            # first preamble's RPN 0 = 48: two checks ran at the Settings' ±49)
            send_all(port, plan.pre, sleep)
            sleep(0.05)
            say(f"check {c.name} ({it.duration:.1f} s"
                + (f", {len(it.timelines)} takes" if len(it.timelines) > 1 else "") + ") ...")
            takes, logs = [], []
            for tl in it.timelines:
                take, log = record_take(port, recorder, tl, held)
                takes.append(take)
                logs.append(log)
            try:
                r = c.analyze_takes(takes, plan.cfg)
            except Exception as e:  # an analysis bug must not leave notes on or lose the takes
                r = [Row(c.name, "analysis", "", f"{type(e).__name__}: {e}", "", "fail")]
            rows += r
            bad = [x for x in r if x.status == "fail"]
            say(f"  {len(r) - len(bad)}/{len(r)} rows ok" + (f"; FAIL: {bad[0].item}" if bad else ""))
            if bad:
                failed_takes += c.save_failures(takes, logs, r, out_dir)
            if c.changes_layout:
                say("  restore: Single mode, MCM, centred channels")
                send_all(port, plan.restore, sleep)
                sleep(setup_mod.MODE_S)
            sleep(0.3)
        completed = True
    finally:
        if held or not completed or plan.changes_layout:
            extra = [note_off(ch, n) for ch, n in sorted(held)]
            msgs = extra + (plan.restore if plan.changes_layout else centre())
            say(f"cleanup: note-offs for {sorted(held)}; "
                + ("Single mode, MCM for the configured zone, " if plan.changes_layout else "")
                + "centred channels")
            send_all(port, msgs, sleep)
        port.close()
    write_report(out_dir, plan, port_name, recorder, rows, failed_takes, started)
    say(table(rows))
    say(f"Report: {out_dir / 'report.md'}")
    return rows


def table(rows):
    head = ("check", "item", "expected", "measured", "tolerance", "result", "note")
    data = [(r.check, r.item, r.expected, r.measured, r.tol, r.status.upper(), r.note) for r in rows]
    w = [max([len(h)] + [len(d[i]) for d in data]) for i, h in enumerate(head)]
    line = lambda cells: "| " + " | ".join(str(c).ljust(w[i]) for i, c in enumerate(cells)) + " |"
    return "\n".join([line(head), "|" + "|".join("-" * (x + 2) for x in w) + "|"] + [line(d) for d in data])


def summary(rows):
    c = Counter(r.status for r in rows)
    return f"{c['pass']} pass, {c['fail']} fail, {c['info']} info"


def write_report(out_dir, plan, port_name, recorder, rows, failed_takes, started):
    cfg = plan.cfg
    meta = {"started": started, "port": port_name, "samplerate": recorder.sr, "inputs": recorder.inputs,
            "mpe_base": cfg.mpe_base, "plain_base": cfg.plain_base, "checks": [c.name for c in plan.checks],
            "zone": cfg.zone, "part_channels": [cfg.part_a_channel, cfg.part_b_channel],
            "summary": summary(rows), "failed_takes": failed_takes}
    try:
        import subprocess
        meta["git"] = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                                     cwd=str(out_dir), timeout=5).stdout.strip()
    except Exception:  # noqa: BLE001 - the report must still be written
        meta["git"] = ""
    (out_dir / "report.json").write_text(json.dumps({**meta, "rows": [asdict(r) for r in rows]}, indent=2))
    md = [f"# hwrig run {started}", "",
          f"{summary(rows)}. Port `{port_name}`, {recorder.sr} Hz, inputs {recorder.inputs}, "
          f"git {meta['git'] or '?'}.", ""]
    if failed_takes:
        md += ["Failing takes (WAV + sent MIDI): " + ", ".join(f"`{n}.wav`" for n in failed_takes), ""]
    md += [table(rows), ""]
    (out_dir / "report.md").write_text("\n".join(md))
