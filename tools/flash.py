#!/usr/bin/env python3
"""Flash a Novation Summit/Peak firmware .syx the way Novation Components does.

The protocol is documented in docs/update-protocol.md (static analysis of
Components, confirmed by a live capture and a hardware run):

  1. identify the running application (Universal Device Inquiry) and check
     that its product matches the file's header;
  2. send the file's own 0x71 header to the application, which reboots into
     the bootloader ("<Product> Bootloader" MIDI ports appear, <= 12 s);
  3. on the bootloader ports send the file's messages in order, one message
     per device 0x72 request (stop-and-wait, 10 s per request, no retries);
  4. after the final 0x73 block wait <= 30 s for the application to return
     and report its version, and compare it with the file header's digits.

  flash.py check FILE.syx                  validate the file, print the plan
  flash.py ports                           list MIDI ports
  flash.py identify [--product summit]     ask the running synth for its version
  flash.py flash FILE.syx --dry-run        full run against a simulated synth
  flash.py flash FILE.syx [--log PATH]     real update (asks for confirmation)

Only firmware files (0x71/0x72/0x73) are accepted; FPGA files (0x7C) are
refused. Run with `.venv/bin/python -I tools/flash.py ...`.
"""
import argparse
import hashlib
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import syx  # noqa: E402

NOVATION = b"\xf0\x00\x20\x29\x00"
IDENTITY_REQUEST = bytes([0xF0, 0x7E, 0x7F, 0x06, 0x01, 0xF7])

# Header product id (MSB first) -> product name.
PRODUCTS = {(0x01, 0x33): "Summit", (0x00, 0x7E): "Peak"}



def _identity_template(device_id, family):
    # Reply bytes 1-11: 7E <dev> 06 02 <00 20 29> <family lo hi> 00 00
    return bytes([0x7E, device_id, 0x06, 0x02, 0x00, 0x20, 0x29, *family, 0x00, 0x00])


# Identity reply bytes 1-11 accepted per product (Kae/Hae.handleVersionMessage).
IDENTITY_TEMPLATES = {
    "Summit": [_identity_template(0x7F, (0x33, 0x01)), _identity_template(0x00, (0x33, 0x11))],
    "Peak": [_identity_template(0x7F, (0x7E, 0x00)), _identity_template(0x00, (0x7E, 0x10))],
}

WAIT_FOR_BOOTLOADER = 12.0   # Summit maxWaitForResetTimeout
SETTLE_AFTER_BOOTLOADER = 0.1
REQUEST_TIMEOUT = 10.0       # FIRMWARE_UPDATE_TIMEOUT
WAIT_FOR_APPLICATION = 30.0  # QEe.waitFor, 60 polls x 500 ms
IDENTITY_TIMEOUT = 2.0
APPLICATION_IDENTITY_ATTEMPTS = int(WAIT_FOR_APPLICATION / IDENTITY_TIMEOUT)
POLL = 0.2


class FlashError(Exception):
    pass


# ---------------------------------------------------------------- file plan

