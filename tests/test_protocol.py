# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Santiago Crespo
import struct, pytest
import gframe as g

def test_crc16_check_value(): assert g.crc16(b'123456789') == 0x29B1 == g.crc16_fast(b'123456789')
def test_crc32_check_value(): assert g.crc32(b'123456789') == 0xCBF43926

def test_crc32_combine_matches_whole():
    import os
    a, b, c = os.urandom(4096), os.urandom(4096), os.urandom(777)
    assert g.crc32_combine(g.crc32(a), g.crc32(b), len(b)) == g.crc32(a + b)
    whole = g.crc32(a)
    for part in (b, c): whole = g.crc32_combine(whole, g.crc32(part), len(part))
    assert whole == g.crc32(a + b + c)

def test_frame_roundtrip_all_fields():
    payload = bytes(range(256)) + b'\xC0\xDB\xDC\xDD'
    raw = g.build(g.T_DATA, 0xBEEF, 7, 1234, 0x4000, 0x0300, payload)
    out = g.Decoder().feed(raw)
    assert len(out) == 1 and out[0][0] == 'frame'
    f = out[0][1]
    assert (f.type, f.session, f.bank, f.seq, f.src, f.off, f.payload) == (g.T_DATA, 0xBEEF, 7, 1234, 0x4000, 0x0300, payload)

def test_end_marker_never_inside_frame():
    raw = g.build(g.T_DATA, 1, 0, 0, 0, 0, b'\xC0' * 50 + b'\xDB' * 50)
    assert raw[0] == g.END and raw[-1] == g.END and g.END not in raw[1:-1]

def test_crc_error_rejected():
    raw = bytearray(g.build(g.T_DATA, 1, 0, 0, 0, 0, b'hello'))
    raw[20] ^= 0x01
    out = g.Decoder().feed(bytes(raw))
    assert out[0][0] == 'reject' and out[0][1] in ('crc', 'length')

@pytest.mark.parametrize('mut,why', [('ver', 'version'), ('magic', 'magic')])
def test_header_rejects(mut, why):
    body = bytearray(g.build(g.T_END, 1, 0xFF, 0, 0, 0, b'')[1:-1])
    if mut == 'ver': body[2] = 1
    else: body[0] = ord('X')
    body[-2:] = struct.pack('<H', g.crc16_fast(bytes(body[:-2])))
    with pytest.raises(g.Reject, match=why): g.parse(bytes(body))

def test_length_field_mismatch_rejected():
    body = bytearray(g.build(g.T_DATA, 1, 0, 0, 0, 0, b'abcd')[1:-1])
    body[13] = 9          # len lo
    body[-2:] = struct.pack('<H', g.crc16_fast(bytes(body[:-2])))
    with pytest.raises(g.Reject, match='length'): g.parse(bytes(body))

def test_bad_escape_rejected():
    raw = bytes([g.END, ord('V'), g.ESC, 0x01, g.END])
    assert g.Decoder().feed(raw)[0][:2] == ('reject', 'escape')

def test_truncated_frame_yields_nothing():
    raw = g.build(g.T_DATA, 1, 0, 0, 0, 0, b'abcdef')
    assert g.Decoder().feed(raw[:-3]) == []

def test_resync_after_garbage():
    f1 = g.build(g.T_END, 1, 0xFF, 0, 0, 0, b'\x01\x00\x01')
    out = g.Decoder().feed(b'\x00\x55\x12' + f1 + b'\xAA' + f1)
    assert [x[0] for x in out].count('frame') >= 1

def test_parmrk_literal_ff_and_line_error():
    f = g.build(g.T_DATA, 1, 0, 0, 0, 0, b'\xFF\xFF\x00')
    marked = f.replace(b'\xFF', b'\xFF\xFF')
    d = g.ParmrkDecoder()
    out = d.feed(marked[:9]) + d.feed(marked[9:])
    assert out[0][0] == 'frame' and out[0][1].payload == b'\xFF\xFF\x00'
    bad = bytearray(f); bad[10:11] = b'\xFF\x00\x80'
    d2 = g.ParmrkDecoder(); out2 = d2.feed(bytes(bad).replace(b'\xFF\x00\x80', b'\xFF\x00\x80'))
    assert d2.line_errors == 1 and all(x[0] == 'reject' for x in out2)
