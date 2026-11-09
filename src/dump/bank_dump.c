// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Santiago Crespo
/*
	bank_dump - PHASE 3: full-data dump of the internal-ROM banks selectable through port 0x01 (window 0x4000-0x7FFF) of the
	Spanish VTech Genio 2000: selectors 0..7, 16384 bytes each (128 KiB = 8 confirmed distinct banks; selectors 8..15 were
	observed to repeat 0..7, see docs/RESEARCH_SELECTORS.md). Genio -> PC only, printer-port soft UART 9600 8N1 (T642).

	Same protections as bank_diag: runs from the cartridge window 0x8000-0x9FFF (code, CRC table), DI, never EI, writes only
	port 0x01 with values 0..7 (never 0x00/0x02/0x03/0x04/0x05), SP checked before the first write, window restored to 0 at the end
	and verified against the start-up CRC. The banked window is only READ (plain loads), never executed.

	Per bank: BANK_BEGIN, 128 x DATA(128 B, own CRC-16), BANK_END { read-1 CRC-16 of the data as sent, read-2 CRC-32 of the whole window }.
	The PC compares the CRC-32 of what it received against the ROM's read 2, so a bank whose two reads differ is detected.
	No ACK / no retransmission: repeat a bank (press its digit) or the whole dump (ENTER) and compare sessions on the PC.

	Keys: ENTER = dump all banks 0..7 in order; digit 0..7 = dump only that bank (a new session); Z/X/C/V/P = timing as before.
*/

#define LCD_MINIMAL
#include <vgldk.h>
#include "../common/bank_common.h"

#define BUILD_ID    0x0101
#define TOOL_DUMP   2
#define NBANKS      8			// selectors 0..7 only (confirmed physically); extend only after a probe result
#define BLOCK_SIZE  128u
#define NBLOCKS     128u			// 16384 / 128
#define WIN1        0x4000u

#define T_BANK_BEGIN 0x20
#define T_BANK_END   0x21

#define SP_MIN 0xC400u
#define SP_MAX 0xE000u

static word crc_data16;		// CRC-16 of the data bytes of the bank as sent (read 1)
static byte sp_ok, banks_done;
static byte sel_cur;
static byte c32_base[4], c32_rest[4], c32_bank[4];

static void screen_dump(byte nth, byte nth_total, byte sel, word blk, const char *what) {
	byte pct;
	blank();
	put(0, 0, "BANK DUMP"); put(0, 10, "s"); put_hex4(0, 11, session);
	put(1, 0, "bank "); wn[1][5] = '1' + nth; put(1, 6, "/"); wn[1][7] = '0' + nth_total; put(1, 9, "sel "); put_hex2(1, 13, sel);
	put(2, 0, "blk "); put_num(2, 4, blk, 3); put(2, 7, "/128");
	pct = (byte)((blk >> 1) + (blk >> 2) + (blk >> 5));		// = blk * 25 / 32 ~ blk * 100 / 128, display only
	if (blk >= NBLOCKS) pct = 100;
	put_num(2, 13, pct, 3); put(2, 16, "%");
	put(3, 0, what);
	draw();
}

static void send_start(byte nsel_first, byte nsel_count, byte mode) {
	byte i;
	seq = 0;
	frame_begin(T_START, SEL_NONE, 0, 0, (word)(15 + nsel_count));
	tx_crc(TOOL_DUMP); tx_w16(BUILD_ID); tx_w16(sp_main);
	tx_crc(mode); tx_crc(nsel_count);
	tx_w16(BLOCK_SIZE); tx_w16(NBLOCKS);
	for (i = 0; i < 4; i++) tx_crc(c32_base[i]);
	for (i = 0; i < nsel_count; i++) tx_crc(nsel_first + i);
	frame_end();
}

