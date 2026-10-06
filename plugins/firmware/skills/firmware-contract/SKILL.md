---
name: firmware-contract
description: Field-by-field reference for <name>.fw.json — mcu, circuit link, pins, peripherals, power, build, analysis, simulations — and the validation rules each field is held to.
version: 0.1.0
license: BSD-3-Clause
triggers:
  - fw.json
  - firmware contract
  - ファーム契約
---

# Firmware contract (`schema_version: 1`)

```json
{
  "schema_version": 1, "system": "firmware", "artifact_kind": "firmware_contract",
  "name": "smart-kettle",
  "mcu": {"profile": "rp2040", "ref": "U1", "flash_kb": 2048, "clock_mhz": 125},
  "circuit": {"connectivity": "circuit/smart-kettle.firmware.json"},
  "pins": [
    {"signal": "boil_button", "pad": "GPIO2", "net": "BTN_BOIL", "function": "gpio_in",
     "pull": "up", "active": "low", "rationale": "Wakes the MCU from dormant."},
    {"signal": "temp_sda", "pad": "GPIO4", "net": "I2C_SDA", "function": "i2c_sda",
     "peripheral": "i2c_temp"}
  ],
  "peripherals": [{"id": "i2c_temp", "kind": "i2c", "instance": 0, "frequency_hz": 400000}],
  "power": {"supply_net": "+3V3", "average_budget_ua": 1500, "modes": [
    {"id": "standby", "kind": "sleep", "current_ua": 900, "duty": 0.9, "wake": ["boil_button"]}
  ]},
  "build": {"backend": "make", "dir": "fw", "target": "all", "elf": "fw/build/app.elf",
            "pins_header": "fw/include/fw_pins.h", "budget": {"flash_pct": 80, "ram_pct": 75}},
  "analysis": {"sources": ["fw/src"], "includes": ["fw/include"], "std": "c11"},
  "simulations": [{"id": "logic", "runner": "qemu-arm", "machine": "mps2-an385",
                   "fidelity": "core", "image": "fw/build/sim.elf", "exit_code": 0,
                   "expect": ["BOOT", "SIM PASS"], "forbid": ["ASSERT"]}]
}
```

Rules enforced at load time (unknown keys are rejected everywhere):

- `pins[].function` is one of `gpio_in`, `gpio_out`, `adc`, `pwm`,
  `i2c_sda/scl`, `spi_sck/mosi/miso/cs`, `uart_tx/rx/cts/rts`, `usb_dp/dm`.
  Bus functions must name a declared `peripheral` of the matching kind
  (checked by `fw.pin_functions`); `pwm`/`adc` pins should name one so the
  instance is checked; GPIO pins take none.
- `initial` applies to `gpio_out`/`pwm` only; `acknowledge` lists
  `strapping`/`jtag` cautions the designer accepted.
- Signals, pads, peripheral ids, mode ids and simulation ids are unique; a
  bus instance (`i2c0`, `uart1`, ...) is declared once.
- `build.backend`: `make` (`make -C dir [target]`), `cmake` (Ninja, build
  dir `<dir>/build`), `platformio` (`pio run -d dir -e env`; the project's
  `platform` must be pinned to an exact `name@x.y.z`).
- `qemu-arm` simulations declare `exit_code` (semihosting exit);
  `qemu-esp` simulations cannot (the image runs until the expectations
  complete or the timeout).
- `cues` (optional) binds a bard `cues.json`: `manifest`, pinned
  `sha256`, the `pwm` `pin` that drives the buzzer, the generated
  `header`, and the transducer band `min_hz` < `max_hz` from its
  datasheet. Re-pin `sha256` only after reviewing a re-rendered cue set;
  then run `firmware cues`.
- `ftm` (optional) binds production-engineering's
  `factory-test-spec.json`: `spec`, pinned `sha256`, the generated
  `header`, and the `peripheral` carrying the factory transport (none for
  swd/jtag). Re-pin only after reviewing a changed spec; then run
  `firmware ftm`.
- Paths are relative to the contract file.
