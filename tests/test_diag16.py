# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Santiago Crespo
"""bank_diag16 (selectors 0x10..0x1F) in the simulator + analysis."""
import functools, pytest
import gframe as g, bankdiag as bd
import sim_genio as sim

B16 = sim.make_banks('distinct')                       # 16 bancos distintos: "5 bits decodificados"
B8 = [B16[k & 7] for k in range(16)]                   # 8 bancos, selector & 7 (lo observado en 0..15)
REF = {k: g.crc32(bytes(B16[k])) for k in range(8)}

def port_mask3(sel): return B16[sel & 7]
def port_mask5(sel): return B16[sel & 15] if sel < 16 else None       # 0x10.. -> vacio (bus libre)

@functools.lru_cache(maxsize=None)
def run16(model='mask3', presses=None):
    port = {'mask3': port_mask3, 'mask4': lambda s: B16[s & 15], 'open': port_mask5}[model]
    return sim.run(B16, 'diag16', fast=True, presses=presses, port1=port, stop_after_end=(presses is None))

def sess(R):
    d = g.Decoder(); s = None
    for it in d.feed(bytes(R.cap)):
        if it[0] == 'frame':
            s = s or bd.Session(it[1].session); s.add(it[1])
    return s

def test_full_run_safety_properties():
    R = run16()
    assert R.pc_outside == [] and R.rom_writes == []
    assert {p for p, v in R.port_writes} == {0x01}
    vals = [v for p, v in R.port_writes]
    assert set(vals) == {0} | set(range(0x10, 0x20))           # only 0 (restore) and 0x10..0x1F; never 1..15
    assert vals[:2] == [0x10, 0] and vals[2:4] == [0x11, 0]       # one untested selector at a time, always followed by restore

def test_every_untested_selector_is_followed_by_restore_to_zero():
    R = run16(); vals = [v for p, v in R.port_writes]
    for i in range(0, len(vals), 2): assert vals[i] >= 0x10 and vals[i + 1] == 0

def test_record_count_and_order():
    s = sess(run16())
    assert s.end and len(s.records) == 66 and [x['stage'] for x in s.stage_ends] == list('ABCD') and s.start['tool'] == g.TOOL_DIAG16
    sels = [r['selector'] for r in s.records if r['stage'] in 'BCD']
    assert sels[0::2] == list(range(0x10, 0x20)) + list(range(0x1F, 0x0F, -1))        # forward then backward
    assert all(x == 0 for x in sels[1::2])

def test_three_bit_decode_detected_as_repeats_of_0_7():
    rep = bd.analyze16(sess(run16('mask3')), REF)
    assert rep['three_bit_decode_consistent'] and rep['flags'] == [] and rep['restore_checks']['all_equal_baseline']
    assert rep['selectors']['16']['equals_reference_bank'] == [0] and rep['selectors']['31']['equals_reference_bank'] == [7]
    assert 'repeat banks 0-7 exactly' in rep['verdict'] and 'do NOT change' in rep['verdict']

def test_four_bit_decode_shows_new_content_candidates_are_not_flagged_as_repeat():
    # selector 0x10 -> bank 0, ... : with &15 the banks 8..15 are NEW content vs the 0..7 reference
    rep = bd.analyze16(sess(run16('mask4')), REF)
    assert not rep['three_bit_decode_consistent'] and rep['new_content_groups'] and any('NEW content' in f for f in rep['flags'])

def test_open_bus_detected_as_empty():
    rep = bd.analyze16(sess(run16('open')), REF)
    assert all(d['empty'] == 'FF' for d in rep['selectors'].values()) and any('filler' in f for f in rep['flags'])

def test_report_text_and_cli_exit_codes(tmp_path):
    import subprocess, sys, os
    cap = tmp_path / 'c.bin'; cap.write_bytes(bytes(run16('mask3').cap))
    # the CLI uses the embedded reference (session 010C CRCs): our simulated banks differ, so a diff verdict (exit 3) is correct here
    rx = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools', 'bank_diag_rx.py')
    p = subprocess.run([sys.executable, rx, '--analyze', str(cap), '--plain', '--outdir', str(tmp_path / 'o')], capture_output=True, text=True)
    assert p.returncode == 3 and 'VERDICT' in p.stdout
    ref = tmp_path / 'ref.json'
    import json
    sel = {str(k): dict(crc32=['%08X' % v], stable=True) for k, v in REF.items()}
    ref.write_text(json.dumps(dict(analysis=dict(selectors=sel))))
    p = subprocess.run([sys.executable, rx, '--analyze', str(cap), '--plain', '--outdir', str(tmp_path / 'o2'), '--reference', str(ref)], capture_output=True, text=True)
    assert p.returncode == 0 and 'repeat banks 0-7 exactly' in p.stdout

@pytest.mark.parametrize('presses,writes', [(1, []), (2, [0x10, 0])])
def test_staged_gating(presses, writes):
    R = run16('mask3', presses)
    assert [v for p, v in R.port_writes] == writes and R.rom_writes == []

def test_mid_sweep_interruption_is_incomplete():
    R = run16(); cut = bytes(R.cap)[:len(R.cap) // 4]
    d = g.Decoder(); s = None
    for it in d.feed(cut):
        if it[0] == 'frame': s = s or bd.Session(it[1].session); s.add(it[1])
    rep = bd.analyze16(s, REF)
    assert not rep['complete'] and 'incomplete sweep' in ' '.join(rep['flags'])

def test_unstable_untested_selector_flagged():
    R = sim.run(B16, 'diag16', fast=True, port1=port_mask3, unstable=(0x12, 1, 0x0010))
    rep = bd.analyze16(sess(R), REF)
    assert not rep['selectors']['18']['stable'] and any('UNSTABLE' in f for f in rep['flags'])
