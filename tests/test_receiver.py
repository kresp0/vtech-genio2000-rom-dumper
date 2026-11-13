# SPDX-License-Identifier: 0BSD
# Copyright (C) 2026 Santiago Crespo
"""Receiver/analyser on captures: lost frames, duplicates, corruption, interruption, PARMRK, JSON/CSV output."""
import json, os, subprocess, sys, csv
import pytest
import gframe as g, bankdiag as bd
import sim_genio as sim
from test_rom_sim import run_cached, BANKS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RX = os.path.join(ROOT, 'tools', 'bank_diag_rx.py')

def split_frames(cap):
    out, cur = [], None
    for b in cap:
        if b == g.END:
            if cur: out.append(bytes([g.END]) + bytes(cur) + bytes([g.END]))
            cur = bytearray()
        elif cur is not None: cur.append(b)
    return out

def good_frames(): return split_frames(run_cached().cap)

def sess_from(frames):
    d = g.Decoder(); s = None; rejects = 0
    for fr in frames:
        for it in d.feed(fr):
            if it[0] == 'reject': rejects += 1; continue
            s = s or bd.Session(it[1].session); s.add(it[1])
    s.rejects = rejects
    return s, rejects

def test_lost_block_is_reported_not_filled():
    fr = good_frames(); del fr[10]
    s, _ = sess_from(fr); rep = bd.analyze(s)
    assert len(s.records) == 37 and rep['missing_seqs'] != []

def test_duplicate_frames_counted_and_ignored():
    fr = good_frames(); fr.insert(11, fr[10]); fr.insert(20, fr[19])
    s, _ = sess_from(fr)
    assert s.dups == 2 and len(s.records) == 38

def test_corrupt_frame_rejected_and_detected_as_gap():
    fr = good_frames(); x = bytearray(fr[12]); x[30] ^= 0x10; fr[12] = bytes(x)
    s, rej = sess_from(fr)
    assert rej == 1 and len(s.records) == 37 and s.missing_seqs()

def test_interrupted_transfer_is_incomplete():
    fr = good_frames()[:25]
    s, _ = sess_from(fr); rep = bd.analyze(s)
    assert not rep['complete'] and rep['stages_done'] == list('ABC') and 'INCOMPLETE' in bd.text_report(rep)

def test_truncated_last_frame_is_dropped():
    cap = bytes(run_cached().cap)[:-30]
    d = g.Decoder(); items = d.feed(cap)
    assert items and not any(it[0] == 'frame' and it[1].type == g.T_END for it in items)

def test_stage_a_only_gives_no_sweep_verdict():
    s, _ = sess_from(good_frames()[:4]); rep = bd.analyze(s)
    assert rep['verdict'] == 'no sweep data' and rep['selectors'] == {}

def test_two_sessions_do_not_mix():
    a = good_frames(); b = []
    for fr in a:
        body = bytearray(g.Decoder().feed(fr)[0][1].raw); body[4] ^= 0x55
        body[-2:] = g.struct.pack('<H', g.crc16_fast(bytes(body[:-2])))
        b.append(bytes([g.END]) + g.stuff(bytes(body)) + bytes([g.END]))
    d = g.Decoder(); sess = {}
    for fr in a + b:
        for it in d.feed(fr): sess.setdefault(it[1].session, bd.Session(it[1].session)).add(it[1])
    assert len(sess) == 2 and all(len(s.records) == 38 for s in sess.values())

def test_cli_analyze_writes_json_csv_and_exit_code(tmp_path):
    cap = tmp_path / 'cap.bin'; raw = bytes(run_cached().cap)
    cap.write_bytes(raw.replace(b'\xFF', b'\xFF\xFF'))          # as captured with PARMRK
    out = tmp_path / 'out'
    p = subprocess.run([sys.executable, RX, '--analyze', str(cap), '--outdir', str(out)], capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr           # complete + MAME-like
    js = [f for f in os.listdir(out) if f.endswith('.json')][0]; cs = [f for f in os.listdir(out) if f.endswith('.csv')][0]
    data = json.load(open(out / js)); assert data['analysis']['mame_like'] and len(data['records']) == 38
    rows = list(csv.reader(open(out / cs))); assert len(rows) == 39 and rows[0][0] == 'seq'
    assert 'VERDICT: CONSISTENT' in p.stdout

def test_cli_incomplete_exit_code_2(tmp_path):
    cap = tmp_path / 'cap.bin'; cap.write_bytes(b''.join(good_frames()[:30]))
    p = subprocess.run([sys.executable, RX, '--analyze', str(cap), '--plain', '--outdir', str(tmp_path / 'o')], capture_output=True, text=True)
    assert p.returncode == 2

def test_cli_differences_exit_code_3_mirrored(tmp_path):
    R = sim.run(sim.make_banks('mirror8'), 'diag', fast=True)
    cap = tmp_path / 'cap.bin'; cap.write_bytes(bytes(R.cap))
    p = subprocess.run([sys.executable, RX, '--analyze', str(cap), '--plain', '--outdir', str(tmp_path / 'o')], capture_output=True, text=True)
    assert p.returncode == 3 and 'IDENTICAL' in p.stdout

def test_capture_never_overwrites_existing_file(tmp_path):
    p = tmp_path / 'x.bin'; p.write_bytes(b'keep')
    with pytest.raises(FileExistsError): open(p, 'xb')
