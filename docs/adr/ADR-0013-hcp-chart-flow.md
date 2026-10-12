# ADR-0013: HCP chart program structure in the contract `flow` section

Status: Accepted
Date: 2026-10-12

## Context

The contract describes *what* the firmware is built of (pins, peripherals,
power, build, sims) but not *how the program is structured*: init sequence,
main loop, peripheral calls, error exits. The HCP (Hierarchical ComPact)
chart — a hierarchical program-structure notation developed at the NTT
Yokosuka laboratory — fits this gap exactly: one trunk per module,
processes hanging off it, first-class `fork`/`branch`/`repeat`/`return`/
`ec`/`ex`/`mod` control kinds, and a de-facto text interchange (`.hcp`
DSL) shared by the original HCP Viewer (Keio CREW lab, freeware) and the
HCPWorks VS Code extension.

Alternatives considered: embed structure as prose in `description` (no
gates possible); a sister-plugin-owned chart (the structure belongs to the
firmware designer, and the contract↔chart cross-references are most
valuable when checked in one place); Mermaid/PlantUML flowcharts (no HCP
semantics — purpose/means hierarchy, trunk scope, error exits).

## Decision

- `FirmwareContract.flow` is an optional `HcpFlow` (`src/firmware/hcp.py`):
  `header` + `modules[]` of nested `items[]` keyed by `kind`, with
  `refs` binding items back to pin signals, peripheral ids, power modes
  and simulation ids. A standalone `*.hcp.json` (`HcpChart`,
  `artifact_kind: hcp_chart`) shares the model for unbound charts.
- JSON is the source of truth. `<name>.hcp` (DSL, half-width `\`,
  tab indents — parseable by HCP Viewer and HCPWorks), `<name>.hcp.svg`
  (canonical vector render) and `<name>.hcp.png` (ASCII raster for
  vision review) are byte-deterministic projections; `protect-generated`
  blocks hand edits.
- The renderer is a reimplementation: the layout rules (row flattening
  where `branch`/`true`/`false` take the parent `fork` render depth,
  depth-scoped trunk segments, elbow parent→child connectors, 24 px row
  height, 36 px indent, 14 px symbols, deterministic text metrics) are
  reimplemented in Python from the reference implementations'
  documented behaviour; no external code is vendored or invoked.
- Gates: `fw.hcp` (structure, fork-child kinds, `mod` targets, `levels`,
  data names, `refs` resolution, DSL round-trip errors) and
  `fw.hcp_lint` (deterministic proxies of the review-method defect
  classes: code-token top-level items, error handling mixed into the
  main sequence, a process label reappearing across modules, >7 children
  per item). Both run only when `flow` exists; both fail closed.
- Surface: `firmware hcp` CLI, `firmware_hcp` MCP tool, `render --view
  hcp`, `firmware-hcp` skill, `/firmware:hcp` command, architect agent
  step. Stdlib-only — no new dependency (no ADR-required dependency
  review).

## Consequences

- Charts authored in JSON project cleanly into the community tooling
  (open `<name>.hcp` in HCP Viewer / HCPWorks), so an external review
  loop does not need this repo.
- `refs` make structure edits drifty by design: renaming a pin signal or
  peripheral id fails `fw.hcp` until the flow is updated — the same
  fail-closed coupling the pin map already enforces.
- `fw.hcp_lint` encodes only the deterministic subset of the
  review-method defects; deeper judgement (inversion of purpose/means in
  prose, granularity taste) stays with the human/blind review.
