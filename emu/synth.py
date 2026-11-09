"""A simulated Summit: MIDI in, the real firmware in the middle, FPGA writes and MIDI out.

    from emu.synth import SimulatedSummit
    s = SimulatedSummit()                 # stock 2.2, or SimulatedSummit("work/patched/x.syx")
    s.midi_in("90 3C 64")                 # DIN by default; port="usb" for USB
    s.tick(5)                             # run 5 ms of firmware time
    s.fpga_events(voice=0, param="pitch")
    s.voices()                            # active voices, notes, pitch, aftertouch
    s.midi_out()                          # what the Summit sent on DIN and USB

What runs is the firmware's own ``main``: the reset path, main's
initialisation and then its endless main loop, preempted by the TIM6
interrupt (20 kHz, the 1 kHz modulation tick and the FPGA queue drain) and the
USART6 interrupt (DIN MIDI). :mod:`emu.board` has the time model and the
peripheral models; this module adds the MIDI ports, state views and settings.

**Observed at the peripheral level:** FPGA writes (SPI1 + GPIOB chip
selects), DIN MIDI in and out (USART6 data register and interrupt), the
DataFlash (SPI4), the display (SPI2) and the panel buttons and encoder (the
GPIO shift-register chain): ``screen_text()``, ``screenshot()``, ``press()``,
``turn()``.

**USB is modelled at the endpoint buffers, not the OTG core** (a fallback;
the OTG peripheral and its interrupt aren't emulated):

* *in:* bytes are packed into USB-MIDI packets (cable 0) and written to the
  OUT endpoint buffer (``0x2000427C``: buffer, size, received count ``+6``,
  read index ``+8``, state ``+0xB``), the way the OTG receive interrupt leaves
  them. The main loop (``usb_out_poll`` ``0x08021168``) then hands them to
  ``usb_midi_rx`` ``0x08021100``, as on the hardware.
* *out:* when the firmware starts an IN transfer (endpoint struct
  ``0x20004288`` state ``+0xB`` = 2), the buffer contents are taken as sent
  and the state goes back to 0 (transfer complete).
* *attach:* :meth:`SimulatedSummit.__init__` marks the device configured
  (``0x20013045`` = 1, IN state 0), as enumeration would.

The first boot formats the blank DataFlash with the firmware's own factory
initialise (about 25 s); the result is cached in ``work/cache/dataflash/``
(never committed, see :mod:`emu.cache`) per image hash and simulator source
hash, and later boots take a few seconds.
"""

from __future__ import annotations

import collections
import hashlib
import pickle
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence, Tuple, Union

from unicorn.arm_const import UC_ARM_REG_PC

from . import cache as cache_mod
from . import screen as screen_mod
from .board import MAIN_LOOP_HEAD, Board
from .panel import ButtonRef, detent_phases
from .firmware import REPO_ROOT, SUMMIT_2_2, load_image
from .fpga import FpgaEvent, filter_events, param_number

#: Part of the DataFlash cache key (emu.cache), as is the hash of emu/*.py. Bump when a board-model change could change what the factory initialise
#: writes, so stale DataFlash caches are ignored.
CACHE_VERSION = 2

# RAM addresses (build 2121; docs/symbols/summit-2.2-2121.csv).
VOICE_STATE = 0x200057D8
VOICE_ACTIVE = VOICE_STATE + 0x334
VOICE_AT = VOICE_STATE + 0xE4
VOICE_AT_SMOOTH = VOICE_STATE + 0x104
VOICE_NOTE = 0x20014950
VOICE_PITCH = 0x200149A8
PARTS, PART_SIZE = 0x20013388, 0x288
PATCHES, PATCH_SIZE = 0x200138A0, 0x201
GLOBALS = 0x200161A4
MULTI_MODE = 0x20004B20
MIDI_CHANNELS = 0x20004B2A  # global, Part A, Part B (0-based)
MODE_REQUEST = 0x20004B38
DIN_RING = 0x200050CC
SOFT_THRU = DIN_RING + 0x205

