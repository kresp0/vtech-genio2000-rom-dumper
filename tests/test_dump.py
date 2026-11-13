# SPDX-License-Identifier: 0BSD
# Copyright (C) 2026 Santiago Crespo
"""bank_dump in the simulator + receiver + verifier (two independent sessions, losses, duplicates, conflicts, ordering)."""
import functools, json, os, random, subprocess, sys
import pytest
import gframe as g, dumpsession as ds
import bank_dump_rx as rx, bank_dump_verify as vf
import sim_genio as sim

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANKS = sim.make_banks('mirror8')         # selectors 0..7 distinct, 8..15 repeat 0..7 (what the real Genio showed)
def port1(sel): return BANKS[sel & 7]

@functools.lru_cache(maxsize=None)
def run_dump(keys=('\r',), unstable=None, seed_ram=0x00):
    return sim.run(BANKS, 'dump', fast=True, keys=list(keys), port1=port1, unstable=unstable, ram_fill=seed_ram)

def frames(cap):
    out, cur = [], None
    for b in cap:
        if b == g.END:
            if cur: out.append(bytes([g.END]) + bytes(cur) + bytes([g.END]))
            cur = bytearray()
        elif cur is not None: cur.append(b)
    return out

def good(): return list(_good())
@functools.lru_cache(maxsize=None)
def _good(): return tuple(frames(run_dump().cap))
def decode(frs, plain=True): return ds.decode_capture(b''.join(frs), plain)[0]
def ftype(fr): return g.Decoder().feed(fr)[0][1]

# ---------- ROM in the simulator ----------
def test_rom_safety_properties():
    R = run_dump()
    assert R.pc_outside == [] and R.rom_writes == []
    vals = [v for p, v in R.port_writes]
    assert {p for p, v in R.port_writes} == {0x01} and vals == list(range(8)) + [0]       # 0..7 in order, then restore to 0
    assert R.final_screen[0].startswith('BANK DUMP DONE') and 'restore sel0: OK' in R.final_screen[2]

def test_every_bank_received_exactly_and_verified_by_rom_crc():
    (s,) = decode(good())
    assert s.end and s.end['banks_sent'] == 8 and s.end['restore_ok'] and s.end['sp_ok']
    assert s.start['selectors'] == list(range(8)) and s.start['block'] == 128 and s.start['nblocks'] == 128 and s.start['mode'] == 0
    assert s.start['baseline_crc32'] == g.crc32(bytes(BANKS[0]))
    for k in range(8):
        assert s.banks[k].status() == 'COMPLETE_VERIFIED_BY_ROM_CRC' and s.banks[k].data() == bytes(BANKS[k])
    assert s.missing_seqs() == [] and s.dups == 0 and s.rejects == 0

def test_frame_count_and_exact_bank_size():
    fr = good(); assert len(fr) == 1 + 8 * (1 + 128 + 1) + 1
    (s,) = decode(fr); assert all(len(s.banks[k].data()) == 16384 for k in range(8))

def test_single_bank_mode():
    R = run_dump(('3',)); (s,) = decode(frames(R.cap))
    assert s.start['mode'] == 1 and s.start['selectors'] == [3] and list(s.banks) == [3] and s.banks[3].data() == bytes(BANKS[3])
    assert [v for p, v in R.port_writes] == [3, 0]

def test_unstable_bank_read_detected_by_rom_crc_mismatch():
    R = run_dump(('\r',), (3, 1, 0x1234, 'pre')); (s,) = decode(frames(R.cap))
    assert s.banks[3].status() == 'COMPLETE_ROM_CRC_MISMATCH' and s.banks[2].status() == 'COMPLETE_VERIFIED_BY_ROM_CRC'

# ---------- transmission damage ----------
def test_lost_block_is_missing_not_zero_filled(tmp_path):
    fr = good(); idx = [i for i, f in enumerate(fr) if ftype(f).type == g.T_DATA and ftype(f).bank == 2 and ftype(f).off == 5 * 128][0]; del fr[idx]
    (s,) = decode(fr); b = s.banks[2]
    assert b.missing == [5] and b.data() is None and b.status() == 'INCOMPLETE'
    d, ok = rx.write_session(s, str(tmp_path), 'T')
    assert not ok and not os.path.exists(os.path.join(d, 'bank_2.bin')) and os.path.exists(os.path.join(d, 'bank_2.PARTIAL.bin'))
    assert json.load(open(os.path.join(d, 'bank_2.mask.json')))['missing'] == [5]
    assert os.path.exists(os.path.join(d, 'bank_3.bin'))                       # undamaged banks still saved individually

