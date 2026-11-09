"""tools/midirec.py with a fake port source: no MIDI hardware is opened."""

import hashlib
import io
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import midirec  # noqa: E402
import mmon  # noqa: E402


class FakeClock:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t


class FakeSource:
    """Stands in for RtMidiSource: records which inputs were opened and
    lets the test deliver messages through the callbacks."""

    def __init__(self, names):
        self._names = list(names)
        self.callbacks = {}
        self.closed = []

    def names(self):
        return self._names

    def open(self, index, name, callback):
        self.callbacks[name] = callback
        return name

    def close(self, handle):
        self.closed.append(handle)


# -- formatting -------------------------------------------------------------------------------


def test_format_line_matches_mmon_log():
    assert midirec.format_line(1.23456, "Ableton Push 3 Live Port", b"\x90\x3c\x64") == \
        "    1.2346 < Ableton_Push_3_Live_Port 90 3c 64\n"
    assert midirec.format_line(0, "Summit", bytes([0xF0, 0x7E, 0x7F, 0x06, 0x01, 0xF7])) == \
        "    0.0000 < Summit f0 7e 7f 06 01 f7\n"
    # the same expression as `mmon.py log` and `flash.py --log`
    t, port, data = 12.5, "Hapax", b"\xe1\x00\x40"
    assert midirec.format_line(t, port, data) == f"{t:10.4f} < {port} {data.hex(' ')}\n"


# -- filtering --------------------------------------------------------------------------------


@pytest.mark.parametrize("data,dropped", [
    (b"\xf8", True), (b"\xfe", True),
    (b"\xfa", False), (b"\xfc", False), (b"\xf1\x10", False),  # transport and MTC stay
    (b"\x90\x3c\x64", False), (b"\xf0\x7e\x7f\x06\x01\xf7", False),
])
def test_clock_and_active_sensing_are_filtered(data, dropped):
    assert midirec.is_filtered(data) is dropped
    assert midirec.is_filtered(data, keep_clock=True) is False


def test_recorder_filters_and_counts(tmp_path):
    clock = FakeClock()
    rec = midirec.Recorder(tmp_path / "r.log", clock=clock)
    for data in (b"\xf8", b"\x90\x3c\x64", b"\xfe", b"\xf8", b"\x80\x3c\x00"):
        clock.t += 0.01
        rec.message("Push 3", data)
    rec.close()
    lines = (tmp_path / "r.log").read_text().splitlines()
    assert [l.split(None, 3)[3] for l in lines] == ["90 3c 64", "80 3c 00"]
    assert rec.counts == {"Push_3": 2}
    assert rec.filtered == {0xF8: 2, 0xFE: 1}


def test_keep_clock_records_everything(tmp_path):
    rec = midirec.Recorder(tmp_path / "r.log", keep_clock=True, clock=FakeClock())
    for data in (b"\xf8", b"\xfe", b"\x90\x3c\x64"):
        rec.message("Hapax", data)
    rec.close()
    assert [l.split()[3] for l in (tmp_path / "r.log").read_text().splitlines()] == ["f8", "fe", "90"]


# -- file names -------------------------------------------------------------------------------


def test_default_path_name():
    p = midirec.default_path(Path("/x"), datetime(2026, 11, 7, 9, 5, 3))
    assert p == Path("/x/rec-20261107-090503.log")
    assert midirec.default_path().parent == ROOT / "work" / "capture"


def test_never_overwrites(tmp_path):
    target = tmp_path / "sub" / "rec-20261107-090503.log"  # the directory is created
    paths = []
    for _ in range(3):
        rec = midirec.Recorder(target, clock=FakeClock())
        rec.message("Summit", b"\x90\x3c\x64")
        rec.close()
        paths.append(rec.path)
    assert [p.name for p in paths] == ["rec-20261107-090503.log", "rec-20261107-090503-2.log",
                                       "rec-20261107-090503-3.log"]
    assert all(p.read_text().count("\n") == 1 for p in paths)


def test_orphan_sidecar_reserves_its_name(tmp_path):
    (tmp_path / "a.log.sha256").write_text("x")
    rec = midirec.Recorder(tmp_path / "a.log", clock=FakeClock())
    rec.close()
    assert rec.path.name == "a-2.log"


# -- streaming and the hash sidecar ---------------------------------------------------------


