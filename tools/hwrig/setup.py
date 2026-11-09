"""`setup`: build a test sound in the Summit's edit buffer over MIDI.

1. Select the recipe's base slot (CC 32 bank, program change): it supplies
   the MPE flag, which MIDI can't set.
2. Send the Init Patch value of every settable sound parameter (NRPN or CC,
   from the firmware's own table), so nothing of the base slot's sound is
   left except the five parameters MIDI can't reach (listed in the plan).
3. Send the recipe's own values.

Nothing is saved; selecting the slot again restores it. Every message is a
channel voice message (the port's allow-list), so no SysEx, no patch
memory, no Settings. Needs the Summit's Settings MIDI CONTROL: CC/NRPN
receive on, and Bank/Patch receive on for step 1.

Hardware-free core: the port and the confirmation are passed in;
tests/test_hwrig_setup.py feeds the same bytes to the simulator and reads
the patch back.
"""
import time
from dataclasses import dataclass

from . import params
from .midi import check_message, slot_msgs

PATCH_LOAD_S = 0.3   # after the program change (the simulator loads in < 200 ms)
MODE_S = 0.3         # after an MCM or a mode switch
BYTE_S = 0.0004      # per byte: 25 % slower than DIN (0.32 ms a byte), so DIN keeps up
GAP_S = 0.001        # at least this between parameters
SETTLE_S = 0.1       # after the last message, before anything plays


@dataclass
class Step:
    data: list       # one parameter's messages (bytes), sent back to back
    what: str
    wait_s: float    # pause after the step


def plan(table, recipe, cfg):
    """[Step] for `recipe` on cfg.channel (a MultiRecipe: on the Part
    channels). Raises before anything is sent if a name, value or message
    is wrong."""
    if getattr(recipe, "base", None) == "multi":
        return multi_plan(table, recipe, cfg)
    return part_plan(table, recipe, cfg, cfg.channel)


# While both parts are set up, both zones are set explicitly to these sizes,
# so channels 4-8 are in no zone whatever MPE flags the stored Multi's parts
# have. With both parts MPE on, the firmware otherwise splits Lower 2-n /
# Upper n+1-15 itself, and a Part channel inside a zone loses its program
# change and its parameter CCs (member-channel messages are dropped):
# observed on the synth, 2026-11-08, and emulated (tests/test_hwrig_run3.py).
SETUP_LOWER, SETUP_UPPER = 2, 7
SETUP_FREE = range(2 + SETUP_LOWER, 16 - SETUP_UPPER)  # 4-8


def multi_plan(table, recipe, cfg):
    from .recipes import RECIPES
    from .stimulus import rpn
    a, b = cfg.part_a_channel, cfg.part_b_channel
    master, members = recipe.zone_channels()
    zone = [master] + members
    for name, ch in (("Part A", a), ("Part B", b)):
        if ch in zone or ch == cfg.channel or a == b:
            raise ValueError(f"{name} channel {ch} (work/hwrig.toml [patches]) lies in the {recipe.zone} zone "
                             f"{min(zone)}-{max(zone)}, on the global channel, or on the other part: "
                             "set the Summit's Part channels and the config to match")
        if ch not in SETUP_FREE:
            raise ValueError(f"{name} channel {ch}: the Multi setup needs both Part channels in "
                             f"{SETUP_FREE[0]}-{SETUP_FREE[-1]} (outside its setup zones Lower 2-3 and Upper 9-15)")
    other = 1 if recipe.zone == "upper" else 16
    steps = [Step(nrpn_mode(cfg.channel, 1), f"NRPN 62:0 = 1 on ch {cfg.channel}: Multi mode", MODE_S),
             Step(rpn(1, 0, 6, SETUP_LOWER), f"MCM {SETUP_LOWER} on ch 1 (setup layout: Lower 2-3)", MODE_S),
             Step(rpn(16, 0, 6, SETUP_UPPER), f"MCM {SETUP_UPPER} on ch 16 (setup layout: Upper 9-15; "
                  f"ch {SETUP_FREE[0]}-{SETUP_FREE[-1]} free)", MODE_S)]
    for name, ch, r in (("Part A", a, recipe.part_a), ("Part B", b, recipe.part_b)):
        part = part_plan(table, RECIPES[r], cfg, ch)
        part[0].what = f"{name} (ch {ch}): " + part[0].what
        steps += part
    steps += [Step(rpn(other, 0, 6, 0), f"MCM 0 on ch {other}: no {'Lower' if other == 1 else 'Upper'} Zone",
                   MODE_S),
              Step(rpn(master, 0, 6, recipe.members),
                   f"MCM {recipe.members} on ch {master}: {recipe.zone.title()} Zone, master {master}, "
                   f"members {min(members)}-{max(members)}", MODE_S),
              # An MCM resets its zone's bend ranges to the Settings values; set them, as the
              # run's preamble does for the Lower Zone (on the synth the Upper Zone came out at
              # ±49 without this, 2026-11-08)
              Step(rpn(members[0], 0, 0, 48) + rpn(master, 0, 0, 2),
                   f"RPN 0 = 48 on ch {members[0]}, 2 on ch {master}: the zone's bend ranges", MODE_S)]
    for s_ in steps:
        for d in s_.data:
            check_message(d)
    return steps


