# Improvement notes

Status of adopted ideas and known gaps.

## Implemented

- VRP v1 records (decisions, impressions, vision reviews) + Stop-hook
  enforcement via `require_records.py` and `records-policy.json`.
- SLP v2 liaison: `firmware_ux_inbox`/`firmware_ux_respond`,
  `liaison/*.ux-*.json`, strict request/response models, stale/blocked
  classification, malformed reporting.
- Stdlib PNG renders: `*.pinmap.png` (DIP layout), `*.fw-report.png`,
  `sim-*.png` (QEMU transcript timeline), inline `ImageContent` in MCP
  results, `vision_review_required`/`vision_hint` payloads.
- `GateReport.metrics` (average uA + budget, flash/RAM usage vs budget).
- `fw_request` v2: sha256-hashed workspace-relative inputs, decision
  refs, `prodeng`/`sim`/`fpga`/`dashboard` targets (dropped
  `production`).
- Launcher fail-closed: Docker-only, no host-interpreter fallback.
- `sibling` → `sister` rename across the repo (CHANGELOG history and
  shared byte-equal files excepted).
- README + docs rebuild from the code.

## Open

- Only two MCU profiles (`esp32s3`, `rp2040`) — add STM32/nRF families.
- Vision review is agent-driven; there is no automated vision gate, by
  design (vision is advisory).
- The UX job-id check on high-risk SLP requests is a local heuristic
  until UX-creator's contract is shared.
- Renders use a 5×7 bitmap font — no anti-aliasing, ASCII only.
- The QEMU timeline plots by transcript line index, not wall-clock
  time (transcripts carry no timestamps).
- The debug advisory carries no vision/impression field, so the VRP
  free-text validation does not apply there.
- SDK `task` delegation from the UX producer is on UX-creator's side.
