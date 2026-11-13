#!/usr/bin/env python3
# SPDX-License-Identifier: 0BSD
# Copyright (C) 2026 Santiago Crespo
"""bank_diag_rx - receiver for the bank diagnostic cartridges bank_diag / bank_diag16 (Genio -> PC; the PC TXD is NOT connected).

Live (serial port 9600 8N1; the raw capture is saved and nothing is ever overwritten):
    python3 tools/bank_diag_rx.py --port /dev/ttyUSB0
Offline, on a saved capture:
    python3 tools/bank_diag_rx.py --analyze dumps/diag/capture_XXXX.bin
Exits on the END frame (stage D complete) or on Ctrl-C; writes JSON and CSV after every record, so if you power the Genio off
between stages nothing already received is lost. Exit codes: 0 complete and consistent with the reference (MAME-like) model /
the 3-bit prediction, 3 complete but with differences, 2 incomplete, 1 usage error.
"""
import argparse, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gframe as g, bankdiag as bd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def handle(frames, sessions, state):
    for item in frames:
        if item[0] == 'reject':
            state['rejects'] += 1
            print('  [rejected] %s (%d bytes)' % (item[1], len(item[2])), flush=True); continue
        f = item[1]
        s = sessions.setdefault(f.session, bd.Session(f.session))
        n0 = len(s.records)
        s.add(f)
        state['last'] = s
        if f.type == g.T_START: print('session %04X: START %s' % (f.session, s.start), flush=True)
        elif len(s.records) > n0:
            r = s.records[-1]
            print('  stage %s window %d sel %-4s crc32 %08X %s' % (r['stage'], r['window'], '--' if r['selector'] is None else r['selector'],
                  r['crc32_whole'], 'ok' if r['quarters_combine_ok'] else 'INCONSISTENT READS'), flush=True)
            state['dirty'] = True
        elif f.type == g.T_STAGE: print('  end of stage %s (%d records)' % (bd.STAGES[f.payload[0]], f.payload[1]), flush=True)
        elif f.type == g.T_END: print('  END received', flush=True); state['ended'] = True

def do_analyze(s, partial, ref):
    return bd.analyze16(s, ref) if s.start and s.start['tool'] == g.TOOL_DIAG16 else bd.analyze(s, partial)

def finish(sessions, outdir, stamp, partial, ref=None):
    code = 2
    for sid, s in sorted(sessions.items()):
        s.rejects = 0
        rep = do_analyze(s, partial, ref)
        base = os.path.join(outdir, 'diag_%s_s%04X' % (stamp, sid))
        bd.write_outputs(rep, s, base)
        print('\n' + (bd.text_report16(rep) if s.start and s.start['tool'] == g.TOOL_DIAG16 else bd.text_report(rep)) + '\n  -> %s.json / .csv' % base)
        if s.start and s.start['tool'] == g.TOOL_DIAG16: code = 0 if (rep['complete'] and rep['three_bit_decode_consistent'] and not rep['flags']) else (3 if rep['complete'] else 2)
        else: code = 0 if (rep['complete'] and rep['mame_like']) else (3 if rep['complete'] else 2)
    return code

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--port', default='/dev/ttyUSB0'); ap.add_argument('--baud', type=int, default=9600)
    ap.add_argument('--analyze', metavar='CAPTURE', help='analyse a saved raw capture (with PARMRK marks unless --plain)')
    ap.add_argument('--plain', action='store_true'); ap.add_argument('--outdir', default=os.path.join(ROOT, 'dumps', 'diag'))
    ap.add_argument('--partial', default=None, help='optional: a 0x0000-0x7FFF partial dump you made yourself; only used to compare its first 16 KiB with the banks')
    ap.add_argument('--reference', help='JSON of a previous bank_diag session (selectors 0-7) used as reference for the 0x10-0x1F diagnostic; default: the reference embedded from the author\'s session 010C')
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    partial = bd.partial_bank0_crc(a.partial)
    ref = bd.load_reference(a.reference)
    sessions, state = {}, dict(rejects=0, dirty=False, ended=False, last=None)
    stamp = time.strftime('%Y%m%d_%H%M%S')
    if a.analyze:
        dec = g.Decoder() if a.plain else g.ParmrkDecoder()
        handle(dec.feed(open(a.analyze, 'rb').read()), sessions, state)
        if not sessions: print('no valid frame'); return 2
        return finish(sessions, a.outdir, stamp, partial, ref)
    import serial, termios
    rawp = os.path.join(a.outdir, 'capture_%s.bin' % stamp)
    ser = serial.Serial(a.port, a.baud, bytesize=8, parity='N', stopbits=1, timeout=0.2, exclusive=True)
    try:
        at = termios.tcgetattr(ser.fileno())
        at[0] = (at[0] | termios.PARMRK | termios.INPCK) & ~(termios.IGNPAR | termios.ISTRIP | termios.IGNBRK | termios.BRKINT)
        termios.tcsetattr(ser.fileno(), termios.TCSANOW, at)
    except Exception as e: print('warning: PARMRK not enabled (%s)' % e, file=sys.stderr)
    dec = g.ParmrkDecoder()
    print('port %s %d 8N1 (RX only)\nraw capture: %s\nPower on the Genio with the cartridge and press ENTER at each stage (Ctrl-C to finish)\n' % (a.port, a.baud, rawp), flush=True)
    try:
        with open(rawp, 'xb') as raw:
            while not state['ended']:
                data = ser.read(4096)
                if not data: continue
                raw.write(data); raw.flush()
                handle(dec.feed(data), sessions, state)
                if state['dirty'] and state['last'] is not None:
                    s = state['last']; bd.write_outputs(do_analyze(s, partial, ref), s, os.path.join(a.outdir, 'diag_%s_s%04X' % (stamp, s.sid))); state['dirty'] = False
    except KeyboardInterrupt: print('\ninterrupted')
    finally: ser.close()
    if not sessions: print('no frame received'); return 2
    return finish(sessions, a.outdir, stamp, partial, ref)

if __name__ == '__main__': sys.exit(main())
