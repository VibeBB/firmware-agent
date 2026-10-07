---
name: firmware-contract-rules
description: Path rule — schema and provenance reminders injected whenever a *.fw.json or *.firmware.json file is touched.
version: 0.1.0
license: BSD-3-Clause
paths:
  - "**/*.fw.json"
  - "**/*.firmware.json"
---

# Firmware contract file rules

- `<name>.fw.json` follows the `firmware_contract` schema (schema_version
  1) in `src/firmware/contract.py` (in plugin-only installs, see
  `docs/contracts.md`). Keep `name` and pin `ref`s stable — gates, the
  generated `fw_pins.h`, and circuit connectivity address them.
- `<design>.firmware.json` is the `circuit_firmware_connectivity` input
  owned by the circuit plugin — never hand-edit it; request changes with
  `firmware_request` (`fw_request` v2) instead.
- Every pin carries `rationale`; strapping/JTAG pins must declare
  `acknowledge`. Claims read off rendered images are observations, never
  substitutes for gate verdicts.
- Generated projections (`fw_pins.h`, `*.fw-pinmap.json`,
  `*.fw-power.json`, `*.fw-production.json`, `*.pinmap.*`, `*.fw-report.*`,
  `sim-*.log`/`sim-*.png`, `debug-*.advisory.json`) are never hand-edited —
  change the contract and re-run the command.
