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
Python-version support. Review any candidate against the upstream release notes,
update the source pin, regenerate `uv.lock` with uv rather than editing it by
hand, and run the CI-equivalent checks and firmware-tools image smoke.

`ESP_QEMU_RELEASE` is compared against the latest `esp-develop-X.Y.Z-YYYYMMDD`
tag of `espressif/qemu` and `ESPRESSIF32_PLATFORM` against the latest
`platformio/platform-espressif32` release, so new upstream releases surface in
the weekly report. The remaining Dockerfile surfaces require manual review
before changing:

- `ESP_QEMU_ASSET` and `ESP_QEMU_SHA256` must be re-verified against the
  upstream release whenever `ESP_QEMU_RELEASE` moves (asset URL and checksum
  travel with the tag).
- The Docker `PLATFORMIO_VERSION` ARG is compared with PyPI.
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

## 2026-10-07 update (sdk 1.53.0)

Bumped `openhands-sdk`/`openhands-tools` 1.52.0 -> 1.53.0 (`sdk-check`
group, `uv.lock` regenerated — no other pins moved). Adoption decisions are
recorded per upstream change in
[SDK v1.53.0 feature evaluation](research/sdk-v1.53.0-feature-evaluation.md):
everything repo-facing was adopted implicitly or not applicable; the new
canvas-extension icon endpoint was not adopted (VibeBB plugins are
AgentCanvas plugins, not canvas extensions). The mcp deferral was refreshed
citing SDK 1.53.0 — `fastmcp>=3.2.0,<4` still caps `mcp<2`.

## 2026-10-05 update (sdk 1.52.0)

Bumped `openhands-sdk`/`openhands-tools` 1.51.0 -> 1.52.0 (`sdk-check`
group, `uv.lock` regenerated — no other pins moved). Adoption decisions are
recorded per upstream change in
[SDK v1.52.0 feature evaluation](research/sdk-v1.52.0-feature-evaluation.md):
everything repo-facing was adopted implicitly or not applicable; no feature
required a repo change. The mcp deferral was refreshed citing SDK 1.52.0 —
`fastmcp>=3.2.0,<4` still caps `mcp<2`.

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

## Decisions - 2026-10-04 round

Adopted now:

| Component | From | To | Evaluation |
|-----------|------|----|------------|
| uv | 0.12.22 | 0.12.23 | Point release; dependency resolution and managed-Python fixes. No workflow changes required. |
| Python pins | 3.12 | 3.14 | `uv python install` / `uv venv --python` / `python3.x` / `.python-version` now resolve 3.14; ci.yml matrix gains a 3.14 leg. |
| Python 3.15 | - | canary leg | Experimental matrix leg runs each step with `continue-on-error`; a `::warning::` annotation records forward-compat failures without failing the check. |

Deferred:

| Candidate | Reason | Re-check |
|-----------|--------|----------|
| Python 3.15 as default | `openhands-sdk` -> `fastuuid==0.14.0` -> PyO3 0.26 caps supported interpreters at 3.14; `uv sync` fails on 3.15 today. The canary leg detects when upstream wheels land. | After 3.15 GA (2026-10-09) and a PyO3 0.27-wheel fastuuid release. |
