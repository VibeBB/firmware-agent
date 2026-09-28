# firmware-tools image

`firmware-tools.Dockerfile` bundles every tool the gates call (see
`THIRD_PARTY_NOTICES.md` and ADR-0004). Build and smoke-test it with:

```bash
docker build -f docker/firmware-tools.Dockerfile -t firmware-tools:dev .
docker run --rm --network none firmware-tools:dev python -m firmware doctor
```

The launcher uses the image named by `FIRMWARE_TOOLS_IMAGE`, or the
`firmware_tools` entry of `docker/image-digests.json` once a published
digest is recorded. The PlatformIO packages are warmed at build time, so
gates run without network access.
