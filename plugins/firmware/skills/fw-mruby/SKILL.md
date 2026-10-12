---
name: fw-mruby
description: Author and ship mruby/c UX logic — .rb sources compiled to bytecode by the pinned mrbc, embedded in the product image, and verified through Emscripten/node simulation legs. Use when a contract declares `mrubyc`, when consuming a ux-creator `*.mruby-manifest.json`, or when choosing the Zephyr/NCS toolchain pins.
triggers: [mruby, mrubyc, ruby, ux-manifest]
---

# fw-mruby — mruby/c UX logic in product firmware

The `mrubyc` contract block embeds the mruby/c VM and compiled Ruby
bytecode into the firmware image. UX-creator authors the `.rb` files and
publishes a `*.mruby-manifest.json`; firmware pins that manifest by
sha256 and gates the declared VM feature flags.

## Contract shape

```jsonc
"mrubyc": {
  "ref": "2dec4802b09be1fc12f388d3c9267ffd9dc6c404", // pinned mrubyc commit (see REF)
  "hal": "zephyr",            // avr|emscripten|esp32|pic24|posix|psoc5lp|rp2040|stm32|zephyr
  "memory_size": 40960,       // static mrbc_init_alloc pool; gate caps at 80% RAM
  "tick_unit_ms": 10,
  "no_timer": false,
  "use_float": 2,             // 0=off 1=single 2=double
  "use_math": false,
  "use_string": true,
  "use_utf8": false,
  "max_vm_count": 2,
  "sources": [
    {"file": "ux/app.rb", "bytecode": "fw/generated/ux_app_bytecode.c", "symbol": "ux_app"}
  ],
  "ux_manifest": {"manifest": "ux/mruby-ux.mruby-manifest.json", "sha256": "<64-hex>"},
  "generated_dir": "fw/generated",
  "config_header": "fw/include/fw_mruby.h"
}
```

Rules the gate (`fw.mrubyc`) enforces:

- `ref` must equal the toolchain pin in `/opt/mrubyc/REF` (release4.0.0
  lacks the AVR/ESP32/RP2040 HALs, so a master commit is pinned).
- `hal` must fit the MCU profile and have a compatible build leg:
  `zephyr`→`west`, `esp32`→`platformio`, `rp2040`→`cmake`,
  `avr`/`pic24`/`psoc5lp`/`emscripten`→`make`, `posix`/`stm32`→`make`/`cmake`/`west`.
- `emscripten` requires a `runner: node` simulation leg — the same `.rb`
  files run under the Emscripten HAL so UX logic is exercised in CI.
- `ux_manifest` sha256 must match the file; its `requires` (float, math,
  string, utf8, tick) must be a subset of the configured VM flags and
  every listed file must appear in `sources` with a matching sha256.
- Generated files are byte-compared against regeneration — a hand edit
  or stale artifact fails. Regenerate with `firmware mrubyc <contract>`.
- Static source scan flags `Float`/`Math.`/`String`/sleep-tick usage the
  configured flags cannot run.

## Toolchain pins (Docker image)

| piece | pin | why |
| --- | --- | --- |
| mruby | 4.0.0 | builds `mrbc` (RITE0400 bytecode) |
| mruby/c | master `2dec4802` | AVR/ESP32/RP2040 HALs + `MRBC_USE_FLOAT=0`/`MRBC_USE_STRING=0` postdate release4.0.0 |
| Zephyr (non-Nordic) | Canonical 26.04 LTS (`zephyr` fork @ `2e4ba3e7`, `zephyr-manifest@26.04.0`) | Canonical-maintained fork of upstream 4.4; moves to the first upstream 4.x LTS (Zephyr 4.6, ~Apr 2027) once it ships |
| nRF Connect SDK | v3.4.1 (LTS) | all Nordic targets build through NCS, never upstream Zephyr |
| Pico SDK | 2.2.0 | `hal rp2040` cmake legs |
| emsdk | 6.0.10 | shared digest pin with the dashboard tools image |

