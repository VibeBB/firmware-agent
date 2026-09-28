---
description: Run every firmware gate (build, netlist match, flash/RAM budget, static analysis, QEMU simulation).
allowed-tools:
  - terminal
---

Run `python3 <firmware plugin root>/scripts/firmware_launcher.py gates <contract>`
and report the verdict and each failing check from `<name>.fw-report.md`.
