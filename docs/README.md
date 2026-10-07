# firmware-agent documentation

## Guides

- [Architecture](architecture.md) — module map, data flow, launcher, MCP server
- [Workflow](workflow.md) — session stages and the records each leaves
- [Agents](agents.md) — the three agents and their duties
- [Skills](skills.md) — plugin skill reference index
- [Commands](commands.md) — every CLI subcommand and `/firmware:*` command
- [MCP tools](mcp.md) — every `firmware_*` tool: inputs, outputs, side effects
- [Hooks](hooks.md) — every hook in `hooks.json` and shared-hook policy
- [Contracts](contracts.md) — every JSON schema and generated artifact
- [Records and vision](records-and-vision.md) — VRP duties and vision review points
- [Records protocol](records-protocol.md) — the generic VibeBB Record Protocol
- [Sister cooperation](sister-cooperation.md) — SLP v2, circuit interchange, fw_request v2
- [Performance and limits](performance-and-limits.md) — timeouts, sizes, coverage gaps
- [Operations](operations.md) — image pinning, attestation, publish, release
- [Development](development.md) — setup, verify commands, how to extend
- [Test coverage and test design](test-coverage.md) — C0/C1/C2/MCC/MC/DC and boundary coverage, floors, test-design techniques
- [Improvement notes](improvement-notes.md) — adopted ideas and open gaps
- [Dependency updates](dependency-updates.md) — dependency review guide

## Architecture decision records

- [ADR-0001](adr/ADR-0001-python-core-json-contracts.md) — Python core, JSON contracts, deterministic gates
- [ADR-0002](adr/ADR-0002-circuit-firmware-interchange.md) — circuit/firmware interchange artifacts
- [ADR-0003](adr/ADR-0003-qemu-simulation-and-advisory-gdb.md) — QEMU simulation gates and advisory GDB
- [ADR-0004](adr/ADR-0004-firmware-tools-image-and-licenses.md) — firmware-tools image, pinning, tool licenses
- [ADR-0005](adr/ADR-0005-vision-and-profile-hooks.md) — image evidence and vision-profile readiness hooks
- [ADR-0006](adr/ADR-0006-pytest-coverage-gate.md) — development-only pytest coverage gate
- [ADR-0007](adr/ADR-0007-publish-firmware-tools-image-by-digest.md) — publish firmware-tools and lock its digest
- [ADR-0008](adr/ADR-0008-attest-published-tools-images.md) — attest published tools images
- [ADR-0009](adr/ADR-0009-records-liaison-vision-refactor.md) — VRP v1, SLP v2, renders, Docker-only launcher, sister rename, docs rebuild
- [ADR-0010](adr/ADR-0010-structural-coverage.md) — structural coverage gate (C0, C1, C2, MC/DC, boundaries)

## Research

- [cppcheck 2.19 adoption](research/cppcheck-2.19-adoption.md)
- [SDK v1.50.0 feature evaluation](research/sdk-v1.50.0-feature-evaluation.md)
- [SDK v1.50.1 feature evaluation](research/sdk-v1.50.1-feature-evaluation.md)
- [SDK v1.51.0 feature evaluation](research/sdk-v1.51.0-feature-evaluation.md)
- [SDK v1.52.0 feature evaluation](research/sdk-v1.52.0-feature-evaluation.md)
- [SDK v1.53.0 feature evaluation](research/sdk-v1.53.0-feature-evaluation.md)
- [Agent Canvas v1.25 feature evaluation](research/ac-v1.25-feature-evaluation.md)
