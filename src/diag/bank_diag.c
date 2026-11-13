// SPDX-License-Identifier: 0BSD
// Copyright (C) 2026 Santiago Crespo
/*
	bank_diag - PHASE 2: bank-selection diagnostic for the Spanish VTech Genio 2000 internal ROM. Genio -> PC only (printer-port soft UART).

	It never modifies the internal ROM (read-only) and never writes any port except, in stages B-D, port 0x01
	(bank register of the CPU window 0x4000-0x7FFF) with values 0..15. Port 0x00 and 0x03 are NEVER written.
	The program executes from the cartridge window 0x8000-0x9FFF (all code and constants there); the banked window is only READ.
	Interrupts: DI at entry and never re-enabled (IFF2 = 0 was already observed on this machine).

	Stages, each started by ENTER and separated by a prompt so you can stop (power off) between them:
	  A  no writes at all: record of window 0x0000 and of window 0x4000 as the firmware left them (baseline).
	  B  one write: OUT (01h),00h  (the value the firmware itself writes on boot; expected: window 0x4000 unchanged).
	  C  one write OUT (01h),01h -> record; then OUT (01h),00h -> record (restore check).
	  D  sweep selectors 0..15 forward, then 15..0 backwards, then a final selector 0 (restore).
	Every record: 4 x CRC-32 of the 4 KiB quarters (read 1), CRC-32 of the 16 KiB (read 2), CRC-32 of the first 256 bytes of window 0
	(taken after the selection: shows that window 0 is unaffected) and 4 x 16-byte samples. PC side combines the quarter CRCs
	(crc32_combine) and compares with the whole-bank CRC to detect unstable reads.

	Frames: protocol v2 (docs/PROTOCOL_V2.md). Nothing but frames is sent. LCD shows stage / selector / progress.
*/

#define LCD_MINIMAL
#include <vgldk.h>
#include "../common/bank_common.h"

#ifdef DIAG16
	// Variant "diag16": probes selectors 0x10..0x1F of port 0x01 (never tried before), each followed by a restore to 0.
	#define BUILD_ID    0x0002
	#define TOOL_DIAG   3
	#define TITLE       "BANK DIAG16 v1"
#else
	#define BUILD_ID    0x0001
	#define TOOL_DIAG   1
	#define TITLE       "BANK DIAG v1"
#endif

#define NSAMP       4
#define SAMP_LEN    16
static const word samp_off[NSAMP] = { 0x0000, 0x1000, 0x2000, 0x3FF0 };

#define STG_A 0
#define STG_B 1
#define STG_C 2
#define STG_D 3

// RAM sanity window for the stack, checked before any bank write (data lives at 0xC000.., see the map file)
#define SP_MIN 0xC400u
#define SP_MAX 0xE000u

static byte rec[28 + NSAMP * SAMP_LEN];
static byte stage_recs;
static word total_recs;
static byte sp_ok;
static byte cur_stage;

static void status_screen(byte window, byte sel, const char *what) {
	blank();
	put(0, 0, "BANK DIAG ST"); wn[0][12] = 'A' + cur_stage;
	put(0, 14, "s"); put_hex4(0, 15, session);
	put(1, 0, window ? "win 4000 " : "win 0000 ");
	if (sel == SEL_NONE) put(1, 9, "sel --"); else { put(1, 9, "sel "); put_hex2(1, 13, sel); }
	put(2, 0, what);
	put(3, 0, "recs "); put_num(3, 5, total_recs, 3);
	draw();
}

// One record: reads CPU memory at base 0x0000 (window 0) or 0x4000 (window 1) as data. No banking write here.
static void do_record(byte window, byte wrote, byte outv) {
	byte q, s, i;
	word base, p;
	base = window ? 0x4000 : 0x0000;
	rec[0] = window; rec[1] = cur_stage; rec[2] = wrote; rec[3] = outv;
	status_screen(window, wrote ? outv : SEL_NONE, "read 1/2 (4 x 4K)");
	for (q = 0; q < 4; q++) {			// read 1: four independent quarter CRC-32
		crc_begin();
		crc_run(base + ((word)q << 12), 0x1000);
		crc_out(&rec[8 + (q << 2)]);
	}
	status_screen(window, wrote ? outv : SEL_NONE, "read 2/2 (16K)");
	crc_begin();					// read 2: the whole 16 KiB again
	crc_run(base, 0x4000);
	crc_out(&rec[4]);
	crc_begin();					// window 0 head, after the selection (must not change)
	crc_run(0x0000, 0x0100);
	crc_out(&rec[24]);
	for (s = 0; s < NSAMP; s++) {			// samples, read once more
		p = base + samp_off[s];
		for (i = 0; i < SAMP_LEN; i++) rec[28 + (s << 4) + i] = *(volatile byte *)(p + i);
	}
	status_screen(window, wrote ? outv : SEL_NONE, "sending");
	frame_begin(T_BANKREC, wrote ? outv : SEL_NONE, base, 0, 28 + NSAMP * SAMP_LEN);
	for (i = 0; i < 28 + NSAMP * SAMP_LEN; i++) tx_crc(rec[i]);
	frame_end();
	stage_recs++; total_recs++;
}

static void send_start(void) {
	byte i;
	seq = 0;
	frame_begin(T_START, SEL_NONE, 0, 0, 15);
	tx_crc(TOOL_DIAG); tx_w16(BUILD_ID); tx_w16(sp_main);
	tx_crc(NSAMP); tx_crc(SAMP_LEN);
	for (i = 0; i < NSAMP; i++) tx_w16(samp_off[i]);
	frame_end();
}
static void send_stage_end(byte ok) {
	frame_begin(T_STAGE, SEL_NONE, 0, 0, 3);
	tx_crc(cur_stage); tx_crc(stage_recs); tx_crc(ok);
	frame_end();
}
static void send_end(void) {
	frame_begin(T_END, SEL_NONE, 0, 0, 3);
	tx_w16(total_recs); tx_crc(sp_ok ? 1 : 0);
	frame_end();
}

