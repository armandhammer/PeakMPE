"""tools/flash.py against a real Components update capture.

The capture (a stock Summit 2.2 update by Novation Components, 2026-10-31,
recorded with MIDI Monitor) lives in the git-ignored work/capture/ because it
contains the firmware bytes. These tests skip without it. They replay the
bootloader's side of the capture into flash.Transfer and require that it
sends exactly what Components sent, message for message.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import flash  # noqa: E402
import mmon  # noqa: E402

# The reference is the text export of the first Components run, the only
# capture that has the bootloader's first messages: in later recordings MIDI
# Monitor attached to the new "Summit Bootloader" ports too late
# (docs/update-protocol.md, "Live capture").
REFERENCE = ROOT / "work" / "capture" / "components-update.log"
CAPTURE = ROOT / "work" / "capture" / "fw_update_log_from_components.mmon"
FIRMWARE = ROOT / "firmware" / "summit-firmware-2.2-build2121.syx"
NOVATION = flash.NOVATION


@pytest.fixture(scope="module")
def events():
    if not FIRMWARE.exists():
        pytest.skip("firmware not present")
    if REFERENCE.exists():
        return list(mmon.read_log(str(REFERENCE)))
    if CAPTURE.exists():
        return list(mmon.messages(str(CAPTURE)))
    pytest.skip("capture not present")


def boot_events(events):
    return [(t, d, data) for t, d, port, data in events if port == "Summit_Bootloader"]


def test_identity_replies_match_templates(events):
    replies = {port: flash.parse_identity(data) for t, d, port, data in events
               if d == "<" and flash.parse_identity(data)}
    assert replies["Summit"] == ("Summit", "2126")
    assert replies["Summit_Bootloader"] == ("Summit", "2126")


def test_transfer_replays_components_exactly(events):
    plan = flash.Plan(FIRMWARE.read_bytes())
    boot = boot_events(events)
    captured_sends = [data for t, d, data in boot if d == ">" and data[:5] == NOVATION]

    transfer = flash.Transfer(plan)
    ours = [transfer.start()]
    for t, d, data in boot:
        if d == "<":
            nxt = transfer.on_message(data)
            if nxt is not None:
                ours.append(nxt)
    assert transfer.done
    assert ours == captured_sends
    assert b"".join(ours) == plan.data


def test_bootloader_repeats_requests_and_sends_nothing_after_final(events):
    boot = boot_events(events)
    counters = [flash.parse_request(data) for t, d, data in boot if d == "<" and flash.parse_request(data)]
    assert counters[0] == 1 and counters[-1] == 8718
    assert all(b >= a for a, b in zip(counters, counters[1:]))
    assert len(counters) - len(set(counters)) > 0      # repeated requests exist and must be ignored
    t_final = next(t for t, d, data in boot if d == ">" and data[:6] == NOVATION + b"\x73")
    assert not [1 for t, d, data in boot if d == "<" and t > t_final]


def test_bootloader_identity_mismatch_is_refused():
    synth = flash.SimulatedSynth("Summit")
    synth.mode = "boot"
    synth.product = "Peak"  # a Peak bootloader on a port that matches "Summit"
    plan = flash.Plan(flash_test_file())
    with pytest.raises(flash.FlashError, match="bootloader is a Peak"):
        flash.flash(plan, synth, flash.Log(out=lambda s: None), confirm=lambda q: True,
                    port_override="Peak", sleep=lambda s: None)
    assert synth.received == []


def flash_test_file():
    import syx
    return syx.encode(bytes.fromhex("0133000002010206"), bytes(32 * 4))
