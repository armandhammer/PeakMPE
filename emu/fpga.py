"""The MCU → FPGA bus, observed at the peripheral level (SPI1 + GPIOB).

Evidence (static, ``docs/findings/summit-2.2-build2121.md`` "The FPGA bus"):

* ``fpga_spi_write`` ``0x08012B24`` (the body of ``fpga_voice_write``
  ``0x08012B94``, which only wraps it in ``cpsid f``/``cpsie f``) selects an
  engine by pulling a GPIOB pin low through ``GPIOB_BSRR`` ``0x40020418``:
  PB7 (mask ``0x80``) for voices 0-7, PB6 (``0x40``) for voices 8-15, both
  (``0xC0``) for broadcasts in Single mode. Then it writes three 16-bit frames
  to ``SPI1_DR`` ``0x4001300C`` (``fpga_spi_tx16`` ``0x08012A84``), waits for
  ``SPI1_SR`` BSY to clear, and releases the pin.
* Frame 0 is ``(target & 0xF) << 12 | (param & 0xFFF)``, frames 1 and 2 are the
  high and low halves of the 32-bit value.
* ``fpga_mod_write`` ``0x08013FCC`` does not touch the bus: it appends
  ``{part_mask, target, param, value}`` to a 128-entry RAM queue
  (``0x20013EE4``, write index ``voice_state+0xBC``). ``fpga_queue_drain``
  ``0x08014458`` pops up to four entries per TIM6 interrupt (20 kHz) and sends
  each through the same ``fpga_spi_write``, with ``part_mask`` (if non-zero)
  overriding the chip-select byte ``0x20013328``.

So every value that reaches the FPGA, immediate or queued, crosses SPI1 with a
GPIOB chip select, and :class:`FpgaBus` decodes it from there. A patch that
writes the FPGA by any route through SPI1 is observed the same way.

The FPGA's answers are modelled minimally (:class:`VoiceStateModel`,
inferred): ``voice_alloc`` asks for the envelope state of each voice through
``fpga_read`` ``0x08012AB8`` (target 0x18, param 0x10, value 1; the frame-2
reply packs 2 bits per voice of the selected engine: 0 idle, 1/2 playing,
3 releasing; ``voice_env_poll`` ``0x08014D54``). The model derives those
states from the envelope commands the MCU sent. Every other read returns 0.

"Engine" is the chip-select line. That the Summit has two voice engines, one
per select line, is inferred (Summit = two Peak engines; one bitstream image).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional

SPI1_BASE = 0x40013000
SPI1_DR = SPI1_BASE + 0x0C
GPIOB_BSRR = 0x40020418
CS_ENGINE0 = 0x80  # PB7: voices 0-7 (Part A in Multi)
CS_ENGINE1 = 0x40  # PB6: voices 8-15 (Part B in Multi)
CS_MASK = CS_ENGINE0 | CS_ENGINE1

#: Names for the parameter numbers whose meaning is known from the MCU side.
#: (observed: which code sends them; meaning on the FPGA side is inferred.)
PARAM_NAMES: Dict[int, str] = {
    0x000: "vmod0",
    0x001: "vmod1",
    0x002: "vmod2",
    0x033: "p33",
    0x034: "p34",
    0x035: "vmod35",
    0x036: "vmod36",
    0x03F: "env1_cmd",
    0x040: "env1_gate",
    0x042: "env2_cmd",
    0x043: "env2_gate",
    0x045: "env3_cmd",
    0x046: "env3_gate",
    0x060: "modwheel",
    0x061: "aftertouch",
    0x062: "breath",
    0x063: "expression",
    0x066: "velocity",
    0x067: "pitch",
    0x068: "bend_up",
    0x069: "bend_down",
}
GATES = (0x40, 0x43, 0x46)
#: Envelope commands, sent by ``env_command`` 0x0801536C as
#: ``state | counter << 2``: state 0 at note-on, 3 at release (observed).
ENV_COMMANDS = (0x3F, 0x42, 0x45)
ENV_START, ENV_RELEASE = 0, 3

_BY_NAME = {v: k for k, v in PARAM_NAMES.items()}


def param_number(param) -> int:
    """Accept a parameter number or one of :data:`PARAM_NAMES`."""
    if isinstance(param, str):
        return _BY_NAME[param]
    return int(param)


def param_name(param: int) -> str:
    return PARAM_NAMES.get(param, f"p{param:03x}")


def _s32(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


@dataclass(frozen=True)
class FpgaEvent:
    """One SPI1 transaction to the FPGA, decoded.

    ``target`` follows ``fpga_voice_write``'s numbering: 0-15 is a voice (the
    frame's target nibble plus 8 for engine 1), 0x18-0x1F a broadcast/part
    target (nibble 8-15). With both engines selected and a voice nibble,
    ``voice`` is the nibble (0-7) and ``engines`` is ``"AB"``.
    """

    time_ms: float
    engines: str  # "A" (PB7), "B" (PB6) or "AB"
    target: int
    param: int
    value: int  # signed 32-bit
    frames: tuple
    read: bool = False  # the MCU read SPI1_DR during the transaction

    @property
    def voice(self) -> Optional[int]:
        return self.target if self.target < 0x10 else None

    @property
    def name(self) -> str:
        return param_name(self.param)

    @property
    def part(self) -> Optional[int]:
        """0 for engine A, 1 for engine B, None for both."""
        return {"A": 0, "B": 1}.get(self.engines)

    def __str__(self) -> str:
        tgt = f"v{self.target:<2d}" if self.target < 0x10 else f"{self.target:#04x}"
        rw = " (read)" if self.read else ""
        return f"{self.time_ms:9.3f} ms  fpga {self.engines:<2} {tgt:<4} {self.name:<11} {self.value}{rw}"


class VoiceStateModel:
    """Per-voice envelope state as the FPGA would report it (inferred).

    ``voice_alloc`` (through ``voice_candidates`` ``0x080155E4``) prefers a
    voice in state 3, then the quietest in state 1 or 2, then the newest in
    state 0, else voice 0 (observed). So 3 is release (and idle, at level 0)
    and 0 is the attack. The model reports: 3 for a voice that never played
    or got a release command (amp envelope ``0x3F`` with state 3); 0 for
    :attr:`attack_ms` after a start command (state 0), then 2. The real FPGA
    isn't emulated; patch envelope times are ignored.

    **Levels** (``voice_env_level``, the other reply words of the same
    reads): with :attr:`release_ms` None (the default) every level reads 0,
    so a released voice is at once as quiet as an idle one and ties go to the
    allocator's rotation order. With :attr:`release_ms` set, a voice reads
    :attr:`SOUNDING_LEVEL` from its start command until its release command,
    then falls linearly to 0 over *release_ms*: a release that ends, which
    the MPE patch's channel-reuse rule tells from idle by the level (above
    0x200 still sounds, as ``voice_candidates`` counts it). The level's scale
    on the FPGA is unknown; only "above 0x200" and "0" matter to the code
    that reads it (observed in ``voice_candidates``).
    """

    ATTACK, DECAY, SUSTAIN, RELEASE = 0, 1, 2, 3
    SOUNDING_LEVEL = 0x4000

    def __init__(self, attack_ms: float = 5.0, release_ms: Optional[float] = None):
        self.attack_ms = attack_ms
        self.release_ms = release_ms
        self.reset()

    def reset(self) -> None:
        self.state = [self.RELEASE] * 16
        self.started_at = [0.0] * 16
        #: when each voice got its release command; None: never started
        self.released_at: List[Optional[float]] = [None] * 16

    def command(self, voice: int, value: int, now: float) -> None:
        st = value & 3
        if st == 0:
            self.state[voice] = self.ATTACK
            self.started_at[voice] = now
            self.released_at[voice] = float("inf")
        elif st == 3:
            self.state[voice] = self.RELEASE
            if self.released_at[voice] is not None and self.released_at[voice] > now:
                self.released_at[voice] = now

    def states(self, now: float) -> List[int]:
        for v in range(16):
            if self.state[v] == self.ATTACK and now - self.started_at[v] >= self.attack_ms:
                self.state[v] = self.SUSTAIN
        return list(self.state)

    def level(self, voice: int, now: float) -> int:
        """The voice's level as the FPGA reports it (0-0xFFFF)."""
        rel = self.released_at[voice]
        if self.release_ms is None or rel is None:
            return 0
        if rel > now:
            return self.SOUNDING_LEVEL
        if self.release_ms <= 0:
            return 0
        left = 1.0 - (now - rel) / self.release_ms
        return int(self.SOUNDING_LEVEL * left) if left > 0 else 0

    def idle(self, voice: int, now: float) -> bool:
        """Released and at level 0 (or never played)."""
        return self.states(now)[voice] == self.RELEASE and self.level(voice, now) == 0

    def packed(self, engine: int, now: float) -> int:
        st = self.states(now)[engine * 8 : engine * 8 + 8]
        return sum((s & 3) << (2 * i) for i, s in enumerate(st))

    #: ``voice_env_poll`` ``0x08014D54`` reads value 1, 2, 0 in turn; reply
    #: word k of each read goes to these voices of the engine (observed), and
    #: word 2 of read 1 is the packed states.
    REPLY_VOICES = {1: (1, 0, None), 2: (4, 3, 2), 0: (7, 6, 5)}
    NEXT_READ = {1: 2, 2: 0, 0: 1}

    def reply(self, engine: int, select: int, word: int, now: float) -> int:
        v = self.REPLY_VOICES[select][word]
        if v is None:
            return self.packed(engine, now)
        return self.level(engine * 8 + v, now)


