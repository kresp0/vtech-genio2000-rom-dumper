// SPDX-License-Identifier: 0BSD
// Copyright (C) 2026 Santiago Crespo
/*
	bank_common.h - code shared by bank_diag.c (diagnostic) and bank_dump.c (full dump) for the VTech Genio 2000.
	Single translation unit: include it from the .c file AFTER <vgldk.h> (the .c files do that).

	HARDWARE-VALIDATED parts copied unchanged from the author's earlier 32 KiB partial dumper and serial test cartridge (not part of this repository):
	  tx_send(), line_set(), wait_bits() - printer-port soft UART, TX only, T642 = H30 F4.
	  LCD (GL4 4x20 map) and keyboard scan.
	NEW here: CRC-32 (asm, table in ROM at 0x9C00), protocol v2 frame layer, bank-port helper.

	Memory discipline (see docs/BANKS_AND_PRECAUTIONS.md):
	  * everything that executes, plus every constant/table, lives in the cartridge window 0x8000-0x9FFF;
	  * variables live from 0xC000 (VGLDK LOC_DATA, same as every previous cartridge); the stack is where the firmware left it;
	  * the only banked window ever READ is 0x0000/0x4000 as DATA, never executed;
	  * the only I/O port written for banking is 0x01 (window 0x4000), never 0x00 / 0x03.
*/

#define NCOLS 20
#define TXFIX 110
#define PRESET_A_H 16
#define PRESET_A_F 4
#define PRESET_B_H 30
#define PRESET_B_F 4		// T642 (validated on this Genio: 256/256 blocks VERIFIED)
#define H_MIN 4
#define H_MAX 44
#define F_MIN 1
#define F_MAX 12

#define SLIP_END     0xC0
#define SLIP_ESC     0xDB
#define SLIP_ESC_END 0xDC
#define SLIP_ESC_ESC 0xDD

#define PROTO_VER    2
#define T_START      1
#define T_DATA       2
#define T_END        3
#define T_BANKREC    0x10	// diagnostic record of one window/selector reading
#define T_STAGE      0x11	// diagnostic stage finished

#define SEL_NONE     0xFF	// "no selector written" in the header's bank field

#include "crc16_table.inc"

// 8-bit I/O port: bank register of the CPU window 0x4000-0x7FFF (MAME: rombank1_w; VGLDK gl4000 notes: port 0x01)
__sfr __at 0x01 port_bank1;

static const byte map_gl4[80] = {
	0,	1,	2,	3,	8,	9,	10,	11,	12,	13,	14,	15,	24,	25,	26,	27,	28,	29,	30,	31,
	64,	65,	66,	67,	72,	73,	74,	75,	76,	77,	78,	79,	88,	89,	90,	91,	92,	93,	94,	95,
	4,	5,	6,	7,	16,	17,	18,	19,	20,	21,	22,	23,	32,	33,	34,	35,	36,	37,	38,	39,
	68,	69,	70,	71,	80,	81,	82,	83,	84,	85,	86,	87,	96,	97,	98,	99,	100,	101,	102,	103
};

// ---- state (all set in main; cart_crt0 has no gsinit) ----
static byte sh[4][NCOLS], wn[4][NCOLS];
static byte serial_byte, serial_hc, serial_f;	// read by the asm routines
static word wb_n;
static byte preset, hc_base, f_base;
static byte kb_last, kb_cand, kb_cnt;
static word crc;			// running CRC-16 of the frame being sent
static word session;		// session id (16 bit), fixed when the first frame of a run is sent
static word seq;
static byte c32[4];			// running CRC-32 (little-endian bytes, not yet inverted)
static word c32_ptr, c32_len;	// arguments of crc32_run()
static word sp_main;

