# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Santiago Crespo
"""The REAL asm routine crc32_run (not the hook) against zlib, including the 16 KiB of a bank and counter wrap-around."""
import os, random, zlib
import pytest
import sim_genio as sim
from z80core import Z80

def run_routine(data, base, init=(0xFF, 0xFF, 0xFF, 0xFF)):
    rom_path, map_path = sim.rom_paths('diag'); sym = sim.symbols(map_path)
    cpu = Z80()
    rom = open(rom_path, 'rb').read(); cpu.mem[0x8000:0xA000] = rom
    cpu.mem[base:base + len(data)] = data
    for i, v in enumerate(init): cpu.mem[sym['_c32'] + i] = v
    cpu.mem[sym['_c32_ptr']] = base & 0xFF; cpu.mem[sym['_c32_ptr'] + 1] = base >> 8
    cpu.mem[sym['_c32_len']] = len(data) & 0xFF; cpu.mem[sym['_c32_len'] + 1] = len(data) >> 8
    cpu.sp = 0xDFF0; cpu.ww(0xDFF0, 0x0000)
    cpu.pc = sym['_crc32_run']; n = 0
    sp0 = cpu.sp
    while True:
        cpu.step(); n += 1
        if cpu.pc == 0x0000 and cpu.sp == sp0 + 2: break
        assert n < 5_000_000
    st = bytes(cpu.mem[sym['_c32']:sym['_c32'] + 4])
    return (~int.from_bytes(st, 'little')) & 0xFFFFFFFF, cpu

def test_table_planes_in_rom_at_9C00():
    rom = open(sim.rom_paths('diag')[0], 'rb').read()
    for p in range(4):
        for i in (0, 1, 2, 255):
            c = i
            for _ in range(8): c = (c >> 1) ^ 0xEDB88320 if c & 1 else c >> 1
            assert rom[0x1C00 + 256 * p + i] == (c >> (8 * p)) & 0xFF

@pytest.mark.parametrize('n', [1, 2, 255, 256, 257, 4096])
def test_crc32_asm_matches_zlib(n):
    data = bytes(random.Random(n).getrandbits(8) for _ in range(n))
    got, _ = run_routine(data, 0x4000)
    assert got == zlib.crc32(data) & 0xFFFFFFFF

def test_crc32_asm_check_value_and_register_preservation():
    got, cpu = run_routine(b'123456789', 0x4000)
    assert got == 0xCBF43926

def test_crc32_asm_full_bank_16384_bytes_and_no_writes_to_data():
    data = bytes(random.Random(99).getrandbits(8) for _ in range(0x4000))
    writes = []
    rom_path, map_path = sim.rom_paths('diag')
    got, cpu = run_routine(data, 0x4000)
    assert got == zlib.crc32(data) & 0xFFFFFFFF
    assert bytes(cpu.mem[0x4000:0x8000]) == data                 # the routine only reads the window
