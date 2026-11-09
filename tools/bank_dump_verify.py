#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Santiago Crespo
"""bank_dump_verify - compares independent captures/sessions of the bank dumper, combines verified blocks and builds
the candidate image. It only READS the captures; it writes into a new directory (never overwrites).

    python3 tools/bank_dump_verify.py CAP1.bin CAP2.bin [...]        # each capture may contain several sessions
        --outdir DIR      (default dumps/final/<date>/)
        --allow-partial   also write a PARTIAL_UNVERIFIED image with a mask (never the 'candidate' image)
        --partial REF     optional previous 32 KiB partial dump to compare bank 0 against

Rules (never relaxed):
  * a block (128 B) is VERIFIED only with >= 2 receptions with valid CRC-16 from DIFFERENT SESSIONS, all identical;
    two different valid reads = CONFLICT (never resolved by majority); a single one = SINGLE; none = MISSING;
  * a bank is VERIFIED only if its 128 blocks are VERIFIED and the CRC-32 of the assembled bank equals the CRC-32 of
    read 2 sent by the cartridge in at least one session;
  * the image 'firmware_8banks_128K_candidate.bin' is only written if all 8 banks (selectors 0..7) are VERIFIED, in the order of
    the observed selector numbering (not the transmission order). It is a CANDIDATE: the physical ROM capacity is not determined.
Exit: 0 = 8 banks verified; 2 = incomplete; 3 = conflicts between reads.
"""
import argparse, hashlib, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gframe as g, dumpsession as ds

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NBANKS = 8

def load_sessions(paths, plain=False):
    out, seen = [], {}
    for p in paths:
        raw = open(p, 'rb').read()
        h = hashlib.sha256(raw).hexdigest()
        if h in seen:
            print('WARNING: duplicate capture ignored (%s is identical to %s): it does not count as an independent read' % (p, seen[h])); continue
        seen[h] = p
        sessions, rej, le = ds.decode_capture(raw, plain)
        for n, s in enumerate(sessions): out.append(('%s:%04X#%d' % (os.path.basename(p), s.sid, n + 1), s))
    return out

def verify(labelled, nbanks=NBANKS, ref_partial=None):
    res = dict(banks={}, sessions=[], conflicts=False)
    for label, s in labelled:
        r = s.report(); res['sessions'].append(dict(label=label, ended=r['ended'], banks={k: v['status'] for k, v in r['banks'].items()}))
    images = {}
    for sel in range(nbanks):
        recs = {}                     # block idx -> {label: data}
        rom_crcs, per_session = {}, {}
        for label, s in labelled:
            b = s.banks.get(sel)
            if not b: continue
            for i, d in b.blocks.items(): recs.setdefault(i, {})[label] = d
            if b.end: rom_crcs[label] = b.end['crc32']
            per_session[label] = b.status()
        bs = dict(blocks={'VERIFIED': 0, 'SINGLE': 0, 'CONFLICT': [], 'MISSING': []}, sessions=per_session)
        data = bytearray(); ok_blocks = True
        for i in range(128):
            r = recs.get(i, {})
            vals = {}
            for lab, d in r.items(): vals.setdefault(d, []).append(lab)
            if not vals: bs['blocks']['MISSING'].append(i); ok_blocks = False; data += b'\x00' * 128; continue
            if len(vals) > 1: bs['blocks']['CONFLICT'].append(i); ok_blocks = False; data += b'\x00' * 128; res['conflicts'] = True; continue
            d, labs = next(iter(vals.items())); data += d
            if len(labs) >= 2: bs['blocks']['VERIFIED'] += 1
            else: bs['blocks']['SINGLE'] += 1; ok_blocks = False
        bs['blocks_verified'] = bs['blocks']['VERIFIED']
        bs['verified'] = False
        full = [l for l, st in per_session.items() if st == 'COMPLETE_VERIFIED_BY_ROM_CRC']
        bs['class_A_received_clean_by_session'] = full
        if ok_blocks:
            crc = g.crc32(bytes(data))
            match = [l for l, c in rom_crcs.items() if c == crc]
            bs['assembled_crc32'] = '%08X' % crc; bs['rom_read2_crc32_agree_in'] = match
            bs['verified'] = bool(match)
            if not match: bs['note'] = 'blocks verified but the CRC-32 of read 2 sent by the cartridge does not confirm the bank'
            images[sel] = bytes(data); bs.update(ds.sha(images[sel]))
        bs['class_B_two_independent_reads_match'] = bs['verified']
        bs['class_D_conflicting_reads'] = bool(bs['blocks']['CONFLICT'])
        bs['class_E_unreadable'] = (not recs)
        res['banks'][sel] = bs
    # C: identical contents between selectors (only for banks we hold fully)
    byhash = {}
    for sel, d in images.items(): byhash.setdefault(ds.sha(d)['sha256'], []).append(sel)
    for sel, bs in res['banks'].items():
        same = [x for h, v in byhash.items() if sel in v for x in v if x != sel]
        bs['class_C_identical_to_selectors'] = same
    res['images'] = images
    res['all_verified'] = all(res['banks'][s]['verified'] for s in range(nbanks))
    if ref_partial:
        d0 = res['images'].get(0)
        res['previous_partial'] = dict(bank0_equals_partial_0000_3FFF=(d0 == ref_partial[:0x4000]) if d0 else None,
                                       bank0_equals_partial_4000_7FFF=(d0 == ref_partial[0x4000:0x8000]) if d0 else None)
    return res

