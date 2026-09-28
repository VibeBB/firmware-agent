---
description: Design or revise <name>.fw.json (MCU, pin map, peripherals, power modes) against the circuit export.
allowed-tools:
  - terminal
  - file_editor
---

Delegate to the `firmware-architect` agent with the product brief and the circuit
`<design>.firmware.json`, then run `firmware check <contract>` and report every
failing check.
