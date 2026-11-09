# Hardware evidence

These are results recorded by the author on a single Spanish VTech Genio 2000 with the modified cartridge, on 2026-11-08.
The raw serial captures are **not** published because they contain VTech firmware. What is published here is derived:
CRC-32 values, hashes and counts. They were reproduced from the raw captures with the tools in this repository (see
[TESTING.md](TESTING.md)).

## Sessions

| Session id | Program (build id) | Records or frames | Result |
|---|---|---|---|
| 010C | `bank_diag` (0x0001) | 38 records, stages A to D, END | 8 distinct stable contents for selectors 0 to 7; selectors 8 to 15 identical to 0 to 7; descending sweep equals ascending; window 0 unchanged; selector 0 restores the start-up content. |
| 0113 | `bank_diag16` (0x0002) | 66 records, stages A to D, END | Selectors 0x10 to 0x1F identical to banks 0 to 7 (`selector & 7`); ascending and descending reads agree; 32 restores to selector 0 all equal to the start-up content. |
| 0301 | `bank_dump` (0x0101) | START, 8 × (BANK_BEGIN, 128 DATA, BANK_END), END | 0 rejected frames, 0 line errors, all banks complete, all bank CRC-32 equal to read 2, restore OK. |
| 0097 | `bank_dump` (0x0101) | same | same; identical to 0301 in every bank. |

Both diagnostic sessions reported the same stack pointer value (0xDFEE, 0xDEE1 in the dump sessions), inside the RAM range
that the programs require.

## Bank contents, as measured through port 0x01

Reference values of the author's unit (**not** a statement about other units or firmware revisions). CRC-32 is the IEEE/zlib CRC
of the 16384 bytes of the window `0x4000-0x7FFF` with that selector.

| Selector | CRC-32 | SHA-256 | SHA-1 |
|---|---|---|---|
| 0 | D49DECF0 | 456c1f7557e17609ef54aee26f0061127ebe49b98d570cb1e455edfde967e5aa | df5404267bf4feba9c7fc80e012000b592cf8b49 |
| 1 | 67EBAB51 | 7f091c9dc51ec8991b6e4144fca911f3f54eebef6ee1eaa35ac4ab5b5b37871f | d3f33f4e94df710d3b550ed7bd5e3e9646270362 |
| 2 | 35C99AC6 | d68f13a1f981620b3048961f6a7b83e30fd9db4e7fd79605587bea44353e349a | 44955ed57ae74f1a98035aace5d66abe0b4e5044 |
| 3 | 021A7E5B | 61fb0fef0e23b60a0ac9b6201ce901437218d26807b55136cc91dbf444adf65c | a465ed714edba86651a5d4f550ef23ac7db8516a |
| 4 | 8A1F0214 | 9d7ada9f39666364ea5e3e9220511248fb0c674a9df90fb3b99de108d58748b6 | b8498515bae14b79e2829f4b40f412da20929db7 |
| 5 | 63924486 | 21b61ed4065e903b8af6706d12174b05d8e2a318b9e4c223ce2c06f7d1170b60 | 662009b6a4e583e974d9b419f05d0f5821337b5e |
| 6 | 8F71AB6E | be66c02627d46fbe274b12bef18971677d32ff38781afef973e65467b5764bf0 | 8baa597946675b32acdfc6f5baaca4cff1bc730b |
| 7 | F28A4E52 | b0fa418cb8b16b5f25515b86a52e94fff669a9e3862b87609afacb2dd6560079 | 66a91fdceada950276a95058275246c361fbc3df |

Concatenation of banks 0 to 7 in selector order: 131072 bytes, SHA-256
`f66f4d51d7152a8264ff9d99cbeb38dbbb5cc2d6f087e3fffb4e067f42e5ea48`, SHA-1 `76e41bc3b19f3f0c0ae4605257ba4ee9d812659f`, CRC-32 `7A9D7B8A`.

## Evidence that is missing

* The SHA-256 of the cartridge images used in each session was not recorded at the time (see [BUILD.md](BUILD.md) for the
  indirect evidence).
* No photograph of the cartridge during the sessions other than the copper-side photograph of the modification.
* The internal mask ROM's capacity is not measured. The author reports that the internal ROM is a 28-pin VTech-marked part
  (`LH531H7H`, `27-5575-00`, date code 1995). That comes from the author's separate photographs, which are not included in this
  repository, and its pinout and capacity are not documented anywhere that was found. Do not treat it as established.
