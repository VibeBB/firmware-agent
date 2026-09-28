---
name: firmware-power-modes
description: Declaring run/idle/sleep/deep-sleep power modes with current, duty cycle, wake sources and powered peripherals, and the average-current budget gate.
version: 0.1.0
license: BSD-3-Clause
triggers:
  - power mode
  - sleep
  - deep sleep
  - battery life
  - 電源モード
  - 省電力
---

# Power modes

```json
"power": {
  "supply_net": "+3V3",
  "average_budget_ua": 1500,
  "modes": [
    {"id": "heating", "kind": "run", "current_ua": 25000, "duty": 0.02,
     "peripherals_on": ["i2c_temp", "led_pwm", "buzzer_pwm", "water_adc"]},
    {"id": "standby", "kind": "sleep", "current_ua": 900, "duty": 0.88,
     "wake": ["boil_button", "lid_switch"]},
    {"id": "dormant", "kind": "deep_sleep", "current_ua": 180, "duty": 0.1,
     "wake": ["boil_button"]}
  ]
}
```

`fw.power_modes` checks:

- At least one mode has `kind: run`.
- `duty` values sum to 1; the duty-weighted average current is at most
  `average_budget_ua` when a budget is set (reported as evidence either
  way).
- Every `sleep`/`deep_sleep` mode has a wake source. A source is `timer`
  or a `gpio_in` signal; `deep_sleep` pin sources must sit on pads the
  profile marks `wake_deep_sleep`.
- `peripherals_on` names declared peripherals.
- `supply_net` must reach the MCU in the circuit export
  (`fw.netlist_match`).

Current figures are design estimates until bench measurements exist;
record the source (datasheet table, measurement) in the rationale of the
affected pins or in the commit message, and replace estimates with
measured values when evaluation evidence arrives.
