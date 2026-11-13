#!/usr/bin/env python3
# SPDX-License-Identifier: 0BSD
# Copyright (C) 2026 Santiago Crespo
"""bank_dump_rx - receiver for the bank_dump cartridge (Genio -> PC; the PC TXD is NOT connected).

Live:      python3 tools/bank_dump_rx.py --port /dev/ttyUSB0
Offline:   python3 tools/bank_dump_rx.py --analyze dumps/dump/capture_XXXX.bin

* Raw capture (with PARMRK marks) in dumps/dump/capture_<date>.bin: opened with 'x', NEVER overwritten.
* Every session (every run of the cartridge) goes to its own directory dumps/dump/<date>_s<ID>/ :
    bank_<sel>.bin            only if the bank is COMPLETE and the CRC-32 of what was received equals read 2 of the cartridge
    bank_<sel>.PARTIAL.bin    received blocks in place and 0x00 where missing, ALWAYS with bank_<sel>.mask.json (list of missing blocks):
                              not a dump, a debugging aid only
    session.json              report, SHA256/SHA1/CRC32 hashes per bank, status
* A single session is not a verification by itself: declaring banks verified needs two independent sessions
  (python3 tools/bank_dump_verify.py ...).
Exit codes: 0 all sessions have complete banks verified by the cartridge CRC; 2 something incomplete/inconsistent; 1 error."""
import argparse, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gframe as g, dumpsession as ds

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def unique_dir(base):
    d, n = base, 1
    while os.path.exists(d): n += 1; d = '%s_%d' % (base, n)
    os.makedirs(d); return d

def write_session(s, outdir, stamp):
    """Write the session directory. Returns (dir, all_ok)."""
    d = unique_dir(os.path.join(outdir, '%s_s%04X' % (stamp, s.sid)))
    rep = s.report(); ok = s.start is not None and s.end is not None
    for sel, b in sorted(s.banks.items()):
        chk = rep['banks'][str(sel)]
        data = b.data()
        if data is not None and chk['status'] == 'COMPLETE_VERIFIED_BY_ROM_CRC':
            with open(os.path.join(d, 'bank_%d.bin' % sel), 'xb') as f: f.write(data)
            chk.update(ds.sha(data))
        else:
            ok = False
            buf = bytearray(b.nblocks * b.block)
            for i, blk in b.blocks.items(): buf[i * b.block:(i + 1) * b.block] = blk
            with open(os.path.join(d, 'bank_%d.PARTIAL.bin' % sel), 'xb') as f: f.write(bytes(buf))
            with open(os.path.join(d, 'bank_%d.mask.json' % sel), 'x') as f:
                json.dump(dict(selector=sel, block_size=b.block, nblocks=b.nblocks, present=sorted(b.blocks), missing=b.missing,
                               conflicting=sorted(set(b.dup_conflict)), NOTE='missing blocks are zero-filled ONLY in the PARTIAL file; this is not a dump'), f, indent=1)
        if data is not None and chk.get('rom_crc32_match') is False: ok = False
    if s.end and not s.end['restore_ok']: ok = False
    rep['all_ok'] = ok
    with open(os.path.join(d, 'session.json'), 'x') as f: json.dump(rep, f, indent=1)
    return d, ok

def text(s):
    r = s.report(); L = ['session %s  %s' % (r['session'], 'COMPLETE (END)' if r['ended'] else 'NO END (interrupted?)')]
    if s.start is None: L.append('  START missing (layout inferred)')
    else: L.append('  mode %s, banks %s, cartridge build %04X, SP %04X, CRC32 of window 0x4000 at start %s' % (
        'all' if s.start['mode'] == 0 else 'one', s.start['selectors'], s.start['build'], s.start['sp_main'], r['start']['baseline_crc32']))
    if r['frames_missing_seq']: L.append('  missing frames (seq): %d' % len(r['frames_missing_seq']))
    if r['duplicate_frames']: L.append('  duplicate frames ignored: %d' % r['duplicate_frames'])
    if r['rejected_data_frames']: L.append('  DATA frames with unexpected fields: %d' % r['rejected_data_frames'])
    for k, c in r['banks'].items():
        L.append('  bank %s: %-28s blocks %3d/%d%s%s' % (k, c['status'], c['blocks_received'], s.banks[int(k)].nblocks,
                 ('  missing %s' % (c['missing_blocks'][:8] + ['...'] if len(c['missing_blocks']) > 8 else c['missing_blocks'])) if c['missing_blocks'] else '',
                 '  CRC32 %s' % c.get('crc32_received', '-')))
    if s.end: L.append('  window restore at the end: %s' % ('OK (CRC = start-up)' if s.end['restore_ok'] else 'DIFFERS'))
    return '\n'.join(L)

