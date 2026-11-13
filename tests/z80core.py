# SPDX-License-Identifier: 0BSD
# Copyright (C) 2026 Santiago Crespo
"""
Compact but complete-enough Z80 interpreter (no T-state counting) to run the code SDCC generates for -mz80.
Used ONLY for verification: hooks replace the hardware-validated asm routines (tx_send / wait_bits / line_set),
everything else (C code compiled by SDCC) runs instruction by instruction. Unsupported opcodes abort loudly.
"""
PAR = [bin(i).count('1') % 2 == 0 for i in range(256)]
S, Z, H, PV, N, C = 0x80, 0x40, 0x10, 0x04, 0x02, 0x01

class Z80:
    def __init__(self):
        self.mem = bytearray(65536)
        self.a = self.f = self.b = self.c = self.d = self.e = self.h = self.l = 0
        self.a2 = self.f2 = self.b2 = self.c2 = self.d2 = self.e2 = self.h2 = self.l2 = 0
        self.ix = self.iy = 0; self.sp = 0xFFF0; self.pc = 0; self.i = 0; self.iff = 0; self.halted = False
        self.hooks = {}; self.io_in = lambda p: 0xFF; self.io_out = lambda p, v: None
        self.write_hook = None; self.count = 0
    # ---- helpers ----
    def rb(self, a): return self.mem[a & 0xFFFF]
    def wb(self, a, v):
        a &= 0xFFFF
        if self.write_hook: self.write_hook(a, v & 0xFF)
        self.mem[a] = v & 0xFF
    def rw(self, a): return self.rb(a) | (self.rb(a + 1) << 8)
    def ww(self, a, v): self.wb(a, v & 0xFF); self.wb(a + 1, v >> 8)
    def fetch(self): v = self.mem[self.pc]; self.pc = (self.pc + 1) & 0xFFFF; return v
    def fetch16(self): lo = self.fetch(); return lo | (self.fetch() << 8)
    def push(self, v): self.sp = (self.sp - 2) & 0xFFFF; self.ww(self.sp, v)
    def pop(self): v = self.rw(self.sp); self.sp = (self.sp + 2) & 0xFFFF; return v
    @property
    def bc(self): return (self.b << 8) | self.c
    @property
    def de(self): return (self.d << 8) | self.e
    @property
    def hl(self): return (self.h << 8) | self.l
    @property
    def af(self): return (self.a << 8) | self.f
    def set_bc(self, v): self.b, self.c = (v >> 8) & 0xFF, v & 0xFF
    def set_de(self, v): self.d, self.e = (v >> 8) & 0xFF, v & 0xFF
    def set_hl(self, v): self.h, self.l = (v >> 8) & 0xFF, v & 0xFF
    def set_af(self, v): self.a, self.f = (v >> 8) & 0xFF, v & 0xFF
    # ---- register file with DD/FD prefix handling ----
    def idxreg(self, p): return self.ix if p == 0xDD else self.iy
    def set_idxreg(self, p, v):
        if p == 0xDD: self.ix = v & 0xFFFF
        else: self.iy = v & 0xFFFF
    def get_r(self, n, p, d):
        if n == 0: return self.b
        if n == 1: return self.c
        if n == 2: return self.d
        if n == 3: return self.e
        if n == 4: return self.h if not p else (self.idxreg(p) >> 8)
        if n == 5: return self.l if not p else (self.idxreg(p) & 0xFF)
        if n == 6: return self.rb(self.hl if not p else self.idxreg(p) + d)
        return self.a
    def set_r(self, n, v, p, d):
        v &= 0xFF
        if n == 0: self.b = v
        elif n == 1: self.c = v
        elif n == 2: self.d = v
        elif n == 3: self.e = v
        elif n == 4:
            if not p: self.h = v
            else: self.set_idxreg(p, (self.idxreg(p) & 0xFF) | (v << 8))
        elif n == 5:
            if not p: self.l = v
            else: self.set_idxreg(p, (self.idxreg(p) & 0xFF00) | v)
        elif n == 6: self.wb(self.hl if not p else self.idxreg(p) + d, v)
        else: self.a = v
    def get_rp(self, n, p, af=False):
        if n == 0: return self.bc
        if n == 1: return self.de
        if n == 2: return self.hl if not p else self.idxreg(p)
        return self.af if af else self.sp
    def set_rp(self, n, v, p, af=False):
        v &= 0xFFFF
        if n == 0: self.set_bc(v)
        elif n == 1: self.set_de(v)
        elif n == 2:
            if not p: self.set_hl(v)
            else: self.set_idxreg(p, v)
        elif af: self.set_af(v)
        else: self.sp = v
    def cond(self, n):
        f = self.f
        return [not (f & Z), bool(f & Z), not (f & C), bool(f & C), not (f & PV), bool(f & PV), not (f & S), bool(f & S)][n]
    # ---- ALU ----
    def alu(self, op, v):
        a = self.a
        if op in (0, 1):    # ADD / ADC
            c = (self.f & C) if op == 1 else 0
            r = a + v + c
            self.f = (r & S) | (Z if (r & 0xFF) == 0 else 0) | (H if ((a & 15) + (v & 15) + c) > 15 else 0) | \
                     (PV if (~(a ^ v) & (a ^ r) & 0x80) else 0) | (C if r > 0xFF else 0)
            self.a = r & 0xFF
        elif op in (2, 3, 7):   # SUB / SBC / CP
            c = (self.f & C) if op == 3 else 0
            r = a - v - c
            self.f = (r & S) | (Z if (r & 0xFF) == 0 else 0) | (H if ((a & 15) - (v & 15) - c) < 0 else 0) | \
                     (PV if ((a ^ v) & (a ^ r) & 0x80) else 0) | N | (C if r < 0 else 0)
            if op != 7: self.a = r & 0xFF
        else:
            if op == 4: r = a & v; h = H
            elif op == 5: r = a ^ v; h = 0
            else: r = a | v; h = 0
            self.f = (r & S) | (Z if r == 0 else 0) | h | (PV if PAR[r] else 0)
            self.a = r
    def inc8(self, v):
        r = (v + 1) & 0xFF
        self.f = (self.f & C) | (r & S) | (Z if r == 0 else 0) | (H if (v & 15) == 15 else 0) | (PV if v == 0x7F else 0)
        return r
    def dec8(self, v):
        r = (v - 1) & 0xFF
        self.f = (self.f & C) | (r & S) | (Z if r == 0 else 0) | (H if (v & 15) == 0 else 0) | (PV if v == 0x80 else 0) | N
        return r
    def rot(self, op, v):
        c = self.f & C
        if op == 0: nc = v >> 7; r = ((v << 1) | nc) & 0xFF
        elif op == 1: nc = v & 1; r = (v >> 1) | (nc << 7)
        elif op == 2: nc = v >> 7; r = ((v << 1) | c) & 0xFF
        elif op == 3: nc = v & 1; r = (v >> 1) | (c << 7)
        elif op == 4: nc = v >> 7; r = (v << 1) & 0xFF
        elif op == 5: nc = v & 1; r = (v >> 1) | (v & 0x80)
        elif op == 6: nc = v >> 7; r = ((v << 1) | 1) & 0xFF
        else: nc = v & 1; r = v >> 1
        self.f = (r & S) | (Z if r == 0 else 0) | (PV if PAR[r] else 0) | nc
        return r
    def add16(self, a, b):
        r = a + b
        self.f = (self.f & (S | Z | PV)) | (H if ((a & 0xFFF) + (b & 0xFFF)) > 0xFFF else 0) | (C if r > 0xFFFF else 0)
        return r & 0xFFFF
    def adc16(self, a, b):
        c = self.f & C; r = a + b + c
        self.f = ((r >> 8) & S) | (Z if (r & 0xFFFF) == 0 else 0) | (H if ((a & 0xFFF) + (b & 0xFFF) + c) > 0xFFF else 0) | \
                 (PV if (~(a ^ b) & (a ^ r) & 0x8000) else 0) | (C if r > 0xFFFF else 0)
        return r & 0xFFFF
    def sbc16(self, a, b):
        c = self.f & C; r = a - b - c
        self.f = ((r >> 8) & S) | (Z if (r & 0xFFFF) == 0 else 0) | (H if ((a & 0xFFF) - (b & 0xFFF) - c) < 0 else 0) | \
                 (PV if ((a ^ b) & (a ^ r) & 0x8000) else 0) | N | (C if r < 0 else 0)
        return r & 0xFFFF
    # ---- execution ----
    def step(self):
        pc0 = self.pc
        if pc0 in self.hooks:
            self.hooks[pc0](self); return
        p = 0; d = 0
        op = self.fetch()
        if op in (0xDD, 0xFD):
            p = op; op = self.fetch()
            if op in (0xDD, 0xFD, 0xED): raise SystemExit('unsupported prefix chain at %04X' % pc0)
        if op == 0xCB:
            if p: d = self.fetch(); d = d - 256 if d > 127 else d
            op2 = self.fetch(); self.cb(op2, p, d); return
        if op == 0xED: self.ed(self.fetch(), pc0); return
        x, y, z = op >> 6, (op >> 3) & 7, op & 7
        q, pp = y & 1, y >> 1
        memop = (p and ((x == 0 and z in (4, 5, 6) and y == 6) or (x == 1 and (y == 6) != (z == 6)) or (x == 2 and z == 6)))
        if memop:
            d = self.fetch(); d = d - 256 if d > 127 else d
        if x == 0:
            if z == 0:
                if y == 0: pass
                elif y == 1: self.a, self.a2 = self.a2, self.a; self.f, self.f2 = self.f2, self.f
                elif y == 2:
                    off = self.fetch(); off = off - 256 if off > 127 else off
                    self.b = (self.b - 1) & 0xFF
                    if self.b: self.pc = (self.pc + off) & 0xFFFF
                elif y == 3:
                    off = self.fetch(); off = off - 256 if off > 127 else off; self.pc = (self.pc + off) & 0xFFFF
                else:
                    off = self.fetch(); off = off - 256 if off > 127 else off
                    if self.cond(y - 4): self.pc = (self.pc + off) & 0xFFFF
            elif z == 1:
                if q == 0: self.set_rp(pp, self.fetch16(), p)
                else:
                    r = self.add16(self.get_rp(2, p), self.get_rp(pp, p))
                    self.set_rp(2, r, p)
            elif z == 2:
                if y == 0: self.wb(self.bc, self.a)
                elif y == 1: self.a = self.rb(self.bc)
                elif y == 2: self.wb(self.de, self.a)
                elif y == 3: self.a = self.rb(self.de)
                elif y == 4: self.ww(self.fetch16(), self.get_rp(2, p))
                elif y == 5: self.set_rp(2, self.rw(self.fetch16()), p)
                elif y == 6: self.wb(self.fetch16(), self.a)
                else: self.a = self.rb(self.fetch16())
            elif z == 3:
                v = self.get_rp(pp, p)
                self.set_rp(pp, v + 1 if q == 0 else v - 1, p)
            elif z == 4: self.set_r(y, self.inc8(self.get_r(y, p, d)), p, d)
            elif z == 5: self.set_r(y, self.dec8(self.get_r(y, p, d)), p, d)
            elif z == 6:
                n = self.fetch(); self.set_r(y, n, p, d)
            else:
                a = self.a
                if y == 0: nc = a >> 7; self.a = ((a << 1) | nc) & 0xFF; self.f = (self.f & (S | Z | PV)) | nc
                elif y == 1: nc = a & 1; self.a = (a >> 1) | (nc << 7); self.f = (self.f & (S | Z | PV)) | nc
                elif y == 2: c = self.f & C; nc = a >> 7; self.a = ((a << 1) | c) & 0xFF; self.f = (self.f & (S | Z | PV)) | nc
                elif y == 3: c = self.f & C; nc = a & 1; self.a = (a >> 1) | (c << 7); self.f = (self.f & (S | Z | PV)) | nc
                elif y == 5: self.a = a ^ 0xFF; self.f |= H | N
                elif y == 6: self.f = (self.f & (S | Z | PV)) | C
                elif y == 7: self.f = (self.f & (S | Z | PV)) | (H if self.f & C else 0) | (0 if self.f & C else C)
                else: raise SystemExit('DAA not supported at %04X' % pc0)
        elif x == 1:
            if y == 6 and z == 6: self.halted = True
            else:
                if z == 6: v = self.get_r(6, p, d); self.set_r(y, v, 0, 0)       # LD r,(HL/IX+d): dest is the plain register
                elif y == 6: self.set_r(6, self.get_r(z, 0, 0), p, d)
                else: self.set_r(y, self.get_r(z, p, d), p, d)
        elif x == 2: self.alu(y, self.get_r(z, p, d))
        else:
            if z == 0:
                if self.cond(y): self.pc = self.pop()
            elif z == 1:
                if q == 0: self.set_rp(pp, self.pop(), p, af=True)
                else:
                    if pp == 0: self.pc = self.pop()
                    elif pp == 1:
                        for k in 'bcdehl': setattr(self, k, getattr(self, k + '2')) if False else None
                        for k in 'bcdehl':
                            t = getattr(self, k); setattr(self, k, getattr(self, k + '2')); setattr(self, k + '2', t)
                    elif pp == 2: self.pc = self.get_rp(2, p)
                    else: self.sp = self.get_rp(2, p)
            elif z == 2:
                n = self.fetch16()
                if self.cond(y): self.pc = n
            elif z == 3:
                if y == 0: self.pc = self.fetch16()
                elif y == 2: n = self.fetch(); self.io_out(n, self.a)
                elif y == 3: n = self.fetch(); self.a = self.io_in(n) & 0xFF
                elif y == 4:
                    t = self.rw(self.sp); self.ww(self.sp, self.get_rp(2, p)); self.set_rp(2, t, p)
                elif y == 5: t = self.de; self.set_de(self.hl); self.set_hl(t)
                elif y == 6: self.iff = 0
                elif y == 7: self.iff = 1
                else: raise SystemExit('bad opcode %02X at %04X' % (op, pc0))
            elif z == 4:
                n = self.fetch16()
                if self.cond(y): self.push(self.pc); self.pc = n
            elif z == 5:
                if q == 0: self.push(self.get_rp(pp, p, af=True))
                elif pp == 0: n = self.fetch16(); self.push(self.pc); self.pc = n
                else: raise SystemExit('bad opcode %02X at %04X' % (op, pc0))
            elif z == 6: self.alu(y, self.fetch())
            else: self.push(self.pc); self.pc = y * 8
        self.count += 1
    def cb(self, op, p, d):
        x, y, z = op >> 6, (op >> 3) & 7, op & 7
        if p:   # (IX+d): result also copied to register z if z != 6 (undocumented) - SDCC never uses it
            v = self.rb(self.idxreg(p) + d); src = None
        else: v = self.get_r(z, 0, 0)
        if x == 0:
            r = self.rot(y, v)
            if p: self.wb(self.idxreg(p) + d, r)
            else: self.set_r(z, r, 0, 0)
        elif x == 1:
            bit = v & (1 << y)
            self.f = (self.f & C) | H | (Z | PV if not bit else 0) | (S if (y == 7 and bit) else 0)
        else:
            r = v & ~(1 << y) if x == 2 else v | (1 << y)
            if p: self.wb(self.idxreg(p) + d, r)
            else: self.set_r(z, r, 0, 0)
    def ed(self, op, pc0):
        if op == 0x44: v = self.a; self.f = 0; self.a = 0; self.alu(2, v)          # NEG
        elif op in (0x46, 0x56, 0x5E): pass                                          # IM n
        elif op == 0x57: self.a = self.i; self.f = (self.f & C) | (self.a & S) | (Z if self.a == 0 else 0) | (PV if self.iff else 0)  # LD A,I
        elif op == 0x47: self.i = self.a
        elif op in (0x42, 0x52, 0x62, 0x72): self.set_hl(self.sbc16(self.hl, self.get_rp((op >> 4) & 3, 0)))
        elif op in (0x4A, 0x5A, 0x6A, 0x7A): self.set_hl(self.adc16(self.hl, self.get_rp((op >> 4) & 3, 0)))
        elif op in (0x43, 0x53, 0x63, 0x73): self.ww(self.fetch16(), self.get_rp((op >> 4) & 3, 0))
        elif op in (0x4B, 0x5B, 0x6B, 0x7B): self.set_rp((op >> 4) & 3, self.rw(self.fetch16()), 0)
        elif op in (0xB0, 0xB8, 0xA0, 0xA8):
            while True:
                self.wb(self.de, self.rb(self.hl))
                inc = 1 if op in (0xB0, 0xA0) else -1
                self.set_hl(self.hl + inc); self.set_de(self.de + inc); self.set_bc(self.bc - 1)
                self.f = (self.f & (S | Z | C)) | (PV if self.bc else 0)
                if op in (0xA0, 0xA8) or not self.bc: break
        else: raise SystemExit('unsupported ED %02X at %04X' % (op, pc0))
