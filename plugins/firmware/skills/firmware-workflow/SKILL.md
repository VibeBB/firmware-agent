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
   writes `fw-reports/<name>.fw-report.{json,md,png}` plus the pin map
   export and `<name>.pinmap.png`.
7. **Render and look** — every written PNG (pin map, fw-report, sim
   timeline) is returned inline by the MCP tool and listed under
   `vision_review_required`: view it (inline or
   `inspect_image_with_vision`) and record a `firmware_record_vision_review`.
8. **Circuit confirmation** — hand `<name>.fw-pinmap.json` to
   `circuit firmware-check`. Both sides must pass.
9. **Debug** — `firmware debug` (advisory) when a simulation fails.

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

## Records you must leave (VibeBB Record Protocol — mandatory, unprompted)

Record these without being asked; the Stop hook refuses to finish a
session that still owes them (see `docs/records-protocol.md`).

- **Decision** (`firmware_record_decision`) for every non-trivial choice:
  the MCU/profile selection, each pin assignment, peripheral and
  power-mode choices, and the simulation plan. Record the question, the
  first principles / electrical laws / standards it rests on, at least
  two options with pros and cons, the chosen option, a rationale of
  200+ characters, evidence (artifact paths are hashed; cite datasheets
  or standards as references), assumptions, unknowns, residual risks
  and the observation that would reopen it. Reason from principles,
  not from habit.
- **Stage impression** (`firmware_record_impression`) when a stage ends,
  after its final regeneration: 400+ characters and 3+ sentences on what
  you noticed, what works, what worries you, how a maker or user would
  read the result, and what to do next. List the stage's output files or
  directories so the impression is bound to their sha256.
- **Vision review** (`firmware_record_vision_review`) every time you
  look at an image (a pin-map or board diagram, a serial/QEMU output
  plot, a photo, an `inspect_image_with_vision` answer): findings plus
  a long-form impression of 400+ characters judging accuracy, ambiguity,
  whether the design intent comes across and whether a firmware or
  hardware engineer could act on it — not only legibility. Bind it to
  `image_path` or to the vision event's `source_event_id`.

Vision and impressions are advisory: they never override a deterministic
gate verdict. Results do not have to be identical from run to run; the
reasoning must be recorded every run. `firmware_records_status` shows
what is still owed.
