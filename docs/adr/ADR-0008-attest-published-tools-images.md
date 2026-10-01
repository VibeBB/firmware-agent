## SBOM attestations

The publisher generates an SPDX-2.3 SBOM for the digest-pinned tools image,
attests it with predicate type `https://spdx.dev/Document/v2.3`, and uploads
the artifact for 30 days. The lock writer records the returned
`sbom_attestation` URL. Locked-image checks verify it when present and warn
when absent; unpinned locks cannot carry this metadata.
# ADR-0008: Attest published tools images

## Status

Accepted

## Context

The firmware tools image is published to GHCR and pinned by digest in the
repository and plugin locks. A digest identifies image content but does not
by itself identify the workflow that produced it.

## Decision

The image publisher will create a GitHub artifact attestation for each tools
image. The attestation URL is recorded with the digest in both lock files.
Locked-image checks verify available attestations against the repository's
publisher workflow and warn when an older lock has no attestation metadata.

## Consequences

New image pins carry provenance that can be verified by the scheduled and
manual locked-image check. Existing digest locks remain usable until the next
publish updates them with an attestation.

## Launcher-side verification

`FIRMWARE_VERIFY_ATTESTATION` accepts `auto` (the default), `require`, or
`off`. Before pulling a lock-provided image, and on every `prewarm`, the
launcher uses `gh attestation verify` with the lock entry and publisher
workflow. `auto` prints one note and skips for an image override, missing
attestation, missing `gh`, or failed `gh auth status`; once verification
starts, failure or timeout prevents the pull. `require` makes skip conditions
errors, while `off` never verifies. Ordinary invocations do not re-verify a
locally present image, and `--warn` doctor paths never verify.