USB_CONFIGURED = 0x20013045
USB_EP_IN = 0x20004288
USB_EP_OUT = 0x2000427C
USB_OUT_POLL = (0x08021168, 0x080211D4)  # usb_out_poll: reads the OUT endpoint's counts

#: USB-MIDI code index number → data bytes (USB-MIDI 1.0 table 4-1).
CIN_LENGTH = {0x5: 1, 0x6: 2, 0x7: 3, 0x8: 3, 0x9: 3, 0xA: 3, 0xB: 3, 0xC: 2, 0xD: 2, 0xE: 3, 0xF: 1, 0x2: 2, 0x3: 3, 0x4: 3}

MidiBytes = Union[bytes, bytearray, Sequence[int], str]


def to_bytes(data: MidiBytes) -> bytes:
    """bytes, a list of ints, or hex text such as ``"90 3C 64"``."""
    if isinstance(data, str):
        return bytes.fromhex(data.replace(",", " "))
    return bytes(data)


def split_messages(stream: Iterable[int]) -> List[bytes]:
    """Split a MIDI byte stream into messages (running status expanded)."""
    return [m for _t, m in split_timed((0.0, b) for b in stream)]


def split_timed(stream: Iterable[Tuple[float, int]]) -> List[Tuple[float, bytes]]:
    """Like :func:`split_messages` for ``(time, byte)`` pairs; a message's
    time is that of its last byte."""
    out: List[Tuple[float, bytes]] = []
    status = None
    cur: List[int] = []
    need = 0
    sysex = False
    for t, b in stream:
        if b >= 0xF8:
            out.append((t, bytes([b])))
            continue
        if b == 0xF0:
            sysex, cur = True, [b]
            continue
        if sysex:
            if b & 0x80 and b != 0xF7:
                sysex = False  # unterminated SysEx; fall through to the new status
            else:
                cur.append(b)
                if b == 0xF7:
                    out.append((t, bytes(cur)))
                    sysex, cur = False, []
                continue
        if b & 0x80:
            if b >= 0xF0:
                status = None
                need = {0xF1: 1, 0xF2: 2, 0xF3: 1}.get(b, 0)
                if need == 0:
                    out.append((t, bytes([b])))
                    cur = []
                else:
                    cur = [b]
                continue
            status = b
            need = 1 if b & 0xE0 == 0xC0 else 2
            cur = [b]
            continue
        if not cur:
            if status is None:
                continue
            cur = [status]
        cur.append(b)
        if len(cur) == need + 1:
            out.append((t, bytes(cur)))
            cur = []
    return out


def usb_packets(data: bytes, cable: int = 0) -> List[bytes]:
    """Pack a byte stream of complete messages into 4-byte USB-MIDI packets."""
    packets = []
    for msg in split_messages(data):
        if msg[0] == 0xF0:
            body = msg
            for i in range(0, len(body), 3):
                chunk = body[i : i + 3]
                if i + 3 >= len(body):
                    cin = {1: 0x5, 2: 0x6, 3: 0x7}[len(chunk)]
                else:
                    cin = 0x4
                packets.append(bytes([cable << 4 | cin]) + chunk.ljust(3, b"\0"))
        elif msg[0] >= 0xF0:
            cin = {1: 0xF if msg[0] >= 0xF8 or msg[0] == 0xF6 else 0x5, 2: 0x2, 3: 0x3}[len(msg)]
            packets.append(bytes([cable << 4 | cin]) + msg.ljust(3, b"\0"))
        else:
            packets.append(bytes([cable << 4 | msg[0] >> 4]) + msg.ljust(3, b"\0"))
    return packets


@dataclass(frozen=True)
class MidiOut:
    time_ms: float
    port: str  # "din" or "usb"
    data: bytes

    def __str__(self) -> str:
        return f"{self.time_ms:9.3f} ms  {self.port:<4} out {self.data.hex(' ').upper()}"


