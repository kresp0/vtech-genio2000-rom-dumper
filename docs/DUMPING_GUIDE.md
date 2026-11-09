# End-to-end dumping guide

This is the procedure the author followed on a Spanish VTech Genio 2000. Commands marked **tested** were run while
preparing this repository on Debian 13; commands marked **untested** were not (for instance anything that needs the real
hardware). Nothing here has been verified on a different unit, a different Genio revision or other VTech models.

## 1. Hardware requirements

* A Spanish VTech Genio 2000 with working LCD and keyboard, and batteries (a mains adapter is not recommended for the first runs).
* A **modified cartridge** with a socketed AT28C256, built as described in [../hardware/README.md](../hardware/README.md) (made on the "Inglés para principiantes" cartridge; other cartridges may need different changes).
  The original cartridge ROM is replaced; use a cartridge you can sacrifice.
* An EEPROM programmer. The author used an **XGecu TL866II Plus** with **Atmel AT28C256-15PI** chips (150 ns). Other programmers are untested.
* A **USB-to-serial adapter** (the author used a CP2102 module) and a way to reach the printer-port data line:
  **DATA0 = pin 2** of a standard DB25 parallel connector (**ground** in common). Connect only DATA0 to the adapter's RXD
  and ground to ground. **Leave the adapter's TXD unconnected.** Check that your adapter accepts the logic levels of
  the printer port before connecting it. The exact physical connector used on the Genio is not documented in this
  repository (see open items in the release notes).
* Multimeter (for the checks in the hardware guide).

## 2. Software requirements

* Linux (tested on Debian 13.7, kernel 6.12.113, Python 3.13.5). Other systems are untested.
* `sdcc` 4.5.0 (Debian package `sdcc` 4.5.0+dfsg-1; provides `sdcc`, `sdasz80`, `sdldz80`, `makebin`), `python3`, GNU coreutils.
* `python3-serial` (pyserial 3.5) for the live receivers only; `pytest` for the tests only.
* Your user must be allowed to open the serial device (on Debian: member of `dialout`).

```bash
sudo apt install sdcc python3 python3-serial python3-pytest
```

## 3. Get the sources and check the build (tested)

```bash
git clone <repository-url> vtech-genio2000-rom-dumper
cd vtech-genio2000-rom-dumper
./build.sh all
sha256sum -c release/SHA256SUMS
```

`build.sh all` writes to `build/diag`, `build/diag16`, `build/dump`. The images in `build/*/` are byte-identical to
those in `release/` (that is how they were checked). You may also program the files from `release/` directly.

## 4. Program the EEPROM (done with the XGecu TL866II Plus; see the hardware guide)

Program the `*_AT28C256_32K.bin` file of the cartridge program you want, then read the chip back and compare. Start with
`bank_diag_AT28C256_32K.bin`. Use the 32768-byte files only; see [BUILD.md](BUILD.md) for why.

## 5. Connect the data interface

DATA0 to the adapter's RXD; common ground; TXD unconnected. Plug the adapter in and find its device:

```bash
ls -l /dev/ttyUSB*
```

Close any other program using the port: the receivers open it exclusively.

## 6. Run the diagnostic program (bank_diag)

On the PC (**untested without hardware**; the offline mode below is tested):

```bash
python3 tools/bank_diag_rx.py --port /dev/ttyUSB0
```

Switch the Genio on with the `bank_diag` cartridge inserted. The LCD shows `BANK DIAG v1`. Press **ENTER** for stage A,
and again after each stage prompt (B, C, D). The PC prints one line per record and finishes on the END frame. Results are
written as `dumps/diag/diag_<date>_s<session>.json` and `.csv`, and the raw capture as `dumps/diag/capture_<date>.bin`
(never overwritten).

If the PC shows rejected frames or line errors, adjust the bit timing on the Genio keyboard before pressing ENTER:
`Z`/`X` lower/raise H, `C`/`V` lower/raise F, `P` toggles between the two presets. The default (preset B, H=30, F=4)
worked on the author's unit.

