# Third-Party Notices

`firmware-agent` is licensed under the BSD 3-Clause License (see
`LICENSE`). The `firmware-tools` image and the development environment
install or invoke the components below. All are unmodified executables
or package-manager installs run as subprocesses; none is import-linked
into `firmware` (ADR-0004).

| Component | Version pin | License | Use |
|---|---|---|---|
| Ubuntu 26.04 | `ubuntu:26.04@sha256:da6fc2be…` | various | Base image |
| uv | `ghcr.io/astral-sh/uv:0.12.23` | Apache-2.0 / MIT | Python and package manager |
| CPython | 3.14.x via uv | PSF-2.0 | Runtime |
| GNU Arm Embedded GCC, binutils, newlib | Ubuntu GCC 14.2.1 (`15:14.2.rel1-1`), binutils `2.45.50.20251209-1ubuntu1+23build1`, newlib `4.6.0.20260123-1` | GPL-3.0 with GCC Runtime Library Exception; newlib: BSD-style | ARM builds |
| GNU Make, CMake, Ninja | Ubuntu Make 4.4.1, CMake 4.2.3, Ninja 1.13.2 | GPL-3.0 / BSD-3-Clause / Apache-2.0 | Build backends |
| GDB (`gdb-multiarch`) | Ubuntu 17.1 | GPL-3.0 | ARM debugging |
| QEMU (`qemu-system-arm`) | Ubuntu 10.2.1 | GPL-2.0 | ARM simulation |
| Cppcheck | Ubuntu 2.19.0 | GPL-3.0 | Static analysis |
| PlatformIO Core | `6.2.0` (pip) | Apache-2.0 | ESP-IDF builds |
| PlatformIO `espressif32` platform, ESP-IDF, Xtensa toolchain, esptool, `xtensa-esp-elf-gdb` | `espressif32@7.1.3` (ESP-IDF 6.1; toolchain 15.2.0+20251204) | Apache-2.0 (platform, ESP-IDF, esptool: GPL-2.0), GPL-3.0 (GCC, GDB) | ESP32-S3 builds and debugging |
| Espressif QEMU (`qemu-system-xtensa`) | release `esp-develop-9.2.2-20260417`, asset `qemu-xtensa-softmmu-esp_develop_9.2.2_20260417-x86_64-linux-gnu.tar.xz`, sha256 `0eecb2a34a5586c0e59110f77b9343b7b336e82fdb0e1a30e1dc1bab8a547e35` | GPL-2.0-or-later | ESP32/ESP32-S3 simulation |
| pydantic | `>=2` via `uv.lock` | MIT | Contract models |
| mcp | `>=1.29,<2` via `uv.lock` | MIT | MCP server |
| openhands-sdk / openhands-tools | `1.52.0` (sdk-check group) | MIT | Plugin-load verification |
| pytest-cov | `7.1.0` (dev group) | MIT | Test coverage reporting |

Ubuntu package versions above are those measured in the 2026-10-01 image
rebuild; packages resolve from the repositories for the digest-pinned
Ubuntu 26.04 base.

Sources: Espressif QEMU <https://github.com/espressif/qemu>; the image
records source, release, checksum and license in
`/usr/share/doc/esp-qemu/SOURCE`. GPL sources for Ubuntu packages are
available from the Ubuntu archive (`apt-get source <package>`).

MCU profile data is transcribed from the vendor datasheets cited in each
profile's `source` field (Raspberry Pi RP2040 Datasheet; Espressif
ESP32-S3 Series Datasheet and Technical Reference Manual).

`plugins/firmware/hooks/scripts/safety_rail.py` and
`protect_generated.py` are adapted from `VibeBB/UX-creator-agent`
(BSD-3-Clause, same copyright holder).
