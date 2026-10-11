# Records and vision

firmware-agent follows the VibeBB Record Protocol v2 (VRP); the generic
rules live in [records-protocol.md](records-protocol.md). This page lists
the firmware duties; `plugins/firmware/hooks/records-policy.json` defines
the artifact globs and `require_records.py` enforces them at Stop.

## Decisions per stage

Record `firmware_record_decision` (`python -m firmware record decision`)
for every non-trivial choice without being asked:

- MCU/profile selection
- each pin assignment (pad, function, net)
- peripheral and power-mode choices
- the simulation plan

Each decision carries first principles, ≥2 options with pros/cons, the
chosen option, a 200+ char rationale, hashed evidence paths or
references, assumptions, unknowns, risks and a revisit trigger. Its
`event_id` is what `fw_request.decision_refs` and SLP v2
`decision_refs` cite.

## Impressions

Record `firmware_record_impression` when a stage ends: ≥400 characters
and ≥3 distinct sentences — what you noticed, what works, what worries
you, how a maker reads the result, what to do next. Bound to the stage's
output paths (hashed).

## Vision points

Every image is reviewed: `*.pinmap.png`, `*.fw-report.png`, `sim-*.png`
from the render pipeline, plus user photos/datasheets and any
`inspect_image_with_vision` answer. Each review is a
`firmware_record_vision_review` bound to `image_path` or the vision
event's `source_event_id` (logged by the `record-vision-tool-event`
post-tool hook).

The `record-image-observation` hook logs every image an observed tool
touched (`file_editor`, `firmware_render`, `firmware_gates`,
`firmware_check`, `firmware_pinmap_export`, `firmware_sim`), and
image-producing payloads mark `vision_review_required` + `vision_hint`
so nothing rendered escapes review.

## VRP v2 logs

`observations/firmware/` holds `decisions.jsonl`, `impressions.jsonl`,
`vision-reviews.jsonl`, `reconciles.jsonl`, `insights.jsonl`, `reads.jsonl`
and `song-receipts.jsonl`. Every line carries `schema_version` 2, `sequence`,
`prev_event_id`, `writer` and `event_id` (the SHA-256 of the canonical
record). The writer verifies the chain before appending and refuses a log
that was edited, truncated or reordered; readers report such a log under
`integrity_problems` and never resolve references into it. A log written
entirely by VRP v1 is renamed to `<name>.v1.jsonl` on the first v2 write.

Impressions carry facets (`observed`, `works`, `concerns`, maker/user
`feelings`, `next_actions`), two or more claims quoting exact tokens from the
bound artifacts, and a confidence; a near copy of an earlier impression, or
a concern a sister already disputed, is refused. Taking in a sister artifact
needs a `firmware_record_read` receipt and an `upstream` entry.

## Blind review

`*.pinmap.png` and `*.fw-report.png` are dual-review images
(`dual_review_globs` in `records-policy.json`). After the primary review,
`firmware-blind-review` reviews the same image without seeing it
(`reviewer: "blind"`), and the caller records `firmware_record_reconcile`
over `[primary, blind]`. A split goes to one tiebreak round
(`[primary, blind, tiebreak]`); a split after the tiebreak stays `unknown`
and never becomes pass.

## Insights, songs, digest

`firmware_record_insight` moves an insight through
tried/adopted/rejected/deferred/superseded. firmware only receives bard
songs: `firmware_record_song_receipt` records one receipt per
`liaison/<id>.bard-song.json` (sha256-pinned, never a gate input, never a
request for another song; the song file is protected from edits).
`firmware_records_digest` and `firmware_records_search` read every plugin's
impressions in the workspace.

## Inline images

MCP image-producing tools attach PNGs inline (max 4, each ≤ 4 MiB;
`images_skipped` lists overflow), so a reviewer sees the render without
a second tool call.

## Advisory only

Vision reviews and impressions never override a deterministic gate
verdict; neither does the GDB debug advisory. Results need not be
identical between runs — the reasoning must be recorded every run.
`firmware_records_status` reports what is still owed.
