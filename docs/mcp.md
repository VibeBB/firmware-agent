# MCP tools

`firmware-mcp/<version>` serves `src/firmware/mcp_server.py` over stdio.
Every tool returns a JSON payload as `TextContent`; the image-producing
tools (`firmware_gates`, `firmware_check`, `firmware_pinmap_export`,
`firmware_sim`, `firmware_render`) additionally attach written PNGs as
inline `ImageContent` (max 4 images, each ≤ 4 MiB; the rest are listed
under `images_skipped`) and mark the payload with
`vision_review_required` + `vision_hint`. Unknown tools and exceptions
return `{"verdict": "fail", "detail": ...}` with `isError` set.

| tool | inputs | result / side effects | read-only |
| --- | --- | --- | --- |
| `firmware_doctor` | — | toolchain probe checks | yes |
| `firmware_validate` | `contract_path` | contract + resolved profile | yes |
| `firmware_check` | `contract_path`, `out_dir` | static `GateReport`; writes `*.fw-report.*`, pin map export, `*.pinmap.png`, `*.fw-report.png` | no |
| `firmware_gates` | `contract_path`, `out_dir` | full `GateReport` incl. build/memory/cppcheck/sims; writes all projections, `sim-*.log`/`.png`, PNGs | no |
| `firmware_pins` | `contract_path` | regenerates `fw_pins.h` | no |
| `firmware_cues` | `contract_path` | regenerates `fw_cues.h` from the pinned bard `cues.json` | no |
| `firmware_fpga_regs` | `contract_path` | regenerates `fw_fpga_regs.h` from the pinned fpga `*.fpga-regmap.json` | no |
| `firmware_ftm` | `contract_path` | regenerates `fw_ftm.h` from the pinned prodeng factory test spec | no |
| `firmware_production_export` | `contract_path`, `out_dir` | `<name>.fw-production.json` for production-engineering-agent (gated ELF only) | no |
| `firmware_pinmap_export` | `contract_path`, `out_dir` | `<name>.fw-pinmap.json`, `*.pinmap.md`, `*.pinmap.png` | no |
| `firmware_sim` | `contract_path`, `out_dir`, `simulation` | one QEMU run → `SimResult`, `sim-<id>.log`, `sim-<id>.png` | no |
| `firmware_debug` | `contract_path`, `out_dir`, `simulation`, `elf`, `breaks`, `prints` | `debug-*.advisory.json` (never changes a verdict) | no |
| `firmware_request` | `contract_path`, `out_dir`, `target`, `risk`, `change`, `rationale`, `nets`, `failing_checks`, `decision_refs` | `<design>.<id>.fw-request.json` v2 (hashed inputs; high risk needs a decision ref) | no |
| `firmware_profile` | `profile` | bundled MCU profile JSON | yes |
| `firmware_render` | `contract_path`, `out_dir`, `views[]` (`pinmap`, `report`, `sim`) | renders selected views; report reruns static gates, sim re-evaluates `sim-*.log` (never runs QEMU); `render_errors` on failure | no |
| `firmware_ux_inbox` | `workspace` (opt) | SLP v2 inbox: requests classified `new`/`stale`/`blocked`/`answered`, `malformed[]`, `other_targets`, `open` | yes |
| `firmware_ux_respond` | `request`, `status`, `reason`, `artifacts[]`, `gate_verdicts[{gate,verdict}]` (pass/fail/unknown), `decision_refs[]`, `impression_refs[]`, `questions_for_user[]`, `report_paths[]`, `workspace` (opt) | validates and atomically writes `liaison/<id>.ux-response.json`; `replaced` on re-answer | no |
| `firmware_record_decision` | VRP decision fields | appends to `observations/firmware/decisions.jsonl` | no |
| `firmware_record_impression` | VRP impression fields (≥400 chars, ≥3 sentences) | appends to `impressions.jsonl` | no |
| `firmware_record_vision_review` | VRP vision fields (`image_path` or `source_event_id`) | appends to `vision-reviews.jsonl` | no |
| `firmware_records_status` | — | `records-status.json` summary: artifacts, records present, what is owed | yes |

`--warn`-style advisory paths do not exist on the MCP side: every tool
fails closed.