@dataclass(frozen=True)
class Voice:
    index: int
    active: bool
    note: int
    pitch: int  # voice_pitch, 8.8 semitones
    aftertouch: int  # voice_state+0xE4 slot (u16)
    aftertouch_smoothed: int


class SimulatedSummit:
    """See the module docstring. Channels in this API are 1-16."""

    def __init__(
        self,
        image: Union[None, bytes, str, Path] = None,
        *,
        cache: bool = True,
        settle_ms: float = 300,
        flash_from: Union[None, bytes, str, Path] = None,
    ):
        """*flash_from*: take the DataFlash formatted by another image (e.g.
        stock for a patched image), which saves the 25 s format when the
        patch doesn't change the factory initialise or the Init Patch.
        *cache* False formats it afresh instead of using ``work/cache/``."""
        self.image = _load(image)
        self.board = Board(self.image)
        self._usb_in: collections.deque = collections.deque()
        self._usb_out: List[Tuple[float, int]] = []  # (time_ms, byte) from IN packets
        #: Where in each ms the USB host's frame starts, µs (a multiple of
        #: 50). A real host's frames aren't locked to the Summit's timer;
        #: tests sweep this to try every phase of USB input against the tick.
        self.usb_phase_us = 0
        self.board.slot_hooks.append(self._usb_slot)
        self._usb_due = False
        # Every boot starts from a DataFlash formatted by the factory
        # initialise of *flash_from* (default: this image), so a cold cache
        # and a warm one boot the same way.
        source = self.image if flash_from is None else _load(flash_from)
        if cache and cache_mod.enabled():
            formatted = pickle.loads(_formatted_dataflash(source))
        else:
            formatted = _format(source)
        self.board.flash[11].restore(formatted)
        self.board.power_on(max_ms=20_000)
        self._usb_attach()
        self.board.run_ms(settle_ms)
        self.clear()
        self._ready = self.board.save_state()

    # -- lifecycle --------------------------------------------------------------

    def reset(self) -> None:
        """Back to the state right after construction (booted, settled, idle),
        with USB frames on the ms boundary again."""
        self.board.load_state(self._ready)
        self._usb_due = False
        self.board.fpga.voices.release_ms = None
        self.usb_phase_us = 0
        self.set_timing()
        self._usb_in.clear()
        self.clear()

    def power_cycle(self, settle_ms: float = 300, before_boot: Optional[Callable[[Board], None]] = None) -> None:
        """Switch off and on again: a new board boots the same image from
        this one's DataFlash (settings, patches, multis); RAM, FPGA and MIDI
        state start afresh. :meth:`reset` then returns to this new boot.

        *before_boot(board)* runs on the new board before it starts, e.g. to
        fill RAM the way a real power-up leaves it, or to queue MIDI that
        arrives while the firmware starts (``board.din.rx_queue``)."""
        flash = self.board.flash[11].snapshot()
        self.board = Board(self.image)
        self.board.slot_hooks.append(self._usb_slot)
        self._usb_due = False
        self._usb_in.clear()
        self.board.flash[11].restore(flash)
        if before_boot:
            before_boot(self.board)
        self.board.power_on(max_ms=20_000)
        self._usb_attach()
        self.board.run_ms(settle_ms)
        self.clear()
        self._ready = self.board.save_state()

    @property
    def release_ms(self) -> Optional[float]:
        """How long the modelled FPGA takes to end a release (its envelope
        level falling to 0), ms. None (the default, and after :meth:`reset`):
        every level reads 0, so a released voice is at once idle to the
        firmware. Inferred model (``emu.fpga.VoiceStateModel``)."""
        return self.board.fpga.voices.release_ms

    @release_ms.setter
    def release_ms(self, ms: Optional[float]) -> None:
        self.board.fpga.voices.release_ms = ms

    def set_timing(self, cpu_scale: float = 1.0, spi_cost: bool = False) -> None:
        """How fast the main thread runs against the timer (emu.board).

        The default (also after :meth:`reset`) is the old model: one
        instruction per cycle and free SPI transfers. *spi_cost* charges
        each SPI1 frame its wire time (15 MHz, from the firmware's SPI1
        set-up); *cpu_scale* is the main thread's instructions per cycle.
        The synth runs from flash with the ART accelerator off
        (``FLASH_ACR`` = 3, ``0x0801141C``); about 0.3 with *spi_cost*
        reproduces what MPE v1.1 did on the synth (inferred, from one
        observation: docs/mpe-design.md#slide-v12)."""
        from .board import SPI1_FRAME_CYCLES

        self.board.cpu_scale = cpu_scale
        self.board.spi1_frame_cycles = SPI1_FRAME_CYCLES if spi_cost else 0

    def voice_idle(self, voice: int) -> bool:
        """The modelled FPGA reports the voice released and at level 0."""
        return self.board.fpga.voices.idle(voice, self.time_ms)

    def clear(self) -> None:
        """Forget recorded FPGA events and MIDI output (state is kept)."""
        self.board.fpga.reset()
        self.board.din.tx_log.clear()
        self._usb_out.clear()

    @property
    def time_ms(self) -> float:
        return self.board.time_us / 1000.0

    def tick(self, ms: float = 1) -> None:
        """Run the firmware for *ms* milliseconds (one modulation tick per ms)."""
        self.board.run_ms(ms)

    run = tick

    # -- MIDI in ------------------------------------------------------------------

    def midi_in(self, data: MidiBytes, port: str = "din", run_ms: float = 0) -> None:
        """Send bytes to the Summit, then optionally run for *run_ms*.

        ``din``: the bytes arrive at USART6 one per 320 µs (31250 baud), each
        raising the receive interrupt. ``usb``: the bytes are packed into
        USB-MIDI packets and delivered 16 per USB frame (1 ms).
        """
        data = to_bytes(data)
        if port == "din":
            for b in data:
                self.board.din.rx_queue.append((self.board.time_us, b))
        elif port == "usb":
            self._usb_in.extend(usb_packets(data))
        else:
            raise ValueError(f"port must be 'din' or 'usb', not {port!r}")
        if run_ms:
            self.tick(run_ms)

    def note_on(self, note: int, velocity: int = 100, channel: int = 1, **kw) -> None:
        self.midi_in([0x90 | (channel - 1), note, velocity], **kw)

    def note_off(self, note: int, velocity: int = 0, channel: int = 1, **kw) -> None:
        self.midi_in([0x80 | (channel - 1), note, velocity], **kw)

    def cc(self, controller: int, value: int, channel: int = 1, **kw) -> None:
        self.midi_in([0xB0 | (channel - 1), controller, value], **kw)

    def nrpn(self, msb: int, lsb: int, value: int, channel: int = 1, **kw) -> None:
        ch = 0xB0 | (channel - 1)
        self.midi_in([ch, 99, msb, ch, 98, lsb, ch, 6, value], **kw)

    def bend(self, value: int, channel: int = 1, **kw) -> None:
        """Pitch bend, -8192..8191."""
        v = max(-8192, min(8191, value)) + 8192
        self.midi_in([0xE0 | (channel - 1), v & 0x7F, v >> 7], **kw)

    def channel_pressure(self, value: int, channel: int = 1, **kw) -> None:
        self.midi_in([0xD0 | (channel - 1), value], **kw)

    def poly_pressure(self, note: int, value: int, channel: int = 1, **kw) -> None:
        self.midi_in([0xA0 | (channel - 1), note, value], **kw)

    # -- outputs ----------------------------------------------------------------

    def fpga_events(self, voice=None, part=None, param=None, target=None, since_ms=None, include_reads=False) -> List[FpgaEvent]:
        """Decoded FPGA writes since the last :meth:`clear`; see
        :func:`emu.fpga.filter_events` for the filters."""
        return filter_events(self.board.fpga.events, voice, part, param, target, since_ms, include_reads)

    def fpga_state(self) -> dict:
        """Last value written per ``(engines, target, param)``, since boot."""
        return dict(self.board.fpga.values)

    def last_value(self, voice=None, param=None, target=None) -> Optional[int]:
        ev = self.fpga_events(voice=voice, param=param, target=target)
        return ev[-1].value if ev else None

    def midi_out(self, port: Optional[str] = None) -> List[MidiOut]:
        """Messages the Summit sent since the last :meth:`clear`, by time."""
        out: List[MidiOut] = []
        if port in (None, "din"):
            out.extend(MidiOut(t, "din", m) for t, m in split_timed(self.board.din.tx_log))
        if port in (None, "usb"):
            out.extend(MidiOut(t, "usb", m) for t, m in split_timed(self._usb_out))
        return sorted(out, key=lambda m: m.time_ms)

    # -- state views ------------------------------------------------------------

    def voices(self, active_only: bool = False) -> List[Voice]:
        b = self.board
        active = b.read(VOICE_ACTIVE, 16)
        notes = b.read(VOICE_NOTE, 16)
        pitch = struct.unpack("<16H", b.read(VOICE_PITCH, 32))
        at = struct.unpack("<16H", b.read(VOICE_AT, 32))
        ats = struct.unpack("<16I", b.read(VOICE_AT_SMOOTH, 64))
        vs = [Voice(v, bool(active[v]), notes[v], pitch[v], at[v], ats[v]) for v in range(16)]
        return [v for v in vs if v.active] if active_only else vs

    def active_voices(self) -> List[int]:
        return [v.index for v in self.voices(active_only=True)]

    def voice_note(self, voice: int) -> int:
        return self.board.u8(VOICE_NOTE + voice)

    def voice_pitch(self, voice: int) -> int:
        return struct.unpack("<H", self.board.read(VOICE_PITCH + 2 * voice, 2))[0]

    def voice_aftertouch(self, voice: int) -> int:
        return struct.unpack("<H", self.board.read(VOICE_AT + 2 * voice, 2))[0]

    def part_bend(self, part: int = 0) -> int:
        """Signed bend stored by ``bend_store`` at ``part+4``."""
        return struct.unpack("<h", self.board.read(PARTS + part * PART_SIZE + 4, 2))[0]

    def part_modwheel(self, part: int = 0) -> int:
        return self.board.u8(PARTS + part * PART_SIZE + 6)

    def patch_byte(self, offset: int, part: int = 0) -> int:
        multi = 1 if self.multi_mode else 0
        return self.board.u8(PATCHES + (multi + part) * PATCH_SIZE + offset)

    def to_pass_start(self) -> None:
        """Run until the main loop starts a pass (MAIN_LOOP_HEAD). The
        firmware changes patch and settings bytes from the main loop, never
        in the middle of its own pass (mod_tick runs in the main loop);
        between two simulator slots a RAM write can land anywhere, so tests
        that measure a single tick poke from here."""
        from unicorn import UC_HOOK_CODE

        uc = self.board.uc
        hit = []
        hook = uc.hook_add(UC_HOOK_CODE, lambda uc, addr, size, user: (hit.append(addr), uc.emu_stop()),
                           begin=MAIN_LOOP_HEAD, end=MAIN_LOOP_HEAD)
        try:
            while not hit:
                self.board._slot()
        finally:
            uc.hook_del(hook)

    def set_patch_byte(self, offset: int, value: int, part: int = 0) -> None:
        """Poke the current patch in RAM (e.g. ``+0x23`` unison, ``+0x22``
        voice mode). Not saved and not sent to the FPGA by itself."""
        multi = 1 if self.multi_mode else 0
        self.board.write(PATCHES + (multi + part) * PATCH_SIZE + offset, bytes([value]))

    # -- settings ---------------------------------------------------------------

    @property
    def multi_mode(self) -> bool:
        return self.board.u8(MULTI_MODE) != 0

    @property
    def channels(self) -> Tuple[int, int, int]:
        """(global, Part A, Part B) as the MIDI path uses them, 1-16."""
        g, a, b = self.board.read(MIDI_CHANNELS, 3)
        return g + 1, a + 1, b + 1

    def global_setting(self, offset: int) -> int:
        return self.board.u8(GLOBALS + offset)

    def set_global(self, offset: int, value: int, run_ms: float = 2) -> None:
        """Write one byte of ``globals`` (as a Settings edit would) and let
        the main loop apply it (``globals_apply_poll``)."""
        self.board.write(GLOBALS + offset, bytes([value]))
        if run_ms:
            self.tick(run_ms)

    def set_channels(self, global_: Optional[int] = None, part_a: Optional[int] = None, part_b: Optional[int] = None, run_ms: float = 2) -> None:
        """Set MIDI channels (1-16) through ``globals`` +0x11/+0x2B/+0x2C.
        The firmware sends CC 120 and all-notes-off on a change."""
        for off, ch in ((0x11, global_), (0x2B, part_a), (0x2C, part_b)):
            if ch is not None:
                self.board.write(GLOBALS + off, bytes([ch - 1]))
        if run_ms:
            self.tick(run_ms)

    def set_mode(self, mode: str, run_ms: float = 5) -> None:
        """``"single"`` or ``"multi"``, through ``mode_request`` (the path
        NRPN 62:0 takes)."""
        value = {"single": 0, "multi": 1}[mode]
        self.board.write(MODE_REQUEST, bytes([0x80 | value]))
        if run_ms:
            self.tick(run_ms)

    def set_soft_thru(self, on: bool) -> None:
        self.board.write(SOFT_THRU, bytes([1 if on else 0]))

    def set_cc_nrpn_receive(self, on: bool = True) -> None:
        """Global ``CC/NRPN`` receive bit (``globals+0x14`` bit 0)."""
        v = self.global_setting(0x14)
        self.set_global(0x14, (v | 1) if on else (v & ~1))

    # -- display and front panel --------------------------------------------
    #
    # The display and the panel are peripheral models (emu.display, emu.panel):
    # the firmware's own scan reads the buttons and the encoder, and what it
    # sends to the OLED is what these methods show. See docs/SIMULATOR.md.

    def screen_text(self) -> List[str]:
        """The four display rows, 20 characters each (see ``emu.display.char_text``)."""
        return self.board.display.lcd.text()

    def boot_screen(self) -> List[str]:
        """The rows as ``boot_screen`` left them, before its FPGA upload."""
        return list(self.board.display.snapshots.get("boot", []))

    @property
    def display_on(self) -> bool:
        return self.board.display.on

    def screen_dump(self, title: Optional[str] = None) -> str:
        """The rows in a frame, for printing."""
        return screen_mod.dump(self.screen_text(), title, self.display_on)

    def screenshot(self, path: Union[str, Path], scale: int = 4) -> Path:
        """Write a PNG of the display (dot matrix; see emu.screen)."""
        return screen_mod.screenshot(self.board.display.lcd, path, scale, self.display_on)

    def hold(self, button: ButtonRef) -> None:
        """Hold a button down (name from ``emu.panel.BUTTONS`` or id 0-69)."""
        self.board.panel.set_button(button, True)

    def release(self, button: ButtonRef) -> None:
        self.board.panel.set_button(button, False)

    def press(self, button: ButtonRef, hold_ms: float = 40, after_ms: float = 60) -> None:
        """Press and release a button, then run *after_ms*.

        The firmware debounces in 10 ms steps (``panel_buttons_poll``), so a
        press needs about 20 ms; 40 ms is safe."""
        self.hold(button)
        self.tick(hold_ms)
        self.release(button)
        self.tick(after_ms)

    def turn(self, steps: int, detent_ms: float = 32, after_ms: float = 40) -> None:
        """Turn the encoder by *steps* detents (positive = the value goes up).

        Each detent is two phase changes 2 ms apart (the scan samples at 1 kHz),
        and detents are *detent_ms* apart: at 30 ms or more each one is a
        delta of 1; faster turns are accelerated by ``encoder_poll``."""
        panel = self.board.panel
        for _ in range(abs(steps)):
            for phase in detent_phases(panel.encoder_phase, steps > 0):
                panel.encoder_phase = phase
                self.tick(2)
            self.tick(max(detent_ms - 4, 0))
        self.tick(after_ms)

    # -- USB endpoint model ---------------------------------------------------

    def _usb_attach(self) -> None:
        b = self.board
        b.write(USB_CONFIGURED, b"\x01")
        b.write(USB_EP_IN + 0x0B, b"\x00")

    def _usb_slot(self, board: Board) -> None:
        # IN (Summit → host): a started transfer completes within the slot.
        if board.u8(USB_EP_IN + 0x0B) == 2:
            buf = board.u32(USB_EP_IN)
            n = struct.unpack("<H", board.read(USB_EP_IN + 6, 2))[0]
            data = board.read(buf, n) if n else b""
            for i in range(0, len(data) - 3, 4):
                pkt = data[i : i + 4]
                for byte in pkt[1 : 1 + CIN_LENGTH.get(pkt[0] & 0xF, 0)]:
                    self._usb_out.append((board.time_us / 1000.0, byte))
            board.write(USB_EP_IN + 0x0B, b"\x00")
        # OUT (host → Summit): one buffer of up to 16 packets per 1 ms frame.
        if self._usb_in and (board.time_us - self.usb_phase_us) % 1000 == 0:
            self._usb_due = True
        if self._usb_due:
            # Not while the main thread is inside usb_out_poll: it loads the
            # received count (0x08021170) and the read index (0x08021172)
            # separately, so a buffer written between the two loads replays
            # the old buffer's later packets. The frame waits one slot. How
            # the synth's OTG interrupt orders these writes is unknown.
            pc = board.uc.reg_read(UC_ARM_REG_PC)
            if USB_OUT_POLL[0] <= pc < USB_OUT_POLL[1]:
                return
            self._usb_due = False
            rx, rd = struct.unpack("<HH", board.read(USB_EP_OUT + 6, 4))
            if rx == rd:
                buf = board.u32(USB_EP_OUT)
                size = struct.unpack("<H", board.read(USB_EP_OUT + 4, 2))[0]
                chunk = b""
                while self._usb_in and len(chunk) + 4 <= size:
                    chunk += self._usb_in.popleft()
                board.write(buf, chunk)
                board.write(USB_EP_OUT + 6, struct.pack("<HH", len(chunk), 0))
                board.write(USB_EP_OUT + 0x0B, b"\x00")


