# ADR-0003: QEMU simulation gates and advisory GDB

- Status: accepted
- Date: 2026-09-28

## Context

Build success and static analysis do not show that firmware behaves.
Bench evidence is the final authority, but a headless emulator catches
logic regressions on every change.

## Decision

- `simulations[]` in the contract declare a runner, machine, fidelity,
  image, ordered `expect` lines, `forbid` lines and a timeout. Each
  becomes gate `fw.sim.<id>`.
- `qemu-arm` (upstream `qemu-system-arm`) runs `core`-fidelity images on
  Cortex-M machines such as `mps2-an385` and requires a semihosting exit
  code. MCUs without a QEMU machine (RP2040) build their MCU-independent
  logic for such a machine from the same sources.
- `qemu-esp` (Espressif's `qemu-system-xtensa` fork) runs `mcu`-fidelity
  ESP32/ESP32-S3 flash images (ROM, bootloader, app) with `-nographic`
  so UART0 reaches stdout. It has no exit code; the run ends when every
  expectation is seen, or fails at the timeout.
- `firmware debug` starts QEMU halted with a gdbstub and drives GDB in
  batch mode (hardware breakpoints on Espressif targets). The record is
  written as `debug-<id>.advisory.json` with `authority: advisory` and
  never changes a verdict.

## Consequences

- Core-fidelity simulation does not exercise real peripherals; the report
  states the fidelity so reviewers weigh the evidence accordingly.
- Espressif QEMU is GPL-2.0-or-later and is run only as a subprocess
  (ADR-0004).
