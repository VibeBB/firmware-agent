# ADR-0007: Publish firmware-tools and lock its digest

**Status:** Accepted
**Date:** 2026-09-30

## Context

The CI end-to-end gates need the pinned PlatformIO, compiler, cppcheck, QEMU,
and GDB toolchain in `docker/firmware-tools.Dockerfile`. Building that image
for every consumer duplicates work and can make checks depend on an upstream
registry being available. The Firmware launcher already resolves an optional
image override, a plugin-local image pin, and the repository image lock.

## Decision

Publish `ghcr.io/vibebb/firmware-tools` from the repository's main branch with
the commit-scoped `${sha}-tools` tag and `latest`. Use the registry digest for
the repository lock and generated plugin-local pin; the publish workflow
updates both through its digest-lock PR. The initial `firmware_tools` lock
entry is intentionally unpinned until the first successful publish.

The publishing workflow measures the tools in the digest-pinned image and runs
the same doctor, example gates, and debug smoke commands as CI. The container
has no network access during those checks. Local image digests are not
committed.

## Consequences

- CI and installed plugins can share an immutable tools image without
  changing the launcher's environment override or fallback order.
- A failed build, measurement, or smoke check blocks digest-lock updates.
- The repository lock and plugin pin are maintained together by the workflow;
  human changes to generated pins are not part of ordinary development.
- GHCR publishing and bot pull requests require Actions permissions for
  package writes, content writes, and pull-request writes.
