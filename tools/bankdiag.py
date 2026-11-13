# SPDX-License-Identifier: 0BSD
# Copyright (C) 2026 Santiago Crespo
"""bankdiag - interpretation of the frames sent by the bank diagnostic cartridges (bank_diag, bank_diag16). Analysis only.
Distinguishes mirrored banks, empty banks, unstable reads and selectors that do not behave like the reference (MAME-like) model."""
import struct, csv, json, hashlib
import gframe as g

SAMP_LEN_DEFAULT = 16
REC_FIXED = 28
STAGES = 'ABCD'
EMPTY_FF = g.crc32(b'\xFF' * g.BANK_SIZE)
EMPTY_00 = g.crc32(b'\x00' * g.BANK_SIZE)

def parse_start(f):
    p = f.payload
    tool, build, sp, nsamp, slen = struct.unpack('<BHHBB', p[:7])
    offs = list(struct.unpack('<%dH' % nsamp, p[7:7 + 2 * nsamp]))
    return dict(tool=tool, build=build, sp_main=sp, nsamp=nsamp, samp_len=slen, samp_off=offs)

def parse_record(f, start):
    p = f.payload
    nsamp, slen = start['nsamp'], start['samp_len']
    if len(p) != REC_FIXED + nsamp * slen: raise g.Reject('record length %d' % len(p))
    window, stage, wrote, outv = p[0], p[1], p[2], p[3]
    whole = struct.unpack('<I', p[4:8])[0]
    quarters = list(struct.unpack('<4I', p[8:24]))
    head0 = struct.unpack('<I', p[24:28])[0]
    samples = [p[REC_FIXED + i * slen:REC_FIXED + (i + 1) * slen] for i in range(nsamp)]
    comb = quarters[0]
    for q in quarters[1:]: comb = g.crc32_combine(comb, q, 0x1000)
    return dict(seq=f.seq, header_bank=f.bank, src=f.src, window=window, stage=STAGES[stage] if stage < 4 else str(stage),
                wrote=bool(wrote), selector=outv if wrote else None, crc32_whole=whole,
                crc32_quarters=quarters, quarters_combine_ok=(comb == whole), crc32_window0_head=head0,
                samples=[s.hex() for s in samples])

class Session:
    """Accumulates the frames of ONE session (16-bit id chosen by the cartridge)."""
    def __init__(self, sid):
        self.sid = sid; self.start = None; self.records = []; self.stage_ends = []; self.end = None
        self.seqs = set(); self.dups = 0; self.gaps = []; self.rejects = 0
    def add(self, f):
        if f.type == g.T_START:
            self.start = parse_start(f); self.seqs = {f.seq}; return
        if f.seq in self.seqs: self.dups += 1; return
        self.seqs.add(f.seq)
        if f.type == g.T_BANKREC and self.start:
            self.records.append(parse_record(f, self.start))
        elif f.type == g.T_STAGE: self.stage_ends.append(dict(stage=STAGES[f.payload[0]], nrec=f.payload[1], ok=f.payload[2]))
        elif f.type == g.T_END: self.end = dict(nrecords=struct.unpack('<H', f.payload[:2])[0], sp_ok=bool(f.payload[2]))
    def missing_seqs(self):
        if not self.seqs: return []
        return [s for s in range(max(self.seqs) + 1) if s not in self.seqs]

