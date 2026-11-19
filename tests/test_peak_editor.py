"""Editor and MIDI-out baseline (docs/peak-features.md, step 5).

The Peak's editor protocol, read from stock's SysEx parsers (findings, "The
editor protocol"): header 00 20 29 01 10 00 7E, a command byte, five bytes
(the 2nd and 3rd zero) and, for a write, the data. Requests 40 (current
patch), 41 (stored patch), 44 (settings), 46 (wavetable block), 47
(wavetable name) and 4A (a whole bank) answer with 00, 01, 04, 06 and 07,
and each answer sent back unchanged is the matching write. Plus the
identity request and stock's tuning-table dump request.

Each test plays one fixed session into the stock image and into the patch
(MPE off, as both boot) over DIN and requires the same bytes out, step by
step. What Components does on top of these messages is not known (the app
was not recorded); series U checks it by hand.
"""
import pytest

from test_peak_arp_echo import ARP_MIDI, ARP_ON, GLOBALS
from test_peak_sim import PATCHES, _boot, _stock, mpe_built  # noqa: F401

pytestmark = pytest.mark.slow

HDR = [0x00, 0x20, 0x29, 0x01, 0x10, 0x00, 0x7E]
IDENTITY = [0xF0, 0x7E, 0x7F, 0x06, 0x01, 0xF7]


def req(cmd, b10=0, b11=0, b12=0):
    return [0xF0] + HDR + [cmd, 0, 0, b10, b11, b12, 0xF7]


def tuning_dump(table):
    return [0xF0, 0x7E, 0x00, 0x08, 0x00, table, 0xF7]


def split(data):
    """Bytes out -> messages (SysEx whole; channel messages by status)."""
    msgs, cur = [], None
    for x in data:
        if x == 0xF0:
            cur = [x]
        elif cur is not None:
            cur.append(x)
            if x == 0xF7:
                msgs.append(bytes(cur))
                cur = None
        elif x & 0x80:
            msgs.append(bytes([x]))
        elif msgs:
            msgs[-1] += bytes([x])
    return msgs


def play(image, steps, setup=None):
    """steps: (label, bytes, ms). Returns {label: [messages out]}."""
    b = _boot(image)
    b.run_ms(300)
    if setup:
        setup(b)
    out = {}
    for label, data, ms in steps:
        b.din.tx_log.clear()
        for x in data:
            b.din.rx_queue.append((b.time_us, x))
        b.run_ms(ms)
        out[label] = split(x for _, x in b.din.tx_log)
    return out


def same_as_stock(patched, steps, setup=None):
    stock = play(_stock(), steps, setup)
    mine = play(patched, steps, setup)
    for label, _, _ in steps:
        assert mine[label] == stock[label], label
    return stock


def one(msgs, length, cmd=None):
    assert len(msgs) == 1, [len(m) for m in msgs]
    m = msgs[0]
    assert len(m) == length
    if cmd is not None:
        assert list(m[1:8]) == HDR and m[8] == cmd
    return m


def test_requests_answer_as_stock(mpe_built):
    steps = [
        ("identity", IDENTITY, 100),
        ("current patch", req(0x40), 400),
        ("A001", req(0x41, 0, 0, 0), 400),
        ("D002", req(0x41, 0, 3, 1), 400),
        ("D128", req(0x41, 0, 3, 127), 400),
        ("settings", req(0x44), 400),
        ("wave block 0 0", req(0x46, 0, 0), 400),
        ("wave block 10 4", req(0x46, 10, 4), 400),
        ("wave name 0", req(0x47, 0), 100),
        ("wave name 73", req(0x47, 73), 100),
        ("tuning 0", tuning_dump(0), 400),
        ("tuning 16", tuning_dump(16), 400),
    ]
    out = same_as_stock(mpe_built.patched, steps)
    assert one(out["identity"], 17)[5:16] == bytes.fromhex("0020297e0000000201 0008".replace(" ", ""))
    one(out["current patch"], 527, 0x00)
    one(out["D002"], 527, 0x01)
    one(out["settings"], 527, 0x04)
    one(out["wave block 10 4"], 531, 0x06)
    assert one(out["wave name 0"], 23, 0x07)[15:22] == b"Sine   "
    assert one(out["tuning 16"], 408)[:5] == bytes([0xF0, 0x7E, 0x00, 0x08, 0x01])


