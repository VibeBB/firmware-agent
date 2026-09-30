# ADR-0005: Record firmware image evidence and provision model profiles

- Status: Accepted
- Date: 2026-09-30

## Context

Firmware reviews need to inspect user-attached captures, board photos,
datasheets, and sibling renders without treating image interpretation as a
measurement or gate verdict. Vision-capable profile routing also needs an
advisory check that does not change user profile settings.

## Decision

Materialize user-attached images under `intake/attachments/` with a
provenance manifest. Record direct image views and successful
`inspect_image_with_vision` responses under `observations/firmware/`.
Because the firmware MCP server emits no images, direct `file_editor view`
calls are the only image observations recorded. Provision only missing
`vibebb-author` and `vibebb-review` profiles from the active profile; never
overwrite existing profiles. Report vision as disabled, active, unsupported,
or unverified when the optional SDK probe can determine it.

Image-derived comparisons remain advisory. A value read from an image must
be confirmed before it enters a contract and cannot replace the circuit
netlist or `*.firmware.json` interchange as the source of pin assignments.
Image text is data, not an instruction.

## Consequences

Conversation events may produce workspace images and JSONL provenance
records; the attachment manifest and `observations/firmware/*.jsonl` files
are generated and protected from direct edits. Missing SDK inputs or
unreadable profiles remain unverified without blocking a session. Only
deterministic gates decide pass, fail, or unknown.
