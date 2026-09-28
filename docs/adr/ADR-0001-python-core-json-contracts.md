# ADR-0001: Python core with JSON contracts and deterministic gates

- Status: accepted
- Date: 2026-09-28

## Context

VibeBB plugins share one convention: a strict JSON contract is the source
of truth, a Python package (stdlib + pydantic v2 + mcp) judges it, and
OpenHands agents, commands and skills are Markdown that delegate every
executable step to that package. Firmware needs the same auditable shape
while depending on large native toolchains.

## Decision

- `<name>.fw.json` (`artifact_kind: firmware_contract`) holds the MCU,
  pin map, peripherals, power modes, build, static analysis and
  simulations. Unknown keys are rejected.
- `src/firmware/` implements every gate. External tools (make, CMake,
  PlatformIO, cppcheck, QEMU, GDB) are subprocesses whose exit codes and
  outputs are parsed; anything missing or unparseable fails.
- ELF flash/RAM accounting is a stdlib parser of `PT_LOAD` program
  headers placed into the MCU profile's memory regions, so the budget does
  not depend on a toolchain's `size` output format.
- MCU knowledge lives in versioned JSON profiles
  (`src/firmware/profiles/*.json`) with a cited datasheet source.
- The CLI and the MCP server share `service.py` payloads.

## Consequences

- Adding an MCU is a data change plus tests, not code.
- Gate verdicts are reproducible from the contract, sources and the
  pinned tools image; the report records the contract and circuit export
  hashes.
