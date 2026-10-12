# Contracts and artifacts

Every model is a strict pydantic model (`extra="forbid"`); JSON files are
the family interchange format. `<name>.fw.json` is the source of truth;
everything else is generated or exchanged.

## `firmware_contract` — `<name>.fw.json` (schema_version 1)

`contract.py::FirmwareContract`:

- `name`, `description`
- `mcu`: `profile` (bundled id), `ref` (schematic ref, e.g. `U1`),
  optional `flash_kb`, `ram_kb`, `clock_mhz`
- `circuit.connectivity`: path to `<design>.firmware.json`
- `pins[]`: `signal`, `pad`, `net`, `function`, `peripheral?`,
  `package_pin?`, `pull` (none/up/down), `active` (high/low), `initial?`
  (gpio_out/pwm only), `acknowledge[]` (strapping/jtag), `rationale`
- `peripherals[]`: `id`, `kind`, `instance`, `frequency_hz?`, `baud?`,
  `rationale`
- `power`: `supply_net`, `average_budget_ua?`, `modes[]`
  (`id`, `kind` run/idle/sleep/deep_sleep, `current_ua`, `duty`,
  `wake[]`, `peripherals_on[]`)
- `build` (extends `BuildStep`): `backend` make/cmake/platformio, `dir`,
  `target?`, `env?` (platformio only, required there), `elf`,
  `timeout_s` (≤7200), `pins_header`, `budget` (`flash_pct`, `ram_pct`)
- `analysis`: `tool` cppcheck, `std`, `sources[]`, `includes[]`,
  `defines[]`, `fail_on[]`, `suppressions[]` (`id`, `file?`, `line?`,
  `rationale`)
- `cues?`: `manifest` (path to bard `cues.json`), `sha256` (pinned
  manifest hash), `pin` (a `pwm` pin signal), `header` (generated
  `fw_cues.h`), `min_hz` < `max_hz` (transducer band), `rationale`
- `fpga?`: `regmap` (path to fpga-agent `<design>.fpga-regmap.json`),
  `sha256` (pinned register-map hash), `peripheral` (the declared spi/i2c/
  uart peripheral that reaches the FPGA; its kind must equal the map's
  `bus`), `header` (generated `fw_fpga_regs.h`), `rationale`
- `ftm?`: `spec` (path to production-engineering `factory-test-spec.json`),
  `sha256` (pinned spec hash), `header` (generated `fw_ftm.h`),
  `peripheral?` (the uart/usb/i2c/spi peripheral carrying the factory
  transport; omitted for swd/jtag), `rationale`
- `security?`: `sdkconfig` (contract-relative ESP-IDF
  `sdkconfig.defaults`), `secure_boot`, `flash_encryption`,
  `ota_rollback`, `jtag_disabled`, `rationale`. Gate `fw.security`
  requires `CONFIG_SECURE_BOOT`+`CONFIG_SECURE_BOOT_V2_ENABLED` and forbids
  `CONFIG_SECURE_BOOT_INSECURE` (secure boot); requires
  `CONFIG_SECURE_FLASH_ENC_ENABLED` + release mode and forbids development
  mode (flash encryption); requires `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE`
  and partition subtypes `ota` (otadata), `ota_0` and `ota_1` from the built-in two-OTA table
  or the custom CSV (OTA rollback); forbids the JTAG-allow options (JTAG
  lock). An unreadable file or a missing setting fails
- `components[]`: `name` (unique), `version`, `supplier`, `license`
  (SPDX expression), `source` (VCS URL), `paths[]` (contract-relative files
  or directories compiled into the image). Gate `fw.sbom` fails when a path
  is missing or when a file under a vendored-code directory of the build
  tree (`lib`, `libs`, `third_party`, `vendor`, `external`, `components`,
  `Drivers`, `Middlewares`; hidden, `build` and `out` directories skipped)
  is not covered by a declared component
- `faults[]`: `code` (1–65535, unique; 0 is reserved for "no fault"),
  `name` (identifier, unique), `severity` (`info`/`warning`/`error`/
  `critical`), `action` (what the user or service technician does). The
  firmware owns this table; dashboard-agent pins the contract
  (`device.firmware_sha256`) and decodes a status field through it in a
  `fault` widget
- `unit_tests?`: host C unit tests of product code — `sources[]` (measured
  product files), `tests[]` (test files holding `main()`, disjoint from
  `sources`), `includes[]`, `defines[]`, `std` (c99/c11/c17),
  `min_line_pct`, `min_branch_pct` (0–100), `timeout_s` (≤1800),
  `rationale`. Gate `fw.unit_coverage` compiles every file with host
  `gcc --coverage -O0`, links and runs the binary (non-zero exit fails),
  then reads `gcov --json-format` line (C0) and branch (C1) coverage of
  `sources` only; a floor miss, compile/link error, timeout or unreadable
  gcov output fails. Logs go to `<out>/unit-tests.log`