def finish(sessions, outdir, stamp):
    allok = bool(sessions)
    for s in sessions:
        d, ok = write_session(s, outdir, stamp); allok &= ok
        print('\n' + text(s) + '\n  -> %s  [%s]' % (d, 'OK' if ok else 'INCOMPLETE/INCONSISTENT'))
    return 0 if allok else 2

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--port', default='/dev/ttyUSB0'); ap.add_argument('--baud', type=int, default=9600)
    ap.add_argument('--analyze', metavar='CAPTURE'); ap.add_argument('--plain', action='store_true')
    ap.add_argument('--outdir', default=os.path.join(ROOT, 'dumps', 'dump'))
    a = ap.parse_args(); os.makedirs(a.outdir, exist_ok=True)
    stamp = time.strftime('%Y%m%d_%H%M%S')
    if a.analyze:
        sessions, rej, le = ds.decode_capture(open(a.analyze, 'rb').read(), a.plain)
        print('rejected frames: %d, line errors: %d' % (rej, le))
        if not sessions: print('no valid frame'); return 2
        return finish(sessions, a.outdir, stamp)
    import serial, termios
    rawp = os.path.join(a.outdir, 'capture_%s.bin' % stamp)
    ser = serial.Serial(a.port, a.baud, bytesize=8, parity='N', stopbits=1, timeout=0.2, exclusive=True)
    try:
        at = termios.tcgetattr(ser.fileno())
        at[0] = (at[0] | termios.PARMRK | termios.INPCK) & ~(termios.IGNPAR | termios.ISTRIP | termios.IGNBRK | termios.BRKINT)
        termios.tcsetattr(ser.fileno(), termios.TCSANOW, at)
    except Exception as e: print('warning: PARMRK not enabled (%s)' % e, file=sys.stderr)
    dec = g.ParmrkDecoder(); sessions = []; cur = {}; rej = 0; nfr = 0; last = time.time()
    print('port %s %d 8N1 (RX only)\nraw capture: %s\nPower on the Genio and press ENTER (all banks) or a digit 0-7. Ctrl-C finishes.\n' % (a.port, a.baud, rawp), flush=True)
    try:
        with open(rawp, 'xb') as raw:
            while True:
                data = ser.read(4096)
                if not data: continue
                raw.write(data); raw.flush()
                for it in dec.feed(data):
                    if it[0] == 'reject': rej += 1; continue
                    f = it[1]; nfr += 1
                    s = cur.get(f.session)
                    if s is None or (f.type == g.T_START and s.start is not None): s = ds.DumpSession(f.session); cur[f.session] = s; sessions.append(s)
                    s.add(f)
                    if f.type == g.T_START: print('session %04X: START %s' % (f.session, s.start), flush=True)
                    elif f.type == g.T_BANK_END: print('  bank %d: %s' % (f.bank, s.banks[f.bank].status()), flush=True)
                    elif f.type == g.T_END: print('  END session %04X (ENTER/digit on the Genio = another session; Ctrl-C = finish)' % f.session, flush=True)
                    elif f.type == g.T_DATA and f.off == 0: print('  bank %d: receiving...' % f.bank, flush=True)
                if time.time() - last > 10: print('  [%d frames, %d rejected, %d line errors]' % (nfr, rej, dec.line_errors), flush=True); last = time.time()
    except KeyboardInterrupt: print('\ninterrupted')
    finally: ser.close()
    if not sessions: print('no frame received'); return 2
    print('rejected %d, line errors %d' % (rej, dec.line_errors))
    return finish(sessions, a.outdir, stamp)

if __name__ == '__main__': sys.exit(main())