def compare_sessions(a, b):
    """a, b: DumpSession. Per bank: both complete? equal? differing bytes."""
    out = {}
    for sel in sorted(set(a.banks) | set(b.banks)):
        da = a.banks[sel].data() if sel in a.banks else None; db = b.banks[sel].data() if sel in b.banks else None
        if da is None or db is None: out[sel] = 'not-comparable (one side incomplete/absent)'
        elif da == db: out[sel] = 'IDENTICAL'
        else: out[sel] = 'DIFFERENT (%d bytes differ, first at 0x%04X)' % (sum(x != y for x, y in zip(da, db)), next(i for i, (x, y) in enumerate(zip(da, db)) if x != y))
    return out

def write_final(res, outdir, allow_partial=False, nbanks=NBANKS):
    os.makedirs(outdir, exist_ok=True)
    man = dict(created=time.strftime('%Y-%m-%d %H:%M:%S'), nbanks=nbanks, banks={}, order='selector number 0..%d (observed numbering, not transmission order)' % (nbanks - 1),
               NOTE='CANDIDATE: banks selected by port 0x01 values 0..7. Physical ROM capacity is NOT determined; selectors 8-15 repeat 0-7 (diag session 010C); '
                    '0x10-0x1F: see diag16 results; ports 0x00/0x02-0x05 never written. Not declared complete.')
    for sel in range(nbanks):
        bs = res['banks'][sel]; d = res['images'].get(sel)
        e = {k: v for k, v in bs.items() if k not in ('sessions',)}
        if d is not None and bs['verified']:
            with open(os.path.join(outdir, 'bank_%d.bin' % sel), 'xb') as f: f.write(d)
            e['file'] = 'bank_%d.bin' % sel
        man['banks'][str(sel)] = e
    man['all_verified'] = res['all_verified']
    if res['all_verified']:
        img = b''.join(res['images'][s] for s in range(nbanks))
        with open(os.path.join(outdir, 'firmware_%dbanks_%dK_candidate.bin' % (nbanks, nbanks * 16)), 'xb') as f: f.write(img)
        man['image'] = dict(file='firmware_%dbanks_%dK_candidate.bin' % (nbanks, nbanks * 16), size=len(img), **ds.sha(img))
        man['verdict'] = 'INTACT RECONSTRUCTION of the %d banks with selectors 0..%d (verified with 2+ independent reads); physical capacity NOT determined' % (nbanks, nbanks - 1)
    else:
        man['verdict'] = 'INCOMPLETE RECONSTRUCTION: verified banks/blocks are missing (see banks); no candidate image written'
        if allow_partial:
            img = bytearray(); mask = {}
            for s in range(nbanks):
                if res['banks'][s]['verified']: img += res['images'][s]
                else: img += b'\x00' * 0x4000; mask[s] = 'NOT VERIFIED (zero-filled here)'
            with open(os.path.join(outdir, 'firmware_PARTIAL_UNVERIFIED.bin'), 'xb') as f: f.write(bytes(img))
            with open(os.path.join(outdir, 'firmware_PARTIAL_UNVERIFIED.mask.json'), 'x') as f: json.dump(mask, f, indent=1)
    man['previous_partial'] = res.get('previous_partial')
    with open(os.path.join(outdir, 'manifest.json'), 'x') as f: json.dump(man, f, indent=1)
    return man

