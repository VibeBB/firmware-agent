---
name: firmware-sister-cooperation
description: How firmware exchanges JSON artifacts with sister plugins — circuit firmware export/check, fw-request change proposals, bard product cues, and the UX producer plan.
version: 0.1.0
license: BSD-3-Clause
triggers:
  - circuit
  - sister
  - fw-request
  - 姉妹連携
---

# Sister cooperation

Cooperation is JSON files in the shared workspace — never code imports.

| direction | artifact | producer | consumer |
| --- | --- | --- | --- |
| in | `<design>.firmware.json` (`circuit_firmware_connectivity`) | `circuit firmware-export` | `fw.netlist_match` |
| out | `<name>.fw-pinmap.json` (`firmware_pinmap`) | `firmware pinmap` / `firmware gates` | `circuit firmware-check` |
| out | `<design>.<id>.fw-request.json` (`fw_request`) | `firmware request` | the target sister |
| in | bard `cues.json` (`bard_cue_manifest`), pinned by `cues.sha256` | bard-agent cue mode (`render_cues.py`) | `firmware cues` → `fw_cues.h`; `fw.bard_cues` |
| in | fpga `<design>.fpga-regmap.json` (`fpga_regmap`), pinned by `fpga.sha256` | `fpga regmap` | `firmware fpga-regs` → `fw_fpga_regs.h`; `fw.fpga_regmap` |
| in | prodeng `factory-test-spec.json` (`prodeng_ftm_spec`), pinned by `ftm.sha256` | `prodeng project` | `firmware ftm` → `fw_ftm.h`; `fw.ftm` |
| out | `<name>.fw-production.json` (`firmware_production`) | `firmware production` / `firmware_production_export` after passing full gates | prodeng `import --from firmware-production`; `firmware.programming` |
| in/out | `<product>.production.json` workstream `firmware` | UX producer | firmware reports as evidence |
| in | `liaison/<id>.ux-request.json` (SLP v2) | ux-creator | `firmware ux inbox` / `firmware_ux_inbox` |
| out | `liaison/<id>.ux-response.json` (SLP v2) | `firmware ux respond` / `firmware_ux_respond` | ux-creator |

SLP v2: ux-creator drops hashed-input requests into `liaison/`; firmware
classifies each as `new`, `stale` (input hash drifted), `blocked`
(missing dependency response or a cycle) or `answered`, and answers via
`ux respond` — `done` needs clean gate verdicts, an artifact, and one
decision + one impression ref. `*.ux-response.json` is generated.

The circuit export carries `brief_sha256` (and `netlist_sha256` for
netlist exports) and the gate report records the export's own hash
(`circuit_sha256`), so a report can be traced to the exact circuit
revision. Re-export after every circuit change; `circuit firmware-check`
always re-derives the connectivity from the current brief/netlist, so a
pin map checked against a stale export fails there.

Change requests: `target` is one of `circuit`, `mech`, `wire`, `ux`,
`bard`, `doc`, `prodeng`, `sim`, `fpga`, `dashboard`; `risk: high` for
anything that changes the board (and then needs at least one decision
ref from `observations/firmware/decisions.jsonl`). The request carries
the contract hash and hashed inputs so the receiver can detect a stale
ask. Never edit a sister's input files.
