# The three cartridge programs

All three are built from the sources in `src/` and run from the cartridge window `0x8000-0x9FFF`. They share
`src/common/bank_common.h` (printer-port soft UART, LCD, keyboard, CRC-32 routine, frame layer). This page was written
from the source code, not from the program names.

Common safety design (checked by `build.sh` through `tools/check_map.py`, and by the tests):

* All code and constants live in the cartridge window `0x8000-0x9FFF`; variables from `0xC000`. Nothing is ever executed
  from a banked window; the banked window is only **read** as data.
* Interrupts are disabled at entry (`DI`) and never re-enabled.
* The only I/O port written for bank selection is **port 0x01** (bank register of the CPU window `0x4000-0x7FFF`). Ports
  `0x00` and `0x03` (other bank windows) and `0x02`, `0x04`, `0x05` are never written (checked on the binaries by the tests).
* The stack pointer is checked to be inside RAM before the first bank write; otherwise the program stops without writing.
* Port 0x01 is write-only, so the program cannot read the start-up value. Each program writes selector 0 afterwards and
  checks that the window again has the CRC-32 it had at start-up.
* Output is serial only: Genio to PC through the printer port, 9600 baud 8N1 (see [PROTOCOL.md](PROTOCOL.md)). The
  LCD shows stage, selector and progress. The keyboard is used for ENTER and for the timing keys `Z X C V P`.

## Which one to run first

1. **`bank_diag`**: the baseline diagnostic. Start here.
2. **`bank_diag16`**: optional, only needed if you want to repeat the selector 0x10 to 0x1F experiment.
3. **`bank_dump`**: the actual dump. Run it **twice** (two independent sessions) so the host can verify every block.

## bank_diag (build ID 0x0001, tool 1)

Source: `src/diag/bank_diag.c`. It identifies what the window `0x4000-0x7FFF` shows for **selectors 0x00 to 0x0F** of
port 0x01. It does not transfer the data of the banks, only fingerprints.

Four stages, each started by ENTER so that you can switch the Genio off between them:

| Stage | Port 0x01 writes | Records sent |
|---|---|---|
| A | none (baseline) | window `0x0000` and window `0x4000` as the Genio firmware left them (2) |
| B | one: `00h` (the value the firmware itself writes at boot) | 1 |
| C | `01h`, then `00h` | 2 |
| D | `00h` to `0Fh` ascending, `0Fh` to `00h` descending, then `00h` | 33 |

A complete run sends 38 records. Each record carries: CRC-32 of the whole 16 KiB window (read 2), four CRC-32 of the 4 KiB
quarters (read 1), CRC-32 of the first 256 bytes of window 0 (taken after the selection, to detect any effect on window 0),
and four 16-byte samples. The host recombines the quarter CRCs with `crc32_combine` and compares them with the whole
CRC: a mismatch means the read was unstable.

How to read the report (`tools/bank_diag_rx.py`):

* `stable yes` for every selector: both reads agreed.
* `same as [8]` etc.: selectors whose content is identical. **On the author's Genio, selectors 8 to 15 repeat 0 to 7.**
  The tool lists this under flags and ends with the verdict "Cannot claim consistency with the reference (MAME-like)
  model". For this unit that is the expected outcome, not an error: it just records that the machine does not behave like
  a 16-distinct-bank model.
* `=window1 at start-up` on selector 0: after writing 00h the window shows what it showed on start-up, as expected.
* Exit code 3 means complete with differences from the reference model (this is the normal result on the author's unit).

## bank_diag16 (build ID 0x0002, tool 3)

Same source file, compiled with `-DDIAG16=1`. Same record format as `bank_diag`. It differs in the selectors tested:
**0x10 to 0x1F**, which `bank_diag` never wrote. It was created because the diagnostic of 0x00-0x0F showed that bit 3 had no
effect, and the next unanswered question was whether bits 4 and above reveal more banks (which would mean more than
128 KiB) before committing to a full dump. A selector never tried before is a risk for the hardware, so every selector is
followed by a write of 00h and a record that checks the restore.

| Stage | Port 0x01 writes | Records |
|---|---|---|
| A | none | 2 |
| B | `10h`, then `00h` | 2 |
| C | `11h` to `1Fh`, each followed by `00h` | 30 |
| D | `1Fh` down to `10h`, each followed by `00h` (second, independent reads) | 32 |

A complete run sends 66 records. The host compares each selector with the reference CRC-32 of banks 0 to 7 (embedded
from the author's `bank_diag` session; `--reference FILE` supplies your own) and tests the prediction `selector & 7`.

## bank_dump (build ID 0x0101, tool 2)

Source: `src/dump/bank_dump.c`. It transmits the full data of the banks selected by port 0x01 values **0 to 7**
(16384 bytes each, 128 KiB in total). It does not write any selector above 7.

* **ENTER**: dump banks 0 to 7 in order. **A digit 0 to 7**: dump only that bank (a new session).
* Per bank: one `BANK_BEGIN` frame, 128 `DATA` frames of 128 bytes (each with its own CRC-16), one `BANK_END` frame that carries
  the CRC-16 of the data as sent (read 1) and the **CRC-32 of a second complete read of the window** (read 2).
* Before the first bank the program computes the CRC-32 of the window as it is; at the end it writes selector 0 again and
  sends the CRC-32 of the restored window, plus a flag saying whether it equals the start-up CRC.
* There is no acknowledgement and no retransmission (the PC cannot talk to the Genio). Repeat a bank or the whole dump
  and compare sessions on the host.
* A complete session takes about 2.6 minutes (author's measurement).
* Keys `Z X C V P` adjust the bit timing as in the diagnostics (see the dumping guide).

## What was run on real hardware

All runs below were made by the author on one Spanish Genio 2000 on 2026-11-08 and are documented in
[HARDWARE_EVIDENCE.md](HARDWARE_EVIDENCE.md). They were recorded by the author; they were not repeated in the session in
which this repository was prepared.

| Program | Session id | Outcome (author's records) |
|---|---|---|
| `bank_diag` | 010C | stages A to D complete, 38 records; selectors 0 to 7 give eight distinct stable contents; selectors 8 to 15 repeat 0 to 7; window 0 unchanged; selector 0 restored correctly |
| `bank_diag16` | 0113 | stages A to D complete, 66 records; selectors 0x10 to 0x1F repeat banks 0 to 7 (`selector & 7`); 32 restores to selector 0 all correct |
| `bank_dump` | 0301 and 0097 | two complete sessions; 128 blocks per bank, no missing block, no rejected frame, no line error; all bank CRC-32 agree; the two sessions are identical; restore correct |

## Observation versus assumption

| Observation (measured on the author's unit) | Not established |
|---|---|
| Selectors 0 to 7 of port 0x01 show 8 different, stable 16 KiB contents in the window `0x4000-0x7FFF`. | Whether selector bits 5 to 7 do anything (they were never written). |
| Selectors 8 to 15 and 0x10 to 0x1F show the same contents as `selector & 7`. | Whether other ports (0x02, 0x04, 0x05) select further banks (never written). |
| The eight banks add up to 131072 bytes that were received intact. | **The physical capacity of the internal mask ROM.** Eight reachable banks do not prove that the chip holds exactly 128 KiB: a larger chip with unreachable parts, or a smaller chip with mirroring inside it, would look the same through port 0x01. |
| The banks are not all mirror copies of each other (all eight CRC-32 differ). | Whether the dump is every byte the machine can ever see (the firmware may bank through other ports). |

The 128 KiB image is therefore a **candidate dump of the banks reachable through port 0x01 selectors 0 to 7**, not a
statement about the chip's capacity.
