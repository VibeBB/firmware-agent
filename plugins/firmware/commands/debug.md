---
description: Attach GDB to a QEMU simulation and record breakpoints, backtraces, registers and expressions (advisory).
allowed-tools:
  - terminal
---

Run `python3 <firmware plugin root>/scripts/firmware_launcher.py debug <contract> --id <sim> --break <location> --print <expression>`
and summarize the stops. The record is advisory; it never changes a gate verdict.