def text(res, man=None):
    L = ['sessions: ' + ', '.join(s['label'] for s in res['sessions'])]
    L.append('bank   blocks VERIF/SINGLE/CONFL/MISSING  A(clean)  B(2 reads)  C(identical to)  D(conflict)  E(unreadable)  status')
    for sel, b in sorted(res['banks'].items()):
        bl = b['blocks']
        L.append('  %d    %3d/%3d/%3d/%3d                  %-9s  %-13s  %-13s  %-12s  %-11s  %s' % (
            sel, bl['VERIFIED'], bl['SINGLE'], len(bl['CONFLICT']), len(bl['MISSING']), 'yes' if b['class_A_received_clean_by_session'] else 'no',
            'yes' if b['verified'] else 'NO', b['class_C_identical_to_selectors'] or '-', 'YES' if b['class_D_conflicting_reads'] else 'no',
            'YES' if b['class_E_unreadable'] else 'no', 'VERIFIED ' + b['sha256'][:16] if b['verified'] else ('NOT verified' + (' (' + b['note'] + ')' if b.get('note') else ''))))
    if 'previous_partial' in res and res['previous_partial']:
        pp = res['previous_partial']; L.append('bank 0 vs previous partial dump: 0x0000-0x3FFF %s, 0x4000-0x7FFF %s' % (pp['bank0_equals_partial_0000_3FFF'], pp['bank0_equals_partial_4000_7FFF']))
    L.append('RESULT: ' + ('INTACT RECONSTRUCTION (8 banks, selectors 0-7; candidate, physical capacity not determined)' if res['all_verified'] else 'INCOMPLETE RECONSTRUCTION'))
    return '\n'.join(L)

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('captures', nargs='+'); ap.add_argument('--plain', action='store_true'); ap.add_argument('--allow-partial', action='store_true')
    ap.add_argument('--outdir'); ap.add_argument('--partial', default=None)
    a = ap.parse_args()
    lab = load_sessions(a.captures, a.plain)
    if not lab: print('no valid session'); return 2
    ref = open(a.partial, 'rb').read() if a.partial and os.path.exists(a.partial) else None
    res = verify(lab, ref_partial=ref)
    outdir = a.outdir or os.path.join(ROOT, 'dumps', 'final', time.strftime('%Y%m%d_%H%M%S'))
    man = write_final(res, outdir, a.allow_partial)
    print(text(res, man)); print('\nmanifest and files: %s' % outdir)
    if len(lab) >= 2:
        print('\npairwise comparison of complete sessions:')
        for i in range(len(lab)):
            for j in range(i + 1, len(lab)): print('  %s vs %s: %s' % (lab[i][0], lab[j][0], compare_sessions(lab[i][1], lab[j][1])))
    return 0 if res['all_verified'] else (3 if res['conflicts'] else 2)

if __name__ == '__main__': sys.exit(main())