Interpretation (author's unit): eight distinct stable contents for selectors 0 to 7, selectors 8 to 15 repeating 0 to 7. See
[PROGRAMS.md](PROGRAMS.md). Analyse a saved capture without the Genio:

```bash
python3 tools/bank_diag_rx.py --analyze dumps/diag/capture_XXXX.bin --outdir /tmp/diag_out
```

**Optional:** program `bank_diag16_AT28C256_32K.bin` and repeat the same procedure to probe selectors 0x10 to 0x1F.

## 7. Dump the firmware (bank_dump)

Program `bank_dump_AT28C256_32K.bin`. On the PC:

```bash
python3 tools/bank_dump_rx.py --port /dev/ttyUSB0
```

Switch the Genio on; the LCD shows `BANK DUMP v1 (0-7)`. Press **ENTER** to send banks 0 to 7. The LCD shows bank, selector,
block and percentage; the PC prints `bank N: receiving...` and a status per bank. A full session takes about 2.6 minutes.
The LCD ends with `restore sel0: OK` if the window returned to its start-up content.

Then **run the dump a second time** for an independent session: press ENTER (or a digit 0 to 7 for a single bank) again
on the Genio, or switch it off and on and repeat. Both sessions may be in the same capture or in two captures. When the
last END has been printed, press **Ctrl-C** on the PC. Every session is written to `dumps/dump/<date>_s<id>/` with
`bank_<n>.bin` (only if the bank is complete and its CRC-32 matches read 2 of the cartridge) and `session.json`.

Exit code 0 = all sessions have all banks complete and CRC-verified by the cartridge. A single session is not a verification.

## 8. Verify the transferred blocks and combine the banks (tested on recorded captures)

```bash
python3 tools/bank_dump_verify.py dumps/dump/capture_A.bin dumps/dump/capture_B.bin
```

It prints, per bank, how many of the 128 blocks are VERIFIED, SINGLE, in CONFLICT or MISSING, and whether the assembled
CRC-32 agrees with the cartridge's second read. If all eight banks verify it writes, in `dumps/final/<date>/`: `bank_0.bin`
to `bank_7.bin`, `manifest.json` and `firmware_8banks_128K_candidate.bin` (banks in the order of selector number).
Exit code 0 = verified, 2 = incomplete, 3 = conflicting reads. The rules are in [PROTOCOL.md](PROTOCOL.md).
A capture file passed twice is detected and ignored as a duplicate.

Corrupt or incomplete transfers are never hidden: a lost block is reported as missing, a damaged frame is rejected, two
differing reads are a conflict, and the tools never pad the data in the verified output.

## 9. Validate the final dump and compute hashes

```bash
cd dumps/final/<date>
sha256sum bank_*.bin firmware_8banks_128K_candidate.bin
python3 -c "import zlib,sys; [print('%08X'%zlib.crc32(open('bank_%d.bin'%i,'rb').read()), i) for i in range(8)]"
```

Compare the CRC-32 of each bank with the per-bank values printed by the diagnostic and by `bank_dump_rx.py`; they must
agree. The author's reference values are in [HARDWARE_EVIDENCE.md](HARDWARE_EVIDENCE.md). Equality with them means
the same firmware content; a difference does not by itself mean a corrupt dump, it can mean a different firmware revision.
What proves integrity is that your two independent sessions agree and every bank CRC-32 matches the cartridge's read 2.

**Do not publish the dumped files.** They are VTech's copyrighted firmware.

## 10. What the 128 KiB is, and what it is not

The result is a candidate image of the **eight banks reachable through port 0x01 selectors 0 to 7**. Selectors 8 to 15 and
0x10 to 0x1F were observed to repeat those eight banks. This says nothing certain about the capacity of the physical
mask ROM (see [PROGRAMS.md](PROGRAMS.md)).

## Troubleshooting

| Problem | What to check |
|---|---|
| `could not open port` | Device name, `dialout` membership, another program using the port. |
| Nothing received | Genio ground and DATA0 reach the adapter; adapter TXD left open; the cartridge shows its title on the LCD; baud 9600. |
| Many rejected frames or line errors | Bit timing: change H or F with the keys, one step at a time; shorten wires; check the adapter's logic level. |
| A bank is `INCOMPLETE` | Repeat that bank (`bank_dump`, digit key) and verify again: blocks from several sessions are combined at block level. |
| `CONFLICT` | Two valid but different reads of one block. Do not trust either; re-run. Check contacts and power. |
| The restore line says `RESTORE DIFFERS!` | Switch the Genio off and on before doing anything else. |
