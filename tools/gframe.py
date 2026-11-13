# SPDX-License-Identifier: 0BSD
# Copyright (C) 2026 Santiago Crespo
"""gframe - protocol v2 of the Genio 2000 bank dumper (Genio -> PC only). See docs/PROTOCOL.md.

Frame (before SLIP byte-stuffing, little-endian):
  'V' 'D' ver type session16 bank seq16 src16 off16 len16 payload[len] crc16
CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) over the bytes from 'V' to the last payload byte; the low byte is sent first.
SLIP delimiting: END=0xC0, ESC=0xDB, ESC_END=0xDC, ESC_ESC=0xDD (same as protocol v1).
"""
import struct, zlib

MAGIC = b'VD'
VER = 2
T_START, T_DATA, T_END, T_BANKREC, T_STAGE = 1, 2, 3, 0x10, 0x11
T_BANK_BEGIN, T_BANK_END = 0x20, 0x21
TOOL_DIAG, TOOL_DUMP, TOOL_DIAG16 = 1, 2, 3
SEL_NONE = 0xFF
HDR = 15
END, ESC, ESC_END, ESC_ESC = 0xC0, 0xDB, 0xDC, 0xDD
BANK_SIZE = 0x4000

def crc16(data, crc=0xFFFF):
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc

_T16 = None
def crc16_fast(data, crc=0xFFFF):
    global _T16
    if _T16 is None:
        _T16 = []
        for i in range(256):
            c = i << 8
            for _ in range(8):
                c = ((c << 1) ^ 0x1021) & 0xFFFF if c & 0x8000 else (c << 1) & 0xFFFF
            _T16.append(c)
    for b in data:
        crc = ((crc << 8) & 0xFFFF) ^ _T16[(crc >> 8) ^ b]
    return crc

assert crc16(b'123456789') == 0x29B1

def crc32(data, crc=0):
    return zlib.crc32(data, crc) & 0xFFFFFFFF

def _gf2_times(mat, vec):
    s, i = 0, 0
    while vec:
        if vec & 1: s ^= mat[i]
        vec >>= 1; i += 1
    return s
def _gf2_square(sq, mat):
    for n in range(32): sq[n] = _gf2_times(mat, mat[n])
def crc32_combine(crc1, crc2, len2):
    """CRC-32 of A||B from crc32(A), crc32(B) and len(B) (zlib algorithm)."""
    if len2 <= 0: return crc1
    even, odd = [0] * 32, [0] * 32
    odd[0] = 0xEDB88320
    row = 1
    for n in range(1, 32): odd[n] = row; row <<= 1
    _gf2_square(even, odd); _gf2_square(odd, even)
    while True:
        _gf2_square(even, odd)
        if len2 & 1: crc1 = _gf2_times(even, crc1)
        len2 >>= 1
        if not len2: break
        _gf2_square(odd, even)
        if len2 & 1: crc1 = _gf2_times(odd, crc1)
        len2 >>= 1
        if not len2: break
    return (crc1 ^ crc2) & 0xFFFFFFFF

assert crc32_combine(crc32(b'hello '), crc32(b'world'), 5) == crc32(b'hello world')

def stuff(b):
    out = bytearray()
    for x in b:
        if x == END: out += bytes([ESC, ESC_END])
        elif x == ESC: out += bytes([ESC, ESC_ESC])
        else: out.append(x)
    return bytes(out)

def build(ftype, session, bank, seq, src, off, payload=b''):
    body = MAGIC + bytes([VER, ftype]) + struct.pack('<HBHHHH', session, bank, seq, src, off, len(payload)) + payload
    body += struct.pack('<H', crc16_fast(body))
    return bytes([END]) + stuff(body) + bytes([END])

class Frame:
    __slots__ = ('type', 'session', 'bank', 'seq', 'src', 'off', 'payload', 'raw')
    def __repr__(self):
        return 'Frame(type=%#x session=%04X bank=%#x seq=%d src=%04X off=%04X len=%d)' % (
            self.type, self.session, self.bank, self.seq, self.src, self.off, len(self.payload))

class Reject(Exception): pass

def parse(body):
    """body = already un-escaped bytes between two END marks. Returns a Frame or raises Reject(reason)."""
    if len(body) < HDR + 2: raise Reject('short')
    if body[:2] != MAGIC: raise Reject('magic')
    if body[2] != VER: raise Reject('version %d' % body[2])
    ftype = body[3]
    session, bank, seq, src, off, ln = struct.unpack('<HBHHHH', body[4:HDR])
    if len(body) != HDR + ln + 2: raise Reject('length')
    if struct.unpack('<H', body[-2:])[0] != crc16_fast(body[:-2]): raise Reject('crc')
    f = Frame(); f.type, f.session, f.bank, f.seq, f.src, f.off = ftype, session, bank, seq, src, off
    f.payload = bytes(body[HDR:HDR + ln]); f.raw = bytes(body)
    return f

class Decoder:
    """Incremental SLIP decoder. feed(bytes) -> list of ('frame', Frame) | ('reject', reason, bytes)."""
    def __init__(self): self.buf = bytearray(); self.esc = False; self.bad = False; self.started = False
    def feed(self, data):
        out = []
        for x in data:
            if x == END:
                if self.started and self.buf:
                    if self.bad: out.append(('reject', 'escape', bytes(self.buf)))
                    else:
                        try: out.append(('frame', parse(bytes(self.buf))))
                        except Reject as e: out.append(('reject', str(e), bytes(self.buf)))
                self.buf = bytearray(); self.esc = False; self.bad = False; self.started = True
                continue
            if not self.started: continue
            if self.esc:
                if x == ESC_END: self.buf.append(END)
                elif x == ESC_ESC: self.buf.append(ESC)
                else: self.bad = True
                self.esc = False
            elif x == ESC: self.esc = True
            else: self.buf.append(x)
        return out


class ParmrkDecoder(Decoder):
    """Like Decoder, but understands termios PARMRK marks: FF FF = literal FF; FF 00 xx = byte xx received with a line error
    (the frame in progress is rejected; it is never 'corrected')."""
    def __init__(self): super().__init__(); self._p = bytearray(); self.line_errors = 0
    def feed(self, data):
        out, plain = [], bytearray()
        self._p += data
        i, n = 0, len(self._p)
        while i < n:
            if self._p[i] != 0xFF: plain.append(self._p[i]); i += 1; continue
            if i + 1 >= n: break
            if self._p[i + 1] == 0xFF: plain.append(0xFF); i += 2; continue
            if self._p[i + 1] == 0x00:
                if i + 2 >= n: break
                if plain: out += Decoder.feed(self, bytes(plain)); plain = bytearray()
                self.line_errors += 1; self.bad = True
                if self._p[i + 2] == END:      # an END that arrived with a line error: do not trust it as delimiter; reset
                    self.buf = bytearray(); self.esc = False; self.bad = False; self.started = False
                i += 3; continue
            plain.append(0xFF); i += 1
        del self._p[:i]
        if plain: out += Decoder.feed(self, bytes(plain))
        return out
