---
name: firmware-workflow
description: End-to-end firmware workflow — contract first, circuit-matched pin map, generated pin header, build, flash/RAM budget, cppcheck, QEMU simulation, advisory GDB — with deterministic fw.* gates.
version: 0.1.0
license: BSD-3-Clause
triggers:
  - firmware
  - embedded
  - mcu
  - ファームウェア
  - 組み込み
---

# Firmware workflow

The firmware contract `<name>.fw.json` is the single source of truth. The
pin header, pin map export, reports and simulation transcripts are
projections of it and are write-protected by the `protect-generated` hook.

1. **Circuit export** — the circuit agent writes `<design>.firmware.json`
   (`python -m circuit firmware-export --brief ... [--netlist ...]`).
   Point `circuit.connectivity` at it.
2. **Contract** — MCU profile + ref, pins, peripherals, power modes, build,
   analysis, simulations (`firmware-contract` skill).
3. **Static gates** — `firmware check <contract>` (MCP `firmware_check`).
4. **Pin header** — `firmware pins <contract>` writes `build.pins_header`.
5. **Implementation** — sources include the header; hardware access stays
   behind a HAL so logic builds for QEMU too.
6. **Full gates** — `firmware gates <contract>` (MCP `firmware_gates`)
   writes `fw-reports/<name>.fw-report.{json,md}` plus the pin map export.
7. **Circuit confirmation** — hand `<name>.fw-pinmap.json` to
   `circuit firmware-check`. Both sides must pass.
8. **Debug** — `firmware debug` (advisory) when a simulation fails.

## Gates (all fail closed)

| id | passes when |
| --- | --- |
| `fw.contract` | contract validates and the MCU profile resolves |
| `fw.pin_functions` | every pad exists, is not reserved, routes its function/peripheral instance; strapping/JTAG pads acknowledged; buses have their required roles |
| `fw.netlist_match` | every pad sits on the declared circuit net of the declared MCU, voltages fit, no active circuit MCU pad is left unassigned, and the supply net reaches the MCU |
| `fw.power_modes` | a run mode exists, duties sum to 1, every sleep mode has a wake source (`gpio_in` pin or `timer`; deep-sleep pins must be wake-capable), powered peripherals exist, average current within budget |
| `fw.pins_header` | the generated header matches the contract byte for byte |
| `fw.build` | the build backend exits 0 and the ELF exists |
| `fw.memory_budget` | flash and RAM usage from the ELF sections are within `build.budget` of the MCU capacity |
| `fw.static_analysis` | cppcheck reports no finding at a `fail_on` severity outside justified suppressions |
| `fw.sim.<id>` | QEMU prints every `expect` line in order, no `forbid` line, and (ARM) exits with `exit_code` before the timeout |

Missing tools, missing files and unparseable output are failures, never
skips. Run `firmware doctor` first when a tool is missing.