- `simulations[]`: `id`, `runner` (qemu-arm needs `exit_code`, qemu-esp
  forbids it), `machine`, `fidelity` (mcu/core), `image`, `build?`,
  `expect[]`, `forbid[]`, `exit_code?`, `timeout_s` (≤600)
- `flow?`: the program structure as an HCP chart (`hcp.py::HcpFlow`,
  ADR-0013) — `header` (`title`/`author`/`date`/`version`) and
  `modules[]` (`name`, `data[]`, `items[]` with `kind`
  process/repeat/fork/branch/true/false/return/ec/ex/mod, `label`,
  `data_in[]`/`data_out[]`, `levels` for `return`, `refs`
  (pins/peripherals/power_modes/simulations), nested `children[]`).
  Gates `fw.hcp` (structure + `refs` resolution + DSL round-trip) and
  `fw.hcp_lint` (notation quality) run when the section exists;
  projections `<name>.hcp`, `.hcp.svg`, `.hcp.png`, `.hcp-lint.json`.

## `hcp_chart` — `<name>.hcp.json` (schema_version 1)

`hcp.py::HcpChart`: standalone HCP chart sharing the flow model
(`name`, `description`, `header`, `modules[]`) for charts not bound to
a firmware contract. `firmware hcp <chart>` validates it; without a
contract there are no `refs` to resolve.

## `mcu_profile` — `src/firmware/profiles/<id>.json`

`profiles::McuProfile`: `part`, `package`, `io_voltage_max_v`,
`flash_bytes`, `ram_bytes`, `pads[]` (`name`, `aliases`, `package_pin`,
`functions[]`, `reserved` power/flash/debug/clock/reset/test,
`caution` strapping/jtag). Bundled: `esp32s3`, `rp2040`.

## `circuit_firmware_connectivity` — `<design>.firmware.json` (schema 1)

`interchange.py`, produced by electrical-circuit-agent: `design`,
`source` (brief/netlist), `brief_sha256`, `netlist_sha256?`,
`mcus[]` (`ref`, `lib_id`, `value?`, `footprint`,
`pins[]`:`pin`, `function?`, `net?`, `signal_class?`, `voltage_v?`).

## `bard_cue_manifest` — bard `cues.json` (schema 0.1)

`interchange.py::BardCueManifest` reads bard-agent's rendered manifest
strictly (`authority: none`): `product`, `device` (piezo/speaker),
`cues[]` (`id`, `purpose`, `ux_feedback`, `loop`, `bpm`, `program`,
`duration_ms`, `mid`/`mml` file refs, `tones[]` of `start_ms`,
`duration_ms`, `midi` or null for a rest, `freq_hz`), `artifacts[]`, and
the optional advisory `accessibility` / `audibility` reports, which are
carried through unread.

## `firmware_gate_report` — `<design>.fw-report.json` (schema 1)

`gates.py::GateReport`: `design`, `scope` (static/full),
`contract_sha256`, `circuit_sha256?`, `profile?`, `verdict`,
`checks[]` (`id`, `subject`, `status` pass/fail/not_applicable,
`detail`, `evidence[]`), `metrics` (floats: `average_ua`,
`average_budget_ua`, `flash_bytes`, `flash_capacity_bytes`,
`flash_budget_bytes`, `ram_*`).

## `firmware_pinmap` — `<name>.fw-pinmap.json` (schema 1)

For `circuit firmware-check`: `design`, `contract_sha256`, `mcu_ref`,
`mcu_profile`, `mcu_part`, `io_voltage_max_v`, `supply_net`,
`pins[]` (`signal`, `pad`, `pad_aliases`, `package_pin`, `net`,
`function`, `peripheral`), `free_pads[]` (`pad`, `pad_aliases`,
`package_pin`).

## `firmware_power` — `<name>.fw-power.json` (schema 1)

`interchange.py::FirmwarePower`, for simulation-agent PDN imports:
`design`, `contract_sha256`, `mcu_ref`, `supply_net`, `peak_current_a`
(largest authored mode current), `average_current_a` (duty-weighted),
`modes[]` (`id`, `kind`, `current_a`, `duty`). Currents are the authored
`current_ua` values in amperes; nothing is estimated.

## `prodeng_ftm_spec` — prodeng `factory-test-spec.json`

`interchange.py::ProdengFtmSpec` mirrors production-engineering's
generated spec with `declared: true`: `entry` (`method`, `detail`,
`conditions[]`), `field_lockout`, `interface` (`transport`, `settings`,
`nets[]`), `commands[]` (`id` `TC-NN`, `name`, `request`,
`response_pattern`, `timeout_ms`, `measures_nets[]`, `covers[]`,
`destructive`), `provisioning[]`, `exit`, `max_duration_s`,
`command_timeout_budget_s`. A spec with `declared: false` or extra keys
is unreadable.

