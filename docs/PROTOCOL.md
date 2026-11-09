# Serial protocol v2 (Genio to PC, one way)

Reference implementations: `src/common/bank_common.h` (sender, Z80), `tools/gframe.py` (receiver, Python). There is no
return channel: the PC's TXD line is not connected, so nothing can be acknowledged or retransmitted.

## Physical layer

* Printer port, **data line DATA0** (pin 2 of a standard DB25 parallel connector) driven by software ("bit-banging").
  Idle level and polarity are produced as in the sender's `tx_send` routine: the line is **inverted** at the port
  (port value `0x00` = line high). A strobe pulse on bit 2 of port 0x12 is generated for every bit; it is not used by the receiver.
* **9600 baud, 8 data bits, no parity, 1 stop bit**, least-significant bit first. The PC reads it as an ordinary UART
  through a USB-serial adapter whose RXD is connected to DATA0 and whose ground is common with the Genio.
* Bit time is produced by delay loops: `T = 110 + 16*H + 13*F` CPU cycles per bit. The default preset B is `H=30, F=4`
  (T = 642), the value that worked on the author's unit; preset A is `H=16, F=4`. Keys `Z/X` (H -/+), `C/V` (F -/+) and
  `P` (switch preset) change it on the Genio's keyboard before a run. The cartridge clock rate was not measured.

## Framing

SLIP-style, as in earlier tools of this project:

| Byte | Meaning |
|---|---|
| `C0` | END (frame delimiter) |
| `DB` | ESC |
| `DB DC` | an `C0` data byte |
| `DB DD` | a `DB` data byte |

A frame is `C0` stuffed(body) `C0`. Any other byte after ESC makes the frame invalid.

## Frame body (little-endian)

| Offset | Size | Field |
|---|---|---|
| 0 | 2 | magic `'V' 'D'` |
| 2 | 1 | protocol version = 2 |
| 3 | 1 | frame type |
| 4 | 2 | session id (free-running counter while the program waits for the first key; fixed during a session) |
| 6 | 1 | bank selector written to port 0x01 (0xFF = none) |
| 7 | 2 | sequence number (START = 0, then incrementing) |
| 9 | 2 | CPU source address (0x0000 window 0, 0x4000 window 1) |
| 11 | 2 | offset inside the bank |
| 13 | 2 | payload length N |
| 15 | N | payload |
| 15+N | 2 | **CRC-16/CCITT-FALSE** (poly 0x1021, init 0xFFFF) over bytes 0 to 14+N, low byte first |

The CRC bytes are stuffed like any other byte but are not themselves covered by the CRC. Check value:
`crc16(b"123456789") = 0x29B1` (asserted in `gframe.py`).

## Frame types

| Type | Name | Used by | Payload |
|---|---|---|---|
| 0x01 | START | all | diagnostics: `tool(1) build(u16) sp(u16) nsamp(u8)=4 samp_len(u8)=16 samp_off[4](u16)` (15 B). dump: `tool(1) build(u16) sp(u16) mode(1: 0=all, 1=one) count(1) block(u16)=128 nblocks(u16)=128 crc32_window_at_start(u32) selectors[count]` |
| 0x02 | DATA | dump | 128 bytes of the window `0x4000`; header: selector, src = 0x4000, offset = multiple of 128, len = 128 |
| 0x03 | END | all | diagnostics: `n_records(u16) sp_ok(u8)`. dump: `banks_sent(u8) restore_ok(u8) sp_ok(u8) crc32_after_restore(u32)` |
| 0x10 | BANKREC | diagnostics | 92 B: `window(u8) stage(u8, 0..3 = A..D) wrote(u8) value(u8) crc32_read2(u32) crc32_quarter[4](u32) crc32_window0_head(u32) samples[4][16]` |
| 0x11 | STAGE | diagnostics | `stage(u8) records_in_stage(u8) ok(u8)` |
| 0x20 | BANK_BEGIN | dump | `selector(u8) window(u8)=1 nblocks(u16)=128 block(u16)=128` |
| 0x21 | BANK_END | dump | `selector(u8) nblocks(u16) crc16_read1(u16) crc32_read2(u32)` |

Tool numbers: 1 = `bank_diag`, 2 = `bank_dump`, 3 = `bank_diag16`. Build ids: 0x0001, 0x0101, 0x0002.

## Verification procedure

* **Per frame:** the CRC-16 must match; otherwise the frame is rejected (never repaired). Line errors reported by the UART
  (framing, parity) are marked by the Linux `PARMRK` mechanism; a frame that contains one is rejected.
* **Per bank (dump):** the sender computes the CRC-16 of the 16384 data bytes *as it sent them* (read 1) and, independently,
  the CRC-32 (IEEE 802.3, the zlib polynomial) of another complete read of the window (read 2). The host assembles the 128
  blocks it received and requires both to agree with the assembled data. If a bank changes between read 1 and read 2 the CRCs differ.
* **Per block (verifier):** a block is *VERIFIED* only if at least two valid receptions from **different sessions** are
  identical. Two valid but different receptions are a *CONFLICT* (no majority vote). One reception is *SINGLE*.
* **Per bank (verifier):** *VERIFIED* only if all 128 blocks are VERIFIED and the assembled CRC-32 equals read 2 of the
  cartridge in at least one session.
* **Candidate image:** `firmware_8banks_128K_candidate.bin` is written only if all eight banks are VERIFIED, in the order of
  selector number (not transmission order). The same capture file given twice does not count as two sessions.

## Missing and damaged data

A lost block stays missing; the receiver never pads the data. A `bank_N.PARTIAL.bin` with a `bank_N.mask.json` is written for
debugging only. Exit codes of `bank_dump_verify.py`: 0 all eight banks verified, 2 incomplete, 3 conflicts.
