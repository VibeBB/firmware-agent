---
name: firmware-qemu
description: QEMU simulation gates (qemu-system-arm core fidelity, Espressif qemu-system-xtensa MCU fidelity for esp32/esp32s3) and advisory GDB debugging through the gdbstub.
version: 0.1.0
license: BSD-3-Clause
triggers:
  - qemu
  - simulation
  - gdb
  - debug
  - シミュレーション
  - デバッグ
---

# QEMU simulation and debugging

## Runners

| runner | binary | fidelity | image |
| --- | --- | --- | --- |
| `qemu-arm` | `qemu-system-arm` (upstream) | `core`: Cortex-M machine (e.g. `mps2-an385`) running the MCU-independent logic, semihosting exit code | ELF (`-kernel`) |
| `qemu-esp` | `qemu-system-xtensa` (Espressif fork) | `mcu`: `esp32` / `esp32s3` machine booting ROM, 2nd-stage bootloader and app | raw flash image (`-drive if=mtd`) |

RP2040 has no upstream QEMU machine (`sim_machine: null`), so its
simulations are `core` fidelity: build the state machines and driver
upper layers for `mps2-an385` from the same sources with a stub HAL that
prints to the UART. ESP32-S3 runs the real ESP-IDF image; PlatformIO
projects add a post-build script that merges bootloader, partition table
and app into a full-size `flash.bin` with `esptool.py merge_bin
--fill-flash-size`.

## Gate `fw.sim.<id>`

Passes only when every `expect` substring appears in order on UART output,
no `forbid` substring appears, and — for `qemu-arm` — QEMU exits with
`exit_code` before `timeout_s`. A missing binary, missing image, timeout,
or crash is a failure. Transcripts are written to
`fw-reports/sim-<id>.log`. Print a single line such as `SIM PASS` only
after the firmware's own self-test asserts passed.

## Advisory debugging

`firmware debug <contract> --id <sim> --break <location> --print <expr>`
starts QEMU halted with a gdbstub on a free localhost port, attaches
`gdb-multiarch` (ARM) or `xtensa-esp32s3-elf-gdb` (Espressif, hardware
breakpoints because code runs from flash), and records every stop's
backtrace, registers and printed expressions in
`fw-reports/debug-<id>.advisory.json`. Locations are function names,
`file:line`, or `*0xADDR`. The symbol file defaults to the simulation's
own build ELF, the image when it is an ELF, or `build.elf`.

The debug record never changes a gate verdict; use it to diagnose, then
fix and re-run `firmware gates`.
