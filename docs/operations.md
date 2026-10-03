# Operations

## SBOM attestations

`publish-firmware-images.yml` generates and attests a package-level SPDX-2.3
SBOM for the published tools digest and uploads the full Syft SBOM as a 90-day
workflow-run artifact. The lock records the `sbom_attestation` URL, which
`locked-image-check.yml` verifies when present;
an absent URL warns and continues.
The attested SBOM omits file entries and relationships involving files to
stay below the 16 MiB limit.

## Launcher-side verification

`FIRMWARE_VERIFY_ATTESTATION` accepts `auto` (the default), `require`, or
`off`. Before pulling a lock-provided image, and on every `prewarm`, the
launcher uses `gh attestation verify` with the lock entry and publisher
workflow. `auto` prints one note and skips for an image override, missing
attestation, missing `gh`, or failed `gh auth status`; once verification
starts, failure or timeout prevents the pull. `require` makes skip conditions
errors, while `off` never verifies. Ordinary invocations do not re-verify a
locally present image, and `--warn` doctor paths never verify.

## Container hardening

Three layers were adopted after a comparative evaluation of Lynis,
`docker build --check`, Trivy, Grype, Dockle, and hadolint:

- **Dockerfile lint** (`dockerfile-lint` job in `ci.yml`): hadolint
  v2.15.1 via `hadolint-action` v3.5.0 plus `docker build --check`
  (BuildKit built-in). `.hadolint.yaml` allows only docker.io and
  ghcr.io registries and waives DL3008 (exact deb pins rot when archives
  drop them; downloaded tools are already version+sha256 pinned).
- **Image scan on publish** (`publish-firmware-images.yml`): Trivy
  v0.75.0 via `trivy-action` v0.36.0 scans the pushed digest for
  CRITICAL/HIGH fixable vulnerabilities, secrets, and misconfiguration,
  gated (`exit-code 1`), with SARIF uploaded to code scanning
  (`category: trivy-firmware-tools`) and a full JSON report as an
  artifact. Only the immutable `<sha>-tools` tag is pushed at build
  time; `:latest` is promoted onto the verified digest with
  `imagetools create` after every gate passes, so a gate failure never
  moves `:latest`. The action is SHA-pinned and `version:` is explicit — the
  March 2026 Trivy supply-chain compromise made both non-negotiable.
- **Weekly audit** (`container-audit.yml`, Mondays 03:52 UTC): pulls the
  pinned digest from `docker/image-digests.json`, re-scans with a fresh
  vulnerability DB (new CVEs against the frozen image), runs the Docker
  CIS compliance report, runs an informational in-image Lynis 3.1.7
  audit, aggregates `container-hardening.json` (artifact), and
  edits/creates a "Container hardening report" issue. The issue closes
  automatically when fixable HIGH/CRITICAL findings reach zero. The
  Lynis Hardening Index is recorded as a trend metric only — its
  denominator shifts with container-skipped tests, so it never gates.

Not adopted, with reasons: `lynis audit dockerfile` (~6 greps, frozen
since 2018, subset of hadolint, hardening index always 1);
Dockle (v0.4.15 stale; its CIS-derived checks are covered by Trivy's
`--compliance docker-cis` report); Grype (equivalent for the SBOM path,
kept as fallback); checkov (redundant third linter); `cisofy/lynis`
Docker image (does not exist — Lynis runs from a pinned git clone);
non-root USER enforcement and HEALTHCHECK enforcement (CI tools images —
deferred policy decisions).

Changelog evaluation for the adopted pins is in the introducing PR.
Suppressions: `.hadolint.yaml` waivers above; `.trivyignore` holds
time-boxed finding IDs — entries must carry an `exp:` date and a
rationale line here when added.

The uv-managed CPython's bundled `pip` payload (vendored urllib3,
msgpack, setuptools — never invoked; dependencies install via `uv` and
the shipped venv is pip-less) is stripped in the `uv python install`
layer. PlatformIO's own `/opt/pio` venv is uv-created without pip and
its `/opt/platformio` runtime environment is pre-warmed at build; the
weekly audit reports any new payload there as a normal finding.