## `firmware_production` — `<name>.fw-production.json` (schema 1)

`interchange.py::FirmwareProduction`, for production-engineering
programming operations: `design`, `contract_sha256`,
`gate_report_sha256`, `mcu_ref`, `mcu_profile`, `part`, `package`, `elf`
(relative to the artifact), `elf_sha256`, `elf_bytes`, `ftm_spec_sha256`
(`null` without an `ftm` link), `ftm_commands[]`. Written only when the
last gate report is a passing full run for the current contract and the
ELF still hashes to the report's `elf_sha256`.

## CycloneDX SBOM — `<name>.fw-sbom.cdx.json`

`sbom.py::cyclonedx`: CycloneDX 1.5 JSON without timestamp or serial
number, so it is byte-stable. `metadata.component` is the firmware
(`contract` SHA-256, MCU profile); `components[]` are the declared
components sorted by name with `licenses[].expression`, `supplier`,
`externalReferences` (vcs) and one SHA-256 per path — a file hash, or for
a directory the hash of its sorted `relative-path NUL file-sha256` lines.

## `fw_request` v2 — `<design>.<id>.fw-request.json` (schema 2)

`requests.py::FirmwareRequest`: `id`, `design`,
`target` (circuit/mech/wire/ux/bard/doc/prodeng/sim/fpga/dashboard),
`risk`, `change`, `rationale`, `nets[]`, `failing_checks[]`,
`inputs[]` (`HashedPath`: workspace-relative POSIX `path` + `sha256`;
contract always included, connectivity when resolvable),
`decision_refs[]` (must exist in `decisions.jsonl`; high risk needs ≥1),
`contract_sha256`.

## SLP v2 — `liaison/<id>.ux-{request,response}.json` (schema 2)

`liaison.py` (strict local mirror of ux-creator):
`UxRequest`: `id`, `target_agent`, `stage`, `risk`, `purpose`,
`rationale`, `requested_changes[]`, `inputs[]` (HashedPath),
`expected_deliverables[]`, `acceptance[]`, `depends_on[]`, `created_at`;
high risk requires a snake_case job id in `rationale` (local heuristic).
`UxResponse`: `request`, `responder`, `status`
(accepted/in_progress/done/rejected/deferred/needs_info), `reason`
(≥20 chars unless accepted/in_progress), `input_hashes`,
`artifacts[]`, `gate_verdicts[]` (pass/fail/unknown), `decision_refs[]`,
`impression_refs[]`, `questions_for_user[]`, `responded_at`;
`done` needs no fail/unknown verdict, ≥1 verdict and ≥1 artifact.

## `debug-*.advisory.json`

`debug.py::DebugSession`: `authority: "advisory"`, `simulation`, `ok`,
`detail`, `qemu_argv`, `gdb_argv`, `stops[]` (`where`, `output`),
`transcript`. Advisory evidence only; never changes a verdict.

## VRP records — `observations/firmware/*.jsonl`

`decisions.jsonl`, `impressions.jsonl`, `vision-reviews.jsonl`,
`reconciles.jsonl`, `insights.jsonl`, `reads.jsonl`, `song-receipts.jsonl` —
VRP v2, hash-chained and append-only, each event carrying an `event_id` used as
`decision_refs`/`impression_refs`. See
[records-protocol.md](records-protocol.md).

## `records-policy.json`

`plugins/firmware/hooks/records-policy.json`: `records_dir`
`observations/firmware`, `artifact_globs` (fw.json, fw_pins.h,
pinmap/report JSON+MD+PNG, fw-request, sim log/png, debug advisory),
`ignore_globs` (examples/, tests/, .devin/, **/.pio/),
`max_stop_denials` 2, `record_hint`. Liaison files are deliberately not
artifact_globs.

## `fpga_regmap` — fpga-agent `<design>.fpga-regmap.json` (read-only mirror)

`interchange.py::FpgaRegmapSource` mirrors fpga-agent's export without
importing it: `design`, `contract_sha256`, `device_ref`, `bus`
(spi/i2c/uart), `i2c_address` (required for i2c only), `data_width`
(8/16/32), `address_width`, `registers[]` (`name`, `offset`, `access`
ro/rw/wo/w1c, `reset`, `description`, `fields[]` of `name`, `lsb`, `width`,
`mask`, `access`, `description`). The mirror re-checks the layout: offsets
unique and ascending inside `address_width`, resets inside `data_width`,
each `mask` equal to its `lsb`/`width`, and no overlapping fields.
