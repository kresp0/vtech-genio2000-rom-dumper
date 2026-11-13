# SPDX-License-Identifier: 0BSD
# Copyright (C) 2026 Santiago Crespo
"""Build artefacts: SDCC output and AT28C256 images. Run ./build.sh all first. Never programs any chip."""
import hashlib, os, re, subprocess
import pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
B = os.path.join(ROOT, 'build', 'diag')

def rd(n): return open(os.path.join(B, n), 'rb').read()

def test_cart_image_size_and_header():
    c = rd('bank_diag.cart.8kb.bin')
    assert len(c) == 8192 and c[:4] == bytes([0x55, 0xAA, 0x59, 0x45]) and c[4] == 0xC3     # sig + autostart + JP

def test_at28c256_image_is_four_mirrored_copies():
    c, m = rd('bank_diag.cart.8kb.bin'), rd('bank_diag_mirrored_AT28C256_32K.bin')
    assert len(m) == 32768 and m == c * 4

def test_code_fits_below_crc_table():
    mp = open(os.path.join(B, 'bank_diag.map')).read()
    m = re.search(r'_CODE\s+([0-9A-F]{8})\s+([0-9A-F]{8})', mp)
    assert int(m.group(1), 16) + int(m.group(2), 16) <= 0x9C00

def test_no_internal_rom_or_port_writes_in_code_besides_bank1():
    """Binary scan: OUT (n),A (D3 nn) never targets ports 0x00/0x03. Informative, may give false positives."""
    c = rd('bank_diag.cart.8kb.bin')[:0x1C00]
    ports = {c[i + 1] for i in range(len(c) - 1) if c[i] == 0xD3}
    assert 0x00 not in ports and 0x03 not in ports
    assert 0x01 in ports

def test_check_map_tool_passes():
    r = subprocess.run(['python3', os.path.join(ROOT, 'tools', 'check_map.py'), os.path.join(B, 'bank_diag.map'), os.path.join(B, 'bank_diag.cart.8kb.bin')], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout

def test_build_is_reproducible(tmp_path):
    """Rebuild in a private directory and compare hashes."""
    import shutil
    for d in ('src', 'tools', 'third_party'): shutil.copytree(os.path.join(ROOT, d), tmp_path / d)
    shutil.copy(os.path.join(ROOT, 'build.sh'), tmp_path / 'build.sh')
    r = subprocess.run(['bash', str(tmp_path / 'build.sh'), 'diag'], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / 'build/diag/bank_diag_mirrored_AT28C256_32K.bin').read_bytes() == rd('bank_diag_mirrored_AT28C256_32K.bin')


import pytest
@pytest.mark.parametrize('target,name', [('diag', 'bank_diag'), ('diag16', 'bank_diag16'), ('dump', 'bank_dump')])
def test_all_roms_at28c256_and_bank_port_discipline(target, name):
    d = os.path.join(ROOT, 'build', target)
    c = open(os.path.join(d, name + '.cart.8kb.bin'), 'rb').read(); m = open(os.path.join(d, name + '_mirrored_AT28C256_32K.bin'), 'rb').read()
    assert len(c) == 8192 and c[:4] == bytes([0x55, 0xAA, 0x59, 0x45]) and len(m) == 32768 and m == c * 4
    code = c[:0x1C00]
    ports = {code[i + 1] for i in range(len(code) - 1) if code[i] == 0xD3}
    assert ports.isdisjoint({0x00, 0x02, 0x03, 0x04, 0x05}) and 0x01 in ports       # only the window-1 bank register among the bank ports
    r = subprocess.run(['python3', os.path.join(ROOT, 'tools', 'check_map.py'), os.path.join(d, name + '.map'), os.path.join(d, name + '.cart.8kb.bin')], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
    assert open(os.path.join(ROOT, 'release', name + '_AT28C256_32K.bin'), 'rb').read() == m

def test_validated_diag_rom_unchanged():
    """The ROM already validated on hardware (session 010C) must stay byte-identical."""
    import hashlib
    h = hashlib.sha256(open(os.path.join(B, 'bank_diag_mirrored_AT28C256_32K.bin'), 'rb').read()).hexdigest()
    assert h == 'e9fab7b61319fb50aa7e8c0319e4bd1f0e329005a73bbb84e5eca55d8767b6ad'
