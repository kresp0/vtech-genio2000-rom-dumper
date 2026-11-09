# Testing

Run everything (about 80 seconds, no hardware, no MAME):

```bash
./build.sh all
python3 -m pytest -q -p no:cacheprovider tests
```

Result recorded while preparing this repository (Debian 13.7, Python 3.13.5, pytest 8.3.5, SDCC 4.5.0): **99 passed in 82 s, 0 failed, 0 skipped.**

## What each kind of evidence means

| Category | What it is | Where |
|---|---|---|
| **Automated tests** | Run by `pytest` on every change. | `tests/` |
| **Simulated tests** | The compiled cartridge images are executed instruction by instruction in a small Z80 interpreter (`tests/z80core.py`) against a model of the banked memory (`tests/sim_genio.py`). Timing routines are replaced by hooks, so **timing and electrical behaviour are not tested**. The memory model follows the MAME `pc2000` driver as described by the author; MAME itself is not used. | `test_rom_sim.py`, `test_diag16.py`, `test_dump.py` |
| **Previously recorded hardware tests** | Runs of the three programs on the author's Genio on 2026-11-08 (sessions 010C, 0113, 0301, 0097). Raw captures are not published (they contain the firmware). Derived facts are in [HARDWARE_EVIDENCE.md](HARDWARE_EVIDENCE.md). | not re-run |
| **New in the preparation session** | Software only: clean rebuild and comparison of all six images; the full test suite; **offline re-analysis of the recorded raw captures** with the cleaned-up tools, which reproduced the author's candidate image hash. **No new physical hardware test was performed.** | this page |

## Automated test coverage

| File | Tests | What it checks |
|---|---|---|
| `test_protocol.py` | 13 | CRC-16 and CRC-32 values, `crc32_combine`, SLIP stuffing, frame parsing, rejection of damaged frames, PARMRK line-error handling. |
| `test_crc32_asm.py` | 9 | The Z80 CRC-32 routine (really executed, not hooked) against `zlib`, including a full 16 KiB bank and counter wrap-around. |
| `test_build.py` | 10 | Header `55 AA 59 45`, 8 KiB image, 32 KiB image = 4 × 8 KiB, code below the CRC table, `check_map.py`, only bank port 0x01 present among bank ports, reproducible rebuild in a temporary directory, release images equal to the build, pinned SHA-256 of `bank_diag_AT28C256_32K.bin`. |
| `test_rom_sim.py` | 20 | `bank_diag` executed in the simulator: PC never leaves the cartridge window, writes only to RAM, only port 0x01 written, stage sequence, window restored, detection of mirrored, empty and unstable banks. |
| `test_diag16.py` | 11 | `bank_diag16`: selectors 0x10 to 0x1F, restore after each, three-bit and four-bit decoding, open-bus detection, interrupted sweep, CLI exit codes. |
| `test_dump.py` | 25 | `bank_dump`: every bank, DATA frame layout, lost/duplicated/corrupt frames, interrupted transfers, bank CRC mismatch, block-level combination of sessions, **conflicting reads**, unreadable banks, **identical capture given twice is not independent**, manifest content, CLI exit codes. |
| `test_receiver.py` | 11 | Diagnostic receiver on captures: lost blocks are reported and not filled, duplicates, corruption, truncated last frame, two sessions not mixed, JSON/CSV output, CLI exit codes, never overwriting existing files. |

## Error handling that is demonstrated by the tests

* Incomplete transfer: reported as `INCOMPLETE`/missing blocks; no candidate image is written.
* Corrupt frame: rejected by CRC-16; the block is reported missing.
* Bank whose second read differs: `COMPLETE_ROM_CRC_MISMATCH`, not accepted.
* Two valid but different reads of a block: `CONFLICT`, no majority vote.
* One session only: blocks stay `SINGLE`, bank not verified, no candidate image.

## Reanalysis of recorded captures (this session)

Using only read access to the author's original captures (not copied into this repository):

* `bank_dump_verify.py` on sessions 0301 and 0097: 8 banks, 128/128 blocks VERIFIED each, all bank CRC-32 agree with the
  cartridge, sessions identical; candidate image SHA-256
  `f66f4d51d7152a8264ff9d99cbeb38dbbb5cc2d6f087e3fffb4e067f42e5ea48`, identical to the value the author recorded earlier.
* `bank_diag_rx.py --analyze` on session 010C (38 records) and 0113 (66 records): the results quoted in the evidence page.

## Limitations

* The simulator does not model timing, so the serial bit timing is validated only by the earlier hardware sessions.
* One host environment; Linux only.
* The live serial receivers (`--port`) are not covered by the automated tests (they need a serial device); their decoding
  code is the same as the offline `--analyze` path, which is tested.
* Nothing about other Genio 2000 hardware revisions or other VTech models is tested.
