---
description: Regenerate the pin header and export <name>.fw-pinmap.json for the circuit agent.
allowed-tools:
  - terminal
---

Run `firmware pins <contract>` then `firmware pinmap <contract> --out <dir>`
through the launcher, and tell the user to run
`python -m circuit firmware-check --pinmap <dir>/<name>.fw-pinmap.json` on the
circuit side.
