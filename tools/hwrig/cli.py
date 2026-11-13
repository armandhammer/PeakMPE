"""Hardware test rig for the MPE Summit (docs/hw-test-rig.md).

  hwrig list                       audio inputs (with channel counts) and MIDI
                                   ports. Sends nothing.
  hwrig patches                    the test-sound recipes and what MIDI can set
                                   (reads the local firmware image). Sends nothing.
  hwrig setup NAME [--check]       build test sound NAME (p1 ... p7) in the edit
                                   buffer over NRPN/CC; --check then plays A3 and
                                   measures it. Prints the plan first and sends
                                   nothing until you type 'play'.
  hwrig run [--checks a,b] [--din] the stage-2 checks (docs/hw-test-rig.md#checks):
                                   one plan, one 'play', then unattended; report
                                   and failing takes in work/hw-runs/<timestamp>/.
  hwrig probe [options]            play single notes on one MIDI port and
                                   channel, record the Summit's outputs, report
                                   pitch (cents), level, latency, noise floor.
                                   Prints every message first and sends nothing
                                   until you type 'play'.

  --yes (setup, run, probe) prints the plan and sends without the prompt,
  for runs approved in advance.

Run from the repository root:
  .venv/bin/python -I tools/hwrig list
  .venv/bin/python -I tools/hwrig probe --inputs 1,2

Settings come from work/hwrig.toml (see tools/hwrig/hwrig.example.toml),
then from the flags.
"""
import argparse
import sys
import time

from . import config as config_mod


def confirm_play():
    try:
        answer = input("Type 'play' to send these messages, anything else aborts: ")
    except (EOFError, OSError):
        return False
    return answer.strip() == "play"


def confirmer(args):
    """--yes: the plan is still printed, but sent without the 'play' prompt
    (for runs the user has approved in advance)."""
    return (lambda: True) if getattr(args, "yes", False) else confirm_play


def cmd_list(args, say=print):
    from . import audio, midi
    say("Audio inputs (index, name, host API, input channels, default rate):")
    try:
        default = audio.default_input()
        devs = audio.input_devices()
    except Exception as e:  # noqa: BLE001 - report and go on to MIDI
        say(f"  could not query audio devices: {e}")
        devs, default = [], None
    for i, name, api, nch, sr in devs:
        mark = "*" if i == default else " "
        say(f" {mark}{i:3}  {name!r}  [{api}]  {nch} in  {sr:.0f} Hz")
    if devs:
        say("  (* = default input; input channels are numbered 1..N for --inputs)")
    say("MIDI outputs (what probe can send to):")
    for name in midi.output_ports():
        say(f"    {name!r}")
    say("MIDI inputs (not used by the rig yet):")
    for name in midi.input_ports():
        say(f"    {name!r}")
    return 0


def cmd_patches(args, say=print):
    from . import params, recipes
    cfg = config_mod.load(args.config).validate()
    t = params.load_table(cfg.product)
    say(f"Base slots: MPE on {cfg.mpe_base}, MPE off {cfg.plain_base} (work/hwrig.toml [patches])")
    for r in recipes.RECIPES.values():
        say(f"  {r.name}  ({r.base} base)  {r.about}")
        for p, value, why in r.resolve(t):
            say(f"        {why:<36} {p}")
    say(f"{len(t.sound_params())} sound parameters are set over MIDI; not settable: "
        + ", ".join(str(p) for p in t.unsettable_sound_params()))
    say("Matrix sources: " + ", ".join(t.sources))
    say("Matrix destinations: " + ", ".join(t.dests))
    return 0


def resolve_port(cfg, args):
    from . import midi
    if getattr(args, "port", None):
        want = args.port
    elif getattr(args, "din", False):
        if not cfg.din_port:
            raise SystemExit("--din: set midi.din_port in work/hwrig.toml (see `list`)")
        want = cfg.din_port
    else:
        want = cfg.usb_port
    return midi.check_port_name(midi.find_port(midi.output_ports(), want))


