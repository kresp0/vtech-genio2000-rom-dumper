# Licensing audit

Audit date: 2026-11-09. Scope: everything in this repository and the tools needed to build it.

## Recommendation

**SPDX identifier for the original code of this repository: `GPL-3.0-or-later`.**
The repository `LICENSE` file is the unmodified GNU GPL version 3 text.

The combined work that is actually distributed (the cartridge binaries, which contain code from VGLDK) is, in practice,
distributable only under **GPL version 3**: see "Why or-later is still acceptable" below.

## Evidence about VGLDK

| Item | Finding |
|---|---|
| Upstream | https://github.com/hotkeymuc/vgldk, author Bernhard "HotKey" Slawik (hotkeymuc) |
| Checked version | commit `6fbd389ace4c7bf156cb2c3fafafb1acf4a2a857` ("LoopFlag bug fixed, unbreaks KQ1, SQ2"), the local clone has no uncommitted changes |
| Repository license file | `LICENSE`: GNU GPL version 3, 29 June 2007, 35 149 bytes, the standard FSF text (copied to `third_party/vgldk/LICENSE`, identical) |
| Per-file notices | **Only `include/vgldk.h`** carries a license header ("2017 Bernhard "HotKey" Slawik ... GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version"). The other six vendored files have an author/date line (2019 or 2020 "Bernhard "HotKey" Slawik") but **no license notice**. |
| Version and "or later" | `vgldk.h`: **GPL-3.0-or-later**. Other files: no statement; the repository-level license is GPL v3 and the files are covered by it. Whether "or later" extends to them is **not stated by upstream**. |
| README | No licensing text. States the project is unofficial and not affiliated with VTech. |

## Which files came from VGLDK

Seven files, vendored byte-identically in `third_party/vgldk/include/` (list in `third_party/README.md`), plus the upstream `LICENSE`
and README. They are exactly the files the SDCC build reads (determined by tracing the compiler). Verified identical to the
upstream commit by `cmp`.

The author's original working copy (`firmware-dump/vendor/vgldk`, not published) contained 85 VGLDK files, of which three differed from upstream:

| File | Difference |
|---|---|
| `include/arch/gl2000/system.h` | Experimental `VGLDK_GL2000_LCD_4X20` option, off by default |
| `include/driver/hd44780.h` | A `defined(VGLDK_LCD_MAP_EXTERNAL)` branch, inactive by default |
| `tools/Makefile.mk` | A `VGLDK_CFLAGS` variable, not used by the dumper build |

These three modifications are **not** included in this repository (the build does not need them; rebuilding with pristine upstream files
gives byte-identical images). The other 78 VGLDK files in the working copy (other platforms, examples, drivers, tools, including the modified `Makefile.mk`) are not used and not
included. The working copy also lacked the upstream `LICENSE` file, which this repository adds. This repository contains no modified upstream file.

## Original versus derived code

| Part | Status |
|---|---|
| `src/common/bank_common.h`, `src/diag/bank_diag.c`, `src/dump/bank_dump.c` | Original to this project; **not** a copy of VGLDK code. They `#include` VGLDK headers and are compiled and linked together with VGLDK's start-up file and LCD/keyboard definitions, so the resulting binary is a combined work. They reuse the author's earlier hardware-validated transmit and timing routines (not part of this repository). The LCD address map table `map_gl4` is a hardware fact (HD44780 DDRAM layout of a 4-row module) and also exists in VGLDK's `hd44780.h`. |
| `src/common/crc16_table.inc` | Generated standard CRC-16/CCITT-FALSE table. |
| `tools/*.py`, `tests/*.py`, `build.sh` | Original to this project. `tests/z80core.py` is an interpreter written for this project's tests. |
| `third_party/vgldk/*` | Upstream VGLDK, unmodified, attributed to its author. |
| Documentation, photographs, annotated images, diagrams | Original; photographs by the author, released under GPL-3.0-or-later (explicit declaration in `hardware/photos/README.md`, authorised by the author on 2026-11-09). Third-party attributions and licenses are untouched. |

## Copyright notices and attribution

* Upstream notices are preserved untouched in the vendored files, and `third_party/vgldk/LICENSE` is included.
* VGLDK and its author are credited in the README and in `third_party/README.md`.
* Original files carry `SPDX-License-Identifier: GPL-3.0-or-later` and
  `Copyright (C) 2026 Santiago Crespo` (confirmed by the owner).

## Why or-later is still acceptable

* The or-later grant applies to the files the author wrote. Choosing GPL-3.0-or-later for them is compatible with all inputs
  (everything is GPL v3 or GPL v3 or later).
* The *combined* binaries include VGLDK files for which "or later" is not stated, so the combined work as conveyed must satisfy GPL v3 and
  is documented as such in the README. This costs nothing in practice: recipients get GPL v3 rights in every case.
* If the owner prefers to avoid any ambiguity, **`GPL-3.0-only`** is also valid and would be the more conservative choice; the only
  loss is that others could not combine the original files with future GPL versions. The evidence (an explicit "or later" in the
  one upstream header that has a notice) favours or-later; nothing contradicts it.
* Optionally ask upstream to add a license notice to the remaining files (not required for compliance).

## Other dependencies and tools

| Item | Used for | License | Included? |
|---|---|---|---|
| SDCC 4.5.0 | compiling | Compiler tools: GPL. Its runtime library is, according to SDCC's documentation, GPL with a linking exception (not independently re-checked here). The three binaries contain a few SDCC runtime helper routines (`__divuchar`, `__divuint`, `__moduint` and similar, visible in the linker maps of all three programs). The linking exception is what allows these in a GPL-3.0 combined work. | No |
| Python 3 | host tools | PSF License | No |
| pyserial 3.5 | live receivers (imported lazily) | BSD-3-Clause | No |
| pytest | tests | MIT | No |
| zlib (Python module) | CRC-32 on the host | zlib license | No |

Compiler output is not subject to the compiler's license merely because of the compiler; the SDCC library exception is mentioned for completeness.

## Material deliberately not included

| Material | Why |
|---|---|
| VTech firmware (any dump, partial dump, captures containing it) | VTech's copyright. Only CRC-32/hashes are published. |
| Datasheet PDFs (Sharp LH531000B, Atmel AT28C256) | Redistribution terms unclear; links are given instead. |
| HotKey's KiCad netlist and Gerber files | Third-party files with unstated license; cited by link and used only as a reference for the pinout. |
| MAME sources and the experimental MAME patch, MAME ROM images | Out of scope; MAME is under its own license (BSD-3-Clause / GPL mix), no MAME code is in this repository. |

## Open licensing questions

1. Copyright holder (Santiago Crespo) and `GPL-3.0-or-later` were confirmed by the owner on 2026-11-09.
2. `hd44780.h` mentions the MAME driver as a source of the LCD layout; MAME's driver is BSD-3-Clause. A bare table of LCD addresses is a
   hardware fact, so this was judged low risk, but it is upstream's file and was not investigated further.
3. Trademarks: "VTech", "Genio" and "Genius Leader" are VTech's. The README states the project is not affiliated with VTech.

This audit is a technical review of the repository contents, not legal advice.
