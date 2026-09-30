# firmware-tools image

`firmware-tools.Dockerfile` bundles every tool the gates call (see
[`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md) and
[ADR-0004](../docs/adr/ADR-0004-firmware-tools-image-and-licenses.md)).
Build and smoke-test it with:

```bash
docker build -f docker/firmware-tools.Dockerfile -t firmware-tools:dev .
docker run --rm --network none firmware-tools:dev python -m firmware doctor
```

The image is published as `ghcr.io/vibebb/firmware-tools` with a commit-scoped
`-tools` tag and `latest`. `docker/image-digests.json` is the repository lock;
the publish workflow opens a bot PR to update it and the plugin-local
`plugins/firmware/tools-image.json` pin. The repository lock starts unpinned;
the plugin pin is created by the first successful publish. Neither should be
filled with a locally built image digest.

The launcher resolves `FIRMWARE_TOOLS_IMAGE`, then
`plugins/firmware/tools-image.json`, then the repository lock. PlatformIO
packages are warmed at build time, so the CI gate and debug smoke commands run
inside the image with network access disabled. Tool versions and their probe
commands are recorded by `scripts/measure_image_tools.py`.
