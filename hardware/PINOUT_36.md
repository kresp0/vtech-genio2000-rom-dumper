# 36-contact VTech cartridge connector (CTL1200-36)

Source of the signal names: the netlist of HotKey's "V-Tech Bus Ficker" cartridge (KiCad, Rev D, 2019-07-31), a design for
the Genius Leader 4000/6000SL family. **No published documentation of the Genio 2000 connector was found**; the table is
therefore INFERRED for the Genio 2000, except where the author measured the cartridge.

Seven ROM pins of the original Genio 2000 cartridge were measured with a multimeter against connector contacts. All seven
agree with the netlist (MEASURED = M). That is strong evidence, not proof, that the rest of the table also holds.

| Contact | Signal | ROM socket pin | Basis |
|---|---|---|---|
| 1 | X1 | – | UNKNOWN function |
| 2 | X2 | – | UNKNOWN function |
| 3 | X3 | – | UNKNOWN function |
| 4 | X4 | – | UNKNOWN function |
| 5 | /WR | – (not wired to the ROM) | netlist |
| 6 | D2 | 13 | netlist |
| 7 | D1 | 12 | netlist |
| 8 | D0 | 11 | netlist |
| 9 | A0 | 10 | netlist |
| 10 | A1 | 9 | netlist |
| 11 | A10 | 21 | netlist |
| 12 | A16 | 22 (through J2) | **M** (pin 22 → J2 → contact 12) |
| 13 | A11 | 23 | netlist |
| 14 | A9 | 24 | netlist |
| 15 | A8 | 25 | netlist |
| 16 | A13 | 26 | **M** |
| 17 | A14 | 27 | **M** |
| 18 | GND | 14 | **M** |
| 19 | A15 | 1 | **M** |
| 20 | A12 | 2 | **M** |
| 21 | A7 | 3 | netlist |
| 22 | A6 | 4 | netlist |
| 23 | A5 | 5 | netlist |
| 24 | A4 | 6 | netlist |
| 25 | A3 | 7 | netlist |
| 26 | A2 | 8 | netlist |
| 27 | D7 | 19 | netlist |
| 28 | D6 | 18 | netlist |
| 29 | D5 | 17 | netlist |
| 30 | D4 | 16 | netlist |
| 31 | D3 | 15 | netlist |
| 32 | GND | – | netlist |
| 33 | /RD | – directly; reaches ROM pin 20 through a diode (D2) | netlist; the diode connection is INFERRED |
| 34 | +5 V | 28 | **M** |
| 35 | "/RST" in the netlist | – directly; reaches pin 20 through a diode (D1) | name unreliable; role on the Genio UNKNOWN |
| 36 | X36 | – | UNKNOWN function |

Notes:

* There are address lines A0 to A16 only (no A17 or higher) at the connector. This is why the cartridge ROM was
  matched against a 1 Mbit (128 KiB) part.
* On the Genio, the CPU window that holds the cartridge (0x8000 to 0xBFFF) is 16 KiB, so only A0 to A13 are CPU
  address lines there; A14, A15 and A16 come from a bank register (INFERRED; the emulator's source models it that way).
* The ROM chip enable (pin 20) is produced by the R1 + D1 + D2 network. Which contacts feed the diode anodes was not
  measured (UNKNOWN); the original ROM works on that net and the modification leaves it untouched.
* The numbering of the cartridge contacts follows the netlist and the author's measurements, not a VTech document.
