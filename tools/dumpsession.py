# SPDX-License-Identifier: 0BSD
# Copyright (C) 2026 Santiago Crespo
"""dumpsession - interpretation of the bank_dump frames (tool=2). Never fills in missing data: a missing block stays missing."""
import struct, hashlib
import gframe as g

BANK_SIZE = 0x4000
WIN1 = 0x4000

def sha(data): return dict(sha256=hashlib.sha256(data).hexdigest(), sha1=hashlib.sha1(data).hexdigest(), crc32='%08X' % g.crc32(data))

def parse_start(f):
    p = f.payload
    tool, build, sp, mode, count, block, nblocks = struct.unpack('<BHHBBHH', p[:11])
    base = struct.unpack('<I', p[11:15])[0]
    sels = list(p[15:15 + count])
    if len(sels) != count: raise g.Reject('start length')
    return dict(tool=tool, build=build, sp_main=sp, mode=mode, count=count, block=block, nblocks=nblocks, baseline_crc32=base, selectors=sels)

class BankRx:
    def __init__(self, sel, nblocks, block):
        self.sel, self.nblocks, self.block = sel, nblocks, block
        self.blocks = {}                 # idx -> bytes (CRC-valid receptions, first one kept)
        self.dup_same = 0; self.dup_conflict = []   # idx list: same block received twice with different data (never resolved)
        self.begin = False; self.end = None          # end = dict(crc16_read1, crc32_read2)
        self.bad_frames = 0
    def add_block(self, idx, data):
        if idx in self.blocks:
            if self.blocks[idx] == data: self.dup_same += 1
            else: self.dup_conflict.append(idx)
            return
        self.blocks[idx] = data
    @property
    def missing(self): return [i for i in range(self.nblocks) if i not in self.blocks]
    @property
    def complete(self): return not self.missing and not self.dup_conflict
    def data(self):
        """Bank bytes if complete, otherwise None (never padded)."""
        if not self.complete: return None
        return b''.join(self.blocks[i] for i in range(self.nblocks))
    def check(self):
        d = self.data()
        out = dict(selector=self.sel, blocks_received=len(self.blocks), missing_blocks=self.missing, conflicting_blocks=sorted(set(self.dup_conflict)),
                   duplicate_identical_blocks=self.dup_same, bank_begin=self.begin, bank_end=self.end is not None)
        if d is not None:
            out['crc32_received'] = '%08X' % g.crc32(d)
            if self.end:
                out['rom_crc32_read2'] = '%08X' % self.end['crc32']
                out['rom_crc32_match'] = (g.crc32(d) == self.end['crc32'])
                out['rom_crc16_read1'] = '%04X' % self.end['crc16']
                out['rom_crc16_match'] = (g.crc16_fast(d) == self.end['crc16'])
        out['status'] = self.status()
        return out
    def status(self):
        d = self.data()
        if d is None: return 'INCOMPLETE' if self.blocks else 'ABSENT'
        if not self.end: return 'COMPLETE_NO_END'
        if g.crc32(d) == self.end['crc32'] and g.crc16_fast(d) == self.end['crc16']: return 'COMPLETE_VERIFIED_BY_ROM_CRC'
        return 'COMPLETE_ROM_CRC_MISMATCH'

class DumpSession:
    def __init__(self, sid):
        self.sid = sid; self.start = None; self.banks = {}; self.end = None
        self.seqs = set(); self.dups = 0; self.rejects = 0; self.order = []
    def add(self, f):
        if f.type == g.T_START:
            self.start = parse_start(f); self.seqs = {f.seq}; return
        if f.seq in self.seqs: self.dups += 1; return
        self.seqs.add(f.seq)
        nb, bs = (self.start['nblocks'], self.start['block']) if self.start else (128, 128)   # START lost: infer from the fixed ROM layout, reported as start missing
        if f.type == g.T_BANK_BEGIN:
            b = self.banks.setdefault(f.bank, BankRx(f.bank, nb, bs)); b.begin = True
            if f.bank not in self.order: self.order.append(f.bank)
        elif f.type == g.T_DATA:
            if f.src != WIN1 or f.off % bs or len(f.payload) != bs or f.off // bs >= nb or (self.start and f.bank not in self.start['selectors']):
                self.rejects += 1; return
            b = self.banks.setdefault(f.bank, BankRx(f.bank, nb, bs))
            if f.bank not in self.order: self.order.append(f.bank)
            b.add_block(f.off // bs, f.payload)
        elif f.type == g.T_BANK_END:
            b = self.banks.setdefault(f.bank, BankRx(f.bank, nb, bs))
            sel, n, c16 = struct.unpack('<BHH', f.payload[:5]); c32 = struct.unpack('<I', f.payload[5:9])[0]
            b.end = dict(crc16=c16, crc32=c32, nblocks=n)
        elif f.type == g.T_END:
            self.end = dict(banks_sent=f.payload[0], restore_ok=bool(f.payload[1]), sp_ok=bool(f.payload[2]),
                            restore_crc32=struct.unpack('<I', f.payload[3:7])[0])
    def missing_seqs(self):
        return [s for s in range(max(self.seqs) + 1) if s not in self.seqs] if self.seqs else []
    def report(self):
        r = dict(session='%04X' % self.sid, start=self.start, ended=self.end is not None, end=self.end,
                 frames_missing_seq=self.missing_seqs(), duplicate_frames=self.dups, rejected_data_frames=self.rejects,
                 banks={str(k): v.check() for k, v in sorted(self.banks.items())})
        if self.end: r['end'] = dict(self.end, restore_crc32='%08X' % self.end['restore_crc32'])
        if self.start: r['start'] = dict(self.start, baseline_crc32='%08X' % self.start['baseline_crc32'])
        return r

def decode_capture(raw, plain=False):
    """Decode a raw capture (PARMRK marks unless plain). Returns (list of DumpSession in order of appearance, rejected frames, line errors).
    A START with an already-started session id opens a NEW session (two runs with the same id are never merged)."""
    dec = g.Decoder() if plain else g.ParmrkDecoder()
    order, cur, rej = [], {}, 0
    for it in dec.feed(raw):
        if it[0] == 'reject': rej += 1; continue
        f = it[1]
        s = cur.get(f.session)
        if s is None or (f.type == g.T_START and s.start is not None):
            s = DumpSession(f.session); cur[f.session] = s; order.append(s)
        s.add(f)
    return order, rej, getattr(dec, 'line_errors', 0)
