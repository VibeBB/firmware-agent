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
