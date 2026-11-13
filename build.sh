#!/bin/bash
# SPDX-License-Identifier: 0BSD
# Copyright (C) 2026 Santiago Crespo
# build.sh <diag|diag16|dump|all>
#   diag    -> bank_diag      (stages A-D, selectors 0x00-0x0F)
#   diag16  -> bank_diag16    (stages A-D, selectors 0x10-0x1F)
#   dump    -> bank_dump      (full-data dump of selectors 0-7)
# Builds only inside build/<target>/ and reads third_party/vgldk (VGLDK headers, unmodified) and src/.
# Needs SDCC (sdcc, sdasz80, sdldz80, makebin) and Python 3. Never programs any chip.
set -euo pipefail
T=${1:?usage: build.sh diag|diag16|dump|all}
cd "$(dirname "$0")"
if [ "$T" = all ]; then for t in diag diag16 dump; do "$0" "$t"; done; exit 0; fi
V=third_party/vgldk
O=build/$T
XD=""
case $T in diag) SRC=src/diag/bank_diag.c; NAME=bank_diag;; diag16) SRC=src/diag/bank_diag.c; NAME=bank_diag16; XD="-DDIAG16=1";; dump) SRC=src/dump/bank_dump.c; NAME=bank_dump;; *) echo "unknown target $T" >&2; exit 2;; esac
mkdir -p "$O"
python3 tools/gen_crc32tab.py "$O/crc32tab.s"
sdasz80 -o "$O/crt0.rel" $V/include/arch/gl2000/cart_crt0.s
sdasz80 -o "$O/crc32tab.rel" "$O/crc32tab.s"
sdcc -mz80 --no-std-crt0 -D VGLDK_SERIES=2000 $XD --code-loc 0x8020 --data-loc 0xc000 \
  --lib-path $V/include -I $V/include -I $V/include/arch/gl2000 -I src/common \
  -o "$O/$NAME.ihx" "$O/crt0.rel" "$O/crc32tab.rel" $SRC 2>&1 | grep -v "warning 283\|warning 84\|warning 110" || true
test -s "$O/$NAME.ihx"
makebin -p -s 65536 "$O/$NAME.ihx" "$O/$NAME.ihx.bin" 2>/dev/null
dd iflag=skip_bytes skip=32768 bs=1024 count=8 if="$O/$NAME.ihx.bin" of="$O/$NAME.cart.8kb.bin" status=none
# AT28C256 image: the 8 KiB cartridge image repeated 4 times (32 KiB), the layout used on the author's hardware
for i in 1 2 3 4; do cat "$O/$NAME.cart.8kb.bin"; done > "$O/${NAME}_mirrored_AT28C256_32K.bin"
python3 tools/check_map.py "$O/$NAME.map" "$O/$NAME.cart.8kb.bin"
sha256sum "$O/${NAME}_mirrored_AT28C256_32K.bin" "$O/$NAME.cart.8kb.bin"
