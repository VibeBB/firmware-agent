# Changelog

## 0.1.0 — unreleased

- Firmware contract (`<name>.fw.json`) with MCU, pin map, peripherals,
  power modes, build, static analysis and QEMU simulations.
- MCU profiles: RP2040, ESP32-S3.
- Gates: contract, pin functions, circuit netlist match, power modes,
  pin header, build (make/CMake/PlatformIO), flash/RAM budget, cppcheck,
  QEMU simulation (ARM, Espressif).
- Advisory GDB debugging on QEMU.
- Circuit interchange (`circuit_firmware_connectivity`, `firmware_pinmap`)
  and sibling change requests (`fw_request`).
- OpenHands plugin: 3 agents, 6 commands, 6 skills, 4 hooks, MCP server.
- firmware-tools image and examples (smart-kettle RP2040, desk-lamp ESP32-S3).
- Updated SDK verification pins, uv, and the ESP32-S3 toolchain; normalized
  flash-image post-build arguments for PlatformIO 7.1.3.
- Added bounded cppcheck version probing and a development-only pytest-cov
  coverage gate.
- Published firmware-tools to GHCR with digest-lock and plugin-local pin updates.