// ---------------- TX / timing routines: identical to serial_test_gl2000 (hardware-validated) ----------------
static void tx_send(void) __naked {
	__asm
		push	af
		push	bc
		push	de
		push	hl
		ld	a, (_serial_byte)
		ld	c, a
		ld	a, (_serial_hc)
		ld	d, a
		ld	a, (_serial_f)
		ld	l, a
		ld	e, #10
		or	a, a			; carry = 0 -> start bit (LOW)
	tx_loop:
		sbc	a, a			; 4   A = 0x00 (bit 0) or 0xff (bit 1)
		cpl				; 4   port value = ~A : bit 1 -> 0x00 (pins HIGH), bit 0 -> 0xff (pins LOW)
		out	(0x10), a		; 11  printer data
		ld	a, #0xff		; 7
		out	(0x11), a		; 11  latch / write enable (GL4000 documentation)
		in	a, (0x12)		; 11  read-modify-write: only bit 2 (STROBE) changes
		or	a, #0x04		; 7
		out	(0x12), a		; 11
		and	a, #0xfb		; 7
		out	(0x12), a		; 11
		ld	h, d			; 4
	tx_d1:
		dec	h			; 4
		jr	nz, tx_d1		; 12 / 7      => 16*H - 5
		ld	b, l			; 4
	tx_d2:
		djnz	tx_d2			; 13 / 8      => 13*F - 5  (+4 for ld b,l)
		scf				; 4
		rr	c			; 8
		dec	e			; 4
		jr	nz, tx_loop		; 12 / 7
		pop	hl
		pop	de
		pop	bc
		pop	af
		ret
	__endasm;
}

static void line_set(void) __naked {
	__asm
		push	af
		ld	a, (_serial_byte)
		and	a, #0x01
		neg				; 0 -> 0x00, 1 -> 0xff
		cpl
		out	(0x10), a
		ld	a, #0xff
		out	(0x11), a
		in	a, (0x12)
		or	a, #0x04
		out	(0x12), a
		and	a, #0xfb
		out	(0x12), a
		pop	af
		ret
	__endasm;
}

static void wait_bits(void) __naked {
	__asm
		push	af
		push	bc
		push	de
		push	hl
		ld	a, (_serial_hc)
		ld	d, a
		ld	a, (_serial_f)
		ld	l, a
		exx
		ld	de, (_wb_n)
		exx
	wb_loop:
		ld	h, d
	wb_d1:
		dec	h
		jr	nz, wb_d1
		ld	b, l
	wb_d2:
		djnz	wb_d2
		push	af
		pop	af
		push	af
		pop	af
		push	af
		pop	af
		nop
		nop
		nop
		nop
		exx
		dec	de
		ld	a, d
		or	a, e
		exx
		jr	nz, wb_loop
		pop	hl
		pop	de
		pop	bc
		pop	af
		ret
	__endasm;
}

// ---------------- CRC-32 (IEEE 802.3, reflected) over CPU memory ----------------
// Table planes crc_t0..crc_t3 are assembled at 0x9C00/0x9D00/0x9E00/0x9F00 (build/crc32tab.s), inside the cartridge window.
// c32[0..3] = running CRC, little-endian. Per byte:  idx = c0 ^ b;  c0 = c1 ^ T0[idx]; c1 = c2 ^ T1[idx]; c2 = c3 ^ T2[idx]; c3 = T3[idx].
// Reads the data with plain LD A,(HL): the data is never executed. Uses only registers + the 4 bytes of c32.
static void crc32_run(void) __naked {
	__asm
		push	af
		push	bc
		push	de
		push	hl
		ld	hl, (_c32_ptr)
		ld	bc, (_c32_len)
	crc32_byte:
		ld	a, (hl)
		inc	hl
		push	hl
		ld	hl, #_c32
		xor	a, (hl)
		ld	e, a
		ld	d, #0x9c		; plane 0 page (checked against the map by build.sh)
		ld	a, (de)
		inc	hl
		xor	a, (hl)
		dec	hl
		ld	(hl), a			; c0 = c1 ^ T0
		inc	hl
		inc	d
		ld	a, (de)
		inc	hl
		xor	a, (hl)
		dec	hl
		ld	(hl), a			; c1 = c2 ^ T1
		inc	hl
		inc	d
		ld	a, (de)
		inc	hl
		xor	a, (hl)
		dec	hl
		ld	(hl), a			; c2 = c3 ^ T2
		inc	hl
		inc	d
		ld	a, (de)
		ld	(hl), a			; c3 = T3
		pop	hl
		dec	bc
		ld	a, b
		or	a, c
		jr	nz, crc32_byte
		pop	hl
		pop	de
		pop	bc
		pop	af
		ret
	__endasm;
}