Nordic: `build.sdk = "nrf-connect"`, `build.board` like
`nrf52840dk/nrf52840`, `nrf54l15dk/nrf54l15`, `nrf9151dk/nrf9151`,
`nrf54lm20dk/nrf54lm20b`. Non-Nordic Zephyr: `build.sdk = "zephyr"`
with boards such as `nucleo_f411re`, `rpi_pico`, `mimxrt1050_evk`,
`esp32c3_devkitm`, `hifive1`, `m2gl025_miv`, `niosv_g`,
`adp_xc7k_ae350`, `native_sim`. RISC-V/other non-ARM boards add
`toolchain: "cross-compile"` + `cross_prefix` (e.g.
`riscv64-unknown-elf-`). The `sdk: "zephyr"` tree is Canonical's Zephyr
26.04 LTS (ubuntu.com/zephyr/docs/26.04/): the Launchpad fork pinned by
`zephyr-manifest@26.04.0`, whose module SHAs match upstream v4.4.2.
Canonical's Workshop environment (snap + LXD) is not usable inside
Docker; only the source set is consumed.

Canonical's supported-platform set (SoC-level support, HIL-validated on
anchor kits — ubuntu.com/zephyr/docs/26.04/reference/supported-boards):
`nrf52840dk/nrf52840`, `nucleo_h753zi`, `frdm_rw612`, `ek_ra8m1`,
`esp32c3_devkitm`, `esp32s3_devkitc`. All six have bundled profiles
(`nrf52840`, `stm32h753zi`, `frdm_rw612`, `ek_ra8m1`, `esp32c3`,
`esp32s3`); the set is reviewed each April and October, so re-check
when the distribution publishes a new cohort. Every other Zephyr 4.4
target is community-level and still usable through `sdk: "zephyr"`.

## HALs that need an external toolchain

The upstream mruby/c tree ships `hal/` for every entry below, and the
gate accepts them all, but three legs require proprietary toolchains
the image does not bundle — declare them only when the product
environment supplies the toolchain:

| `hal` | build leg | external toolchain |
| --- | --- | --- |
| `pic24` | `make` | Microchip XC16 (license-restricted) |
| `psoc5lp` | `make` | Infineon PSoC Creator toolchain |
| `stm32` | `make`/`cmake`/`west` | bare-metal legs need a user-supplied ST HAL/Cube tree; prefer `hal: "zephyr"` instead |

Xilinx MicroBlaze is not a Zephyr 4.4 board/SoC; Xilinx coverage runs
through `kv260_r5` (Cortex-R5) or the RISC-V soft-core profiles
(`neorv32`, `adp_xc7k_ae350`, `hifive1`, `longan_nano`). Re-evaluate
MicroBlaze support once it lands in an upstream Zephyr LTS release —
the pin policy moves to each new LTS, so support arrives automatically
when the LTS baseline includes it.

## M5Stack coverage

Every ESP32-based M5Stack product maps onto a bundled profile through
its silicon:

| M5Stack series | example products | profile |
| --- | --- | --- |
| ESP32 | Core, Core2, StickC, StickC-Plus, Fire | `esp32` |
| ESP32-S3 | CoreS3, Atom S3/AtomS3R/Atom Echo, Stamp-S3, Cardputer, M5Dial, Paper S3, StickC-Plus2 | `esp32s3` |
| ESP32-C3 | Stamp-C3, Atom (C3 var.) | `esp32c3` |
| ESP32-C6 | NanoC6, Stamp-C6 | `esp32c6` |

Build them via the mrubyc `hal: "esp32"` leg (upstream mruby/c
`hal/esp32`, PlatformIO/ESP-IDF) or via Zephyr with `sdk: "zephyr"`
boards such as `esp32s3_devkitc`. M5-specific pin labels (Grove ports,
LCD/backlight GPIOs) belong in the circuit netlist and contract pads;
the profiles describe the silicon. CoreMP135 (STM32MP135) and Tab5
(ESP32-P4) are out of scope: one is a Linux MPU, the other is not in
Zephyr 4.4.

## ux-creator handshake

UX-creator emits `ux/<product>.mruby-manifest.json` listing every `.rb`
with its sha256 plus a `requires` block. Pin it in `ux_manifest`; a
re-authored manifest changes the hash and fails the gate until re-pinned.

## Verification

Targets without MCU emulation still verify the UX logic: the
`emscripten` HAL runs under `node`, and a `mps2/an385` Zephyr leg covers
cortex-m execution. Always keep at least one such leg.
