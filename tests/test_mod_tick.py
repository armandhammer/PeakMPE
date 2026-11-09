"""Modulation tick: TIM6 setup 0x08011F34 and the TIM6_DAC ISR 0x08011F90.

``tim6_init`` programs PSC = 59 and ARR = 49, so TIM6 updates at
f_TIM6 / 3000. The ISR (vector 70, IRQ 54) increments the tick request
``voice_state+0x14C`` every 20th interrupt. ``mod_tick`` 0x080144E4, called
from the main loop, runs ``mod_update`` for both parts once while that byte is
non-zero, then clears it. The 20 kHz / 1 kHz figures come from the RCC set-up
(see the findings); these tests check only the ratios that the code fixes.
"""

TIM6_INIT = 0x08011F34
TIM6_ISR = 0x08011F90
TIM6_PSC, TIM6_ARR, TIM6_DIER, TIM6_CR1 = 0x40001028, 0x4000102C, 0x4000100C, 0x40001000
TICK_REQUEST = 0x200057D8 + 0x14C

# Callees of the 1 kHz branch: front panel, display, LEDs and other work
# that isn't under test here.
ISR_CALLEES = (0x080144DC, 0x080115E4, 0x08011A44, 0x08011764, 0x08013178, 0x08019B44)


def writes(machine):
    return {a.addr: a.value for a in machine.periph_log if a.kind == "w"}


def test_tim6_init_sets_divider_and_enables_update_irq(machine):
    machine.call(TIM6_INIT, budget=1_000)
    w = writes(machine)
    assert (w[TIM6_PSC] + 1) * (w[TIM6_ARR] + 1) == 3000
    assert w[TIM6_DIER] == 1  # UIE
    assert w[TIM6_CR1] & 1  # CEN
    assert w[0xE000E104] & (1 << (54 - 32))  # NVIC ISER1: IRQ 54 (TIM6_DAC)


def test_isr_requests_one_tick_per_20_interrupts(machine):
    for addr in ISR_CALLEES:
        machine.stub(addr, lambda m: None)
    counts = []
    for _ in range(60):
        machine.call(TIM6_ISR, budget=1_000)
        counts.append(machine.u8(TICK_REQUEST))
    assert counts[18] == 0 and counts[19] == 1
    assert counts[39] == 2 and counts[59] == 3
