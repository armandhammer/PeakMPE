"""Test sounds, built over MIDI in the Summit's edit buffer (docs/hw-test-rig.md).

A recipe is a base slot (which supplies the MPE flag, the one sound setting
MIDI can't reach) plus parameter values. `setup` sends the Init Patch value
of every settable sound parameter first, then the recipe's values, so the
result doesn't depend on what else is in the base slot. Nothing is saved:
selecting the slot again restores it.

Values are given by name and checked against the firmware's own tables
(params.Table), so a wrong offset or another build fails before anything is
sent.
"""
from dataclasses import dataclass, field

# Matrix depth is bipolar: 64 = 0 (descriptor display type 3, as BendRange).
DEPTH_ZERO = 64


@dataclass
class Recipe:
    name: str
    base: str            # "mpe" or "plain": the config's base slot
    about: str
    values: dict = field(default_factory=dict)       # (offset, param name) -> value
    matrix: list = field(default_factory=list)       # [(slot 1-16, source, depth -64..63, dest)]

    def resolve(self, table):
        """[(Param, value, why)] of the recipe's own changes, checked."""
        out = []
        for (offset, pname), value in self.values.items():
            p = table.param(offset, pname)
            label = value
            if isinstance(value, str):
                names = table.waves if pname == "Wave" else table.modes if pname == "Mode" else None
                if names is None:
                    raise ValueError(f"{pname}: give a number")
                value = table.index(names, value, pname)
                label = f"{label} ({value})"
            out.append((p, value, f"{pname} = {label}"))
        for slot, source, depth, dest in self.matrix:
            if not 1 <= slot <= 16 or not -64 <= depth <= 63:
                raise ValueError(f"matrix slot {slot} depth {depth}")
            base = 0x0FC + 4 * (slot - 1)
            out += [
                (table.param(base, "SourceA"), table.index(table.sources, source, "matrix source"),
                 f"slot {slot} source A = {source}"),
                (table.param(base + 1, "SourceB"), 0, f"slot {slot} source B = Direct"),
                (table.param(base + 2, "Depth"), DEPTH_ZERO + depth, f"slot {slot} depth {depth:+d}"),
                (table.param(base + 3, "Destin"), table.index(table.dests, dest, "matrix destination"),
                 f"slot {slot} destination = {dest}"),
            ]
        return out


# The common clean voice: Init Patch (one saw osc, filter fully open, no FX,
# no LFO amounts, poly) with a sine, a fast amp envelope and no velocity.
SINE = {
    (0x038, "Wave"): "Sine",
    (0x092, "AmpAttack"): 0,
    (0x093, "AmpDecay"): 0,
    (0x094, "AmpSustain"): 127,
    (0x095, "AmpRelease"): 0,
    (0x096, "Velocity"): 64,   # amp velocity amount 0 (bipolar, 64 = 0)
}

@dataclass
class MultiRecipe:
    """Multi mode with one recipe per part (docs/hw-test-rig.md#m1).

    The Settings Part channels are globals and can't be set over MIDI, so
    the config names them (Summit defaults: Part A 2, Part B 3). Both lie in
    the Lower Zone's member channels, so the setup first moves the zone:
    MCM (RPN 6) 0 on channel 1 removes the Lower Zone, MCM n on 16 makes
    an Upper Zone of n members (16 master, 15 down to 16 - n). Then NRPN
    62:0 = 1 on the global channel selects Multi, and each part gets its
    base slot (program change on its Part channel) and its sound."""
    name: str
    about: str
    part_a: str        # recipe name for Part A
    part_b: str        # recipe name for Part B
    zone: str = "upper"   # the zone Part A gets: "upper" (master 16) or "lower" (master 1)
    members: int = 7
    base = "multi"

    def zone_channels(self):
        """(master, member channels) of the zone this recipe sets up."""
        if self.zone == "upper":
            return 16, list(range(16 - self.members, 16))
        return 1, list(range(2, 2 + self.members))


RECIPES = {r.name: r for r in [
    Recipe("p1", "mpe", "P1 sine: one sine, filter open, no FX/LFO, fast envelope", dict(SINE)),
    Recipe("p2", "mpe", "P2 pressure -> pitch: P1, AftTouch -> Osc1 pitch", dict(SINE),
           [(1, "AftTouch", 16, "Osc1Ptch")]),
    Recipe("p3", "mpe", "P3 slide -> pitch: P1, ModWheel (Slide) -> Osc1 pitch", dict(SINE),
           [(1, "ModWheel", 16, "Osc1Ptch")]),
    Recipe("p4", "mpe", "P4 pressure -> level: P1 at half level, AftTouch -> Osc1 level",
           {**SINE, (0x06F, "Osc1Level"): 64}, [(1, "AftTouch", 32, "Osc1 Lev")]),
    Recipe("p5", "plain", "P5 sine, MPE off: P1 on the MPE-off base slot", dict(SINE)),
    Recipe("p5o", "plain", "P5 an octave up (O1Range 4'): Multi's Part B, told apart from Part A by pitch",
           {**SINE, (0x030, "O1Range"): 65}),
    Recipe("p6", "mpe", "P6 sine mono legato: P1 in MonoLG mode, no glide",
           {**SINE, (0x022, "Mode"): "MonoLG", (0x027, "GlideTime"): 0}),
    Recipe("p7", "mpe", "P7 sine, Diverge 127, release 64: voices told apart by pitch (voice rotation, F1)",
           {**SINE, (0x02B, "Diverge"): 127, (0x095, "AmpRelease"): 64}),
    MultiRecipe("m1", "M1 Multi: Part A = P1 (MPE, Upper Zone 9-15 + master 16), Part B = P5 an octave up "
                "(MPE off, its Part channel)", "p1", "p5o"),
    MultiRecipe("f5", "F5 Multi: as M1, but Part A on a Lower Zone 2-4 whose master is the global channel 1",
                "p1", "p5o", zone="lower", members=3),
]}
