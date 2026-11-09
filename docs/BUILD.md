# Building, release images and reproducibility

## Toolchain used (the only one tested)

| Tool | Version |
|---|---|
| OS | Debian GNU/Linux 13.7, kernel 6.12.113+deb13-amd64, x86-64 |
| SDCC | 4.5.0 #15242 (Debian package `sdcc` 4.5.0+dfsg-1): `sdcc -mz80`, `sdasz80`, `sdldz80`, `makebin` |
| Python | 3.13.5 (only `tools/gen_crc32tab.py` and `tools/check_map.py` are needed to build) |
| coreutils | 9.7 (`dd`, `sha256sum`, `cat`) |
| VGLDK headers | commit 6fbd389ace4c, vendored unmodified in `third_party/vgldk` |

Other SDCC versions were not tried. Different compiler versions may produce different binaries.

## Build

```bash
./build.sh all        # or: ./build.sh diag | diag16 | dump
```

`build.sh` runs, for each program: `gen_crc32tab.py` (CRC-32 table placed at `0x9C00`), `sdasz80` for the VGLDK start-up
file and the table, `sdcc -mz80 --no-std-crt0 -D VGLDK_SERIES=2000 --code-loc 0x8020 --data-loc 0xc000`, `makebin`
(64 KiB image), then cuts the 8 KiB cartridge image from offset `0x8000`, builds the mirrored 32 KiB image, and runs
`tools/check_map.py`, which fails the build if code is outside `0x8020-0x9BFF`, data outside `0xC000-0xC3FF`, the table is
not at `0x9C00`, or the header is not `55 AA 59 45`.

## Release images

| File | Size | Use |
|---|---|---|
| `bank_diag.cart.8kb.bin`, `bank_diag16.cart.8kb.bin`, `bank_dump.cart.8kb.bin` | 8192 B | The raw cartridge image: the code as the Genio sees it at `0x8000`. For emulators and inspection. **Not the layout tested on hardware.** |
| `bank_diag_AT28C256_32K.bin`, `bank_diag16_AT28C256_32K.bin`, `bank_dump_AT28C256_32K.bin` | 32768 B | **These can be programmed directly into an AT28C256.** Each is the 8 KiB image repeated four times. |

### Why 8 KiB versus 32 KiB, and why mirroring

The cartridge image is 8 KiB (code at `0x8000-0x9FFF`). An AT28C256 holds 32 KiB, so a file for the chip must be 32 KiB.
Writing only the 8 KiB file would leave the rest of the chip blank, and then what the Genio reads depends on which
address lines are active. Because of the modification (see the hardware guide), the EEPROM sees the CPU lines A0 to A13
and bus line A15 on its A14 pin, while the bank-select lines A14 and A16 are not connected. Which bank the Genio selects for
the cartridge window at start-up is unknown. With **four identical copies**, the 8 KiB of code appears at every
combination of A13 and A14 of the EEPROM, so the program is found whatever those lines do. That reasoning is the design
rationale (INFERRED); what is certain is that the mirrored layout ran on the author's hardware.

## Reproducibility check (this session, software only)

1. Rebuilt all three programs from a fresh copy of the sources in a new directory, with (a) the VGLDK files vendored in the
   original project and (b) pristine files from the upstream VGLDK commit 6fbd389. **All six release images were
   byte-identical to the originally verified files in both cases.**
2. The three modified files in the original project's vendored VGLDK copy (an experimental 4×20 LCD option in
   `hd44780.h`, `arch/gl2000/system.h` and `tools/Makefile.mk`) are inactive unless a macro is defined; the build does not define it, so they
   do not influence the binaries. This repository vendors the unmodified upstream files.
3. After the cleanup (translation of messages, header comments, SPDX lines, file moves) the images were rebuilt again and compared: identical.
4. `tests/test_build.py` rebuilds `bank_diag` in a temporary directory and compares it to the committed build, and pins the
   SHA-256 of `bank_diag_AT28C256_32K.bin` (the image used in the author's hardware session 010C).

Limitations: one host, one compiler version; not tested in a container or on another distribution.

## SHA-256

See `release/SHA256SUMS`:

```
6122661e035cb05de84e72a9d95021b7ed37678802710eb5fd79e067a65c82f5  bank_diag.cart.8kb.bin
e9fab7b61319fb50aa7e8c0319e4bd1f0e329005a73bbb84e5eca55d8767b6ad  bank_diag_AT28C256_32K.bin
c88fe904ac5a717ff885eb11a90565f8a525044e3ee43fd5b914ca016b40a04b  bank_diag16.cart.8kb.bin
bc392ee393376f1184fe5141d1060e1208007c74d2d9a0aa567b43d672dca050  bank_diag16_AT28C256_32K.bin
a9d8bf18f93521454660c8d5941fa76a9c7a7dac8317982c23c864e9a70044bd  bank_dump.cart.8kb.bin
d9f1a3ec13056f0776605b07ceee9589332f1992bc383e4a0706be883a3c774c  bank_dump_AT28C256_32K.bin
```

## Hardware-test status of each image

| Image | Status |
|---|---|
| `bank_diag_AT28C256_32K.bin` | Used in the author's hardware session 010C (recorded). |
| `bank_diag16_AT28C256_32K.bin` | Used in session 0113 (recorded). |
| `bank_dump_AT28C256_32K.bin` | Used in sessions 0301 and 0097 (recorded). |
| the three `*.cart.8kb.bin` | **Not tested standalone.** Each is the first 8 KiB of the corresponding 32 KiB image; they were never programmed alone. |

How the link between the recorded sessions and these exact files is established: the captures identify the program by build
id (`0001`, `0002`, `0101`) and tool number, which match the source constants. The SHA-256 of the files was not recorded at capture time, but the
files in the author's `deliverables/` folder were written before the captures, and a rebuild reproduces them exactly. It is
a consistent chain of evidence, not a signed one. Nobody repeated the hardware runs while preparing this repository.