static void crc_begin(void) { c32[0] = 0xFF; c32[1] = 0xFF; c32[2] = 0xFF; c32[3] = 0xFF; }
static void crc_run(word p, word n) { c32_ptr = p; c32_len = n; crc32_run(); }
static void crc_out(byte *d) {		// final inversion; stored little-endian
	d[0] = (byte)~c32[0]; d[1] = (byte)~c32[1]; d[2] = (byte)~c32[2]; d[3] = (byte)~c32[3];
}

static void get_sp(void) __naked {
	__asm
		ld	hl, #0
		add	hl, sp
		ld	(_sp_main), hl		; includes the 2-byte return address of this call
		ret
	__endasm;
}

// ---------------- LCD (GL4 map) ----------------
static void blank(void) {
	byte r, c;
	for (r = 0; r < 4; r++) for (c = 0; c < NCOLS; c++) wn[r][c] = ' ';
}
static void lcd_reset_screen(void) {
	byte r, c;
	lcd_writeControl(LCD_CLEARDISPLAY);
	lcd_writeControl(LCD_RETURNHOME);
	lcd_delay_long();
	lcd_writeControl(LCD_ENTRYMODESET | LCD_ENTRYLEFT | LCD_ENTRYSHIFTDECREMENT);
	lcd_writeControl(LCD_DISPLAYCONTROL | LCD_DISPLAYON | LCD_CURSOROFF | LCD_BLINKOFF);
	for (r = 0; r < 4; r++) for (c = 0; c < NCOLS; c++) sh[r][c] = ' ';
}
static void draw(void) {
	byte r, c, a, nxt;
	nxt = 0xff;
	for (r = 0; r < 4; r++) for (c = 0; c < NCOLS; c++) {
		if (wn[r][c] != sh[r][c]) {
			a = map_gl4[(r << 4) + (r << 2) + c];
			if (a != nxt) lcd_writeControl(LCD_SETDDRAMADDR | a);
			lcd_writeData(wn[r][c]);
			sh[r][c] = wn[r][c];
			nxt = a + 1;
		}
	}
}
static void put(byte r, byte c, const char *s) { while (*s && c < NCOLS) wn[r][c++] = *s++; }
static void put_num(byte r, byte c, word v, byte digits) {
	byte i, k;
	word d, p;
	for (i = 0; i < digits; i++) {
		p = 1; for (k = i + 1; k < digits; k++) p = (word)(p << 3) + (word)(p << 1);
		d = 0; while (v >= p) { v -= p; d++; }
		if (c + i < NCOLS) wn[r][c + i] = '0' + (byte)d;
	}
}
static void put_hex2(byte r, byte c, byte v) {
	static const char hx[17] = "0123456789ABCDEF";
	wn[r][c] = hx[(v >> 4) & 15]; wn[r][c + 1] = hx[v & 15];
}
static void put_hex4(byte r, byte c, word v) { put_hex2(r, c, (byte)(v >> 8)); put_hex2(r, c + 2, (byte)v); }

