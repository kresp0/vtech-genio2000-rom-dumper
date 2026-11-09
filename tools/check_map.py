#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Santiago Crespo
"""Build-time check of the memory discipline of a dumper image: all code/constants in the cartridge window
0x8000-0x9FFF below the CRC-32 table (0x9C00), variables in 0xC000-0xC3FF (below SP_MIN),
_crc_t0 == 0x9C00 (the asm uses D=0x9C), header 55 AA 59 45. Exits with code 1 if anything fails."""
import re, sys
mp, cart = sys.argv[1], sys.argv[2]
areas, syms, cur = {}, {}, None
for line in open(mp):
    m = re.match(r'^(_\w+)\s+([0-9A-F]{8})\s+([0-9A-F]{8})\s*=', line)
    if m: areas[m.group(1)] = (int(m.group(2), 16), int(m.group(3), 16))
    m = re.match(r'^\s+([0-9A-F]{8})\s+(\S+)\s+\S+\s*$', line)
    if m: syms[m.group(2)] = int(m.group(1), 16)
bad = []
code = areas.get('_CODE')
if not code or code[0] != 0x8020 or code[0] + code[1] > 0x9C00: bad.append('_CODE outside 0x8020..0x9BFF: %s' % (code,))
for a in ('_DATA', '_INITIALIZED', '_INITIALIZER', '_BSS', '_HEAP'):
    if a in areas and areas[a][1]:
        s, n = areas[a]
        if not (0xC000 <= s and s + n <= 0xC400): bad.append('%s outside 0xC000..0xC3FF: %04X+%d' % (a, s, n))
if syms.get('_crc_t0') != 0x9C00: bad.append('_crc_t0 != 0x9C00')
d = open(cart, 'rb').read()
if len(d) != 8192 or d[:4] != bytes([0x55, 0xAA, 0x59, 0x45]): bad.append('cartridge header/size')
for a, (s, n) in sorted(areas.items()):
    if n: print('  %-14s %04X-%04X (%d B)' % (a, s, s + n - 1, n))
print('check_map: ' + ('FAILED: ' + '; '.join(bad) if bad else 'OK'))
sys.exit(1 if bad else 0)
