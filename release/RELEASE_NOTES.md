# v1.0.0: first public release

**Title:** vtech-genio2000-rom-dumper v1.0.0: cartridge images for dumping the Spanish VTech Genio 2000 firmware

Six images, all rebuilt from this tag with SDCC 4.5.0 and byte-identical to the originally verified files.

| File | Size | SHA-256 |
|---|---|---|
| `bank_diag_AT28C256_32K.bin` | 32768 | `e9fab7b61319fb50aa7e8c0319e4bd1f0e329005a73bbb84e5eca55d8767b6ad` |
| `bank_diag16_AT28C256_32K.bin` | 32768 | `bc392ee393376f1184fe5141d1060e1208007c74d2d9a0aa567b43d672dca050` |
| `bank_dump_AT28C256_32K.bin` | 32768 | `d9f1a3ec13056f0776605b07ceee9589332f1992bc383e4a0706be883a3c774c` |
| `bank_diag.cart.8kb.bin` | 8192 | `6122661e035cb05de84e72a9d95021b7ed37678802710eb5fd79e067a65c82f5` |
| `bank_diag16.cart.8kb.bin` | 8192 | `c88fe904ac5a717ff885eb11a90565f8a525044e3ee43fd5b914ca016b40a04b` |
| `bank_dump.cart.8kb.bin` | 8192 | `a9d8bf18f93521454660c8d5941fa76a9c7a7dac8317982c23c864e9a70044bd` |

Check with `sha256sum -c SHA256SUMS`.

## Which file to use

* **Program the `*_AT28C256_32K.bin` files into an AT28C256.** Each is the 8 KiB cartridge image repeated four times.
* The `*.cart.8kb.bin` files are the raw cartridge images for inspection and emulators. They were not programmed on their own.
* Run `bank_diag` first, optionally `bank_diag16`, then `bank_dump` twice.

## Hardware-test status

| Image | Status |
|---|---|
| `bank_diag_AT28C256_32K.bin` | used in the author's recorded hardware session 010C |
| `bank_diag16_AT28C256_32K.bin` | used in session 0113 |
| `bank_dump_AT28C256_32K.bin` | used in sessions 0301 and 0097 |
| the three 8 KiB images | not tested standalone |

The recorded sessions were made on one Spanish Genio 2000 on 2026-11-08 with a modified cartridge. They were not repeated for this
release. The SHA-256 of the images used was not recorded at the time; a rebuild reproduces the original files exactly.

## You need

A modified cartridge (see `hardware/README.md`; the guide was made on the "Inglés para principiantes" cartridge, and other cartridges with different jumper settings may need different changes). **Inserting an AT28C256 into an unmodified cartridge can corrupt the EEPROM and
does not work.** Read the electrical-risks section first.

## Known limitations

* Tested on a single unit; no compatibility with other Genio revisions or VTech models is claimed.
* The dump covers selectors 0 to 7 of port 0x01 (131072 bytes); the physical capacity of the internal ROM is not determined.
* No VTech firmware is included. Do not upload dumps to the issue tracker.

## Licence

GPL-3.0-or-later for the original code (images contain VGLDK code: GPL v3). Built with VGLDK by Bernhard "HotKey" Slawik,
commit 6fbd389. Not affiliated with VTech.
