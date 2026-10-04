# Dependency update review

Run the report locally with:

```bash
uv sync --locked
uv run python scripts/check_dependency_updates.py \
  --markdown /tmp/firmware-dependencies.md \
  --json /tmp/firmware-dependencies.json
```

The report checks direct PyPI dependencies and locked transitive drift, the uv
pin, GitHub Actions SHA pins (including subpath actions such as
`github/codeql-action/upload-sarif`), pinned `uvx` tools, Docker ARG pins,
the Ubuntu base tag, `git clone --branch` pins inside workflows,
direct-download pins inside workflows (release-asset URLs, PyPI wheel
filenames, and trivy `version:` inputs on aquasecurity actions), and
Python-version support. The Docker `PLATFORMIO_VERSION` ARG is
compared with PyPI. Review any candidate against the upstream release notes,
update the source pin, regenerate `uv.lock` with uv rather than editing it by
hand, and run the CI-equivalent checks and firmware-tools image smoke.

These Dockerfile surfaces require manual review before changing:

- `ESPRESSIF32_PLATFORM` is a PlatformIO registry platform pin. The previously
  probed registry API URL
  `https://api.registry.platformio.org/v3/platforms/platformio/espressif32`
  returned 404, so no automated latest-version check is configured. Verify
  the current release and compatibility in the official PlatformIO registry.
- `ESP_QEMU_RELEASE`, `ESP_QEMU_ASSET`, and `ESP_QEMU_SHA256` identify the
  Espressif QEMU release artifact and its checksum. Verify the asset and
  checksum against the upstream release before updating them.
- The Ubuntu base-image digest is a security pin. Review the upstream image
  digest and supported `26.04` tag together; do not update the digest from a
  local build or an unverified mirror.

The Docker-base checker handles Ubuntu release tags generically and selects
the latest `xx.04` tag. Its tests cover the digest-pinned `26.04` base; no
version-specific checker target is needed when the Ubuntu LTS tag changes.

## Workflow git clone pins

`container-audit.yml` clones `CISOfy/lynis` at `git clone --depth 1 --branch
3.1.7` for the informational Lynis audit. The checker treats
`git clone --branch <ref>` pins inside workflows as a `git-clone` surface and
compares each ref against the upstream repo's highest semver tag, so a new
Lynis release surfaces in the weekly report.

Deferrals and their review dates are tracked in
`scripts/dependency_update_deferrals.json`. A deferred candidate still needs
an owner to revisit it by the listed date; deferrals do not change source
pins.

## 2026-10-03 scheduled update

Bumped `openhands-sdk`/`openhands-tools` 1.50.1 -> 1.51.0 and uv
0.12.21 -> 0.12.22 (`required-version`, Dockerfile `UV_VERSION`/`UV_DIGEST`,
THIRD_PARTY_NOTICES). ruff was already locked at 0.16.10 and
`anchore/sbom-action` already at v0.24.3, so no pin moved for either.
Adoption decisions are recorded per upstream change in
[SDK v1.51.0 feature evaluation](research/sdk-v1.51.0-feature-evaluation.md):
everything repo-facing was inherent or lock-only; the new agent-profiles
API was not adopted (plugins use `LLMProfileStore`), and `UV_PYTHON_ARCH`
was not adopted (x86_64-only builds). The mcp deferral was refreshed to
`latest: 2.3.0` citing SDK 1.51.0 — `fastmcp>=3.2.0,<4` still caps `mcp<2`.
