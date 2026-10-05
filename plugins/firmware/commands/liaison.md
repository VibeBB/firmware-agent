---
description: Answer ux-creator SLP v2 requests via the liaison inbox/respond tools.
allowed-tools:
  - terminal
---

Run `firmware ux inbox [--workspace <dir>]` through the launcher to scan
`liaison/*.ux-request.json`. Every firmware-targeted request is classified
`new`, `stale` (an input changed vs the request or the stored
`input_hashes`), `blocked` (a `depends_on` peer has no response, or a cycle)
or `answered`.

Answer each open request with `firmware ux respond --json <file>` where the
file holds `request`, `status`, `reason`, `artifacts`, `gate_verdicts`,
`decision_refs`, `impression_refs`, `questions_for_user` and
`report_paths` — or call `firmware_ux_respond` with the same fields.
`report_paths` merge the checks of a `*.fw-report.json` into the response's
gate verdicts. Status `done` requires clean gate verdicts, at least one
artifact, and one decision + one impression ref from
`observations/firmware/*.jsonl`. `*.ux-response.json` is generated —
never write it by hand.