def _dataflash_entry(image: bytes) -> Path:
    return cache_mod.path("dataflash", cache_mod.key(
        "dataflash", str(CACHE_VERSION), hashlib.sha256(image).hexdigest(), cache_mod.emu_sources_hash()), ".pickle")


def _format(image: bytes):
    """The DataFlash snapshot after *image*'s factory initialise (uncached)."""
    board = Board(image)
    board.power_on(max_ms=20_000)
    return board.flash[11].snapshot()


def _formatted_dataflash(image: bytes) -> bytes:
    """Pickled DataFlash snapshot formatted by *image*, from the cache or made now."""
    entry = _dataflash_entry(image)
    with cache_mod.locked(entry):
        data = cache_mod.read(entry)
        if data is None:
            data = pickle.dumps(_format(image))
            cache_mod.write(entry, data)
        return data


def _load(image) -> bytes:
    if image is None:
        data = load_image(SUMMIT_2_2)
        if data is None:
            raise FileNotFoundError(f"firmware/{SUMMIT_2_2} not present (run scripts/fetch-firmware.sh)")
        return data
    if isinstance(image, (bytes, bytearray)):
        return bytes(image)
    path = Path(image)
    raw = path.read_bytes()
    if path.suffix.lower() == ".syx":
        from .firmware import _syx_module

        _header, data = _syx_module().decode(raw)
        return data
    return raw