static void idle_screen(const char *l1, const char *l2) {
	blank();
	put(0, 0, TITLE);
	put(1, 0, l1);
	put(2, 0, l2);
	put(3, 0, "H"); put_num(3, 1, serial_hc, 2); put(3, 4, "F"); put_num(3, 5, serial_f, 2);
	put(3, 8, "T"); put_num(3, 9, bit_t(), 3);
	draw();
}

static byte wait_enter(const char *l1, const char *l2, byte bump) {	// returns after ENTER; Z/X/C/V/P adjust timing
	byte c;
	idle_screen(l1, l2);
	while (1) {
		c = kb_event();
		if (c == '\r') break;
		if (c) { timing_key(c); idle_screen(l1, l2); }
		if (bump) session++;			// free-running counter while waiting for stage A: becomes the session id, then fixed
		wb_n = 96; wait_bits();
	}
	kb_last = kb_scan();			// a held ENTER is ignored until released
	return 1;
}

static void stage_done(byte next_prompt_ok) {
	send_stage_end(next_prompt_ok);
	serial_byte = 1; line_set();
}

void main() {
	byte s;

	__asm
		di
	__endasm;
	preset = 1; serial_byte = 1; wb_n = 96;
	kb_cnt = 0; kb_cand = 0xff; session = 0; seq = 0;
	crc = 0; total_recs = 0; stage_recs = 0; cur_stage = 0;
	get_sp();
	sp_ok = (sp_main >= SP_MIN && sp_main <= SP_MAX) ? 1 : 0;
	apply_preset();
	lcd_reset_screen();
	kb_last = kb_scan();

	// ---------------- Stage A: baseline, NO writes ----------------
	wait_enter("ENTER=stage A (no", "writes, baseline)", 1);
	cur_stage = STG_A; stage_recs = 0;
	serial_byte = 1; line_set();
	wb_n = 2880; wait_bits();			// ~300 ms idle line
	send_start();
	do_record(0, 0, 0);
	do_record(1, 0, 0);
	stage_done(sp_ok);
	if (!sp_ok) {
		blank(); put(0, 0, "STOP: SP out of RAM"); put(1, 0, "SP="); put_hex4(1, 3, sp_main);
		put(2, 0, "no bank write done"); put(3, 0, "power off"); draw();
		while (1) { wb_n = 960; wait_bits(); }
	}

#ifdef DIAG16
	// ---------------- Stage B: ONE untested selector, 0x10, then restore 0 ----------------
	wait_enter("A done. ENTER=B:", "OUT 01h<-10h,then 00", 0);
	cur_stage = STG_B; stage_recs = 0;
	bank1_select(0x10);
	do_record(1, 1, 0x10);
	bank1_select(0);
	do_record(1, 1, 0);
	stage_done(1);

	// ---------------- Stage C: 0x11..0x1F, each followed by a restore to 0 ----------------
	wait_enter("B done. ENTER=C:", "sel 11h..1Fh +restore", 0);
	cur_stage = STG_C; stage_recs = 0;
	for (s = 0x11; s <= 0x1F; s++) {
		bank1_select(s); do_record(1, 1, s);
		bank1_select(0); do_record(1, 1, 0);
	}
	stage_done(1);

	// ---------------- Stage D: 0x1F..0x10 (second, independent readings), each followed by a restore ----------------
	wait_enter("C done. ENTER=D:", "sel 1Fh..10h +restore", 0);
	cur_stage = STG_D; stage_recs = 0;
	for (s = 0x20; s > 0x10; s--) {
		bank1_select(s - 1); do_record(1, 1, s - 1);
		bank1_select(0); do_record(1, 1, 0);
	}
	stage_done(1);
	send_end();
#else
	// ---------------- Stage B: one write, OUT (01h),00h ----------------
	wait_enter("A done. ENTER=B:", "OUT 01h<-00h once", 0);
	cur_stage = STG_B; stage_recs = 0;
	bank1_select(0);
	do_record(1, 1, 0);
	stage_done(1);

	// ---------------- Stage C: select 1, then back to 0 ----------------
	wait_enter("B done. ENTER=C:", "OUT 01h<-01h,then 00", 0);
	cur_stage = STG_C; stage_recs = 0;
	bank1_select(1);
	do_record(1, 1, 1);
	bank1_select(0);
	do_record(1, 1, 0);
	stage_done(1);

	// ---------------- Stage D: sweep 0..15, 15..0, restore 0 ----------------
	wait_enter("C done. ENTER=D:", "sweep 0..15,15..0", 0);
	cur_stage = STG_D; stage_recs = 0;
	for (s = 0; s < 16; s++) { bank1_select(s); do_record(1, 1, s); }
	for (s = 16; s > 0; s--) { bank1_select(s - 1); do_record(1, 1, s - 1); }
	bank1_select(0);
	do_record(1, 1, 0);
	stage_done(1);
	send_end();

#endif

	blank();
	put(0, 0, "BANK DIAG DONE");
	put(1, 0, "recs "); put_num(1, 5, total_recs, 3);
	put(2, 0, "window 4000 <- sel 0");
	put(3, 0, "power off now");
	draw();
	while (1) { wb_n = 960; wait_bits(); }
}