class Plan:
    """A validated firmware file: its raw messages in file order."""

    def __init__(self, data):
        self.data = data
        self.sha256 = hashlib.sha256(data).hexdigest()
        self.messages = []
        pos = 0
        while pos < len(data):
            if data[pos] != 0xF0:
                raise FlashError(f"expected F0 at offset {pos:#x}")
            end = data.index(0xF7, pos)
            self.messages.append(data[pos:end + 1])
            pos = end + 1
        cmds = [m[5] if m[:5] == NOVATION else None for m in self.messages]
        if None in cmds:
            raise FlashError("file contains non-Novation SysEx")
        if 0x7C in cmds:
            raise FlashError("this is an FPGA image (0x7C); only firmware files are supported")
        if cmds[0] != syx.CMD_HEADER or cmds[-1] != syx.CMD_FINAL or cmds.count(syx.CMD_FINAL) != 1 \
                or cmds.count(syx.CMD_HEADER) != 1 or set(cmds[1:-1]) != {syx.CMD_DATA}:
            raise FlashError("expected one 0x71 header, then 0x72 blocks, then one 0x73 final block")
        if any(len(m) != 6 + syx.SEPTETS + 1 for m in self.messages[1:]):
            raise FlashError("a data block has the wrong length")
        self.header, self.image = syx.decode(data)  # also checks the 7-bit packing
        product_id = tuple(self.header[:2])
        if product_id not in PRODUCTS:
            raise FlashError(f"unknown product id {self.header[:2].hex()} in header")
        self.product = PRODUCTS[product_id]
        # Header bytes 4-7 are the version digits the identity reply reports
        # (docs/firmware-format.md); a byte above 9 is kept as its number.
        self.version = "".join(str(d) for d in self.header[4:8])

    def describe(self):
        return (f"{self.product} firmware {self.version}, {len(self.messages)} messages "
                f"(1 header, {len(self.messages) - 2} blocks, 1 final), image {len(self.image)} bytes\n"
                f"header  {self.header.hex(' ')}\nsha256  {self.sha256}")


# ------------------------------------------------------------ device replies

def parse_identity(msg):
    """Return (product, version) for an accepted identity reply, else None."""
    if len(msg) < 17 or msg[0] != 0xF0:
        return None
    for product, templates in IDENTITY_TEMPLATES.items():
        if bytes(msg[1:12]) in templates:
            return product, "".join(str(d) for d in msg[12:16])
    return None


def parse_request(msg):
    """Device 0x72 'send next' request -> counter, else None."""
    if bytes(msg[:6]) != NOVATION + b"\x72":
        return None
    if len(msg) == 10:
        return msg[6] + (msg[7] << 7) + (msg[8] << 14)
    if len(msg) == 15:
        e = msg[6:14]
        return e[7] + (e[6] << 4) + (e[5] << 8)
    return None


def parse_status(msg):
    """Device 0x73 status report -> code, else None."""
    if len(msg) == 10 and bytes(msg[:6]) == NOVATION + b"\x73":
        return msg[6]
    return None


STATUS_FATAL = {0x7C: "device reported a CRC error (composition not viable)",
                0x7E: "device reported a CRC error (composition viable)",
                0x10: "update cancelled on the device"}


class Transfer:
    """Stop-and-wait sender for the bootloader stream (s1.#$i in Components)."""

    def __init__(self, plan):
        self.messages = plan.messages
        self.index = 0
        self.last_counter = 0
        self.done = False

    def start(self):
        self.index = 1
        return self.messages[0]

    def on_message(self, msg):
        """Return the next message to send, or None to keep waiting."""
        status = parse_status(msg)
        if status in STATUS_FATAL:
            raise FlashError(f"{STATUS_FATAL[status]} at block {self.index}")
        if status == 0x7F:
            return self._next()
        counter = parse_request(msg)
        if counter is None:
            return None
        if counter > self.last_counter or counter == 0:
            self.last_counter = counter
            return self._next()
        return None

    def _next(self):
        if self.done or self.index >= len(self.messages):
            return None
        msg = self.messages[self.index]
        self.index += 1
        self.done = self.index == len(self.messages)
        return msg


# --------------------------------------------------------------- MIDI layer

def port_key(name, platform=sys.platform):
    """A port's name without the index Windows' MIDI API appends ("Peak 2" ->
    "Peak"), so an input and its output match; unchanged elsewhere."""
    if platform == "win32":
        return re.sub(r" \d+$", "", name)
    return name


def _port_index(ports, name):
    keys = [port_key(p) for p in ports]
    if name not in keys:
        raise FlashError(f"MIDI port {name!r} is gone")
    return keys.index(name)


class RtMidiBackend:
    """Real MIDI ports through python-rtmidi (CoreMIDI on macOS, WinMM on Windows)."""

    def __init__(self):
        import rtmidi
        self.rtmidi = rtmidi

    def port_names(self):
        return ([port_key(n) for n in self.rtmidi.MidiIn().get_ports()],
                [port_key(n) for n in self.rtmidi.MidiOut().get_ports()])

    def open(self, name):
        return RtMidiPort(self.rtmidi, name)


