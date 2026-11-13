#!/usr/bin/env python3
# SPDX-License-Identifier: 0BSD
# Copyright (C) 2026 Santiago Crespo
"""Generates build/<target>/crc32tab.s: CRC-32 table (IEEE 802.3, reflected, poly 0xEDB88320) as 4 planes of 256 bytes,
256-aligned, in an ABS area at 0x9C00 (inside the 8 KiB cartridge image). crc32_run() (bank_common.h)
uses D=0x9C as the page of plane 0, +1 for plane 1, etc. Assembler: sdasz80."""
import sys
BASE = 0x9C00
def table():
    t = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0xEDB88320 if c & 1 else c >> 1
        t.append(c)
    return t
def main(out):
    t = table()
    assert t[1] == 0x77073096 and t[255] == 0x2D02EF8D
    L = ["\t.module crc32tab", "\t.area _CRC32T (ABS)", "\t.org 0x%04X" % BASE]
    for p in range(4):
        L.append("_crc_t%d::" % p)
        for r in range(0, 256, 16):
            L.append("\t.db " + ",".join("0x%02X" % ((t[r + k] >> (8 * p)) & 0xFF) for k in range(16)))
    open(out, "w").write("\n".join(L) + "\n")
if __name__ == "__main__":
    main(sys.argv[1])
