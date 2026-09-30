# ADR-0004: firmware-tools image, pinning and tool licenses

- Status: accepted
- Date: 2026-09-28

## Context

The gates need ARM GCC, CMake/Ninja, PlatformIO with the Espressif
platform and ESP-IDF, cppcheck, upstream and Espressif QEMU, and GDB.
Results must be reproducible, and several tools are GPL-licensed.

## Decision

- `docker/firmware-tools.Dockerfile` builds one image from a
  digest-pinned `ubuntu:24.04` base, Ubuntu packages, PlatformIO
  `6.2.0` with `espressif32@7.1.3` (ESP-IDF 6.1 and toolchain
  `15.2.0+20251204` resolved by the platform), and the Espressif QEMU release
  `esp-develop-9.2.2-20260417` verified by sha256. The PlatformIO
  packages are warmed by building the ESP32-S3 example, so gates run with
  `--network none`.
- PlatformIO projects must pin `platform = name@x.y.z`; the build gate
  fails otherwise.
- GPL tools (GCC, GDB, QEMU, cppcheck, ESP-IDF components built into the
  user's image) are separate executables invoked as subprocesses; no GPL
  or AGPL code is imported into `firmware`. Source, release, checksum and
  license of Espressif QEMU are recorded in
  `/usr/share/doc/esp-qemu/SOURCE` inside the image and in
  `THIRD_PARTY_NOTICES.md`.
- The plugin launcher runs entry points in the image named by
  `$FIRMWARE_TOOLS_IMAGE` or `docker/image-digests.json`; without a pin it
  runs on the host, where missing tools fail their gates.

## Consequences

- The image is large (the ESP-IDF toolchain dominates); ARM-only users
  may run on the host with the Ubuntu packages instead.
- Bumping any tool is a Dockerfile change reviewed with its complete
  changelog.
