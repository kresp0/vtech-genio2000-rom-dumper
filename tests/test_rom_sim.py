# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Santiago Crespo
"""The REAL diagnostic cartridge image executed in the Z80 simulator with MAME-like banks (see sim_genio.py)."""
import functools, struct, pytest
import gframe as g, bankdiag as bd
import sim_genio as sim

BANKS = sim.make_banks('distinct')
PARTIAL = None

@functools.lru_cache(maxsize=None)
def run_cached(kind='distinct', presses=None, port1='mame', unstable=None):
    banks = sim.make_banks(kind) if kind != 'distinct' else BANKS
    return sim.run(banks, 'diag', fast=True, presses=presses, port1=port1, unstable=unstable, stop_after_end=(presses is None))

def session_of(R):
    d = g.Decoder(); sessions = {}
    for it in d.feed(bytes(R.cap)):
        if it[0] == 'frame':
            s = sessions.setdefault(it[1].session, bd.Session(it[1].session)); s.add(it[1])
    assert len(sessions) == 1
    return next(iter(sessions.values()))

# ---------- full run on MAME-like banks ----------
def test_full_run_executes_only_from_cartridge_window():
    R = run_cached()
    assert R.pc_outside == []                 # PC never left 0x8000-0x9FFF (nothing executed from a banked window)

def test_no_writes_outside_ram_and_only_port_01():
    R = run_cached()
    assert R.rom_writes == []                 # nothing written below 0xC000 or above 0xDFFF
    assert {p for p, v in R.port_writes} == {0x01}            # ports 0x00 and 0x03 never written
    assert all(0 <= v <= 15 for p, v in R.port_writes)         # only selectors 0..15

def test_stack_and_variables_stay_in_ram():
    R = run_cached()
    assert 0xDFF0 - R.min_sp < 256            # tiny stack use

def test_record_count_and_stage_order():
    s = session_of(run_cached())
    assert s.end and s.end['nrecords'] == len(s.records) == 38 and s.end['sp_ok']
    assert [x['stage'] for x in s.stage_ends] == list('ABCD')
    assert [r['stage'] for r in s.records] == list('AA') + ['B'] + ['C', 'C'] + ['D'] * 33
    assert s.missing_seqs() == [] and s.dups == 0

def test_every_selector_crc_matches_the_bank_in_the_rom_model():
    s = session_of(run_cached())
    for r in s.records:
        if r['wrote']:
            b = BANKS[r['selector']]
            assert r['crc32_whole'] == g.crc32(bytes(b)), r
            assert r['crc32_quarters'] == [g.crc32(bytes(b[i * 0x1000:(i + 1) * 0x1000])) for i in range(4)]
            assert r['quarters_combine_ok']
            assert r['samples'][0] == bytes(b[0:16]).hex() and r['samples'][3] == bytes(b[0x3FF0:0x4000]).hex()
            assert r['crc32_window0_head'] == g.crc32(bytes(BANKS[0][:0x100]))
        else:
            assert r['crc32_whole'] == g.crc32(bytes(BANKS[0]))

def test_sweep_order_forward_backward_and_final_restore():
    s = session_of(run_cached())
    d = [r['selector'] for r in s.records if r['stage'] == 'D']
    assert d == list(range(16)) + list(range(15, -1, -1)) + [0]
    assert s.records[-1]['selector'] == 0          # window 0x4000 returned to selector 0 (the boot value) at the end

def test_end_state_window_equals_baseline():
    R = run_cached()
    assert bytes(R.cpu.mem[0x4000:0x8000]) == bytes(BANKS[0]) and bytes(R.cpu.mem[0x0000:0x4000]) == bytes(BANKS[0])

def test_analysis_declares_mame_like():
    s = session_of(run_cached()); rep = bd.analyze(s, g.crc32(bytes(BANKS[0])))
    assert rep['mame_like'] and rep['complete'] and rep['flags'] == []
    assert rep['selectors']['0']['equals_previous_partial'] and rep['selectors']['0']['equals_baseline_window1']
    assert rep['baseline']['windows_identical']

def test_lcd_shows_stage_selector_and_progress():
    R = run_cached()
    assert any('ENTER=' in (sc[1] + sc[2]) for sc in R.screens)
    assert R.final_screen[0].startswith('BANK DIAG DONE') and 'recs 038' in R.final_screen[1]

def test_stream_is_frames_only_no_stray_bytes():
    R = run_cached(); d = g.Decoder(); items = d.feed(bytes(R.cap))
    assert all(it[0] == 'frame' for it in items) and len(items) == 44
    # every byte between delimiters belongs to a valid frame: total = sum of re-encoded lengths
    assert sum(len(it[1].raw) for it in items) > 0

# ---------- staged safety: stopping after a stage means no later write happened ----------
@pytest.mark.parametrize('presses,writes', [(1, []), (2, [0]), (3, [0, 1, 0])])
def test_staged_writes(presses, writes):
    R = run_cached('distinct', presses, 'mame', None) if presses is not None else None
    # the run stops only by instruction budget: it parks in the prompt loop
    assert [v for p, v in R.port_writes] == writes
    assert R.rom_writes == [] and R.pc_outside == []

# ---------- different hardware behaviours ----------
def test_mirrored_banks_detected():
    R = run_cached('mirror8'); s = session_of(R); rep = bd.analyze(s)
    assert not rep['mame_like'] and [0, 8] in rep['identical_groups'] and any('IDENTICAL' in f for f in rep['flags'])

def test_duplicate_bank_detected():
    s = session_of(run_cached('dup')); rep = bd.analyze(s)
    assert [4, 5] in rep['identical_groups']

def test_empty_bank_detected():
    s = session_of(run_cached('empty3')); rep = bd.analyze(s)
    assert rep['selectors']['3']['empty'] == 'FF' and any('empty banks' in f for f in rep['flags'])

def test_selector_register_ignored_detected():
    s = session_of(run_cached('distinct', None, 'ignore')); rep = bd.analyze(s)
    assert len(rep['identical_groups']) == 1 and len(rep['identical_groups'][0]) == 16 and not rep['mame_like']

@pytest.mark.parametrize('off', [0x0010, 0x2345])
def test_unstable_read_detected(off):
    # 0x0010: byte changes after the first quarter was read -> quarters and whole-bank CRC disagree inside one record
    # 0x2345: byte changes in the window copy -> forward and backward sweep readings of the same selector differ
    s = session_of(run_cached('distinct', None, 'mame', (2, 1, off))); rep = bd.analyze(s)
    assert not rep['selectors']['2']['stable']
    assert any('UNSTABLE' in f for f in rep['flags']) and not rep['mame_like']


def test_full_run_with_real_asm_crc32_identical_to_fast_run():
    """Same run, but crc32_run executes the real assembly (no Python hook): byte-identical frame stream."""
    slow = sim.run(BANKS, 'diag', fast=False, stop_after_end=True)
    assert bytes(slow.cap) == bytes(run_cached().cap)
    assert slow.pc_outside == [] and slow.rom_writes == []