def analyze(sess, partial_bank0_crc=None):
    """Returns a serialisable dict with the per-selector diagnosis and the verdict."""
    recs = sess.records
    rep = dict(session='%04X' % sess.sid, start=sess.start, nrecords=len(recs), stages_done=[s['stage'] for s in sess.stage_ends],
               complete=sess.end is not None, missing_seqs=sess.missing_seqs(), duplicate_frames=sess.dups, rejected_frames=sess.rejects)
    base0 = next((r for r in recs if r['stage'] == 'A' and r['window'] == 0), None)
    base1 = next((r for r in recs if r['stage'] == 'A' and r['window'] == 1), None)
    rep['baseline'] = dict(window0=base0, window1=base1,
                           windows_identical=(base0 is not None and base1 is not None and base0['crc32_whole'] == base1['crc32_whole']))
    rep['partial_bank0_crc32'] = partial_bank0_crc
    by_sel = {}
    for r in recs:
        if r['wrote'] and r['window'] == 1: by_sel.setdefault(r['selector'], []).append(r)
    sels = {}
    for s in sorted(by_sel):
        rs = by_sel[s]; crcs = sorted({r['crc32_whole'] for r in rs})
        q = rs[0]['crc32_quarters']
        sels[s] = dict(readings=len(rs), crc32=['%08X' % c for c in crcs],
                       stable=(len(crcs) == 1 and all(r['quarters_combine_ok'] for r in rs)),
                       quarters_combine_ok=all(r['quarters_combine_ok'] for r in rs),
                       empty=('FF' if crcs == [EMPTY_FF] else '00' if crcs == [EMPTY_00] else None),
                       quarter_mirror=(len(set(q)) < 4),
                       window0_changed=any(base0 is not None and r['crc32_window0_head'] != base0['crc32_window0_head'] for r in rs),
                       equals_baseline_window1=(len(crcs) == 1 and base1 is not None and crcs[0] == base1['crc32_whole']),
                       equals_baseline_window0=(len(crcs) == 1 and base0 is not None and crcs[0] == base0['crc32_whole']),
                       equals_previous_partial=(len(crcs) == 1 and partial_bank0_crc is not None and crcs[0] == partial_bank0_crc),
                       samples_first=rs[0]['samples'])
    groups = {}
    for s, d in sels.items():
        if d['stable']: groups.setdefault(d['crc32'][0], []).append(s)
    for s, d in sels.items():
        d['identical_to'] = sorted(x for x in groups.get(d['crc32'][0], []) if x != s) if d['stable'] else []
    rep['selectors'] = {('%d' % s): d for s, d in sels.items()}
    rep['identical_groups'] = [sorted(v) for v in groups.values() if len(v) > 1]
    stable = [s for s, d in sels.items() if d['stable']]
    unstable = [s for s, d in sels.items() if not d['stable']]
    flags = []
    if len(sels) < 16: flags.append('incomplete sweep: only selectors %s' % sorted(sels))
    if unstable: flags.append('UNSTABLE reads in selectors %s' % unstable)
    if any(d['window0_changed'] for d in sels.values()): flags.append('window 0 changed when port 0x01 was written (unexpected)')
    if rep['baseline']['windows_identical'] is False and base0 and base1: flags.append('windows 0 and 1 were NOT identical at start-up')
    if rep['identical_groups']: flags.append('selectors with IDENTICAL content (mirrored or repeated): %s' % rep['identical_groups'])
    if any(d['empty'] for d in sels.values()): flags.append('empty banks: %s' % [s for s, d in sels.items() if d['empty']])
    if 0 in sels and base1 and not sels[0]['equals_baseline_window1']: flags.append('selector 0 does NOT match the window 0x4000 content at start-up')
    if any(d['quarter_mirror'] for d in sels.values()): flags.append('repeated 4 KiB quarters inside a bank: %s' % [s for s, d in sels.items() if d['quarter_mirror']])
    expected = (len(sels) == 16 and not unstable and not rep['identical_groups'] and not any(d['empty'] for d in sels.values())
                and not any(d['window0_changed'] for d in sels.values()))
    rep['flags'] = flags
    rep['mame_like'] = bool(expected)
    rep['verdict'] = ('CONSISTENT with the reference (MAME-like) model in this test: 16 stable, distinct selectors' if expected else
                      'Cannot claim consistency with the reference (MAME-like) model: see flags') if len(sels) else 'no sweep data'
    rep['note'] = ('Diagnostic: it identifies banks; it is NOT a dump. A bank is only declared verified with intact data frames '
                   'and two matching independent reads (bank_dump cartridge).')
    return rep

