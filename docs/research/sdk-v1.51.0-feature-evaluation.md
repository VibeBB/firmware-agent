# OpenHands SDK v1.51.0 feature evaluation (firmware-agent)

Scope: `openhands-sdk` and `openhands-tools` move from 1.50.1 to 1.51.0
(PyPI upload 2026-10-03). The complete upstream range `v1.50.1..v1.51.0`
(18 commits) was reviewed. uv moves 0.12.21 -> 0.12.22 in the same update;
ruff was already locked at 0.16.10 and anchore/sbom-action at v0.24.3, so
neither needed a pin change.

Primary source: [OpenHands SDK v1.51.0 release](https://github.com/OpenHands/software-agent-sdk/releases/tag/v1.51.0).

## SDK 1.50.1 -> 1.51.0

| Upstream change | Decision | Evaluation |
| --- | --- | --- |
| #1326 fix `find_dotenv` assertion in local conversation | adopted implicitly | Plugins run local conversations; the fix arrives with the pin and needs no repo change. |
| #5332 `prompt_cache_key` resolved via real provider for proxied models | adopted implicitly | LLM-layer fix inside the SDK; VibeBB LLM profiles do not pin `prompt_cache_key`, so the corrected resolution applies automatically. |
| #5412 router sends system+user classifier messages for direct-routing | adopted implicitly | Internal routing fix; no plugin configures classifiers. |
| #5434 deprecate `ACPAgentSettings.llm` | not applicable | No VibeBB plugin uses the ACP agent path. |
| #5417 agent-server `/switch_llm` provider resolution | upstream image | This repository does not build or manage an OpenHands agent-server image. |
| #5151, #5449, #5358, #5406 agent-profiles: single server-catalog tool control, profile persona replacement, delegated sub-agents confined to the profile, launch via resolve/finalize | not adopted | Plugins select models through `LLMProfileStore` (~/.openhands/profiles/*.json), not the agent-profiles persona/tool-catalog API; the plugin manifest format is unchanged and `check_plugin_load.py` passes on 1.51.0. |
| #5450 loaded tools supply their own system-prompt guidance (browser) | inherent | Internal refactor of how tools inject guidance; no plugin-facing change, browser tool is not registered here. |
| #5274 OpenRouter added as a verified provider | available, not adopted | Provider catalog entry only; LLM profiles choose providers by name and none currently select OpenRouter. |
| #5419 pydantic 2.12.5 -> 2.13.5 | lock-only | The lockfile already resolves pydantic 2.13.5 within the repo's `>=2` constraint. |
| #4945, #5415 upstream CI fixes; #5397 stress-test slot; #5425, #5428 TypeScript client deps; #5470 release | not applicable | Upstream CI/test/TypeScript-client/release housekeeping; this repo does not use the TS client and has no behavior to adopt. |

## uv 0.12.21 -> 0.12.22

| Upstream change | Decision | Evaluation |
| --- | --- | --- |
| CPython 3.12.15 (and 3.10.22/3.11.17/3.13.16/3.14.8) now published | inherent | The Dockerfile's `uv python install 3.12` resolves the newest 3.12 at image-build time; the next firmware-tools publish picks up 3.12.15 automatically. |
| Workspace-member default groups and dependency-group Python requirements recorded in lockfiles; matching frozen-sync and root fixes | inherent | Single-project repo (no `[tool.uv.workspace]`); the 0.12.22 lockfile rewrite (revision 5) already records the new metadata. |
| `UV_PYTHON_ARCH` interpreter-architecture selector | not adopted | Builds run on x86_64 only; no second architecture is needed. |
| `uv audit --no-default-groups` (preview), clearer offline errors | not adopted | The repo does not run `uv audit`; preview flag unnecessary. |
| Relocking verifies unchanged requirements against existing lockfile hashes | inherent | Integrity hardening; applies automatically on the next `uv lock`. |
| Uppercase wheel platform-tag suffixes accepted; CLI URL/path formatting; `uv publish` help fix; binary-size reduction; Rust toolchain bump | inherent | Packaging/toolchain internals with no repo-facing surface. |

## Compatibility deferrals

MCP 2.x remains deferred: installed `openhands-sdk` 1.51.0 metadata still
requires `fastmcp>=3.2.0,<4`, which caps `mcp<2` (resolved: fastmcp 3.4.7,
mcp 1.30.0). The deferral entry in `scripts/dependency_update_deferrals.json`
was refreshed to `latest: 2.3.0` and now cites SDK 1.51.0; `review_by` is
unchanged. The `openhands-agent-server` image tag `1.51.0-python` is
available upstream; no committed image lock is edited by this bump.