// ---------------- keyboard (P10 matrix; polled, no interrupts) ----------------
static byte kb_scan(void) {
	byte r, m, v, k, idx;
	idx = 0xff;
	m = 0x01;
	for (r = 0; r < 8; r++) {
		keyboard_port_matrixRowOut = m;
		v = keyboard_port_matrixColIn;
		keyboard_port_matrixRowOut = 0x00;
		if (v != 0xff && idx == 0xff) {
			for (k = 0; k < 8; k++) if (!(v & (1 << k))) { idx = (r << 3) + k; break; }
		}
		m = m << 1;
	}
	return idx;
}
static byte kb_event(void) {
	byte idx;
	idx = kb_scan();
	if (idx == 0xff) { kb_last = 0xff; kb_cand = 0xff; kb_cnt = 0; return 0; }
	if (idx == kb_last) return 0;
	if (idx == kb_cand) {
		if (++kb_cnt >= 3) { kb_last = idx; return vgl_key_map[idx]; }
	} else { kb_cand = idx; kb_cnt = 0; }
	return 0;
}

// ---------------- frame layer, protocol v2 (see docs/PROTOCOL_V2.md) ----------------
// frame = END stuff( 'V' 'D' ver type session16 bank seq16 src16 off16 len16 payload[len] crc16 ) END, little endian,
// CRC-16/CCITT-FALSE over every byte from 'V' to the last payload byte (same CRC and SLIP framing as protocol v1).
static void tx_raw(byte b) { serial_byte = b; tx_send(); }
static void tx_stuffed(byte b) {
	if (b == SLIP_END) { tx_raw(SLIP_ESC); tx_raw(SLIP_ESC_END); }
	else if (b == SLIP_ESC) { tx_raw(SLIP_ESC); tx_raw(SLIP_ESC_ESC); }
	else tx_raw(b);
}
static void tx_crc(byte b) {
	crc = (word)(crc << 8) ^ crc16_tab[(byte)((crc >> 8) ^ b)];
	tx_stuffed(b);
}
static void tx_w16(word w) { tx_crc((byte)w); tx_crc((byte)(w >> 8)); }

static void frame_begin(byte type, byte sel, word src, word off, word len) {
	tx_raw(SLIP_END);
	crc = 0xFFFF;
	tx_crc('V'); tx_crc('D'); tx_crc(PROTO_VER); tx_crc(type);
	tx_w16(session); tx_crc(sel); tx_w16(seq); tx_w16(src); tx_w16(off); tx_w16(len);
	seq++;
}
static void frame_end(void) {
	word c;
	c = crc;				// the CRC bytes themselves are stuffed but not CRC'd
	tx_stuffed((byte)c); tx_stuffed((byte)(c >> 8));
	tx_raw(SLIP_END);
}

// ---------------- serial timing presets (same keys as before) ----------------
static void apply_preset(void) {
	if (preset) { hc_base = PRESET_B_H; f_base = PRESET_B_F; } else { hc_base = PRESET_A_H; f_base = PRESET_A_F; }
	serial_hc = hc_base; serial_f = f_base;
}
static word bit_t(void) { return TXFIX + ((word)serial_hc << 4) + (((word)serial_f << 3) + ((word)serial_f << 2) + serial_f); }
static void timing_key(byte c) {
	switch (c) {
		case 'Z': if (hc_base > H_MIN) hc_base--; break;
		case 'X': if (hc_base < H_MAX) hc_base++; break;
		case 'C': if (f_base > F_MIN) f_base--; break;
		case 'V': if (f_base < F_MAX) f_base++; break;
		case 'P': preset ^= 1; apply_preset(); break;
		default: break;
	}
	serial_hc = hc_base; serial_f = f_base;
}

// ---------------- bank window access ----------------
// Select a bank for the window 0x4000-0x7FFF. The only banking write of the whole program. 0..15 only.
// A few NOPs of settling before the first read (address decoding only; nothing here executes from the window).
static void bank1_select(byte sel) {
	port_bank1 = sel;
	__asm
		nop
		nop
		nop
		nop
	__endasm;
}