class FpgaBus:
    """Decode GPIOB chip selects plus SPI1 data frames into :class:`FpgaEvent`."""

    def __init__(self, clock: Callable[[], float], single_engine_cs: Optional[int] = None):
        self._clock = clock
        self.voices = VoiceStateModel()
        #: Chip-select line -> (engine name, engine index). The Summit has two
        #: engines (PB7 A, PB6 B); the Peak one, on PB6 (fpga_write 0x0800EBF0),
        #: reported as engine A, voices 0-7.
        if single_engine_cs is None:
            self._lines = {CS_ENGINE0: ("A", 0), CS_ENGINE1: ("B", 1), CS_MASK: ("AB", None)}
        else:
            self._lines = {single_engine_cs: ("A", 0)}
        #: The GPIOB lines that are FPGA chip selects (the Peak drives PB7 for
        #: something else and leaves it low).
        self._cs_mask = CS_MASK if single_engine_cs is None else single_engine_cs
        #: Last value written per (engines, target, param): the FPGA's
        #: register state as far as the MCU set it. Not cleared by reset().
        self.values: Dict[tuple, int] = {}
        self.events: List[FpgaEvent] = []
        self.malformed: List[tuple] = []
        self._cs = 0  # selected lines (active low on the pins)
        self._frames: List[int] = []
        self._read = False
        self._env_select = 1  # the next envelope read voice_env_poll makes

    def reset(self) -> None:
        self.events.clear()
        self.malformed.clear()
        self._cs = 0
        self._frames = []
        self._read = False

    # -- peripheral hooks (called by the board) --------------------------------

    def gpiob_bsrr(self, value: int) -> None:
        select = (value >> 16) & self._cs_mask
        release = value & self._cs_mask
        if select:
            if not self._cs:
                self._frames = []
                self._read = False
            self._cs |= select
        if release and self._cs:
            cs = self._cs
            self._cs &= ~release
            if not self._cs:
                self._finish(cs)

    def spi_write(self, value: int) -> None:
        if self._cs:
            self._frames.append(value & 0xFFFF)

    def spi_read(self) -> int:
        if not self._cs:
            return 0
        f = self._frames
        # The Peak's SPI routine (0x0800EB94) reads DR after every frame; only
        # a transfer that starts with the envelope request 0x8010 is a read.
        if self._cs_mask == CS_MASK or (f and f[0] == 0x8010):
            self._read = True
        if f and f[0] == 0x8010 and len(f) <= 3 and self._lines.get(self._cs, (None, None))[1] is not None:
            # The read's value (1, 2 or 0) is its third frame, so the
            # replies to the first two follow voice_env_poll's order; the
            # third frame resyncs it.
            engine = self._lines[self._cs][1]
            if len(f) == 3:
                select = f[2] if f[2] in self.voices.REPLY_VOICES else None
                if select is None:
                    return 0
                self._env_select = self.voices.NEXT_READ[select]
            else:
                select = self._env_select
            return self.voices.reply(engine, select, len(f) - 1, self._clock())
        return 0

    # -- decoding ---------------------------------------------------------------

    def _finish(self, cs: int) -> None:
        frames = tuple(self._frames)
        self._frames = []
        if len(frames) != 3:
            if frames:
                self.malformed.append((self._clock(), cs, frames))
            return
        w0, hi, lo = frames
        nibble, param = w0 >> 12, w0 & 0xFFF
        if cs & CS_MASK not in self._lines:
            self.malformed.append((self._clock(), cs, frames))
            return
        engines = self._lines[cs & CS_MASK][0]
        if nibble >= 8:
            target = 0x10 | nibble
        elif engines == "B":
            target = 8 + nibble
        else:
            target = nibble
        event = FpgaEvent(self._clock(), engines, target, param, _s32(hi << 16 | lo), frames, self._read)
        self.events.append(event)
        if not self._read:
            self.values[(engines, target, param)] = event.value
        if param == ENV_COMMANDS[0] and not self._read and target < 0x10 and engines != "AB":
            self.voices.command(target, event.value, event.time_ms)


def filter_events(
    events: Iterable[FpgaEvent],
    voice: Optional[int] = None,
    part: Optional[int] = None,
    param=None,
    target: Optional[int] = None,
    since_ms: Optional[float] = None,
    include_reads: bool = False,
) -> List[FpgaEvent]:
    """Select events. ``param`` may be a number, a name, or a collection of
    either. ``part`` selects by engine (0 = A/PB7, 1 = B/PB6); broadcasts to
    both engines match either part."""
    params = None
    if param is not None:
        if isinstance(param, (str, int)):
            params = {param_number(param)}
        else:
            params = {param_number(p) for p in param}
    out = []
    for e in events:
        if e.read and not include_reads:
            continue
        if voice is not None and e.voice != voice:
            continue
        if target is not None and e.target != target:
            continue
        if part is not None and e.part not in (part, None):
            continue
        if params is not None and e.param not in params:
            continue
        if since_ms is not None and e.time_ms < since_ms:
            continue
        out.append(e)
    return out
