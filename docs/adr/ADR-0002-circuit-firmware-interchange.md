# ADR-0002: Circuit/firmware interchange through workspace artifacts

- Status: accepted
- Date: 2026-09-28

## Context

The pin map is owned jointly: the circuit decides which MCU pad sits on
which net; firmware decides which peripheral drives each pad. Sibling
plugins cooperate through files in the shared workspace and never import
each other's code.

## Decision

- The circuit agent exports `<design>.firmware.json`
  (`circuit_firmware_connectivity`): per MCU ref, every pad with its KiCad
  pin function name, net, signal class and voltage, plus the sha256 of the
  brief (and netlist) it was derived from.
- Firmware's `fw.netlist_match` resolves each contract pad against that
  export by pad name, profile aliases (e.g. `IO43`, `TXD0`) or package
  pin, and fails on wrong nets, wrong MCU refs, over-voltage, power nets
  used as signals, active pads left unassigned, or a supply net that does
  not reach the MCU.
- Firmware exports `<name>.fw-pinmap.json` (`firmware_pinmap`) with pad
  aliases and free pads; the circuit agent's `firmware-check` validates it
  against a fresh export. Both sides must pass.
- Disagreements become `fw_request` artifacts for the owning agent;
  firmware never edits circuit inputs.

## Consequences

- Either side can change independently; the next gate run on the other
  side detects drift.
- The schemas are duplicated as strict models on both sides and versioned
  by `schema_version`.
