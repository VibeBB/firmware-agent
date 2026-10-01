# Operations

## SBOM attestations

`publish-firmware-images.yml` generates and attests an SPDX-2.3 SBOM for the
published tools digest and uploads it for 30 days. The lock records the
`sbom_attestation` URL, which `locked-image-check.yml` verifies when present;
an absent URL warns and continues.

## Launcher-side verification

`FIRMWARE_VERIFY_ATTESTATION` accepts `auto` (the default), `require`, or
`off`. Before pulling a lock-provided image, and on every `prewarm`, the
launcher uses `gh attestation verify` with the lock entry and publisher
workflow. `auto` prints one note and skips for an image override, missing
attestation, missing `gh`, or failed `gh auth status`; once verification
starts, failure or timeout prevents the pull. `require` makes skip conditions
errors, while `off` never verifies. Ordinary invocations do not re-verify a
locally present image, and `--warn` doctor paths never verify.

## CI runner network auditing

CI and image-publishing jobs use `step-security/harden-runner` in audit-only mode. It observes network egress without blocking requests; per-run insights are available in the GitHub Actions job summary.

## Digest-lock PR verification

The publisher dispatches `ci.yml` and `workflow-lint.yml` on the lock branch, then polls the authoritative required-check set for up to 30 minutes. Non-required failures do not block publishing; a concluded required-check failure or a PR closed without merge fails the job. A PR merged externally triggers the existing post-merge main workflows without waiting for their results. If required checks remain pending at the deadline, the publisher arms squash auto-merge with branch deletion and exits successfully so branch protection can complete the merge.

SPDX SBOM generation prefers the GHCR registry source, writes temporary data under the runner's temporary directory, and disables file metadata. A guard reports disk space and SBOM size immediately after generation and fails above 16 MiB, the attestation service's maximum.
