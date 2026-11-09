# Third-party components

| Component | Upstream | Version | What is vendored | License |
|---|---|---|---|---|
| VGLDK (VTech Genius LEADER Development Kit), by Bernhard "HotKey" Slawik | https://github.com/hotkeymuc/vgldk | commit `6fbd389ace4c7bf156cb2c3fafafb1acf4a2a857` | 7 unmodified files from `include/` (list below), the upstream `LICENSE` and `README.md` | GNU GPL v3 (`third_party/vgldk/LICENSE`); `vgldk.h` carries the notice "version 3 ... or (at your option) any later version" |

Vendored files (byte-identical to the upstream commit above):

```
include/vgldk.h
include/basictypes.h
include/driver/hd44780.h
include/arch/gl2000/cart_crt0.s
include/arch/gl2000/keyboard.h
include/arch/gl2000/sound.h
include/arch/gl2000/system.h
```

These are exactly the VGLDK files the three cartridge programs read when they are compiled (determined by tracing the compiler).
Everything else in VGLDK (other platforms, examples, drivers, tools) is not used and not included.
The upstream README is kept as `vgldk/README.upstream.md` for attribution.

To check that the copy is unmodified:

```bash
git clone https://github.com/hotkeymuc/vgldk /tmp/vgldk && git -C /tmp/vgldk checkout 6fbd389
for f in include/vgldk.h include/basictypes.h include/driver/hd44780.h include/arch/gl2000/cart_crt0.s \
         include/arch/gl2000/keyboard.h include/arch/gl2000/sound.h include/arch/gl2000/system.h LICENSE; do
  cmp /tmp/vgldk/$f third_party/vgldk/$f && echo "identical: $f"
done
```

Other tools (not vendored): SDCC (GPL), Python 3 and pyserial (receiver only), pytest (tests only). See `docs/LICENSE_AUDIT.md`.
