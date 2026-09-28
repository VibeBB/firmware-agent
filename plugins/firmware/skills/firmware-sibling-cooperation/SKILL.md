---
name: firmware-sibling-cooperation
description: How firmware exchanges JSON artifacts with sibling plugins — circuit firmware export/check, fw-request change proposals, bard product cues, and the UX producer plan.
version: 0.1.0
license: BSD-3-Clause
triggers:
  - circuit
  - sibling
  - fw-request
  - 姉妹連携
---

# Sibling cooperation

Cooperation is JSON files in the shared workspace — never code imports.

| direction | artifact | producer | consumer |
| --- | --- | --- | --- |
| in | `<design>.firmware.json` (`circuit_firmware_connectivity`) | `circuit firmware-export` | `fw.netlist_match` |
| out | `<name>.fw-pinmap.json` (`firmware_pinmap`) | `firmware pinmap` / `firmware gates` | `circuit firmware-check` |
| out | `<design>.<id>.fw-request.json` (`fw_request`) | `firmware request` | the target sibling |
| in | bard `cues.json` / MIDI | bard-agent product cue mode | firmware sound tables (buzzer PWM) |
| in/out | `<product>.production.json` workstream `firmware` | UX producer | firmware reports as evidence |

The circuit export carries `brief_sha256` (and `netlist_sha256` for
netlist exports) and the gate report records the export's own hash
(`circuit_sha256`), so a report can be traced to the exact circuit
revision. Re-export after every circuit change; `circuit firmware-check`
always re-derives the connectivity from the current brief/netlist, so a
pin map checked against a stale export fails there.

Change requests: `target` is one of `circuit`, `mech`, `wire`, `ux`,
`bard`, `doc`, `production`; `risk: high` for anything that changes the
board. The request carries the contract hash so the receiver can detect a
stale ask. Never edit a sibling's input files.
