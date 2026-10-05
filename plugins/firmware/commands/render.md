---
description: Render pin map, gate report and sim timeline PNGs (advisory vision inputs).
allowed-tools:
  - terminal
---

Run `firmware render <contract> [--out <dir>] [--view pinmap|report|sim ...]`
through the launcher. The `report` view reruns the static gates; the `sim`
view re-evaluates existing `sim-*.log` transcripts and never runs QEMU.

Every PNG written is listed in the payload under `vision_review_required`.
Inspect each render with `inspect_image_with_vision` (or the inline image
returned by `firmware_render`) and record a `firmware_record_vision_review`
with a >=400-char, >=3-sentence impression judging accuracy against the
contract, ambiguity, design intent and usefulness to the maker. Vision is
advisory and never overrides a gate verdict.