class RtMidiPort:
    def __init__(self, rtmidi, name):
        self.min, self.mout = rtmidi.MidiIn(), rtmidi.MidiOut()
        self.min.ignore_types(sysex=False, timing=True, active_sense=True)
        self.min.open_port(_port_index(self.min.get_ports(), name))
        self.mout.open_port(_port_index(self.mout.get_ports(), name))
        self.name = name

    def send(self, msg):
        self.mout.send_message(list(msg))

    def receive(self, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            got = self.min.get_message()
            if got:
                return bytes(got[0])
            time.sleep(0.001)
        return None

    def close(self):
        self.min.close_port()
        self.mout.close_port()


def find_port(backend, product, bootloader, override=None):
    """Name of the port pair for the application or bootloader, or None."""
    ins, outs = backend.port_names()
    want = override or product
    names = [n for n in ins if want in n and n in outs
             and (("Bootloader" in n) == bootloader)]
    if len(names) > 1:
        raise FlashError(f"several matching ports, pick one with --port: {names}")
    return names[0] if names else None


def identify(port, timeout=IDENTITY_TIMEOUT):
    port.send(IDENTITY_REQUEST)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        msg = port.receive(max(0.0, deadline - time.monotonic()))
        if msg is None:
            break
        ident = parse_identity(msg)
        if ident:
            return ident
    return None


# ------------------------------------------------------------------ the flow

class Log:
    def __init__(self, path=None, out=print):
        self.file = open(path, "w") if path else None
        self.out = out
        self.t0 = time.monotonic()

    def say(self, text):
        self.out(text)

    def midi(self, direction, port, msg):
        if self.file:
            self.file.write(f"{time.monotonic() - self.t0:10.4f} {direction} {port} {bytes(msg).hex(' ')}\n")

    def close(self):
        if self.file:
            self.file.close()


class LoggedPort:
    def __init__(self, port, log):
        self.port, self.log, self.name = port, log, port.name

    def send(self, msg):
        self.log.midi(">", self.name, msg)
        self.port.send(msg)

    def receive(self, timeout):
        msg = self.port.receive(timeout)
        if msg is not None:
            self.log.midi("<", self.name, msg)
        return msg

    def close(self):
        self.port.close()


def wait_for_port(backend, product, bootloader, timeout, override=None, sleep=time.sleep):
    deadline = time.monotonic() + timeout
    while True:
        name = find_port(backend, product, bootloader, override)
        if name or time.monotonic() >= deadline:
            return name
        sleep(POLL)


def flash(plan, backend, log, confirm, port_override=None, sleep=time.sleep):
    """Run the whole update. Returns the version the application reports afterwards (or None)."""
    product = plan.product
    log.say(plan.describe())

    boot_name = find_port(backend, product, True, port_override)
    if boot_name:
        log.say(f"bootloader already active on '{boot_name}' (manual entry / recovery path)")
        if not confirm(f"Send {product} firmware to '{boot_name}'?"):
            raise FlashError("not confirmed")
    else:
        main_name = find_port(backend, product, False, port_override)
        if not main_name:
            raise FlashError(f"no '{product}' MIDI port found; is the synth connected?")
        main = LoggedPort(backend.open(main_name), log)
        try:
            ident = identify(main)
            if ident is None:
                raise FlashError(f"no identity reply on '{main_name}'")
            if ident[0] != product:
                raise FlashError(f"device is a {ident[0]} but the file is {product} firmware")
            log.say(f"device: {ident[0]} on '{main_name}', firmware {ident[1]}")
            if not confirm(f"Reboot the {product} into its bootloader and flash this file?"):
                raise FlashError("not confirmed")
            main.send(plan.messages[0])
        finally:
            main.close()
        log.say("waiting for bootloader ports ...")
        boot_name = wait_for_port(backend, product, True, WAIT_FOR_BOOTLOADER, port_override, sleep)
        if not boot_name:
            raise FlashError("bootloader ports did not appear within 12 s")
        sleep(SETTLE_AFTER_BOOTLOADER)

    boot = LoggedPort(backend.open(boot_name), log)
    transfer = Transfer(plan)
    total = len(plan.messages)
    try:
        # Components asks the bootloader for its identity before the header
        # (observed in the 2026-10-31 capture); we also use it as a product check.
        ident = identify(boot)
        if ident is None:
            raise FlashError(f"no identity reply from '{boot_name}'")
        if ident[0] != product:
            raise FlashError(f"bootloader is a {ident[0]} but the file is {product} firmware")
        log.say(f"bootloader: {ident[0]} on '{boot_name}', reports {ident[1]}")
        boot.send(transfer.start())
        while not transfer.done:
            msg = boot.receive(REQUEST_TIMEOUT)
            if msg is None:
                raise FlashError(f"no request from the device for {REQUEST_TIMEOUT:.0f} s after message "
                                 f"{transfer.index - 1} of {total} (last counter {transfer.last_counter}); "
                                 f"restart the update from the beginning in bootloader mode")
            nxt = transfer.on_message(msg)
            if nxt is not None:
                boot.send(nxt)
                if transfer.index % 500 == 0 or transfer.done:
                    log.say(f"  sent {transfer.index}/{total}")
    finally:
        boot.close()

    log.say("transfer complete; waiting for the application to restart ...")
    main_name = wait_for_port(backend, product, False, WAIT_FOR_APPLICATION, port_override, sleep)
    if not main_name:
        log.say("Unable to confirm update: the application ports did not return within 30 s")
        return None
    # The port name is back ~2 s after the final block, but the application
    # answers only ~6 s after it (hardware run 2026-10-31). Keep asking, and
    # reopen the port each time in case the first endpoint was stale.
    ident = None
    for _ in range(APPLICATION_IDENTITY_ATTEMPTS):
        main_name = find_port(backend, product, False, port_override)
        if main_name:
            # On Windows the returning port can refuse SysEx for a moment
            # (WinMM "error sending sysex message", 2026-11-12 Peak flash):
            # count that as no reply yet and ask again.
            try:
                main = LoggedPort(backend.open(main_name), log)
                try:
                    ident = identify(main)
                finally:
                    main.close()
            except Exception as e:  # rtmidi raises its own SystemError
                log.say(f"  application port not ready ({type(e).__name__}: {e}); retrying")
                ident = None
            if ident:
                break
        sleep(POLL)
    if ident is None:
        log.say("Unable to confirm update: no identity reply after reboot")
        return None
    if ident[1] == plan.version:
        log.say(f"application back: {ident[0]} firmware {ident[1]}, as in the file header")
    else:
        log.say(f"application back: {ident[0]} firmware {ident[1]}, but the file header says "
                f"{plan.version}: the device is not running this file's version")
    return ident[1]


# -------------------------------------------------------------- simulation

class SimulatedSynth:
    """A device model for --dry-run and tests, following docs/update-protocol.md.

    It plays the application until it receives a 0x71 header, then the
    bootloader, as observed in the 2026-10-31 Components capture: identity
    reply with the bootloader template; after each message one 0x72 request
    whose counter is the number of messages received so far (1, 2, ...); no
    reply after the 0x73 final block; then the application again, reporting
    the version digits of the header it was sent (`keep_version` keeps the old
    version instead, as if the new image had not been taken).
    `duplicate_requests=N` repeats every Nth request (the real bootloader did
    so 197 times, about every 45 blocks); `stall_after` and `status_after`
    inject faults. `slow_boot=N` makes the restarted application ignore its
    first N identity requests, as the real one does for ~4 s after its port
    reappears.
    """

    def __init__(self, product="Summit", version="2126", stall_after=None,
                 duplicate_requests=0, status_after=None, slow_boot=0, keep_version=False):
        self.product, self.version = product, version
        self.keep_version = keep_version
        self.mode = "app"
        self.received = []
        self.outbox = []
        self.stall_after = stall_after
        self.duplicate_requests = duplicate_requests
        self.status_after = status_after
        self.slow_boot = slow_boot
        self.ignore_identity = 0

    def port_names(self):
        name = f"{self.product} Bootloader" if self.mode == "boot" else self.product
        return [name], [name]

    def open(self, name):
        return SimulatedPort(self, name)

    def identity(self):
        template = IDENTITY_TEMPLATES[self.product][1 if self.mode == "boot" else 0]
        return b"\xf0" + template + bytes(int(d) for d in self.version) + b"\xf7"

    def handle(self, msg):
        if msg == IDENTITY_REQUEST:
            if self.ignore_identity:
                self.ignore_identity -= 1
                return
            self.outbox.append(self.identity())
            return
        if self.mode == "app":
            if msg[:6] == NOVATION + b"\x71":
                self.mode = "boot"
            return
        self.received.append(msg)
        if msg[5] == syx.CMD_FINAL:
            self.mode = "app"
            if not self.keep_version:
                self.version = "".join(str(d) for d in self.received[0][10:14])
            self.ignore_identity = self.slow_boot
            return
        n = len(self.received)
        if self.status_after is not None and n == self.status_after[0]:
            self.outbox.append(NOVATION + bytes([0x73, self.status_after[1], 0, 0, 0xF7]))
            return
        if self.stall_after is not None and n >= self.stall_after:
            return
        req = NOVATION + bytes([0x72, n & 0x7F, (n >> 7) & 0x7F, (n >> 14) & 0x7F, 0xF7])
        self.outbox.append(req)
        if self.duplicate_requests and n % self.duplicate_requests == 0:
            self.outbox.append(req)


class SimulatedPort:
    def __init__(self, synth, name):
        self.synth, self.name = synth, name

    def send(self, msg):
        self.synth.handle(bytes(msg))

    def receive(self, timeout):
        return self.synth.outbox.pop(0) if self.synth.outbox else None

    def close(self):
        pass


# ---------------------------------------------------------------------- CLI

def ask(question):
    answer = input(f"{question} Type 'flash' to continue: ")
    return answer.strip().lower() == "flash"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("check")
    s.add_argument("syx")
    sub.add_parser("ports")
    s = sub.add_parser("identify")
    s.add_argument("--product", default="Summit", type=str.capitalize, choices=sorted(IDENTITY_TEMPLATES))
    s.add_argument("--port")
    s = sub.add_parser("flash")
    s.add_argument("syx")
    s.add_argument("--dry-run", action="store_true", help="simulate the synth; no MIDI port is opened")
    s.add_argument("--port", help="substring that selects the ports instead of the product name")
    s.add_argument("--log", help="write every MIDI message sent and received to this file")
    args = p.parse_args(argv)

    try:
        if args.command == "check":
            print(Plan(Path(args.syx).read_bytes()).describe())
        elif args.command == "ports":
            ins, outs = RtMidiBackend().port_names()
            print("inputs: ", ins)
            print("outputs:", outs)
        elif args.command == "identify":
            backend = RtMidiBackend()
            name = find_port(backend, args.product, False, args.port) or find_port(backend, args.product, True, args.port)
            if not name:
                raise FlashError(f"no '{args.product}' port found")
            port = backend.open(name)
            try:
                print(name, identify(port) or "no identity reply")
            finally:
                port.close()
        elif args.command == "flash":
            plan = Plan(Path(args.syx).read_bytes())
            log = Log(args.log)
            try:
                if args.dry_run:
                    log.say("DRY RUN: simulated synth, no MIDI port is opened")
                    synth = SimulatedSynth(plan.product)
                    flash(plan, synth, log, confirm=lambda q: True, sleep=lambda s: None)
                    if b"".join(synth.received) != plan.data:
                        raise FlashError("simulated bootloader did not receive the file byte-for-byte")
                    log.say("dry run ok: the bootloader stream equals the file byte-for-byte")
                else:
                    flash(plan, RtMidiBackend(), log, confirm=ask, port_override=args.port)
            finally:
                log.close()
    except FlashError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
