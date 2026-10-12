---
name: firmware-hcp
description: Authoring the contract `flow` section — the program structure as an HCP chart (modules, processes, forks/branches, loops, returns, error exits) with DSL/SVG/PNG projections and the fw.hcp + fw.hcp_lint gates.
version: 0.1.0
license: BSD-3-Clause
triggers:
  - HCP chart
  - HCPチャート
  - program structure
  - control flow
  - module flow
  - プログラム構造
  - 階層的コンパクト記述
---

# HCP chart (contract `flow`)

`flow` is an optional contract section describing the firmware's program
structure as an HCP (Hierarchical ComPact) chart — the notation developed
at the NTT Yokosuka lab, one trunk line per module with processes hanging
off it. JSON is the source of truth; `<name>.hcp` (HCP Viewer / HCPWorks
DSL), `<name>.hcp.svg` and `<name>.hcp.png` are generated projections.

```json
"flow": {
  "header": {"title": "Desk lamp", "version": "0.1"},
  "modules": [
    {"name": "main",
     "data": ["lamp_state"],
     "items": [
       {"label": "read inputs", "refs": {"pins": ["sw1"]}},
       {"kind": "fork", "label": "switch state", "children": [
         {"kind": "true", "label": "pressed", "children": [
           {"label": "toggle lamp", "data_out": ["lamp_state"]}]},
         {"kind": "false", "label": "released"}]},
       {"kind": "repeat", "label": "pwm ramp", "children": [
         {"label": "step duty", "data_in": ["lamp_state"]}]},
       {"kind": "return"}]},
    {"name": "idle_tick",
     "items": [{"label": "enter sleep prep"}]}
  ]
}
```

## Rules

- `kind` ∈ `process` (default, bare label), `repeat`, `fork`, `branch`,
  `true`, `false`, `return` (`levels` = `\return n`), `ec`, `ex`, `mod`
  (call to a module name).
- `fork` children must be `branch`/`true`/`false`; those kinds appear
  nowhere else.
- A `mod` label must name a module in the same chart.
- Data names (module `data`, `data_in`, `data_out`) contain no spaces or
  dots.
- `refs` bind an item back to the contract: `pins` (signal names),
  `peripherals`, `power_modes`, `simulations`. `fw.hcp` fails on any
  unknown reference — keep them in sync with pin/peripheral/sim edits.
- Depth ≤ 8; every module has ≥1 item; top-level items state the purpose
  (`fw.hcp_lint` flags code-token labels, error handling mixed into the
  main sequence, a process label reappearing across modules, >7 children
  under one item — the Keio review-method defect classes).

## Commands

```bash
python -m firmware hcp <contract-or-chart> [--out <dir>]
python -m firmware render <contract> --view hcp
```

`firmware hcp` validates structure + refs (fail-closed), then writes all
projections and the lint report. `firmware check`/`gates` run `fw.hcp`
and `fw.hcp_lint` whenever `flow` is present. The `.hcp.png` lands in
`vision_review_required` like every render — inspect it and record a
`firmware_record_vision_review` (advisory, ≥400 chars, ≥3 sentences).

For a chart that is not tied to a firmware contract, author a standalone
`*.hcp.json` (`"artifact_kind": "hcp_chart"` with `name`, `header`,
`modules`) and point `firmware hcp` at it.
