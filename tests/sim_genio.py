# SPDX-License-Identifier: 0BSD
# Copyright (C) 2026 Santiago Crespo
"""
sim_genio - runs the REAL compiled image (8 KiB cartridge) instruction by instruction in a Z80 interpreter (z80core.py)
over a memory model with BANKS modelled after MAME pc2000.cpp (a simulation; MAME itself is not needed):
  window 0 0x0000-0x3FFF (port 0x00, no write expected), window 1 0x4000-0x7FFF (port 0x01, entry = data & 0x1F),
  cartridge at 0x8000 (mirrored 8 KiB x2), RAM 0xC000-0xDFFF. All three windows start in bank 0.
The timing routines tx_send / wait_bits / line_set (validated on hardware) are replaced by hooks;
crc32_run runs REAL unless fast=True (then an equivalent Python hook is used, which also allows injecting instability).
Checked during execution: PC always inside 0x8000-0x9FFF (nothing is executed from banked windows), writes only to RAM
0xC000-0xDFFF, ports written, minimum stack, keyboard and LCD.
"""
import os, re, sys, random
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'tools'))
from z80core import Z80
import gframe as g

ROOT = os.path.dirname(HERE)
GL4 = [0,1,2,3,8,9,10,11,12,13,14,15,24,25,26,27,28,29,30,31,64,65,66,67,72,73,74,75,76,77,78,79,88,89,90,91,92,93,94,95,
       4,5,6,7,16,17,18,19,20,21,22,23,32,33,34,35,36,37,38,39,68,69,70,71,80,81,82,83,84,85,86,87,96,97,98,99,100,101,102,103]

def rom_paths(target='diag'):
    name = {'diag': 'bank_diag', 'diag16': 'bank_diag16', 'dump': 'bank_dump'}[target]
    d = os.path.join(ROOT, 'build', target)
    return os.path.join(d, name + '.cart.8kb.bin'), os.path.join(d, name + '.map')

def symbols(mapfile):
    """Simbolos absolutos: .map (globales) + .sym (estaticos; offset relativo al area: 0=_CODE@0x8020, 1=_DATA@0xC000)."""
    sym = {}
    for line in open(mapfile):
        m = re.match(r'^\s+([0-9A-F]{8})\s+(\S+)\s+\S+\s*$', line)
        if m: sym[m.group(2)] = int(m.group(1), 16)
    for line in open(mapfile[:-4] + '.sym'):
        m = re.match(r'\s+(\d)\s+(\S+)\s+([0-9A-F]{8})', line)
        if m and m.group(2) not in sym: sym[m.group(2)] = (0x8020 if m.group(1) == '0' else 0xC000) + int(m.group(3), 16)
    return sym

def make_banks(kind='distinct', seed=7):
    """16 banks of 16 KiB. kind: distinct | mirror8 (bank k+8 == k) | dup (bank 5 == bank 4) | empty3 (bank 3 all FF)."""
    rnd = random.Random(seed)
    banks = [bytearray(rnd.getrandbits(8) for _ in range(0x4000)) for _ in range(16)]
    for k, b in enumerate(banks):
        b[0:2] = bytes([0xF0 + k, k])                      # easy-to-spot signature per bank
        for a in range(0x100, 0x180): b[a] = 0xC0          # estres SLIP en todos los bancos (muestras sin relevancia)
    banks[0][0:6] = b'\xF3\xED\x56\xC3\xAA\x0F'
    if kind == 'mirror8':
        for k in range(8, 16): banks[k] = bytearray(banks[k - 8])
    elif kind == 'dup': banks[5] = bytearray(banks[4])
    elif kind == 'empty3': banks[3] = bytearray(b'\xFF' * 0x4000)
    return banks

class Result: pass

