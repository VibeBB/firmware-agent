# Third-Party Notices

`firmware-agent` is licensed under the BSD 3-Clause License (see
`LICENSE`). The `firmware-tools` image and the development environment
install or invoke the components below. All are unmodified executables
or package-manager installs run as subprocesses; none is import-linked
into `firmware` (ADR-0004).

| Component | Version pin | License | Use |
|---|---|---|---|
| Ubuntu 24.04 | `ubuntu:24.04@sha256:008173c2…` | various | Base image |
| uv | `ghcr.io/astral-sh/uv:0.12.19` | Apache-2.0 / MIT | Python and package manager |
| CPython | 3.12.x via uv | PSF-2.0 | Runtime |
| GNU Arm Embedded GCC, binutils, newlib | Ubuntu `gcc-arm-none-eabi` 13.2.rel1 | GPL-3.0 with GCC Runtime Library Exception; newlib: BSD-style | ARM builds |
| GNU Make, CMake, Ninja | Ubuntu packages | GPL-3.0 / BSD-3-Clause / Apache-2.0 | Build backends |
| GDB (`gdb-multiarch`) | Ubuntu 15.1 | GPL-3.0 | ARM debugging |
| QEMU (`qemu-system-arm`) | Ubuntu 8.2.2 | GPL-2.0 | ARM simulation |
| Cppcheck | Ubuntu 2.13.0 | GPL-3.0 | Static analysis |
| PlatformIO Core | `6.2.0` (pip) | Apache-2.0 | ESP-IDF builds |
| PlatformIO `espressif32` platform, ESP-IDF, Xtensa toolchain, esptool, `xtensa-esp-elf-gdb` | `espressif32@6.10.0` | Apache-2.0 (platform, ESP-IDF, esptool: GPL-2.0), GPL-3.0 (GCC, GDB) | ESP32-S3 builds and debugging |
| Espressif QEMU (`qemu-system-xtensa`) | release `esp-develop-9.2.2-20260417`, asset `qemu-xtensa-softmmu-esp_develop_9.2.2_20260417-x86_64-linux-gnu.tar.xz`, sha256 `0eecb2a34a5586c0e59110f77b9343b7b336e82fdb0e1a30e1dc1bab8a547e35` | GPL-2.0-or-later | ESP32/ESP32-S3 simulation |
| pydantic | `>=2` via `uv.lock` | MIT | Contract models |
| mcp | `>=1.29,<2` via `uv.lock` | MIT | MCP server |
| openhands-sdk / openhands-tools | `1.49.6` (sdk-check group) | MIT | Plugin-load verification |

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