def write_outputs(rep, sess, base):
    """base: path without extension. Writes .json and .csv (overwrites ONLY the files of this same session/capture)."""
    with open(base + '.json', 'w') as f: json.dump(dict(analysis=rep, records=sess.records), f, indent=1)
    with open(base + '.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['seq', 'stage', 'window', 'wrote', 'selector', 'crc32_whole', 'q0', 'q1', 'q2', 'q3', 'quarters_combine_ok', 'crc32_window0_head'] + ['sample%d' % i for i in range(4)])
        for r in sess.records:
            w.writerow([r['seq'], r['stage'], r['window'], int(r['wrote']), '' if r['selector'] is None else r['selector'],
                        '%08X' % r['crc32_whole']] + ['%08X' % q for q in r['crc32_quarters']] +
                       [int(r['quarters_combine_ok']), '%08X' % r['crc32_window0_head']] + r['samples'])

def text_report(rep):
    L = ['session %s   records %d   stages %s   %s' % (rep['session'], rep['nrecords'], ''.join(rep['stages_done']) or '-',
                                                       'COMPLETE (END received)' if rep['complete'] else 'INCOMPLETE (no END)')]
    if rep['start']: L.append('  cartridge build %04X, SP in main = %04X' % (rep['start']['build'], rep['start']['sp_main']))
    if rep['missing_seqs']: L.append('  missing frames (seq): %s' % rep['missing_seqs'])
    b = rep['baseline']
    if b['window0'] and b['window1']:
        L.append('  start-up: window0 %08X  window1 %08X  -> %s' % (b['window0']['crc32_whole'], b['window1']['crc32_whole'],
                 'IDENTICAL' if b['windows_identical'] else 'DIFFERENT'))
    if rep['partial_bank0_crc32'] is not None: L.append('  CRC32 of 0x0000-0x3FFF of the reference partial dump: %08X' % rep['partial_bank0_crc32'])
    L.append('  sel  reads     crc32      stable   notes')
    for s, d in sorted(rep['selectors'].items(), key=lambda kv: int(kv[0])):
        notes = []
        if d['equals_baseline_window1']: notes.append('=window1 at start-up')
        if d['equals_previous_partial']: notes.append('=partial dump')
        if d['identical_to']: notes.append('same as %s' % d['identical_to'])
        if d['empty']: notes.append('EMPTY(%s)' % d['empty'])
        if d['quarter_mirror']: notes.append('repeated quarters')
        if d['window0_changed']: notes.append('WINDOW0 CHANGED')
        L.append('  %3s  %8d  %s  %-7s  %s' % (s, d['readings'], ','.join(d['crc32']), 'yes' if d['stable'] else 'NO', '; '.join(notes)))
    for fl in rep['flags']: L.append('  ! ' + fl)
    L.append('  VERDICT: ' + rep['verdict'])
    L.append('  ' + rep['note'])
    return '\n'.join(L)

def partial_bank0_crc(path):
    if not path: return None
    try:
        d = open(path, 'rb').read()
        return g.crc32(d[:0x4000]) if len(d) >= 0x4000 else None
    except OSError: return None


# ---------------------------------------------------------------------------------------------------------------
# diag16: selectors 0x10..0x1F of port 0x01 (bank_diag16 cartridge, tool=3).
# Reference = CRC32 of banks 0..7 as measured in the author's hardware session 010C (bank_diag; 8-15 repeated 0-7).
KNOWN_REF_010C = {0: 0xD49DECF0, 1: 0x67EBAB51, 2: 0x35C99AC6, 3: 0x021A7E5B, 4: 0x8A1F0214, 5: 0x63924486, 6: 0x8F71AB6E, 7: 0xF28A4E52}

def load_reference(path=None):
    """Returns {selector: crc32} from a bank_diag (tool 1) JSON or the embedded reference (session 010C)."""
    if path:
        d = json.load(open(path))
        sel = d['analysis']['selectors']
        return {int(k): int(v['crc32'][0], 16) for k, v in sel.items() if v['stable'] and int(k) < 8}
    return dict(KNOWN_REF_010C)

def analyze16(sess, reference=None):
    reference = reference or dict(KNOWN_REF_010C)
    recs = sess.records
    rep = dict(session='%04X' % sess.sid, start=sess.start, nrecords=len(recs), stages_done=[s['stage'] for s in sess.stage_ends],
               complete=sess.end is not None, missing_seqs=sess.missing_seqs(), duplicate_frames=sess.dups,
               reference={str(k): '%08X' % v for k, v in sorted(reference.items())})
    base0 = next((r for r in recs if r['stage'] == 'A' and r['window'] == 0), None)
    base1 = next((r for r in recs if r['stage'] == 'A' and r['window'] == 1), None)
    rep['baseline_ok'] = bool(base1 and base0 and base1['crc32_whole'] == base0['crc32_whole'] == reference.get(0))
    by = {}
    for r in recs:
        if r['wrote'] and r['window'] == 1: by.setdefault(r['selector'], []).append(r)
    restore = by.get(0, [])
    rep['restore_checks'] = dict(n=len(restore), all_equal_baseline=all(r['crc32_whole'] == reference.get(0) for r in restore))
    refrev = {}
    for k, v in reference.items(): refrev.setdefault(v, []).append(k)
    sels, flags = {}, []
    for v in sorted(x for x in by if x >= 16):
        rs = by[v]; crcs = sorted({r['crc32_whole'] for r in rs})
        stable = len(crcs) == 1 and all(r['quarters_combine_ok'] for r in rs)
        c = crcs[0] if stable else None
        sels[v] = dict(readings=len(rs), crc32=['%08X' % x for x in crcs], stable=stable,
                       equals_reference_bank=(refrev.get(c) if c is not None else None),
                       empty=('FF' if crcs == [EMPTY_FF] else '00' if crcs == [EMPTY_00] else None),
                       window0_changed=any(base0 is not None and r['crc32_window0_head'] != base0['crc32_window0_head'] for r in rs),
                       three_bit_prediction=(refrev.get(c) == [v & 7]) if c is not None else None,
                       samples_first=rs[0]['samples'])
    new_groups = {}
    for v, d in sels.items():
        if d['stable'] and d['equals_reference_bank'] is None and not d['empty']: new_groups.setdefault(d['crc32'][0], []).append(v)
    rep['selectors'] = {str(v): d for v, d in sels.items()}
    rep['new_content_groups'] = [sorted(x) for x in new_groups.values()]
    if len(sels) < 16: flags.append('incomplete sweep: only selectors %s' % sorted(sels))
    un = [v for v, d in sels.items() if not d['stable']]
    if un: flags.append('UNSTABLE reads in selectors %s' % un)
    if not rep['restore_checks']['all_equal_baseline']: flags.append('the RESTORE (selector 0) did NOT always return the start-up content')
    if any(d['window0_changed'] for d in sels.values()): flags.append('window 0 changed when port 0x01 was written')
    if not rep['baseline_ok'] and base1: flags.append('start-up content does NOT match the bank 0 reference')
    emp = [v for v, d in sels.items() if d['empty']]
    if emp: flags.append('selectors returning FF/00 filler (floating bus / empty?): %s' % emp)
    if rep['new_content_groups']: flags.append('selectors with NEW content (none of 0-7): %s -> they need to be dumped' % rep['new_content_groups'])
    three = len(sels) == 16 and all(d['three_bit_prediction'] for d in sels.values())
    rep['flags'] = flags; rep['three_bit_decode_consistent'] = bool(three)
    if not sels: rep['verdict'] = 'no 16-31 sweep data'
    elif three and not flags: rep['verdict'] = ('The 16 selectors 0x10-0x1F repeat banks 0-7 exactly (selector & 7): '
                                                'bits 3 and 4 of port 0x01 do NOT change the window. Observed capacity through this port: 8 banks (128 KiB) '
                                                'up to selector 0x1F; other bits/ports not tested.')
    else: rep['verdict'] = 'Result differs from the 3-bit prediction: see flags and selectors'
    rep['note'] = 'CRC32 and sample based diagnostic; it is not a dump and does not prove the physical ROM size.'
    return rep

def text_report16(rep):
    L = ['session %s  records %d  stages %s  %s' % (rep['session'], rep['nrecords'], ''.join(rep['stages_done']) or '-',
         'COMPLETE (END)' if rep['complete'] else 'INCOMPLETE (no END)')]
    if rep['missing_seqs']: L.append('  missing frames (seq): %s' % rep['missing_seqs'])
    L.append('  reference 0-7 (hardware session 010C): ' + ' '.join('%s=%s' % (k, v) for k, v in rep['reference'].items()))
    L.append('  start-up matches bank 0: %s;  restores to 0: %d, all = start-up: %s' % (rep['baseline_ok'], rep['restore_checks']['n'], rep['restore_checks']['all_equal_baseline']))
    L.append('  sel   read  crc32     stable   = ref bank    prediction(sel&7)')
    for k, d in sorted(rep['selectors'].items(), key=lambda kv: int(kv[0])):
        L.append('  0x%02X  %4d  %s  %-7s  %-11s  %s' % (int(k), d['readings'], ','.join(d['crc32']), 'yes' if d['stable'] else 'NO',
                 str(d['equals_reference_bank']) if d['equals_reference_bank'] else ('NEW' if not d['empty'] else 'EMPTY'),
                 {True: 'holds', False: 'does NOT hold', None: '-'}[d['three_bit_prediction']]))
    for fl in rep['flags']: L.append('  ! ' + fl)
    L.append('  VERDICT: ' + rep['verdict']); L.append('  ' + rep['note'])
    return '\n'.join(L)
