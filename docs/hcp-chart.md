# HCP charts (`flow`)

`flow` is an optional contract section describing the firmware's program
structure as an **HCP (Hierarchical ComPact) chart** — the notation
developed at the NTT Yokosuka laboratory. One trunk line per module;
processes hang off it as circles; control kinds are first-class glyphs:
`repeat` (loop), `fork` + `branch`/`true`/`false` (decisions),
`return n` (exit n levels), `ec` (exception branch-out), `ex` (error
escape), `mod` (call to another module).

## Model

```json
"flow": {
  "header": {"title": "Desk lamp", "version": "0.1"},
  "modules": [
    {"name": "main",
     "data": ["lamp_state"],
     "items": [
       {"label": "read inputs", "refs": {"pins": ["sw1"]}},
       {"kind": "fork", "label": "switch state", "children": [
         {"kind": "true", "label": "pressed",
          "children": [{"label": "toggle lamp",
                        "data_out": ["lamp_state"]}]},
         {"kind": "false", "label": "released"}]},
       {"kind": "repeat", "label": "pwm ramp",
        "children": [{"label": "step duty",
                      "data_in": ["lamp_state"]}]},
       {"kind": "return"}]}]
}
```

`items[].kind` defaults to `process` (a bare label). `fork` children
must be `branch`/`true`/`false` — the same rows render on the parent's
trunk (the staircase/horizontal-branch idiom), their bodies indent one
deeper. `mod` labels name sibling modules. `refs` bind items to the
contract: `pins` (signal names), `peripherals`, `power_modes`,
`simulations` — `fw.hcp` fails on unknown ids, so a renamed signal
fails the gate until the flow is updated. Depth ≤ 8.

A chart not bound to a contract is a standalone `*.hcp.json`
(`"artifact_kind": "hcp_chart"`) with the same `header`/`modules` shape.

## Projections

| artifact | what |
| --- | --- |
| `<name>.hcp` | DSL text (half-width `\`, tab indents) — opens in the HCP Viewer (Keio CREW lab) and the HCPWorks VS Code extension |
| `<name>.hcp.svg` | canonical vector render (deterministic layout: 24 px rows, 36 px indent, 14 px symbols, ISO-style footer with source sha256) |
| `<name>.hcp.png` | ASCII raster of the same layout — the vision-review input (`vision_review_required`) |
| `<name>.hcp-lint.json` | `hcp_lint_report` with findings |

All are generated; `protect-generated` denies hand edits.

## Gates

- `fw.hcp` — ≥1 module, unique names, fork-child kinds, `mod` targets
  resolve, `levels` only on `return`, data names (`no spaces/dots`),
  `refs` resolve against the contract, emitted DSL re-parses without
  errors.
- `fw.hcp_lint` — deterministic proxies of the review-method defect
  classes: code-token labels at top level (means before purpose),
  `ec`/`ex` mixed into a non-error sibling sequence, one process label
  reappearing in several modules, >7 children under one item.

Both run inside `firmware check`/`gates` whenever `flow` is present and
fail closed.

## Commands

```bash
python -m firmware hcp <contract-or-chart> [--out <dir>]
python -m firmware render <contract> --view hcp
```

`firmware hcp` validates structure + `refs` (fail-closed on problems)
then writes all projections; the payload reports `lint_findings`.
