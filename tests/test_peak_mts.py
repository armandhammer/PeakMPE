"""Peak: MIDI Tuning Standard messages stock drops (patches/peak_mpe/mts.c).

Stock takes the single-note tuning change (F0 7F 00 08 02 tt ll kk xx yy
zz F7) with device ID 00 and exactly one note, and the bulk dump (F0 7E 00
08 01 ...) with device ID 00. The patch adds device ID 7F (all devices) for
both and any number of notes in a single-note change. Entries go through
stock's tuning_note_set: xx << 8 | yy << 1 | zz >> 6, in 1/256 semitone.
"""
import pytest

from test_peak_sim import PATCHES, _boot, _send, _stock, mpe_built  # noqa: F401

pytestmark = pytest.mark.slow

TABLES = 0x20012CF4           # 17 x 128 u16 (tuning_note_set's literal)
TABLE_SEL = 0x162             # patch offset: the patch's tuning table
VOICE_PITCH = 0x200127C4      # 8 x u16, the note pitch of each voice
VOICE_NOTE = 0x20012794       # 8 x u8


def _entry(b, table, key):
    return int.from_bytes(b.uc.mem_read(TABLES + (key + table * 128) * 2, 2), "little")


def _single(dev, table, notes):
    msg = [0xF0, 0x7F, dev, 0x08, 0x02, table, len(notes)]
    for kk, xx, yy, zz in notes:
        msg += [kk, xx, yy, zz]
    return msg + [0xF7]


def _bulk(dev, table, semis):
    """Every key k tuned to k + semis semitones."""
    msg = [0xF0, 0x7E, dev, 0x08, 0x01, table] + list(b"MPE TEST TUNING ")
    for k in range(128):
        msg += [min(k + semis, 127), 0, 0]
    return msg + [0x00, 0xF7]


@pytest.fixture(scope="module")
def stock():
    return _stock()


def test_stock_ignores_device_7f_and_two_notes(stock):
    b = _boot(stock)
    _send(b, *_single(0x7F, 1, [(61, 62, 0, 0)]), ms=50)
    _send(b, *_single(0x00, 1, [(62, 63, 0, 0), (64, 65, 0, 0)]), ms=50)
    assert [_entry(b, 1, k) for k in (61, 62, 64)] == [61 << 8, 62 << 8, 64 << 8]
    _send(b, *_single(0x00, 1, [(60, 61, 0x40, 0)]), ms=50)
    assert _entry(b, 1, 60) == 0x3D80                      # one note, device 00: stock takes it


def test_device_7f_single_note(mpe_built):
    b = _boot(mpe_built.patched)
    _send(b, *_single(0x7F, 1, [(60, 61, 0x40, 0)]), ms=50)
    assert _entry(b, 1, 60) == 0x3D80                      # 61 semitones and 50 cents


def test_several_notes_in_one_message(mpe_built):
    b = _boot(mpe_built.patched)
    notes = [(60, 60, 0x20, 0), (64, 63, 0x7F, 0x40), (67, 67, 0x10, 0)]
    for dev, table in ((0x00, 3), (0x7F, 4)):
        _send(b, *_single(dev, table, notes), ms=80)
        assert [_entry(b, table, k) for k in (60, 64, 67)] == [0x3C40, 0x3FFF, 0x4320], dev
        assert _entry(b, table, 62) == 62 << 8              # untouched keys stay


def test_device_00_one_note_still_stock(mpe_built):
    b = _boot(mpe_built.patched)
    _send(b, *_single(0x00, 1, [(60, 61, 0x40, 0)]), ms=50)
    assert _entry(b, 1, 60) == 0x3D80


def test_malformed_messages_change_nothing(mpe_built):
    b = _boot(mpe_built.patched)
    bad = [
        _single(0x7F, 1, [(60, 61, 0, 0)])[:-5] + [0xF7],                  # ll = 1, no note
        _single(0x7F, 1, [(60, 61, 0, 0), (61, 62, 0, 0)])[:-1] + [9, 0xF7],  # one byte too many
        _single(0x10, 1, [(60, 61, 0, 0)]),                                 # another device ID
        _single(0x7F, 17, [(60, 61, 0, 0)]),                                # no table 17
        _single(0x7F, 1, [(60, 61, 0, 0)])[:-1] + [0x90, 60, 100],          # a note-on ends it
    ]
    for msg in bad:
        _send(b, *msg, ms=50)
    _send(b, 0x80, 60, 0, ms=20)
    assert _entry(b, 1, 60) == 60 << 8 and _entry(b, 1, 61) == 61 << 8


def test_real_time_byte_inside_the_message(mpe_built):
    b = _boot(mpe_built.patched)
    msg = _single(0x7F, 1, [(60, 61, 0x40, 0), (61, 62, 0, 0)])
    _send(b, *(msg[:8] + [0xF8] + msg[8:]), ms=60)
    assert _entry(b, 1, 60) == 0x3D80 and _entry(b, 1, 61) == 62 << 8


def test_bulk_dump_device_7f(mpe_built):
    b = _boot(mpe_built.patched)
    _send(b, *_bulk(0x7F, 2, 1), ms=300)
    assert [_entry(b, 2, k) for k in (0, 60, 126, 127)] == [1 << 8, 61 << 8, 127 << 8, 127 << 8]
    assert _entry(b, 1, 60) == 60 << 8                      # other tables untouched


def test_sounding_note_retuned(mpe_built):
    """The patch's table: a held note moves at once, as stock does for device 00."""
    b = _boot(mpe_built.patched)
    b.uc.mem_write(PATCHES + TABLE_SEL, bytes([5]))
    _send(b, 0x90, 60, 100, ms=40)
    voices = [v for v in range(8) if b.u8(VOICE_NOTE + v) == 60]
    assert voices
    _send(b, *_single(0x7F, 5, [(60, 62, 0, 0)]), ms=50)
    for v in voices:
        assert int.from_bytes(b.uc.mem_read(VOICE_PITCH + 2 * v, 2), "little") == 62 << 8