def nrpn_mode(ch, value):
    st = 0xB0 | (ch - 1)
    return [bytes([st, 99, 62]), bytes([st, 98, 0]), bytes([st, 6, value])]


def part_plan(table, recipe, cfg, ch):
    base = cfg.mpe_base if recipe.base == "mpe" else cfg.plain_base
    steps = [Step([m.data for m in slot_msgs(ch, base)], f"select {base.upper()} (base, {recipe.base})",
                  PATCH_LOAD_S)]
    own = recipe.resolve(table)
    mine = {p.offset for p, _, _ in own}
    for p in table.sound_params():
        if p.offset not in mine:
            steps.append(_step(p, ch, table.init_value(p.offset), f"init {p.name}"))
    for p, value, why in own:
        steps.append(_step(p, ch, value, why))
    for s in steps:
        for d in s.data:
            check_message(d)
    return steps


def _step(p, ch, value, why):
    data = p.messages(ch, value)
    return Step(data, f"{why}: {p}", max(GAP_S, BYTE_S * sum(len(d) for d in data)))


def expected_patch(table, recipe):
    """{offset: value} the edit buffer should hold afterwards (one part)."""
    out = {p.offset: table.init_value(p.offset) for p in table.sound_params()}
    out.update({p.offset: v for p, v, _ in recipe.resolve(table)})
    for o in params.DERIVED:
        out.pop(o, None)
    return out


def listing(steps):
    lines = []
    for i, s in enumerate(steps, 1):
        lines.append(f"{i:4}. {' | '.join(d.hex(' ').upper() for d in s.data):<26} {s.what}")
    return "\n".join(lines)


def plan_text(table, recipe, cfg, port_name, steps, listing_path=None):
    if getattr(recipe, "base", None) == "multi":
        return multi_text(table, recipe, cfg, port_name, steps, listing_path)
    n_msgs = sum(len(s.data) for s in steps)
    n_bytes = sum(len(d) for s in steps for d in s.data)
    secs = sum(s.wait_s for s in steps)
    own = recipe.resolve(table)
    lines = [f"Set up {recipe.name}: {recipe.about}",
             f"MIDI to port {port_name!r}, channel {cfg.channel}, edit buffer only (nothing is saved):",
             f"  1. {' | '.join(d.hex(' ').upper() for d in steps[0].data)}  {steps[0].what}",
             f"  2. {len(steps) - 1 - len(own)} parameters to their Init Patch values (NRPN: CC 99/98/6; "
             f"or one CC each)",
             "  3. the recipe's values:"]
    for p, value, why in own:
        lines.append(f"       {' | '.join(d.hex(' ').upper() for d in p.messages(cfg.channel, value)):<26} {why}")
    unset = unsettable_text(table)
    lines.append(f"{n_msgs} messages, {n_bytes} bytes, about {secs:.1f} s. "
                 f"MIDI can't set {unset}: they stay as in the base slot.")
    if listing_path:
        lines.append(f"Every message: {listing_path}")
    return "\n".join(lines)


def multi_text(table, recipe, cfg, port_name, steps, listing_path=None):
    from .recipes import RECIPES
    n_msgs = sum(len(s.data) for s in steps)
    lines = [f"Set up {recipe.name}: {recipe.about}",
             f"MIDI to port {port_name!r}, edit buffers only (nothing is saved); the zone and mode change live:"]
    for i, s in enumerate(steps[:3], 1):
        lines.append(f"  {i}. {' | '.join(d.hex(' ').upper() for d in s.data)}  {s.what}")
    k = 3
    for k, (name, ch, r) in enumerate((("Part A", cfg.part_a_channel, recipe.part_a),
                                       ("Part B", cfg.part_b_channel, recipe.part_b)), 4):
        base = cfg.mpe_base if RECIPES[r].base == "mpe" else cfg.plain_base
        vals = "; ".join(why for _, _, why in RECIPES[r].resolve(table))
        lines.append(f"  {k}. {name} on ch {ch}: select {base.upper()}, Init values, then {r}: {vals}")
    for i, st in enumerate(steps[-3:], k + 1):
        lines.append(f"  {i}. {' | '.join(d.hex(' ').upper() for d in st.data)}  {st.what}")
    lines.append(f"  Part channels from work/hwrig.toml: A = {cfg.part_a_channel}, B = {cfg.part_b_channel}. "
                 "They must match the Summit's Settings > MIDI CHANNEL (MIDI can't set them).")
    lines.append(f"{n_msgs} messages, about {sum(s.wait_s for s in steps):.1f} s. To leave: the Summit's Patch "
                 "button (Single mode); the zone stays until a power cycle or another MCM "
                 "(`hwrig run` restores both itself).")
    if listing_path:
        lines.append(f"Every message: {listing_path}")
    return "\n".join(lines)


def unsettable_text(table):
    names, fx = [], False
    for p in table.unsettable_sound_params():
        if p.msb in params.REJECTED_NRPN_MSB:
            fx = True
        else:
            names.append(f"{p.name} {p.offset:#05x}")
    return ", ".join(names + (["FX-matrix slots 5-8"] if fx else []))


def send(steps, port, sleep=time.sleep):
    for s in steps:
        for d in s.data:
            port.send(d)
        sleep(s.wait_s)
    sleep(SETTLE_S)
