"""The front-panel button chain and the encoder, at the peripheral level (GPIO).

Evidence (static, ``docs/findings/summit-2.2-build2121.md`` "Display and
front panel"):

* ``panel_scan`` ``0x080115E4`` runs in the TIM6 interrupt once per ms. It
  pulses PB2 low (``panel_load`` ``0x080110DC``: the parallel load of a chain
  of shift registers, inferred 74HC165-style), then for each of 7 words and
  16 bits: reads ``GPIOC_IDR`` ``0x40020810`` bit 11 (inverted: a pressed
  input reads 0), drives the next LED bit on PC12 (``GPIOC_BSRR``
  ``0x40020818``), and pulses PC10 (``panel_clock`` ``0x080110C0``). Then it
  pulses PA15 (``panel_latch`` ``0x080110F8``, the LED registers' latch).
  The words land at ``panel_inputs`` ``0x20013318``: bit *j* of word *r* is
  the input clocked out *16r + j* clocks after the load.
* ``panel_buttons_poll`` ``0x080111FC`` (every 10 ms from the main loop)
  turns words 0-4 into button events: button id = ``16r + j - 2`` for bits
  2 and up, so ids 0-69, queued as ``id | pressed << 7`` (``timer_state`` +0x88)
  and dispatched by ``ui_button_event`` ``0x0801AC80`` through the button
  table ``0x200010D8`` (u32 per id: kind, action, argument).
* Word 0 bits 0-1 are the encoder's two phases. ``encoder_sample``
  ``0x08011764`` (1 kHz, after the scan) steps a quadrature table
  (``0x080494F4``) into a counter (``timer_state`` +0); ``encoder_poll``
  ``0x08011698`` turns it into one signed, accelerated delta every 30 ms.
  A detent is two phase changes; one detent per 30 ms gives a delta of ±1.
* The 72 pots and the pedal inputs come through ADC1 and an 8-way multiplexer
  by DMA (``0x08011A44``); they are not modelled here.

:class:`PanelChain` holds the input state and answers ``GPIOC_IDR`` reads by
counting the load and clock edges, so the firmware's own scan code reads the
buttons. It also shifts in what the firmware drives on PC12 and latches it on
PA15: :attr:`PanelChain.leds` are the chain's LED bits, numbered as the
firmware's LED words at ``0x20013240`` (``16 * word + bit``).
"""

from __future__ import annotations

from typing import Dict, Optional, Set, Tuple, Union

GPIOA_BSRR = 0x40020018
GPIOB_BSRR = 0x40020418
GPIOC_IDR = 0x40020810
GPIOC_BSRR = 0x40020818
LOAD_PIN = 2  # PB2, active low
CLOCK_PIN = 10  # PC10, rising edge
DATA_IN_PIN = 11  # PC11, active low
LED_DATA_PIN = 12  # PC12
LATCH_PIN = 15  # PA15
CHAIN_BITS = 7 * 16
ENC_BITS = (0, 1)  # word 0 bits 0 (phase A) and 1 (phase B)

#: Button ids (``16 * word + bit - 2``), named from the button table's action
#: and from what each does in the simulator. ``emulated``: checked by pressing
#: it in the simulator (screen or state). ``inferred``: from the action code
#: only. The menu buttons are named by the menu they open.
BUTTONS: Dict[str, int] = {}
#: name → "emulated" or "inferred"
BUTTON_CONFIDENCE: Dict[str, str] = {}


def _button(name: str, bid: int, confidence: str) -> None:
    BUTTONS[name] = bid
    BUTTON_CONFIDENCE[name] = confidence


# Menu buttons: ui_mode_button(mode); named by the menu's first page title.
for _name, _id in (("patch", 18), ("multi", 19), ("osc", 24), ("mod_matrix", 25), ("fx", 26), ("lfo", 27),
                   ("voice", 28), ("env", 29), ("settings", 34), ("save", 35), ("arp", 36), ("fx_matrix", 37)):
    _button(_name, _id, "emulated")
# Navigation, checked on screen in the simulator.
_button("page_next", 22, "emulated")  # ui_page_step(+1): page n/N up by one
_button("page_prev", 23, "emulated")  # ui_page_step(-1)
_button("item1", 14, "emulated")  # moves the ▶ cursor to display row 1 (action 2, arg 0)
_button("item2", 15, "emulated")  # row 2
_button("item3", 6, "emulated")  # row 3
_button("value_dec", 32, "emulated")  # the encoder's handler with -1 (action 5)
_button("value_inc", 33, "emulated")  # ... +1; both together: value 0
_button("patch_prev", 16, "emulated")  # patch_step(-1) (action 4)
_button("patch_next", 17, "emulated")  # patch_step(+1); both at boot: factory initialise
# From the action code and the MIDI the press sends, not from the panel legend.
_button("octave_down", 4, "inferred")  # NRPN 0:6 value 63 (action 0, arg -1)
_button("octave_up", 5, "inferred")  # NRPN 0:6 value 65
_button("animate_1", 3, "inferred")  # CC 114 127/0 while held (action 6, arg 0)
_button("animate_2", 2, "inferred")  # CC 115 127/0 while held (action 6, arg 1)
_button("shift", 20, "inferred")  # action 8: a held flag (ui flags +9) that blocks action 7
_button("part_a", 10, "inferred")  # action 9, Multi mode only: part select, both = both parts
_button("part_b", 7, "inferred")