def cmd_setup(args, say=print):
    from . import audio, midi, params, probe, recipes, setup
    cfg = config_mod.load(args.config)
    if args.channel is not None:
        cfg.channel = args.channel
    cfg.validate()
    if args.name not in recipes.RECIPES:
        raise ValueError(f"no recipe {args.name!r}; known: {', '.join(recipes.RECIPES)}")
    recipe = recipes.RECIPES[args.name]
    table = params.load_table(cfg.product)
    port_name = resolve_port(cfg, args)
    steps = setup.plan(table, recipe, cfg)
    out = config_mod.RUNS_DIR / time.strftime("%Y-%m-%d_%H%M%S") / f"setup-{recipe.name}"
    out.mkdir(parents=True, exist_ok=True)
    listing = out / "messages.txt"
    listing.write_text(setup.listing(steps) + "\n", encoding="utf-8")
    say(setup.plan_text(table, recipe, cfg, port_name, steps, listing))
    rec = None
    if args.check:
        cfg.notes = [57]
        dev = audio.resolve_device(cfg.audio_device)
        rec = audio.SoundDeviceRecorder(dev[0], cfg.inputs, cfg.samplerate, input_delay_s=cfg.input_delay_ms / 1000.0)
        say(f"Then the check, audio from {dev[1]!r} inputs {cfg.inputs}:")
        say(probe.plan_text(cfg, port_name))
    if not confirmer(args)():
        say("Not confirmed: nothing sent.")
        return 2
    port = midi.RtMidiOut(port_name)
    try:
        setup.send(steps, port)
    finally:
        port.close()
    say(f"Sent {sum(len(s.data) for s in steps)} messages: {recipe.name} is in the edit buffer.")
    if not args.check:
        return 0
    res = probe.run(cfg, port_name, lambda: midi.RtMidiOut(port_name), rec, lambda: True, out,
                    say=say, show_plan=False)
    say(f"WAV and report: {out}")
    return 0 if all(r.status == "ok" for r in res) else 1


def cmd_run(args, say=print):
    from . import audio, checks, checks3, checks4, checks5, midi, params, run
    cfg = config_mod.load(args.config).validate()
    available = checks3.all_checks(args.b1_trials)
    stages = {"2": [c.name for c in checks.stage2()], "3": [c.name for c in checks3.stage3()],
              "4": [c.name for c in checks4.stage4()], "5": [c.name for c in checks5.stage5()]}
    stages["all"] = stages["2"] + stages["3"] + stages["4"] + stages["5"]
    names = args.checks.split(",") if args.checks else stages[args.stage]
    unknown = [n for n in names if n not in available]
    if unknown:
        raise ValueError(f"unknown checks {unknown}; known: {', '.join(available)}")
    table = params.load_table(cfg.product)
    port_name = resolve_port(cfg, args)
    dev = audio.resolve_device(cfg.audio_device)
    if max(cfg.inputs) > dev[3]:
        raise SystemExit(f"inputs {cfg.inputs}: device {dev[1]!r} has {dev[3]} input channels")
    plan = run.Plan(cfg, table, [available[n] for n in names])
    rec = audio.SoundDeviceRecorder(dev[0], cfg.inputs, cfg.samplerate, input_delay_s=cfg.input_delay_ms / 1000.0)
    out = config_mod.RUNS_DIR / time.strftime("%Y-%m-%d_%H%M%S")
    say(f"Audio from {dev[1]!r} (index {dev[0]}), inputs {cfg.inputs}, {cfg.samplerate} Hz")
    rows = run.run(plan, port_name, lambda: midi.RtMidiOut(port_name), rec, confirmer(args), out, say=say)
    if rows is None:
        return 2
    say(run.summary(rows))
    return 0 if all(r.status != "fail" for r in rows) else 1


def apply_flags(cfg, args):
    if args.channel is not None:
        cfg.channel = args.channel
    if args.device is not None:
        cfg.audio_device = args.device
    if args.inputs is not None:
        cfg.inputs = [int(c) for c in args.inputs.split(",") if c.strip()]
    if args.samplerate is not None:
        cfg.samplerate = args.samplerate
    if args.notes is not None:
        cfg.notes = [int(n) for n in args.notes.split(",") if n.strip()]
    if args.slot is not None:
        cfg.slot = args.slot
    if args.velocity is not None:
        cfg.velocity = args.velocity
    if args.hold is not None:
        cfg.hold_s = args.hold
    return cfg.validate()


