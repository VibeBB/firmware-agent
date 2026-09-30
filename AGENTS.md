# AGENTS.md — VibeBB firmware-agent

Guidance for AI agents and humans working on this repository, the
firmware sibling in the VibeBB OpenHands plugin family.

## Authoring rules

- Executable logic is Python 3.12 under `src/firmware/` (stdlib +
  pydantic v2 + mcp). Agents, commands and skills under
  `plugins/firmware/` are Markdown and delegate every step to
  `python -m firmware` through `plugins/firmware/scripts/firmware_launcher.py`.
- The contract `<name>.fw.json` is the source of truth. `fw_pins.h`,
  `*.fw-pinmap.json`, `*.pinmap.md`, `*.fw-report.*`, `sim-*.log`,
  `debug-*.advisory.json`, `observations/firmware/*.jsonl` and
  `intake/attachments/manifest.jsonl` are generated; never edit them by hand.
- Gates fail closed: missing tools, files or unparseable output are
  failures. GDB output is advisory and never changes a verdict.
- Sibling cooperation is JSON artifacts in the workspace; never import a
  sibling's code and never edit a sibling's inputs (write a
  `fw_request`).
- External tools run as subprocesses. Do not import GPL/AGPL code.
  Downloaded tools are pinned by version and sha256 and listed in
  `THIRD_PARTY_NOTICES.md`.
- `ensure_llm_profiles.py` and `safety_rail.py` are canonical across the
  plugin family; `_provenance.py` is canonical where present and intentionally
  absent from UX and Production Engineering. Change copies together and update
  `EXPECTED` in `scripts/check_shared_hooks.py`.
  `intake_attachments.py` and `record_*` hooks are intentionally repo-specific.
- New dependencies or tools need an ADR under `docs/adr/`.

## Voice and commit policy

- Code, comments, docs, commit messages and PR text are English.
- Commit style: `feat(scope): imperative summary`, max 72 chars.
- PRs follow `.github/PULL_REQUEST_TEMPLATE.md`.

## Verification

```bash
uv sync --locked
uv run ruff check . && uv run ruff format --check .
uv run pyright
uv run pytest
uv run python scripts/check_plugin_load.py
uv run python scripts/verify_docs.py
```

The `e2e` CI job builds `docker/firmware-tools.Dockerfile` and runs the
full gates for both examples inside it with `--network none`.