ButtonRef = Union[str, int]


def button_id(button: ButtonRef) -> int:
    if isinstance(button, int):
        if not 0 <= button < 70:
            raise ValueError(f"button id {button} out of range 0-69")
        return button
    try:
        return BUTTONS[button.lower()]
    except KeyError:
        raise KeyError(f"unknown button {button!r}; known: {', '.join(sorted(BUTTONS))}") from None


class PanelChain:
    """The shift-register chain behind ``panel_scan``. See the module docstring."""

    def __init__(self) -> None:
        self.inputs: Set[int] = set()  # chain positions held active (low)
        self.encoder_phase = 0  # bit 0 = A, bit 1 = B (1 = active)
        self._loaded: Set[int] = set()
        self._index = 0
        self._clock_high = False
        self._led_data = 0
        self._led_shift = 0
        self._led_clocks = 0
        #: LED bits latched at the last PA15 pulse, as firmware LED ids.
        self.leds: Set[int] = set()
        self.scans = 0

    # -- input state ------------------------------------------------------------

    def set_button(self, button: ButtonRef, pressed: bool) -> None:
        pos = button_id(button) + 2
        if pressed:
            self.inputs.add(pos)
        else:
            self.inputs.discard(pos)

    def pressed(self) -> Set[int]:
        return {p - 2 for p in self.inputs if p >= 2}

    def _active(self) -> Set[int]:
        enc = {b for b in ENC_BITS if self.encoder_phase >> b & 1}
        return set(self.inputs) | enc

    # -- bus side ---------------------------------------------------------------

    def gpiob_bsrr(self, value: int) -> None:
        if value >> (LOAD_PIN + 16) & 1:
            self._loaded = self._active()
            self._index = 0
            self.scans += 1

    def gpioc_bsrr(self, value: int) -> None:
        if value >> LED_DATA_PIN & 1:
            self._led_data = 1
        elif value >> (LED_DATA_PIN + 16) & 1:
            self._led_data = 0
        if value >> CLOCK_PIN & 1 and not self._clock_high:
            self._clock_high = True
            self._index += 1
            self._led_shift = (self._led_shift << 1 | self._led_data) & ((1 << CHAIN_BITS) - 1)
            self._led_clocks += 1
        elif value >> (CLOCK_PIN + 16) & 1:
            self._clock_high = False

    def gpioa_bsrr(self, value: int) -> None:
        if value >> LATCH_PIN & 1:
            # The first bit shifted is the furthest one: word r bit 15-k went
            # out at clock 16r + k (panel_scan sends each word MSB first).
            n = self._led_clocks
            self.leds = {
                16 * ((n - 1 - i) // 16) + 15 - (n - 1 - i) % 16
                for i in range(min(n, CHAIN_BITS))
                if self._led_shift >> i & 1
            }
            self._led_clocks = 0
            self._led_shift = 0

    def idr(self, addr: int, size: int) -> int:
        """``GPIOC_IDR``: every input high except PC11 while a held input is clocked out."""
        value = 0xFFFF
        if self._index in self._loaded:
            value &= ~(1 << DATA_IN_PIN)
        return value >> (8 * (addr & 3))


#: Encoder phases per detent (A = bit 0, B = bit 1). The detents rest at 0 and 3;
#: ``encoder_sample``'s table counts B leading A as +1 on the display.
_DETENT_UP = {0: (2, 3), 3: (1, 0)}
_DETENT_DOWN = {0: (1, 3), 3: (2, 0)}


def detent_phases(phase: int, up: bool) -> Tuple[int, int]:
    """The two phase states one detent passes through from rest *phase*."""
    table = _DETENT_UP if up else _DETENT_DOWN
    if phase not in table:
        raise ValueError(f"encoder not at a detent (phase {phase})")
    return table[phase]


def led_word_bits(leds: Set[int], word: int) -> int:
    return sum(1 << (i - 16 * word) for i in leds if 16 * word <= i < 16 * word + 16)


def describe(button: ButtonRef) -> Optional[str]:
    bid = button_id(button)
    for name, i in BUTTONS.items():
        if i == bid:
            return name
    return None
