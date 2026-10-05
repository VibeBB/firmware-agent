# firmware-agent documentation

## Architecture decision records

- [ADR-0001](adr/ADR-0001-python-core-json-contracts.md) — Python core, JSON contracts, deterministic gates
- [ADR-0002](adr/ADR-0002-circuit-firmware-interchange.md) — circuit/firmware interchange artifacts
- [ADR-0003](adr/ADR-0003-qemu-simulation-and-advisory-gdb.md) — QEMU simulation gates and advisory GDB
- [ADR-0004](adr/ADR-0004-firmware-tools-image-and-licenses.md) — firmware-tools image, pinning, tool licenses
- [ADR-0005](adr/ADR-0005-vision-and-profile-hooks.md) — image evidence and vision-profile readiness hooks
- [ADR-0006](adr/ADR-0006-pytest-coverage-gate.md) — development-only pytest coverage gate
- [ADR-0007](adr/ADR-0007-publish-firmware-tools-image-by-digest.md) — publish firmware-tools and lock its digest
- [ADR-0008](adr/ADR-0008-attest-published-tools-images.md) — attest published tools images

## Research

- [SDK v1.50.0 feature evaluation](research/sdk-v1.50.0-feature-evaluation.md)
- [SDK v1.50.1 feature evaluation](research/sdk-v1.50.1-feature-evaluation.md) — OpenHands SDK/tools adoption decisions
- [SDK v1.51.0 feature evaluation](research/sdk-v1.51.0-feature-evaluation.md) — OpenHands SDK/tools and uv adoption decisions
- [SDK v1.52.0 feature evaluation](research/sdk-v1.52.0-feature-evaluation.md) — OpenHands SDK/tools adoption decisions

## Skills

The workflow and field references live in the plugin skills:
[workflow](../plugins/firmware/skills/firmware-workflow/SKILL.md),
[contract](../plugins/firmware/skills/firmware-contract/SKILL.md),
[MCU and pin map](../plugins/firmware/skills/firmware-mcu-pinmap/SKILL.md),
[power modes](../plugins/firmware/skills/firmware-power-modes/SKILL.md),
[sister cooperation](../plugins/firmware/skills/firmware-sister-cooperation/SKILL.md),
[QEMU and GDB](../plugins/firmware/skills/firmware-qemu/SKILL.md).

## Records

- [VibeBB Record Protocol](records-protocol.md) — decisions, stage impressions and vision reviews every session must leave

## Maintenance

See the [dependency update review guide](dependency-updates.md).
