# ADR-0009: Records, liaison and vision refactor

## Status

Accepted

## Context

The VibeBB family adopted a shared record protocol and a sister liaison
protocol while firmware's documentation drifted from the code and its
renders were missing: pin maps and reports were JSON/Markdown only, so an
agent could not "look" at a design. The launcher still had a
host-interpreter fallback that bypassed the pinned tools image.

## Decision

- Port the VibeBB Record Protocol v1: append-only
  `observations/firmware/{decisions,impressions,vision-reviews}.jsonl`,
  `records-policy.json`, byte-equal `require_records.py`/`_records.py`
  Stop enforcement, `firmware_record_*` MCP tools and `record` CLI.
- Implement SLP v2 as a strict local mirror (`liaison.py`,
  `liaison/*.ux-*.json`): inbox classification (new/stale/blocked/
  answered + malformed) and validated, atomically written responses.
- Add stdlib PNG renders (`render.py`): DIP pin map, gate report, QEMU
  transcript timeline, hand-authored 5×7 font; attach PNGs as inline
  `ImageContent` (max 4, ≤ 4 MiB each) and mark payloads with
  `vision_review_required`/`vision_hint`. Renders are advisory and never
  change a verdict.
- `GateReport.metrics`; `fw_request` v2 with sha256-hashed inputs and
  decision refs bound to `decisions.jsonl`.
- Make the launcher fail closed: Docker-only, no host-interpreter
  fallback.
- Rename sibling → sister across the plugin.
- Rebuild README and `docs/` from the code.

## Consequences

Every session leaves auditable decisions, impressions and vision
reviews; the Stop hook refuses unfinished books. Agents can inspect
renders inline and must record a vision review per image. Sister
requests and responses are hash-bound and refuse stale or unrecorded
work. All tool execution requires the pinned image.
