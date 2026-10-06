# Architecture

firmware-agent is a Python core (`src/firmware/`, stdlib + pydantic v2 + mcp)
wrapped in an OpenHands plugin (`plugins/firmware/`): agents, commands,
skills and hooks that all delegate to `python -m firmware` through the
launcher.

## Module map (src/firmware/)

| module | responsibility |
| --- | --- |
| `contract.py` | `<name>.fw.json` firmware contract model (MCU, pins, peripherals, power, build, analysis, simulations) + `load_contract`, `resolve` |
| `profiles/` | bundled MCU profiles `esp32s3`, `rp2040` (pads, functions, memory regions, package) + `load_profile` |
| `gates.py` | deterministic gate evaluation: static (`fw.contract`, `fw.pin_functions`, `fw.netlist_match`, `fw.power_modes`, `fw.pins_header`) and toolchain (`fw.build`, `fw.memory_budget`, `fw.static_analysis`, `fw.sim.<id>`); `GateReport` + `metrics`; `write_outputs` |
| `interchange.py` | sister-facing models: `CircuitFirmwareConnectivity` (in), `FirmwarePinmap` (out), `sha256_file` |
| `projections.py` | generated projections: `fw_pins.h`, `*.fw-pinmap.json`, `*.fw-power.json`, `*.pinmap.md`, `*.fw-report.md`; `write_text`/`write_bytes` |
| `render.py` | stdlib PNG renders (Canvas, 5×7 hand-authored font, PNG encoder): `render_pinmap`, `render_report`, `render_sim_timeline`, `render_glyph_sheet` |
| `build.py` | make/CMake/PlatformIO build subprocesses |
| `elf.py` | ELF segment accounting for the memory budget gate |
| `analysis.py` | cppcheck runner and finding parser |
| `sim.py` | QEMU runner (`qemu-arm` / `qemu-esp`), expect/forbid matching, `SimResult` |
| `debug.py` | scripted GDB session on a QEMU run; `debug-*.advisory.json` (advisory only) |
| `doctor.py` | toolchain probes used by `firmware doctor` |
| `liaison.py` | SLP v2 mirror: `UxRequest`/`UxResponse`, `inbox()`, `respond()` |
| `records.py` | VibeBB Record Protocol v1: decisions, impressions, vision reviews, status (JSONL under `observations/firmware/`) |
| `requests.py` | `*.fw-request.json` v2: hashed inputs, decision refs, sister targets |
| `service.py` | one `*_payload` function per CLI command/MCP tool; renders + `vision_review_required` meta; liaison wrappers |
| `mcp_server.py` | MCP stdio server: `TOOLS` schemas, `dispatch`, inline `ImageContent` for image-producing tools |
| `cli.py` | `python -m firmware` argparse front end |
| `workspace.py` | workspace root (`OPENHANDS_PROJECT_DIR` or cwd), path resolution, symlink rejection |

## Data flow

```
product brief / liaison request
  -> circuit agent's <design>.firmware.json  (interchange.py in)
  -> <name>.fw.json                          (contract.py; source of truth)
  -> static gates                            (gates.py)
  -> projections                             (fw_pins.h, pinmap json/md, report md)
  -> renders                                 (pinmap.png, fw-report.png, sim-*.png)
  -> records                                 (decisions/impressions/vision JSONL)
  -> liaison response / fw-request           (liaison.py, requests.py)
```

## Launcher and tools image

`plugins/firmware/scripts/firmware_launcher.py` resolves a digest-pinned
`firmware-tools` image (`docker/image-digests.json` / `FIRMWARE_TOOLS_IMAGE`)
and runs the CLI or MCP server inside it, mounting the workspace. It is
Docker-only: when no image resolves it prints a fail payload and exits
non-zero (`--warn` keeps doctor exit 0). Prewarm, and
`FIRMWARE_VERIFY_ATTESTATION` attestation verification happen before pulls.

## MCP server

`firmware_mcp` exposes every service payload as a tool (see `docs/mcp.md`).
Image-producing tools attach PNGs as inline `ImageContent` (max 4 images,
each ≤ 4 MiB, overflow listed under `images_skipped`) and mark payloads
with `vision_review_required` + `vision_hint`.
