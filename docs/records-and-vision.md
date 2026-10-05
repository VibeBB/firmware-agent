# Records and vision

firmware-agent follows the VibeBB Record Protocol v1 (VRP); the generic
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

## Inline images

MCP image-producing tools attach PNGs inline (max 4, each ≤ 4 MiB;
`images_skipped` lists overflow), so a reviewer sees the render without
a second tool call.

## Advisory only

Vision reviews and impressions never override a deterministic gate
verdict; neither does the GDB debug advisory. Results need not be
identical between runs — the reasoning must be recorded every run.
`firmware_records_status` reports what is still owed.
