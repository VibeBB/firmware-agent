# Commands

Every command prints a JSON payload; exit code is `0` only when
`verdict` is `pass` (`firmware doctor --warn` always exits 0). Slash
commands in `plugins/firmware/commands/` run the same CLI through the
launcher.

## CLI subcommands (`python -m firmware`)

| command | arguments | what it does |
| --- | --- | --- |
| `doctor` | `--warn` | probe the toolchain; `--warn` always exits 0 |
| `validate` | `contract` | parse `<name>.fw.json`, resolve the MCU profile |
| `check` | `contract` `[--out dir]` | static gates only; writes report + pin map projections and PNGs |
| `gates` | `contract` `[--out dir]` | all gates incl. build, memory budget, cppcheck, QEMU sims |
| `pins` | `contract` | regenerate `build.pins_header` (`fw_pins.h`) |
| `cues` | `contract` | regenerate `cues.header` (`fw_cues.h`) from the pinned bard `cues.json`; fails when the manifest hash differs from `cues.sha256` |
| `ftm` | `contract` | regenerate `ftm.header` (`fw_ftm.h`) from the pinned prodeng `factory-test-spec.json`; fails when the spec hash differs from `ftm.sha256` |
| `production` | `contract` `[--out dir]` | export `<name>.fw-production.json` (ELF sha256/size, contract/report sha256, MCU, factory test spec) from the last passing full gate run; never flashes hardware |
| `pinmap` | `contract` `[--out dir]` | export `<name>.fw-pinmap.json` + `*.pinmap.md`/`*.pinmap.png` |
| `sim` | `contract` `--id <sim>` `[--out dir]` | run one declared QEMU simulation; writes `sim-<id>.log`/`sim-<id>.png` |
| `debug` | `contract` `--id <sim>` `[--elf f] [--break b] [--print e] [--out dir]` | scripted GDB session → `debug-<id>.advisory.json` (advisory) |
| `request` | `contract` `--target t --risk low|high --change c --rationale r [--net n] [--failing-check g] [--decision-ref id] [--out dir]` | write `*.fw-request.json` v2; high risk needs a decision ref |
| `profile` | `id` | print a bundled MCU profile (`esp32s3`, `rp2040`) |
| `record` | `decision|impression|vision-review|status` `--json <file>` | append a VRP record or print records status |
| `render` | `contract` `[--out dir] [--view pinmap|report|sim]` | render PNGs; `report` reruns static gates, `sim` re-evaluates `sim-*.log` and never runs QEMU |
| `ux` | `inbox|respond` `[--workspace dir] [--json <file>]` | SLP v2: inbox lists requests; respond writes `<id>.ux-response.json` (fields in the JSON file) |

## Plugin commands (`/firmware:*`)

`plugins/firmware/commands/` mirrors the CLI:

- `doctor.md` — `/firmware:doctor`, toolchain probe.
- `design.md` — `/firmware:design`, contract design flow.
- `gates.md` — `/firmware:gates`, full gate run.
- `pinmap.md` — `/firmware:pinmap`, pin map export.
- `simulate.md` — `/firmware:simulate`, one QEMU sim.
- `debug.md` — `/firmware:debug`, advisory GDB.
- `render.md` — `/firmware:render`, PNG views + vision review hint.
- `liaison.md` — `/firmware:liaison`, ux-creator inbox/respond.
