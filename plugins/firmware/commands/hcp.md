---
description: Validate the contract flow section (or a standalone *.hcp.json) and write the .hcp DSL, SVG/PNG renders and the lint report.
allowed-tools:
  - terminal
---

Run `firmware hcp <chart> [--out <dir>]` through the launcher. `<chart>`
is the `<name>.fw.json` contract (reads its `flow` section) or a
standalone `<name>.hcp.json` chart.

The command is deterministic and fail-closed: structural errors (bad
kinds, `branch`/`true`/`false` outside a `fork`, an unresolvable `mod`
target or `refs`) make the payload `fail` and nothing is written. On
`pass` the payload lists `written` (`<name>.hcp`, `.hcp.svg`, `.hcp.png`,
`.hcp-lint.json`) and `lint_findings`; the PNG also appears under
`vision_review_required` — inspect it with `inspect_image_with_vision`
and record `firmware_record_vision_review` (advisory, ≥400 chars, ≥3
sentences).

See the `firmware-hcp` skill for the model shape and notation rules.
