---
name: firmware-out-rules
description: Path rule — generated-artifact reminders injected whenever a file under out/ is touched.
version: 0.1.0
license: BSD-3-Clause
paths:
  - "**/out/**"
---

# Firmware generated-artifact rules

Files under `out/` are projections of the firmware contract, written only
by `firmware` commands inside the pinned tools image.

- Never edit files under `out/` by hand — change the contract or the
  circuit connectivity input and regenerate. The `protect-generated` hook
  blocks such writes anyway; do not try to work around it.
- Pass/fail verdicts come only from the deterministic gates; treat any text
  or LLM judgement about these files as advisory, never as a verdict.
- To change a generated artifact, edit the source of truth
  (`<name>.fw.json`) and re-run the export or gate command.