def cmd_probe(args, say=print):
    from . import audio, midi, probe
    cfg = apply_flags(config_mod.load(args.config), args)
    port_name = resolve_port(cfg, args)
    dev = audio.resolve_device(cfg.audio_device)
    if max(cfg.inputs) > dev[3]:
        raise SystemExit(f"inputs {cfg.inputs}: device {dev[1]!r} has {dev[3]} input channels")
    say(f"Audio from {dev[1]!r} (index {dev[0]}), inputs {cfg.inputs}, {cfg.samplerate} Hz")
    out = config_mod.RUNS_DIR / time.strftime("%Y-%m-%d_%H%M%S") / "probe"
    rec = audio.SoundDeviceRecorder(dev[0], cfg.inputs, cfg.samplerate, input_delay_s=cfg.input_delay_ms / 1000.0)
    res = probe.run(cfg, port_name, lambda: midi.RtMidiOut(port_name), rec, confirmer(args), out, say=say)
    if res is None:
        return 2
    say(f"WAVs and report: {out}")
    return 0 if all(r.status == "ok" for r in res) else 1


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):  # a Windows console code page lacks ±, ≥ ...
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    p = argparse.ArgumentParser(prog="hwrig", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="audio inputs and MIDI ports; sends nothing")
    pp = sub.add_parser("patches", help="test-sound recipes; sends nothing")
    pp.add_argument("--config", help="config file (default work/hwrig.toml)")
    ru = sub.add_parser("run", help="the stage-2 checks, unattended after one 'play'")
    ru.add_argument("--config", help="config file (default work/hwrig.toml)")
    ru.add_argument("--yes", action="store_true", help="send without the 'play' prompt (plan still printed)")
    gr = ru.add_mutually_exclusive_group()
    gr.add_argument("--port", help="MIDI output port (name or unique substring)")
    gr.add_argument("--din", action="store_true", help="use midi.din_port")
    ru.add_argument("--checks", help="comma-separated subset, e.g. bend_one_note,b1_zone_change")
    ru.add_argument("--stage", choices=["2", "3", "4", "5", "all"], default="2",
                    help="which checks (default 2; 4: MPE v1.1 voice rotation; 5: LinnStrument patterns)")
    ru.add_argument("--b1-trials", type=int, default=60, help="B1 trials per delay (default 60, 5 delays)")
    su = sub.add_parser("setup", help="build a test sound in the edit buffer (asks first)")
    su.add_argument("name", help="recipe: p1 ... p7 (see `patches`)")
    su.add_argument("--config", help="config file (default work/hwrig.toml)")
    su.add_argument("--yes", action="store_true", help="send without the 'play' prompt (plan still printed)")
    gs = su.add_mutually_exclusive_group()
    gs.add_argument("--port", help="MIDI output port (name or unique substring)")
    gs.add_argument("--din", action="store_true", help="use midi.din_port")
    su.add_argument("--channel", type=int, help="MIDI channel 1-16")
    su.add_argument("--check", action="store_true", help="then play A3 and measure it")
    s = sub.add_parser("probe", help="play test notes and measure them (asks first)")
    s.add_argument("--config", help="config file (default work/hwrig.toml)")
    s.add_argument("--yes", action="store_true", help="send without the 'play' prompt (plan still printed)")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--port", help="MIDI output port (name or unique substring)")
    g.add_argument("--din", action="store_true", help="use midi.din_port instead of midi.usb_port")
    s.add_argument("--channel", type=int, help="MIDI channel 1-16")
    s.add_argument("--device", help="audio input device: index or name substring")
    s.add_argument("--inputs", help="1-based input channels, comma-separated, e.g. 1,2")
    s.add_argument("--samplerate", type=int)
    s.add_argument("--notes", help="MIDI note numbers, comma-separated (57 = A3)")
    s.add_argument("--velocity", type=int)
    s.add_argument("--hold", type=float, help="seconds each note is held")
    s.add_argument("--slot", help="select a patch slot first, e.g. D002 (CC 32 + program change)")
    args = p.parse_args(argv)
    try:
        if args.command == "list":
            return cmd_list(args)
        if args.command == "patches":
            return cmd_patches(args)
        if args.command == "setup":
            return cmd_setup(args)
        if args.command == "run":
            return cmd_run(args)
        return cmd_probe(args)
    except (LookupError, ValueError, FileNotFoundError) as e:
        print(f"hwrig: {e}", file=sys.stderr)
        return 2