def test_lines_are_on_disk_before_close(tmp_path):
    rec = midirec.Recorder(tmp_path / "r.log", clock=FakeClock())
    rec.message("Summit", b"\x90\x3c\x64")
    assert (tmp_path / "r.log").read_text() == "    0.0000 < Summit 90 3c 64\n"
    rec.close()


def test_sha256_sidecar(tmp_path):
    rec = midirec.Recorder(tmp_path / "r.log", clock=FakeClock())
    rec.message("Summit", b"\x90\x3c\x64")
    digest = rec.close()
    content = (tmp_path / "r.log").read_bytes()
    assert digest == hashlib.sha256(content).hexdigest()
    assert (tmp_path / "r.log.sha256").read_text() == f"{digest}  r.log\n"
    assert rec.close() == digest  # closing twice is harmless
    assert digest in rec.summary() and "Summit" in rec.summary()


def test_sidecar_checks_with_shasum(tmp_path):
    rec = midirec.Recorder(tmp_path / "r.log", clock=FakeClock())
    rec.message("Summit", b"\xfa")
    rec.close()
    out = subprocess.run(["shasum", "-a", "256", "-c", "r.log.sha256"], cwd=tmp_path,
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr


def test_messages_after_close_are_ignored(tmp_path):
    rec = midirec.Recorder(tmp_path / "r.log", clock=FakeClock())
    rec.close()
    rec.message("Summit", b"\x90\x3c\x64")  # a late rtmidi callback
    assert rec.marker() is None
    assert (tmp_path / "r.log").read_text() == ""


# -- round trip through mmon.read_log ------------------------------------------------------


def test_round_trip_through_read_log(tmp_path):
    clock = FakeClock()
    rec = midirec.Recorder(tmp_path / "r.log", clock=clock)
    sent = [
        (0.0, "Ableton Push 3 Live Port", bytes([0xB0, 0x65, 0x00])),  # an MCM, CC 101 ...
        (0.0012, "Ableton Push 3 Live Port", bytes([0xB0, 0x64, 0x06])),
        (0.0024, "Ableton Push 3 Live Port", bytes([0xB0, 0x06, 0x0F])),
        (0.5, "Hapax", bytes([0x91, 0x3C, 0x64])),
        (0.5001, "Summit", bytes([0xF0, 0x00, 0x20, 0x29, 0x00, 0x7F, 0xF7])),
    ]
    for t, port, data in sent:
        clock.t = 100.0 + t
        rec.message(port, data)
    clock.t = 101.0
    rec.marker()
    clock.t = 101.25
    rec.message("Hapax", bytes([0x81, 0x3C, 0x00]))
    rec.close()

    got = list(mmon.read_log(str(rec.path)))
    want = [(t, "<", port.replace(" ", "_"), data) for t, port, data in sent] + \
        [(1.25, "<", "Hapax", bytes([0x81, 0x3C, 0x00]))]
    assert [(d, p, b) for _, d, p, b in got] == [(d, p, b) for _, d, p, b in want]
    assert [round(t, 4) for t, *_ in got] == [round(t, 4) for t, *_ in want]
    assert "# marker 1 1.0000\n" in rec.path.read_text()


def test_read_log_skips_comments_and_blank_lines(tmp_path):
    log = tmp_path / "x.log"
    log.write_text("# a header\n    0.1000 > Summit f0 7e 7f 06 01 f7\n\n"
                   "# marker 1 0.2000\n  # indented comment\n    0.3000 < Summit fa\n")
    assert list(mmon.read_log(str(log))) == [
        (0.1, ">", "Summit", bytes.fromhex("f07e7f0601f7")),
        (0.3, "<", "Summit", b"\xfa"),
    ]


# -- the record loop with a fake source -----------------------------------------------------


def test_select_ports():
    names = ["Ableton Push 3 Live Port", "Hapax", "Summit", "IAC Driver Bus 1"]
    assert midirec.select_ports(names, None) == list(enumerate(names))
    assert midirec.select_ports(names, ["summit", "HAPAX"]) == [(1, "Hapax"), (2, "Summit")]
    assert midirec.select_ports(names, ["nothing"]) == []


def test_record_with_fake_source_and_markers(tmp_path):
    source = FakeSource(["Ableton Push 3 Live Port", "Hapax", "Summit"])
    stop = threading.Event()
    out = []
    rec_box = {}

    class Markers(io.StringIO):
        """Delivers messages, then one Enter, then stops the recording."""
        def __iter__(self):
            source.callbacks["Hapax"]([0x90, 0x3C, 0x64])
            source.callbacks["Hapax"]([0xF8])
            source.callbacks["Summit"]([0xF0, 0x7E, 0x7F, 0x06, 0x02, 0xF7])
            yield "\n"
            source.callbacks["Hapax"]([0x80, 0x3C, 0x00])
            stop.set()

    def run():
        rec_box["rec"] = midirec.record(source, out=tmp_path / "rec.log", filters=["hapax", "summit"],
                                        marker_input=Markers(), stop=stop, say=out.append)
    t = threading.Thread(target=run)
    t.start()
    t.join(10)
    assert not t.is_alive()
    rec = rec_box["rec"]
    assert sorted(source.callbacks) == ["Hapax", "Summit"]  # Push not opened
    assert sorted(source.closed) == ["Hapax", "Summit"]
    assert rec.counts == {"Hapax": 2, "Summit": 1}
    text = rec.path.read_text()
    assert text.count("# marker 1 ") == 1 and " f8" not in text
    assert [(d, p, b[0]) for _, d, p, b in mmon.read_log(str(rec.path))] == \
        [("<", "Hapax", 0x90), ("<", "Summit", 0xF0), ("<", "Hapax", 0x80)]
    assert (tmp_path / "rec.log.sha256").exists()
    assert any("sha256" in line for line in out)


def test_record_duration_stops():
    class TickingClock:
        def __init__(self):
            self.t = 0.0

        def __call__(self):
            self.t += 0.5
            return self.t

    source = FakeSource(["Summit"])
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        rec = midirec.record(source, out=Path(d) / "r.log", duration=2.0, clock=TickingClock(),
                             say=lambda s: None)
        assert rec.digest == hashlib.sha256(b"").hexdigest()
    assert source.closed == ["Summit"]


def test_record_without_matching_port_creates_nothing(tmp_path):
    with pytest.raises(SystemExit, match="no matching MIDI input"):
        midirec.record(FakeSource(["Summit"]), out=tmp_path / "r.log", filters=["push"], say=lambda s: None)
    assert list(tmp_path.iterdir()) == []


def test_record_closes_file_on_ctrl_c(tmp_path):
    source = FakeSource(["Summit"])

    class Interrupt:
        def is_set(self):
            return False

        def set(self):
            pass

        def wait(self, _t):
            source.callbacks["Summit"]([0x90, 0x3C, 0x64])
            raise KeyboardInterrupt

    rec = midirec.record(source, out=tmp_path / "r.log", stop=Interrupt(), say=lambda s: None)
    assert rec.counts == {"Summit": 1} and source.closed == ["Summit"]
    assert (tmp_path / "r.log.sha256").exists()


def test_rtmidi_source_settings(monkeypatch):
    """RtMidiSource against a stand-in rtmidi module: SysEx, clock and
    active sensing reach the Recorder (it filters F8/FE itself, so MTC F1
    survives), the callback gets the message bytes, and nothing is sent."""
    calls = []

    class MidiIn:
        def get_ports(self):
            return ["Summit", "Hapax"]

        def ignore_types(self, **kw):
            calls.append(("ignore_types", kw))

        def set_callback(self, fn):
            self.fn = fn

        def open_port(self, i):
            calls.append(("open_port", i))

        def close_port(self):
            calls.append(("close_port",))

        def delete(self):
            calls.append(("delete",))

    fake = type(sys)("rtmidi")
    fake.MidiIn = MidiIn
    monkeypatch.setitem(sys.modules, "rtmidi", fake)
    source = midirec.RtMidiSource()
    assert source.names() == ["Summit", "Hapax"]
    got = []
    handle = source.open(1, "Hapax", got.append)
    handle.fn(([0xF1, 0x10], 0.001), None)
    source.close(handle)
    assert got == [[0xF1, 0x10]]
    assert ("ignore_types", {"sysex": False, "timing": False, "active_sense": False}) in calls
    assert ("open_port", 1) in calls and ("close_port",) in calls
    assert not hasattr(MidiIn, "send_message")
