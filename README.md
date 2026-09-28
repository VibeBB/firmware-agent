# firmware-agent

VibeBB firmware plugin for OpenHands (AgentCanvas). It designs and verifies
microcontroller firmware together with the sibling plugins
(`electrical-circuit-agent`, `mechanical-agent`, `wire-agent`,
`UX-creator-agent`, `bard-agent`, `document-agent`).

A firmware contract `<name>.fw.json` declares the MCU, pin map, peripherals
and power modes. Deterministic gates decide whether the design and the
code are acceptable:

| gate | checks |
| --- | --- |
| `fw.contract` | contract schema, MCU profile, circuit export readable |
| `fw.pin_functions` | pad exists, not reserved, routes the function and peripheral instance; strapping/JTAG pads acknowledged |
| `fw.netlist_match` | every pad is on the declared circuit net of the declared MCU; no active pad unassigned; voltage and supply net |
| `fw.power_modes` | duty cycle, wake sources, powered peripherals, average-current budget |
| `fw.pins_header` | generated pin header matches the contract |
| `fw.build` | make / CMake / PlatformIO build succeeds and produces the ELF |
| `fw.memory_budget` | flash and RAM from ELF segments within budget |
| `fw.static_analysis` | cppcheck with no blocking finding |
| `fw.sim.<id>` | QEMU run prints the expected UART lines (ARM core fidelity or Espressif ESP32/ESP32-S3) |

`firmware debug` attaches GDB to a QEMU run and records breakpoints,
backtraces, registers and expressions as advisory evidence.

## Layout

- `src/firmware/` — contract models, MCU profiles, gates, CLI, MCP server.
- `plugins/firmware/` — the OpenHands plugin: agents
  (`firmware-architect`, `firmware-developer`, `firmware-review`),
  commands (`doctor`, `design`, `gates`, `pinmap`, `simulate`, `debug`),
  skills, hooks, launcher, `.mcp.json`.
- `examples/smart-kettle/` — RP2040 bare-metal C, Make build, ARM QEMU
  (`mps2-an385`) logic simulation.
- `examples/desk-lamp-s3/` — ESP32-S3 ESP-IDF via PlatformIO, Espressif
  QEMU full-image simulation, circuit export from a KiCad netlist.
- `docker/firmware-tools.Dockerfile` — pinned toolchain image.
- `docs/` — ADRs.

## Quick start

```bash
uv sync --locked
uv run python -m firmware doctor
uv run python -m firmware check examples/smart-kettle/smart-kettle.fw.json
docker build -f docker/firmware-tools.Dockerfile -t firmware-tools:dev .
FIRMWARE_TOOLS_IMAGE=firmware-tools:dev \
  python3 plugins/firmware/scripts/firmware_launcher.py gates examples/desk-lamp-s3/desk-lamp.fw.json
```

CLI: `firmware {doctor,validate,check,gates,pins,pinmap,sim,debug,request,profile}`.
MCP tools: `firmware_doctor`, `firmware_validate`, `firmware_check`,
`firmware_gates`, `firmware_pins`, `firmware_pinmap_export`,
`firmware_sim`, `firmware_debug`, `firmware_request`, `firmware_profile`.

## Circuit cooperation

```bash
# circuit side
python -m circuit firmware-export --brief board.brief.json --netlist board.net --out circuit/
# firmware side
python -m firmware gates board.fw.json
# circuit side confirms the firmware pin map
python -m circuit firmware-check --brief board.brief.json --netlist board.net \
  --pinmap fw-reports/board.fw-pinmap.json
```

## Development

```bash
uv run ruff check . && uv run ruff format --check .
uv run pyright
uv run pytest
uv run python scripts/check_plugin_load.py
uv run python scripts/verify_docs.py
```

## License

BSD-3-Clause. Third-party tools are listed in `THIRD_PARTY_NOTICES.md`.