def test_duplicate_frames_counted_and_identical_blocks_ignored():
    fr = good(); fr.insert(40, fr[39]); fr.insert(90, fr[89])
    (s,) = decode(fr); assert s.dups == 2 and s.banks[0].status() == 'COMPLETE_VERIFIED_BY_ROM_CRC'

def test_corrupt_frame_rejected_by_crc():
    fr = good(); x = bytearray(fr[50]); x[40] ^= 0x08; fr[50] = bytes(x)
    sessions, rej, _ = ds.decode_capture(b''.join(fr), True)
    assert rej == 1 and sessions[0].banks[0].missing

def test_conflicting_duplicate_block_is_flagged_not_resolved():
    fr = good(); orig = ftype(fr[10]); assert orig.type == g.T_DATA
    alt = g.build(g.T_DATA, orig.session, orig.bank, orig.seq + 5000, orig.src, orig.off, bytes([orig.payload[0] ^ 1]) + orig.payload[1:])
    (s,) = decode(fr + [alt]); b = s.banks[orig.bank]
    assert b.dup_conflict == [orig.off // 128] and b.data() is None and b.status() == 'INCOMPLETE'

def test_interrupted_transfer_has_no_end_and_incomplete_banks():
    fr = good()[:300]; (s,) = decode(fr)
    assert s.end is None and s.banks[0].status() == 'COMPLETE_VERIFIED_BY_ROM_CRC' and s.banks[2].status() in ('INCOMPLETE', 'ABSENT')

def test_overflow_fields_rejected():
    (s0,) = decode(good())
    sid = s0.sid; base = list(good()[:1])
    bad = [g.build(g.T_DATA, sid, 0, 9000, 0x4000, 128 * 128, bytes(128)),            # block index past the bank
           g.build(g.T_DATA, sid, 0, 9001, 0x4000, 64, bytes(128)),                   # offset not block aligned
           g.build(g.T_DATA, sid, 0, 9002, 0x4000, 0, bytes(100)),                    # wrong length
           g.build(g.T_DATA, sid, 0, 9003, 0x8000, 0, bytes(128)),                    # wrong source window
           g.build(g.T_DATA, sid, 9, 9004, 0x4000, 0, bytes(128))]                    # selector not in this dump
    (s,) = decode(base + bad); assert s.rejects == 5 and not s.banks

def test_start_lost_still_decodes_with_default_layout():
    fr = good()[1:]; (s,) = decode(fr); assert s.start is None and s.banks[0].status() == 'COMPLETE_VERIFIED_BY_ROM_CRC'

def test_same_session_id_twice_in_one_capture_opens_new_session():
    fr = good(); sessions = decode(fr + fr); assert len(sessions) == 2 and sessions[0].banks[0].data() == sessions[1].banks[0].data()

# ---------- verification of two independent sessions ----------
def renumber(frs, sid):
    """Same frames with another session id (what a real second run looks like: the ROM's free-running counter differs)."""
    out = []
    for fr in frs:
        f = ftype(fr); out.append(g.build(f.type, sid, f.bank, f.seq, f.src, f.off, f.payload))
    return out

@functools.lru_cache(maxsize=None)
def _third(fill): return tuple(renumber(frames(sim.run(BANKS, 'dump', fast=True, keys=['\r'], port1=port1, ram_fill=fill).cap), 0x1000 + fill))
def second_run():
    """Independent second run: different RAM contents at start. Returns a fresh list each time (tests mutate it)."""
    return list(_third(0xA5))

def labelled(*caps):
    out = []
    for i, c in enumerate(caps): out += [('cap%d:%04X#%d' % (i, s.sid, 1), s) for s in decode(c)]
    return out

def test_one_session_is_not_verified():
    res = vf.verify(labelled(good()))
    assert not res['all_verified'] and all(b['blocks']['SINGLE'] == 128 and not b['verified'] and b['class_A_received_clean_by_session'] for b in res['banks'].values())

def test_two_independent_sessions_verify_all_banks_in_selector_order(tmp_path):
    a, b = good(), second_run()
    res = vf.verify(labelled(a, b), ref_partial=bytes(BANKS[0]) + bytes(BANKS[0]))
    assert res['all_verified'] and all(x['class_B_two_independent_reads_match'] for x in res['banks'].values())
    assert res['previous_partial']['bank0_equals_partial_0000_3FFF'] and res['previous_partial']['bank0_equals_partial_4000_7FFF']
    man = vf.write_final(res, str(tmp_path / 'out'))
    img = open(os.path.join(tmp_path, 'out', man['image']['file']), 'rb').read()
    assert len(img) == 8 * 16384 and img == b''.join(bytes(BANKS[k]) for k in range(8))
    assert man['banks']['0']['file'] == 'bank_0.bin' and '128K' in man['image']['file']
    assert 'NOT determined' in man['verdict'] and 'NOT determined' in man['NOTE']
    assert 'candidate' in man['image']['file'] and man['image']['sha256'] == ds.sha(img)['sha256']

def test_transmission_order_does_not_decide_physical_order(tmp_path):
    a = good(); head, tail = a[:1], a[-1:]; body = a[1:-1]
    groups = [body[i * 130:(i + 1) * 130] for i in range(8)]
    shuffled = head + [f for k in (5, 2, 7, 0, 3, 6, 1, 4) for f in groups[k]] + tail
    res = vf.verify(labelled(shuffled, second_run()))
    assert res['all_verified']
    man = vf.write_final(res, str(tmp_path / 'o')); img = open(os.path.join(tmp_path, 'o', man['image']['file']), 'rb').read()
    assert img == b''.join(bytes(BANKS[k]) for k in range(8))

def test_block_level_combination_of_partial_sessions():
    """Three sessions, each missing a different block: every block still has two agreeing independent receptions."""
    def drop(fr, bank, blk):
        return [f for f in fr if not (ftype(f).type == g.T_DATA and ftype(f).bank == bank and ftype(f).off == blk * 128)]
    s1 = drop(good(), 1, 3); s2 = drop(second_run(), 1, 9); s3 = drop(list(_third(0x5A)), 1, 77)
    res = vf.verify(labelled(s1, s2, s3)); assert res['all_verified'] and res['banks'][1]['blocks']['VERIFIED'] == 128
    res2 = vf.verify(labelled(s1, s2)); assert not res2['all_verified'] and res2['banks'][1]['blocks']['SINGLE'] == 2

def test_conflict_between_sessions_is_not_resolved_by_majority(tmp_path):
    a, b = good(), second_run()
    i = [k for k, f in enumerate(b) if ftype(f).type == g.T_DATA and ftype(f).bank == 4 and ftype(f).off == 10 * 128][0]; o = ftype(b[i])
    b[i] = g.build(g.T_DATA, o.session, o.bank, o.seq, o.src, o.off, bytes([o.payload[0] ^ 0xFF]) + o.payload[1:])
    res = vf.verify(labelled(a, b))
    assert res['conflicts'] and res['banks'][4]['class_D_conflicting_reads'] and res['banks'][4]['blocks']['CONFLICT'] == [10] and not res['banks'][4]['verified']
    man = vf.write_final(res, str(tmp_path / 'c'))
    assert 'image' not in man and not os.path.exists(os.path.join(tmp_path, 'c', 'bank_4.bin')) and 'INCOMPLETE' in man['verdict']

def test_unreadable_bank_class_E_and_partial_flag(tmp_path):
    a = [f for f in good() if ftype(f).bank != 6]; b = [f for f in second_run() if ftype(f).bank != 6]
    res = vf.verify(labelled(a, b)); assert res['banks'][6]['class_E_unreadable'] and not res['all_verified']
    man = vf.write_final(res, str(tmp_path / 'p'), allow_partial=True)
    assert os.path.exists(os.path.join(tmp_path, 'p', 'firmware_PARTIAL_UNVERIFIED.bin')) and 'image' not in man
    assert '6' in json.load(open(os.path.join(tmp_path, 'p', 'firmware_PARTIAL_UNVERIFIED.mask.json')))

def test_identical_banks_reported_as_mirror_class_C():
    banks = [bytearray(b) for b in BANKS[:8]]; banks[5] = bytearray(banks[4])
    cap = frames(sim.run(banks + list(BANKS[8:]), 'dump', fast=True, keys=['\r'], port1=lambda s: banks[s & 7]).cap)
    res = vf.verify(labelled(cap, cap[:]))          # same capture twice is NOT independent: still only one session label each? -> labels differ, content equal
    assert res['banks'][4]['class_C_identical_to_selectors'] == [5] and res['banks'][5]['class_C_identical_to_selectors'] == [4]

def test_unstable_rom_crc_blocks_verification():
    """Blocks agree between sessions but the ROM's own read-2 CRC never confirms the assembled bank -> not verified."""
    a = good(); bad = run_dump(('\r',), (3, 1, 0x1234, 'pre'))
    b = frames(bad.cap)
    # both captures: bank 3 data from the same flipped-free reads, but ROM crc32 differs only in b; a's crc confirms -> verified via a
    res = vf.verify(labelled(a, a[:]))      # sanity: identical captures verify
    assert res['all_verified']
    only_bad = vf.verify(labelled(b, [f for f in b]))
    assert not only_bad['banks'][3]['verified'] and 'CRC-32' in only_bad['banks'][3].get('note', '')

def test_compare_two_complete_sessions():
    s1, = decode(good()); s2, = decode(second_run()); cmp = vf.compare_sessions(s1, s2)
    assert set(cmp.values()) == {'IDENTICAL'}
    fr = second_run(); i = [k for k, f in enumerate(fr) if ftype(f).type == g.T_DATA and ftype(f).bank == 1 and ftype(f).off == 0][0]; o = ftype(fr[i])
    fr[i] = g.build(g.T_DATA, o.session, o.bank, o.seq, o.src, o.off, b'\x00' + o.payload[1:])
    s3, = decode(fr); assert 'DIFFERENT' in vf.compare_sessions(s1, s3)[1]

# ---------- CLIs ----------
def test_cli_receiver_and_verifier(tmp_path):
    c1, c2 = tmp_path / 'a.bin', tmp_path / 'b.bin'
    c1.write_bytes(b''.join(good()).replace(b'\xFF', b'\xFF\xFF')); c2.write_bytes(b''.join(second_run()).replace(b'\xFF', b'\xFF\xFF'))
    p = subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'bank_dump_rx.py'), '--analyze', str(c1), '--outdir', str(tmp_path / 'rx')], capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    sdir = [d for d in os.listdir(tmp_path / 'rx')][0]; sj = json.load(open(tmp_path / 'rx' / sdir / 'session.json'))
    assert sj['all_ok'] and all(os.path.exists(tmp_path / 'rx' / sdir / ('bank_%d.bin' % k)) for k in range(8))
    assert sj['banks']['0']['sha256'] == ds.sha(bytes(BANKS[0]))['sha256']
    v1 = subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'bank_dump_verify.py'), str(c1), '--outdir', str(tmp_path / 'v1')], capture_output=True, text=True)
    assert v1.returncode == 2 and 'INCOMPLETE' in v1.stdout
    v2 = subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'bank_dump_verify.py'), str(c1), str(c2), '--outdir', str(tmp_path / 'v2')], capture_output=True, text=True)
    assert v2.returncode == 0 and 'INTACT RECONSTRUCTION' in v2.stdout and 'IDENTICAL' in v2.stdout
    man = json.load(open(tmp_path / 'v2' / 'manifest.json')); assert man['all_verified'] and man['image']['size'] == 131072
    again = subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'bank_dump_verify.py'), str(c1), str(c2), '--outdir', str(tmp_path / 'v2')], capture_output=True, text=True)
    assert again.returncode != 0                                     # refuses to overwrite an existing result directory (open 'x')

def test_same_capture_file_given_twice_is_not_independent(tmp_path):
    c1 = tmp_path / 'a.bin'; c1.write_bytes(b''.join(good())); c2 = tmp_path / 'copy.bin'; c2.write_bytes(c1.read_bytes())
    v = subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'bank_dump_verify.py'), str(c1), str(c2), '--plain', '--outdir', str(tmp_path / 'v')], capture_output=True, text=True)
    assert v.returncode == 2 and 'duplicate' in v.stdout and 'INCOMPLETE' in v.stdout

def test_unique_dir_never_overwrites(tmp_path):
    a = rx.unique_dir(str(tmp_path / 'd')); b = rx.unique_dir(str(tmp_path / 'd')); assert a != b and os.path.isdir(a) and os.path.isdir(b)
