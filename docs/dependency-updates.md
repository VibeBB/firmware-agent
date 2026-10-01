# Dependency update review

Run the report locally with:

```bash
uv sync --locked
uv run python scripts/check_dependency_updates.py \
  --markdown /tmp/firmware-dependencies.md \
  --json /tmp/firmware-dependencies.json
```

The report checks direct PyPI dependencies and locked transitive drift, the uv
pin, GitHub Actions SHA pins, pinned `uvx` tools, Docker ARG pins, the Ubuntu
base tag, and Python-version support. The Docker `PLATFORMIO_VERSION` ARG is
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

Deferrals and their review dates are tracked in
`scripts/dependency_update_deferrals.json`. A deferred candidate still needs
an owner to revisit it by the listed date; deferrals do not change source
pins.