static void send_bank(byte nth, byte nth_total, byte sel) {
	word blk, i, off;
	byte b;
	bank1_select(sel);				// the only banking write; selector 0..7
	screen_dump(nth, nth_total, sel, 0, "reading + sending");
	frame_begin(T_BANK_BEGIN, sel, WIN1, 0, 6);
	tx_crc(sel); tx_crc(1); tx_w16(NBLOCKS); tx_w16(BLOCK_SIZE);
	frame_end();
	crc_data16 = 0xFFFF;
	for (blk = 0; blk < NBLOCKS; blk++) {
		off = blk * BLOCK_SIZE;
		if ((blk & 3) == 0) screen_dump(nth, nth_total, sel, blk, "reading + sending");
		frame_begin(T_DATA, sel, WIN1, off, BLOCK_SIZE);
		for (i = 0; i < BLOCK_SIZE; i++) {
			b = *(volatile byte *)(WIN1 + off + i);			// plain load from the banked window (never executed)
			crc_data16 = (word)(crc_data16 << 8) ^ crc16_tab[(byte)((crc_data16 >> 8) ^ b)];
			tx_crc(b);
		}
		frame_end();
	}
	screen_dump(nth, nth_total, sel, NBLOCKS, "read 2 (CRC-32)");
	crc_begin(); crc_run(WIN1, 0x4000); crc_out(c32_bank);	// read 2 of the whole window
	frame_begin(T_BANK_END, sel, WIN1, 0, 9);
	tx_crc(sel); tx_w16(NBLOCKS); tx_w16(crc_data16);
	for (i = 0; i < 4; i++) tx_crc(c32_bank[i]);
	frame_end();
	banks_done++;
}

static void idle_screen(const char *l1, const char *l2) {
	blank();
	put(0, 0, "BANK DUMP v1 (0-7)");
	put(1, 0, l1); put(2, 0, l2);
	put(3, 0, "H"); put_num(3, 1, serial_hc, 2); put(3, 4, "F"); put_num(3, 5, serial_f, 2);
	put(3, 8, "T"); put_num(3, 9, bit_t(), 3);
	draw();
}

// returns '\r' (all banks) or a digit '0'..'7' (one bank); Z/X/C/V/P adjust the timing
static byte wait_key(const char *l1, const char *l2, byte redraw) {
	byte c;
	if (redraw) idle_screen(l1, l2);
	while (1) {
		c = kb_event();
		if (c == '\r' || (c >= '0' && c < '0' + NBANKS)) break;
		if (c) { timing_key(c); idle_screen(l1, l2); }
		session++;				// free-running while waiting: every run gets a different session id
		wb_n = 96; wait_bits();
	}
	kb_last = kb_scan();
	return c;
}

static void dump_run(byte first, byte count, byte mode) {
	byte k, i, restore_ok;
	banks_done = 0;
	serial_byte = 1; line_set();
	wb_n = 2880; wait_bits();				// ~300 ms idle
	screen_dump(0, count, first, 0, "baseline CRC-32");
	crc_begin(); crc_run(WIN1, 0x4000); crc_out(c32_base);	// window 0x4000 as it is right now (before any write of this run)
	send_start(first, count, mode);
	for (k = 0; k < count; k++) send_bank(k, count, first + k);
	bank1_select(0);					// restore the boot value
	screen_dump(count - 1, count, 0, NBLOCKS, "restore check");
	crc_begin(); crc_run(WIN1, 0x4000); crc_out(c32_rest);
	restore_ok = 1;
	for (i = 0; i < 4; i++) if (c32_rest[i] != c32_base[i]) restore_ok = 0;
	frame_begin(T_END, SEL_NONE, 0, 0, 7);
	tx_crc(banks_done); tx_crc(restore_ok); tx_crc(sp_ok);
	for (i = 0; i < 4; i++) tx_crc(c32_rest[i]);
	frame_end();
	serial_byte = 1; line_set();
	blank();
	put(0, 0, "BANK DUMP DONE s"); put_hex4(0, 16, session);
	put(1, 0, "banks sent "); put_num(1, 11, banks_done, 2);
	put(2, 0, restore_ok ? "restore sel0: OK" : "RESTORE DIFFERS!");
	put(3, 0, "ENTER/0-7 = again");
	draw();
	kb_last = kb_scan();
}

void main() {
	byte c, first_wait;
	first_wait = 1;

	__asm
		di
	__endasm;
	preset = 1; serial_byte = 1; wb_n = 96;
	kb_cnt = 0; kb_cand = 0xff; session = 0; seq = 0;
	crc = 0; banks_done = 0;
	get_sp();
	sp_ok = (sp_main >= SP_MIN && sp_main <= SP_MAX) ? 1 : 0;
	apply_preset();
	lcd_reset_screen();
	kb_last = kb_scan();
	if (!sp_ok) {
		blank(); put(0, 0, "STOP: SP out of RAM"); put(1, 0, "SP="); put_hex4(1, 3, sp_main);
		put(2, 0, "no bank write done"); put(3, 0, "power off"); draw();
		while (1) { wb_n = 960; wait_bits(); }
	}
	while (1) {
		c = wait_key("ENTER=all banks 0-7", "0-7 = one bank only", first_wait);
		first_wait = 0;
		if (c == '\r') dump_run(0, NBANKS, 0);
		else dump_run(c - '0', 1, 1);
	}
}
