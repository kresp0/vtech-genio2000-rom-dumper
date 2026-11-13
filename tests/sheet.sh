#!/bin/sh
# Runs bank_diag and bank_dump in headless MAME with tests/shots.lua (scripts tests/shots_diag.txt and
# tests/shots_dump.txt) and joins their native LCD snapshots, x4, two per row, into screens_mame.png
# (the layout of the examples in kresp0/vtech-genio2000). Needs a MAME with the genio2000 driver and
# your own ROM: GENIO_MAME (default mame), GENIO_ROMPATH (default roms). No window is opened.
# Copyright (C) 2026 Santiago Crespo
# SPDX-License-Identifier: 0BSD
set -e
HERE=$(cd "$(dirname "$0")/.." && pwd)
MAME=${GENIO_MAME:-mame}
ROMPATH=$(realpath -m "${GENIO_ROMPATH:-roms}")
OUT=$HERE/build/shots
rm -rf "$OUT"
unset DISPLAY WAYLAND_DISPLAY
export SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy
for p in diag dump; do
  SHOTS_SCRIPT="$HERE/tests/shots_$p.txt" "$MAME" genio2000 -rompath "$ROMPATH" \
    -cart "$HERE/release/bank_${p}_AT28C256_32K.bin" -skip_gameinfo -nothrottle -video none -sound none \
    -seconds_to_run 900 -snapshot_directory "$OUT/$p" -snapview native -cfg_directory "$OUT/cfg" -nvram_directory "$OUT/nvram" \
    -autoboot_script "$HERE/tests/shots.lua" > "$OUT.$p.log" 2>&1 || true
done
python3 - "$OUT" "$HERE/screens_mame.png" <<'PY'
import glob, sys
from PIL import Image
fs = sorted(glob.glob(sys.argv[1] + "/diag/genio2000/*.png")) + sorted(glob.glob(sys.argv[1] + "/dump/genio2000/*.png"))
sheet = Image.new("RGB", (2 * 490, (len(fs) + 1) // 2 * 170), "white")
for i, f in enumerate(fs):
    sheet.paste(Image.open(f).convert("RGB").resize((480, 160), Image.NEAREST), ((i % 2) * 490, (i // 2) * 170))
sheet.save(sys.argv[2])
print("%d snapshots -> %s" % (len(fs), sys.argv[2]))
PY