def test_bank_dump_starts_as_stock(mpe_built):
    """4A sends 128 patches, paced (about 21 s over DIN); the first 3 s."""
    out = same_as_stock(mpe_built.patched, [("bank B", req(0x4A, 0, 2), 3000)])
    msgs = out["bank B"]
    assert len(msgs) >= 10 and all(len(m) == 527 and m[8] == 0x01 for m in msgs)


def _renamed(msg, name):
    m = bytearray(msg)
    m[16:16 + len(name)] = name
    return list(m)


def test_writes_read_back_as_stock(mpe_built):
    """Each answer, changed and sent back, is what the next request returns."""
    def first(image, steps):
        return play(image, steps)

    base = first(_stock(), [("cur", req(0x40), 400), ("d010", req(0x41, 0, 3, 9), 400),
                            ("wave", req(0x46, 10, 4), 400), ("name", req(0x47, 73), 100)])
    cur = _renamed(base["cur"][0], b"Edited Current  ")
    d010 = _renamed(base["d010"][0], b"Stored D010     ")
    wave = bytearray(base["wave"][0])
    wave[20:28] = bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x01])
    name = bytearray(base["name"][0])
    name[14] = 73 - 64          # the write takes the user slot (0 to 9); the request 64 + slot
    name[15:22] = b"Baseln "
    steps = [
        ("write current", cur, 400), ("read current", req(0x40), 400),
        ("write D010", d010, 1500), ("read D010", req(0x41, 0, 3, 9), 400),
        ("write wave", list(wave), 1500), ("read wave", req(0x46, 10, 4), 400),
        ("write name", list(name), 1500), ("read name", req(0x47, 73), 100),
    ]
    out = same_as_stock(mpe_built.patched, steps)
    assert out["read current"][0][9:] == bytes(cur)[9:]
    assert out["read D010"][0][9:] == bytes(d010)[9:]
    assert out["read wave"][0][20:28] == bytes(wave)[20:28]   # the Peak fills in other bytes of the block
    assert out["read name"][0][15:22] == b"Baseln "


def test_midi_out_as_stock(mpe_built):
    """MIDI out for a fixed set of inputs: notes with the arp on and Arp>Midi
    On, CCs, a program change and All Notes Off."""
    def arp_on(b):
        b.uc.mem_write(PATCHES + ARP_ON, b"\x01")
        b.uc.mem_write(GLOBALS + ARP_MIDI, b"\x01")
        b.run_ms(100)

    steps = [
        ("notes, arp", [0x90, 60, 100, 0x90, 64, 100], 700),
        ("notes off", [0x80, 60, 0, 0x80, 64, 0], 300),
        ("CC 74, mod wheel", [0xB0, 74, 90, 0xB0, 1, 64, 0xB0, 1, 0], 200),
        ("program change", [0xC0, 5], 600),
        ("all notes off", [0xB0, 123, 0], 200),
    ]
    out = same_as_stock(mpe_built.patched, steps, setup=arp_on)
    assert any(m[0] & 0xF0 == 0x90 for m in out["notes, arp"])   # the arp's notes go out


# The patch's stored settings (patches/peak_mpe/mpe.h), one valid value each.
PATCH_SETTINGS = {0x30: 1, 0x31: 7, 0x32: 24, 0x33: 12, 0x34: 1, 0x35: 2, 0x36: 1, 0x37: 1, 0x38: 1,
                  0x3E: 2, 0x3F: 1, 0x40: 1, 0x45: 5, 0x46: 8, 0x47: 3, 0x48: 2, 0x49: 4, 0x4A: 1}


def test_a_settings_dump_keeps_the_patch_settings(mpe_built):
    """What Components does with the settings: 44 reads them, 04 writes them
    back. The patch's own settings travel with the dump (roadmap step 7 asked
    whether Components leaves them alone)."""
    b = _boot(mpe_built.patched)
    b.run_ms(300)
    for off, v in PATCH_SETTINGS.items():
        b.uc.mem_write(GLOBALS + off, bytes([v]))

    def send(data, ms):
        b.din.tx_log.clear()
        for x in data:
            b.din.rx_queue.append((b.time_us, x))
        b.run_ms(ms)
        return split(x for _, x in b.din.tx_log)

    dump = one(send(req(0x44), 400), 527, 0x04)
    for off in PATCH_SETTINGS:
        b.uc.mem_write(GLOBALS + off, b"\x00")
    send(list(dump), 1500)
    got = {off: b.u8(GLOBALS + off) for off in PATCH_SETTINGS}
    assert got == PATCH_SETTINGS