def run(banks, target='diag', fast=True, port1='mame', presses=None, max_instr=300_000_000, unstable=None,
        ram_fill=0x00, sp=0xDFF0, stop_after_end=True, key_hold_polls=6, enter_when=None, verbose=False, keys=None):
    """port1: 'mame' (entrada = dato & 0x1F; >=16 -> bus libre 0xFF) | 'ignore' (escritura sin efecto) | callable(sel)->banco o None.
       unstable: (selector, n_read) -> on read number n_read (1-based, of crc32_run, per selector) one byte of the bank changes."""
    rom_path, map_path = rom_paths(target)
    rom = open(rom_path, 'rb').read(); sym = symbols(map_path)
    cpu = Z80()
    R = Result(); R.port_writes = []; R.rom_writes = []; R.pc_outside = []; R.min_sp = sp; R.max_sp_use = 0
    R.cap = bytearray(); R.screens = []; R.keys_pressed = 0; R.cur_sel = None; R.instr = 0; R.crc_calls = 0
    state = dict(sel=0, reads_by_sel={}, ad=0, mask=0, polls=0, pressed_for=0, last_prompt='', pressed_prompt=None)
    cpu.mem[0x0000:0x4000] = banks[0]; cpu.mem[0x4000:0x8000] = banks[0]
    cpu.mem[0x8000:0xA000] = rom; cpu.mem[0xA000:0xC000] = rom
    for a in range(0xC000, 0xE000): cpu.mem[a] = ram_fill
    cpu.sp = sp; cpu.pc = 0x8004
    ddram = bytearray(b' ' * 128)
    def screen():
        return [''.join((chr(ddram[GL4[r * 20 + c]]) if 32 <= ddram[GL4[r * 20 + c]] < 127 else '?') for c in range(20)) for r in range(4)]
    def hook_tx(c): R.cap.append(c.rb(sym['_serial_byte'])); c.pc = c.pop()
    def hook_wait(c): c.pc = c.pop()
    def hook_line(c): c.pc = c.pop()
    cpu.hooks[sym['_tx_send']] = hook_tx; cpu.hooks[sym['_wait_bits']] = hook_wait; cpu.hooks[sym['_line_set']] = hook_line
    def hook_crc(c):
        R.crc_calls += 1
        p, n = c.rw(sym['_c32_ptr']), c.rw(sym['_c32_len'])
        crc = c.rb(sym['_c32']) | c.rb(sym['_c32'] + 1) << 8 | c.rb(sym['_c32'] + 2) << 16 | c.rb(sym['_c32'] + 3) << 24
        crc = (~crc) & 0xFFFFFFFF
        import zlib
        if unstable and len(unstable) > 3 and unstable[3] == 'pre' and 0x4000 <= p < 0x8000:     # flip BEFORE this read
            s0 = state['sel']; k0 = state['reads_by_sel'].get(s0, 0) + 1
            if (s0, k0) == tuple(unstable[:2]): c.mem[0x4000 + unstable[2]] ^= 0x01
        data = bytes(c.mem[p:p + n])
        # (the asm internal state is the non-inverted CRC; zlib works with the inverted one)
        crc = (~zlib.crc32(data, crc) & 0xFFFFFFFF)
        for i in range(4): c.mem[sym['_c32'] + i] = (crc >> (8 * i)) & 0xFF
        if unstable and not (len(unstable) > 3 and unstable[3] == 'pre') and p >= 0x4000 and p < 0x8000:
            s = state['sel']; k = state['reads_by_sel'].get(s, 0) + 1; state['reads_by_sel'][s] = k
            if (s, k) == tuple(unstable[:2]): c.mem[0x4000 + unstable[2]] ^= 0x01
        if unstable and len(unstable) > 3 and unstable[3] == 'pre' and 0x4000 <= p < 0x8000:
            state['reads_by_sel'][state['sel']] = state['reads_by_sel'].get(state['sel'], 0) + 1
        c.pc = c.pop()
    if fast: cpu.hooks[sym['_crc32_run']] = hook_crc
    def set_window1(sel):
        state['sel'] = sel
        if port1 == 'ignore': return
        if callable(port1): b = port1(sel)
        else: b = banks[sel & 0x1F] if (sel & 0x1F) < 16 else None
        cpu.mem[0x4000:0x8000] = b if b is not None else b'\xFF' * 0x4000
    def io_out(p, v):
        if p in (0x00, 0x01, 0x03) or 0x00 <= p <= 0x05: R.port_writes.append((p, v))
        if p == 0x01: set_window1(v)
        if p == 0x0A:
            if v == 0x01: ddram[:] = b' ' * 128; state['ad'] = 0
            elif v == 0x02: state['ad'] = 0
            elif v & 0x80: state['ad'] = v & 0x7F
        elif p == 0x0B: ddram[state['ad'] & 0x7F] = v; state['ad'] = (state['ad'] + 1) & 0x7F
        elif p == 0x10:
            state['mask'] = v
            if v == 0x01: state['polls'] += 1
    # keyboard: ENTER = row 7, col 4, pressed when the LCD shows a prompt with 'ENTER=' that was not pressed yet
    def kb_in(p):
        if p != 0x10: return 0x00
        row, col = state.get('key', (7, 4))
        if state['pressed_for'] > 0 and state['mask'] == (1 << row): return 0xFF & ~(1 << col)
        return 0xFF
    cpu.io_out = io_out; cpu.io_in = kb_in
    def wh(a, v):
        if not (0xC000 <= a < 0xE000): R.rom_writes.append((a, v))
    cpu.write_hook = wh
    KEYPOS = {'\r': (7, 4)}
    for dgt, rc in (('0', (6, 0)), ('1', (1, 1)), ('2', (2, 0)), ('3', (2, 1)), ('4', (3, 0)), ('5', (3, 1)), ('6', (4, 0)), ('7', (4, 1))): KEYPOS[dgt] = rc
    if keys is not None: presses = len(keys)
    n = 0; npress = 0
    while n < max_instr:
        pc = cpu.pc
        if not (0x8000 <= pc < 0xA000): R.pc_outside.append(pc); break
        cpu.step(); n += 1
        if cpu.sp < R.min_sp: R.min_sp = cpu.sp
        if (n & 0xFFF) == 0 or state['mask'] == 0x01:
            if state['mask'] == 0x01 and state['polls'] != state.get('seen', -1):
                state['seen'] = state['polls']
                if state['pressed_for'] > 0: state['pressed_for'] -= 1
                else:
                    sc = screen(); txt = ''.join(sc)
                    prompt = '|'.join(sc)
                    if 'ENTER' in txt and prompt != state['pressed_prompt'] and (presses is None or npress < presses):
                        state['key'] = KEYPOS[keys[npress]] if keys is not None else (7, 4)
                        state['pressed_for'] = key_hold_polls; state['pressed_prompt'] = prompt; npress += 1; R.keys_pressed += 1
                        R.screens.append(sc)
        if stop_after_end and (n & 0x3FFF) == 0 and R.cap.count(0xC0) > 0 and sc_done(R):
            R.end_at = getattr(R, 'end_at', n)
            if n > R.end_at + 200_000: break      # let the final screen / idle loop run for a while
        if presses is not None and npress == presses and state['pressed_for'] == 0 and (n & 0x3FF) == 0:
            sc = screen()
            if 'ENTER' in ''.join(sc) and '|'.join(sc) != state['pressed_prompt']:
                R.settle = getattr(R, 'settle', 0) + 1
                if R.settle > 50: break          # parked in the next prompt: later stage NOT started
    R.instr = n; R.final_screen = screen(); R.ddram = ddram; R.sym = sym
    R.cpu = cpu
    return R

def sc_done(R):
    # END frame detected: scan decoded frames lazily (cheap check on the tail)
    tail = bytes(R.cap[-40:])
    if len(R.cap) < 20: return False
    d = g.Decoder(); fr = d.feed(bytes(R.cap[-400:]))
    return any(x[0] == 'frame' and x[1].type == g.T_END for x in fr)

def frames_of(cap):
    d = g.Decoder(); return d.feed(bytes(cap))

if __name__ == '__main__':
    import time
    t = time.time()
    R = run(make_banks(), fast=True)
    print('instr', R.instr, 'bytes', len(R.cap), 'frames', len(frames_of(R.cap)), 'time %.1fs' % (time.time() - t))
    print('port writes:', sorted(set(R.port_writes)), 'pc outside:', R.pc_outside[:3], 'rom writes:', R.rom_writes[:3], 'min sp %04X' % R.min_sp)
    for r in R.final_screen: print('|%s|' % r)
