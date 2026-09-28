---
name: firmware-mcu-pinmap
description: Choosing an MCU profile and assigning pads — function routing, peripheral instances, reserved and strapping/JTAG pads, pad aliases, and matching the circuit netlist.
version: 0.1.0
license: BSD-3-Clause
triggers:
  - pin map
  - pinout
  - pin assignment
  - peripheral
  - ピンマップ
  - ピン割り当て
  - 周辺機能
---

# MCU profiles and pin maps

Built-in profiles: `rp2040`, `esp32s3` (`firmware profile <id>` prints
one). A profile declares the part, core, flash/RAM capacity, memory
regions, peripheral instance counts, the QEMU machine (if any), and per-pad
`functions` tokens `<kind><instance|*>.<role>` such as `i2c0.sda`,
`uart*.tx`, `pwm3.a`, `adc0.ch0`.

Assignment rules checked by `fw.pin_functions`:

- The pad must exist and must not be `reserved` (power, flash, debug,
  clock, reset, test).
- The pad must route the pin's function for the peripheral's instance
  (`uart0.tx` for a `uart_tx` pin on `uart` instance 0; `*` matches any
  instance for matrix-routed MCUs like the ESP32-S3).
- The instance must exist on the MCU (`peripherals` counts).
- Pads with `caution: strapping|jtag` need the caution listed in
  `acknowledge` plus a `rationale` explaining the boot/debug impact.
- Buses carry their required roles (I2C: SDA+SCL; SPI: SCK + MOSI or
  MISO; UART: TX or RX; USB: D+ and D-).

## Matching the circuit (`fw.netlist_match`)

Profiles list pad `aliases` (e.g. ESP32-S3 `GPIO43` = `IO43`/`TXD0`/`U0TXD`)
so KiCad pin names resolve. A pin may give `package_pin` when the circuit
only knows pin numbers (brief-only exports). Resolution order: pad name,
aliases, then package pin — and it fails when nothing matches.

When the circuit disagrees, decide which side is wrong. Fix the contract
if firmware is wrong; otherwise write
`firmware request <contract> --target circuit --risk high --change ... --rationale ... --net <NET> --failing-check fw.netlist_match`.
