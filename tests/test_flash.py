"""tools/flash.py against the simulated synth (no MIDI port is opened).

Most tests use a small synthetic Summit image built with tools/syx.py, so they
run without the Novation firmware; the last one uses the real file if present.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import flash  # noqa: E402
import syx  # noqa: E402
from flash import FlashError, Plan, SimulatedSynth  # noqa: E402

SUMMIT_HEADER = bytes.fromhex("0133000002010206")
PEAK_HEADER = bytes.fromhex("007e000002010008")


def make_file(header=SUMMIT_HEADER, blocks=40):
    image = bytes((i * 7) & 0xFF for i in range(32 * blocks))
    return syx.encode(header, image)


def run(plan, synth, confirm=lambda q: True, port_override=None):
    lines = []
    log = flash.Log(out=lines.append)
    result = flash.flash(plan, synth, log, confirm=confirm, port_override=port_override,
                         sleep=lambda s: None)
    return result, lines


def test_plan_validates_order_and_product():
    plan = Plan(make_file())
    assert plan.product == "Summit"
    assert len(plan.messages) == 41
    assert plan.messages[0][5] == 0x71 and plan.messages[-1][5] == 0x73


@pytest.mark.parametrize("mutate, message", [
    (lambda m: m[1:] + m[:1], "expected one 0x71 header"),            # header moved to the end
    (lambda m: m[:-1], "expected one 0x71 header"),                    # final block missing
    (lambda m: m[:1] + [m[1][:-3] + b"\xf7"] + m[2:], "wrong length"),  # truncated block
])
def test_plan_rejects_malformed(mutate, message):
    msgs = Plan(make_file()).messages
    with pytest.raises(FlashError, match=message):
        Plan(b"".join(mutate(list(msgs))))


def test_plan_rejects_fpga_file():
    fpga = b"\xf0\x00\x20\x29\x00\x7c\x01\x33\x00\x00\x00\xf7"
    with pytest.raises(FlashError, match="FPGA"):
        Plan(fpga)


def test_flash_sends_file_byte_for_byte():
    plan = Plan(make_file())
    synth = SimulatedSynth("Summit", version="2121")
    result, _ = run(plan, synth)
    assert b"".join(synth.received) == plan.data
    assert result == "2126"


@pytest.mark.parametrize("port_override, message", [
    (None, "no 'Peak' MIDI port found"),                          # ports are matched by the file's product
    ("Summit", "device is a Summit but the file is Peak"),        # forced port: identity check catches it
])
def test_peak_file_is_refused_on_a_summit_before_anything_is_sent(port_override, message):
    plan = Plan(make_file(PEAK_HEADER))
    synth = SimulatedSynth("Summit")
    with pytest.raises(FlashError, match=message):
        run(plan, synth, port_override=port_override)
    assert synth.mode == "app" and synth.received == []


def test_declined_confirmation_sends_nothing():
    synth = SimulatedSynth("Summit")
    with pytest.raises(FlashError, match="not confirmed"):
        run(Plan(make_file()), synth, confirm=lambda q: False)
    assert synth.mode == "app" and synth.received == []


def test_stale_requests_are_ignored():
    plan = Plan(make_file())
    synth = SimulatedSynth("Summit", duplicate_requests=3)
    run(plan, synth)
    assert b"".join(synth.received) == plan.data  # no block sent twice


def test_stall_stops_before_the_final_block():
    plan = Plan(make_file())
    synth = SimulatedSynth("Summit", stall_after=10)
    with pytest.raises(FlashError, match="no request from the device"):
        run(plan, synth)
    assert all(m[5] != 0x73 for m in synth.received)  # vectors never written


def test_crc_status_aborts():
    plan = Plan(make_file())
    synth = SimulatedSynth("Summit", status_after=(5, 0x7C))
    with pytest.raises(FlashError, match="CRC error"):
        run(plan, synth)
    assert all(m[5] != 0x73 for m in synth.received)


def test_slow_application_after_reboot_is_still_confirmed():
    # Hardware run 2026-10-31: the port was back long before the application
    # answered, and a single identity attempt reported "no identity reply".
    plan = Plan(make_file())
    synth = SimulatedSynth("Summit", slow_boot=3)
    result, _ = run(plan, synth)
    assert result == "2126"


def test_silent_application_after_reboot_gives_up():
    plan = Plan(make_file())
    synth = SimulatedSynth("Summit", slow_boot=flash.APPLICATION_IDENTITY_ATTEMPTS)
    result, lines = run(plan, synth)
    assert result is None
    assert "no identity reply after reboot" in lines[-1]


def test_recovery_path_when_bootloader_is_already_active():
    plan = Plan(make_file())
    synth = SimulatedSynth("Summit")
    synth.mode = "boot"
    result, lines = run(plan, synth)
    assert any("recovery" in line for line in lines)
    assert b"".join(synth.received) == plan.data
    assert result == "2126"


def test_application_version_is_compared_with_the_file_header():
    plan = Plan(make_file(bytes.fromhex("0133000002010207")))
    assert plan.version == "2127"
    result, lines = run(plan, SimulatedSynth("Summit", version="2126"))
    assert result == "2127"
    assert lines[-1] == "application back: Summit firmware 2127, as in the file header"


def test_old_version_after_reboot_is_reported():
    plan = Plan(make_file(bytes.fromhex("0133000002010207")))
    result, lines = run(plan, SimulatedSynth("Summit", version="2126", keep_version=True))
    assert result == "2126"
    assert "the file header says 2127: the device is not running this file's version" in lines[-1]


def test_parse_identity_and_requests():
    reply = SimulatedSynth("Summit", version="2121").identity()
    assert flash.parse_identity(reply) == ("Summit", "2121")
    assert flash.parse_identity(SimulatedSynth("Peak", version="2108").identity()) == ("Peak", "2108")
    assert flash.parse_identity(reply[:10] + b"\xf7") is None
    assert flash.parse_request(bytes.fromhex("f000202900720102 03f7".replace(" ", ""))) == 1 + (2 << 7) + (3 << 14)
    fifteen = bytes.fromhex("f000202900720000000000010203f7")
    assert flash.parse_request(fifteen) == 3 + (2 << 4) + (1 << 8)


def test_real_summit_file_dry_run():
    path = ROOT / "firmware" / "summit-firmware-2.2-build2121.syx"
    if not path.exists():
        pytest.skip("firmware not present (run scripts/fetch-firmware.sh)")
    plan = Plan(path.read_bytes())
    synth = SimulatedSynth("Summit")
    run(plan, synth)
    assert b"".join(synth.received) == plan.data
    assert len(plan.messages) == 8719
