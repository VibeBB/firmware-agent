# Development

## Setup

```bash
uv sync --locked          # uv per pyproject required-version
```

## Verify

```bash
uv run ruff check . && uv run ruff format --check .
uv run pyright
uv run pytest
uv run python scripts/check_plugin_load.py
uv run python scripts/verify_docs.py
uv run python scripts/check_shared_hooks.py
uv run --group sdk-check python scripts/check_plugin_load.py
```

pytest runs under
`env -u BASH_ENV -u "BASH_FUNC_gh%%" uv run pytest ...`.
The `e2e` CI job builds `docker/firmware-tools.Dockerfile` and runs the
full gates for both examples inside it with `--network none`.

## Layout

- `src/firmware/` — the Python package (see
  [architecture.md](architecture.md)); pydantic models are strict
  (`extra="forbid"`), pyright-strict, ruff-formatted.
- `tests/` — pytest files mirroring modules (`test_render.py`,
  `test_liaison.py`, `test_requests.py`, `test_records.py`,
  `test_docs_coverage.py`, ...); `test_plugin.py` asserts the MCP tool
  list, plugin load and launcher behavior.
- `plugins/firmware/` — agents, commands, skills, hooks, launcher.

## Adding an MCU profile

Drop `<id>.json` under `src/firmware/profiles/` matching `McuProfile`
(pads with `functions`, `aliases`, `package_pin`, `reserved`,
`caution`; `part`, `package`, `io_voltage_max_v`, memory sizes), then
reference it from `mcu.profile` in a contract.

## Adding a gate

Write a `Check` in `gates.py` (`_check` helper: any problem string fails
closed), wire it into `run_gates`, give it an `fw.*` id and add it to
the report renders/tests.

## Adding an MCP tool

Add the `TOOLS` entry (description, JSON schema, read-only flag), a
`dispatch` handler calling a `service.*_payload` function, the CLI
subcommand if needed, the `test_mcp_tools_registered` expectation and
the docs ([mcp.md](mcp.md)).

## Shared hooks and workflows

`ensure_llm_profiles.py`, `safety_rail.py`, `_records.py`,
`require_records.py` are byte-equal across the family — change all
copies together and update `EXPECTED` in
`scripts/check_shared_hooks.py`. Shared workflows likewise via
`scripts/check_shared_workflows.py`.

## Release

Digest-lock PRs use `scripts/publish_image_pin_pr.sh`; the release bump
state machine is `scripts/release_bump.sh` with stubbed-`gh` tests.
See [operations.md](operations.md).