Remaining publish-gate findings are vendored upstream payloads that
runtime tooling requires, covered by `.trivyignore` waivers that expire
2027-01-03 and a matching deferral in
`scripts/dependency_update_deferrals.json` (re-scan and drop cleared
waivers at the next `ESPRESSIF32_PLATFORM` / ESP-IDF bump):

- `cryptography` 46.0.7 in `tool-esptoolpy/_contrib` and the ESP-IDF
  helper venv (CVE-2026-69247, CVE-2026-69249, GHSA-537c-gmf6-5ccf) —
  esptool invokes it for secure-boot/signing; the fix lands only when
  upstream re-vendors.
- `urllib3` 1.26.20 in the ESP-IDF helper venv (CVE-2025-66418,
  CVE-2025-66471, CVE-2026-21441, CVE-2026-44431, CVE-2026-97687,
  CVE-2026-97689) — idf_tools fetches with it; gates run with
  `--network none`, so it carries no runtime network surface.
- DS-0002/DS-0029 on example Dockerfiles inside
  `framework-espidf/` (never built by this repo).
- `private-key` on upstream mbedtls/openthread test keys inside
  `framework-espidf/` — 354 findings, all published test fixtures.
- QEMU debs (`qemu-system-arm`, `-common`, `-data`,
  `ubuntu-helper-virt-hwe`, `ubuntu-virt`; CVE-2026-3886) and the
  vendored `ecdsa` package (CVE-2024-23342) — unfixable HIGHs with no
  released fix upstream; recorded as expiring acceptances so the
  unfixed count is deliberate, re-evaluated at each ubuntu:26.04
  base-digest and `ESPRESSIF32_PLATFORM` / `ESP_QEMU` bump.

The weekly audit runs Lynis as container root (`--user 0`) with the
committed `docker/lynis-container.prf` profile, which skips tests that
are inapplicable inside a container (kernel/systemd/mounts/storage/
network/PAM/accounting are governed by the runtime flags below, not the
image fs). The profile raises the Hardening Index and reduces the
suggestion list to image-actionable items; remaining suggestions are
fixed in the Dockerfile (`UMASK 027` in `/etc/login.defs`, Lynis
AUTH-9328) or silenced only with a documented reason.

`firmware_launcher.py` applies the runtime-hardening flags the
container profile defers to: `--network none`, `--user uid:gid`,
`--cap-drop ALL`, `--security-opt no-new-privileges`. A `--read-only`
root filesystem stays an optional hardening for callers that supply
tmpfs for tools that need scratch space.

## CI runner network auditing

CI and image-publishing jobs use `step-security/harden-runner` in audit-only mode. It observes network egress without blocking requests; per-run insights are available in the GitHub Actions job summary.

## Digest-lock PR verification

The lock pull request's own `pull_request` runs are the single CI path:
`workflow_dispatch` runs never satisfy required checks, and dispatching
`ci.yml` on the lock branch duplicated a ~12-minute e2e build on the same
head SHA. The publisher approves the action_required pull_request runs,
then polls the authoritative required-check set for up to 15 minutes.
Non-required failures do not block publishing; a concluded required-check
failure or a PR closed without merge fails the job. A PR merged externally
triggers the existing post-merge main workflows without waiting for their
results. If required checks remain pending at the deadline, the publisher
arms squash auto-merge with branch deletion and exits successfully so
branch protection can complete the merge.

Post-merge coverage for merges that land outside a live publisher (armed
auto-merge completing late, or merges performed by the sweep) comes from
`digest-lock-sweep.yml`: bot merges do not fire push events, so the sweep
scans recently merged lock PRs every 6 hours and dispatches `ci.yml` and
`locked-image-check.yml` on main for any merge with no dispatch since.

`dependency-review.yml` additionally requires the repository's
Dependency graph setting (Settings → Advanced Security); the action
fails with "Dependency review is not supported on this repository" when
it is disabled.

SPDX generation prefers the GHCR registry source, writes temporary data under
the runner's temporary directory, and disables file metadata. The publisher
removes file entries and relationships involving files to produce the
package-level SPDX-2.3 SBOM. A guard reports disk space and the attested SBOM
size after transformation and fails above 16 MiB; the full Syft SBOM is
uploaded as a 90-day workflow-run artifact.
