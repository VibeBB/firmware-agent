# OpenHands SDK v1.50.0 feature evaluation (firmware-agent)

Scope: openhands-sdk / openhands-tools 1.49.6 -> 1.50.0 (PyPI upload
2026-09-29), uv 0.12.19 -> 0.12.21, and the Agent Canvas state at the time
of the bump. Every commit in `v1.49.6..v1.50.0` of
OpenHands/software-agent-sdk (25 commits) and both uv releases (0.12.20,
0.12.21) were reviewed. Decisions: **adopted** (repo change in this PR),
**inherent** (arrives with the pin, no repo change), **n/a** (does not
touch this plugin), **deferred** (useful, blocked; revisit trigger given).

## SDK 1.49.6 -> 1.50.0

| Upstream change | Decision | Notes for firmware-agent |
| --- | --- | --- |
| #5345 keep conversations alive when MCP startup fails | inherent | If the `firmware` MCP server fails to start, the conversation continues without `firmware_*` tools instead of ending. `/firmware:doctor` / the firmware-doctor hook report the cause; agents must not claim gate results when `firmware_*` tools are missing. |
| #5309 surface LiteLLM budget denials without retry backoff | inherent | Sub-agent `max_budget_per_run` caps and proxy budget denials now end the run immediately instead of retrying. |
| #5222 refresh-on-401 hook on managed-proxy LLMs (agent-server) | inherent | No agent-server image is built by this repo. |
| #5270 manage optional backend processes for Canvas apps (agent-server) | n/a | The plugin ships no Canvas extension/app backend. |
| #5013 client-owned browser event stream transport | n/a | TypeScript client only. |
| #5361 anyio 4.14.2 (CVE-2026-63374) | inherent | Picked up by the lock refresh. |
| #4967 resolve async response secrets outside the event loop | inherent | |
| #4159 centralize LLM call context | n/a | Internal refactor. |
| #5327 tolerate null `cache_creation_tokens` | inherent | |
| #5238 goal judge prompt split into system + user | n/a | Goal mode is not used. |
| #5143, #5148, #5149, #5241, #5242 condenser keeps the leading system prompt / splits summarization prompt | inherent | Long sub-agent runs keep the agent definition (and its fail-closed rules) after condensation or a hard context reset. |
| #5239 system message prepended to profile pre-flight ping | inherent | `vibebb-*` profile checks behave with system-first providers. |
| #5240 GraySwan analyzer system-first guarantee | n/a | Security analyzer not configured by the plugin. |
| #4322 anyOf `false` branch no longer widened to accept-all | inherent | no firmware tool schema uses a `false` branch; the fix only affects schemas that do. |
| #4656 docstrings for image helper functions | inherent (informs vision design) | Confirms: for a non-vision model the SDK rewrites only images in the latest user message into `inspect_image_with_vision` references; images in tool observations are not delegated. |
| #5328 gate `prompt_cache_key` on provider support | inherent | |
| #5298 aiosqlite 0.22.1 | inherent | |
| #5286 OpenAPI exemption for tool metadata | n/a | |
| #5040, #5313, #4298, #5331, #5374 docs / CI / release | n/a | |

## uv 0.12.19 -> 0.12.21

| Release | Change | Decision |
| --- | --- | --- |
| 0.12.20 | Lockfile reuse when declarations are semantically equivalent; preserve CRLF wheel-script encoding declarations; XDG_CONFIG_DIRS search fix; HTTP cache scheduling change; hash checks for repeated requirements; `uv upgrade` restores pyproject on failure; package exclusion, metadata builds, and shell/requirements/Python/resolver panic fixes | inherent |
| 0.12.20 | Preview: lockfile-normalization, pylock.toml group/path fixes, tool-install-locks dedupe, and workspace metadata path fixes | n/a (preview features not enabled) |
| 0.12.21 | CPython builds use OpenSSL 3.5.9; empty `[manifest]` tables omitted from lockfiles; post-release/pre-release compatibility fix; `uv python pin --rm` global-file fix | inherent |
| 0.12.21 | Preview: `resolution-inputs` | n/a |

## Agent Canvas and community state

| Item | Decision |
| --- | --- |
| Agent Canvas v1.24.0 (2026-09-25) is still the latest release; it was evaluated with the v1.49.6 bump. | no change |
| OpenHands/OpenHands#17822 (open PR): inline previews for created SVG / PNG / PDF / Office artifacts in the chat. | deferred until released; rendered artifacts written with `file_editor create` would then preview inline for humans. |
| software-agent-sdk#5360 / #5367 (open): DeepSeek models have images stripped by `force_string_serializer`. | deferred; do not route `vibebb-review` to a DeepSeek vision model until #5367 ships. |
| software-agent-sdk#5351 (open): `VisionInspectTool` auto-attaches even with `include_default_tools=[]`. | n/a; plugin agents do not rely on disabling default tools. |
| software-agent-sdk#5381 (closed, not planned): a sub-agent's own `mcp_config` is not narrowed to the parent's tools. | noted; sub-agent `mcp_config` here only launches this plugin's own fail-closed server. |
| MCP 2.x / fastmcp 4.x: SDK 1.50.0 still requires `fastmcp>=3.2.0,<4` (and therefore `mcp<2`). | deferred; keep `mcp<2` in `pyproject.toml`. |

## PlatformIO espressif32 6.10.0 -> 7.1.3

| Release | Complete release notes reviewed | Decision for firmware-agent |
| --- | --- | --- |
| 6.11.0 | ESP-IDF 5.4.1, Seeed Xiao ESP32C6, ESP32 ROM ELF package, exception-decoder backtrace improvements, and Freenove ESP32-Wrover OpenOCD config correction | No C6 or Freenove board is used; debugging remains advisory. Later ESP-IDF support supersedes 5.4.1. |
| 6.12.0 | ESP32C6 boards, ESP-IDF 5.5, CMake 3.30, initial Secure Features support | The example uses ESP32-S3 and does not enable Secure Features; later IDF support supersedes 5.5. |
| 6.13.0 | ESP-IDF 5.5.3, toolchain 14.2.0+20251107, esptool 4.11.0, minor fixes | Not selected: 7.1.3 builds and passes the e2e gates after a scoped flash-image helper fix, so 6.13.0 was not needed as the fallback. |
| 7.0.0 | ESP-IDF 6.0, toolchain 15.2.0+20251107, symlink-aware IDF component-directory matching, minor fixes | The newer toolchain is relevant; the symlink fix is not exercised by this project. |
| 7.0.1 | ESP-IDF 6.0.1 | Superseded by ESP-IDF 6.1 in the selected release. |
| 7.1.0 | ESP-IDF 6.1, C++ flag-leak fix, minor fixes | Adopt ESP-IDF 6.1; the scoped flag fix is relevant to the example's strict build flags. |
| 7.1.1 | Reorganized upstream examples for CI compatibility | No firmware-agent source or configuration change is needed. |
| 7.1.2 | Binary-file generation refactor for compatibility with the latest PlatformIO Core, minor fixes | PlatformIO Core 6.2.0 is already current; validate the new packaging path in the image build. |
| 7.1.3 | Corrected build flags being applied to the wrong compiler scope | Adopt; this directly addresses how the example's `-Wall -Wextra -Werror` flags are applied. |

PlatformIO Core 6.2.0 is already current, Arduino remains 2.0.17 across
these platform releases, and the firmware example uses ESP-IDF rather than
Arduino. Espressif QEMU `esp-develop-9.2.2-20260417` remains the latest
release and is unchanged. The Ubuntu 24.04 index digest was resolved via
`mirror.gcr.io`; it is unchanged at
`sha256:008173c23f95b170204355c12626cb5a965d779a7e1283b09e9cffbb1bf33ca3`.
The fresh `7.1.3` install resolves both `toolchain-xtensa-esp-elf` and
`toolchain-riscv32-esp` at `15.2.0+20251204` (newer than the
`15.2.0+20251107` first recorded in the 7.0.0 release notes), ESP-IDF
6.1.0, and esptool 4.11.0.

## Verification

- `UV_NO_CONFIG=1 uv lock --upgrade` resolved six environments. Package
  updates: `blake3` 1.0.9 -> 1.0.10; `boto3` 1.43.103 -> 1.43.105;
  `botocore` 1.43.103 -> 1.43.105; `charset-normalizer` 3.5.1 -> 3.5.2;
  `cryptography` 50.0.1 -> 50.0.2; `cyclopts` 5.0.0 -> 5.1.0;
  `filelock` 4.0.5 -> 4.0.7; `google-api-core` 2.39.0 -> 2.40.0;
  `google-auth` 2.58.1 -> 2.59.0; `google-auth-httplib2` 0.4.2 -> 0.4.3;
  `google-auth-oauthlib` 1.4.1 -> 1.5.0; `googleapis-common-protos`
  1.75.4 -> 1.75.5; `litellm` 1.103.0 -> 1.103.1; `ollama` 0.6.2 ->
  0.6.3; `openhands-sdk` 1.49.6 -> 1.50.0; `openhands-tools` 1.49.6 ->
  1.50.0; `platformdirs` 4.12.1 -> 4.12.2; `posthog` 7.60.1 -> 7.61.0;
  `proto-plus` 1.28.4 -> 1.29.0; `pyjwt` 2.15.0 -> 2.15.1;
  `regex` 2026.9.10 -> 2026.9.29; `sse-starlette` 3.4.11 -> 3.5.0.
  `uv sync --locked` and `uv sync --locked --group sdk-check` passed.
  AnyIO remains 4.15.1 and runtime MCP is 1.30.0 (`mcp>=1.29,<2`).
- `ruff check .`, `ruff format --check .` (58 files), `pyright` (0 errors,
  warnings, or informations), and `pytest -q` (62 passed) passed.
- `uv run --group sdk-check python scripts/check_plugin_load.py` and
  `uv run python scripts/verify_docs.py` passed.
- The first Docker Hub base-image metadata request returned HTTP 429. The
  fresh `firmware-tools:dev` build passed using
  `mirror.gcr.io/library/ubuntu:24.04` with the unchanged pinned digest.
  The first PlatformIO 7.1.3 build reached the example's `merge_flash.py`
  callback and failed with `TypeError: expected str, bytes or os.PathLike
  object, not int` in `subprocess.run`. The example now stringifies all
  SCons-substituted command arguments. The rebuilt image's ESP32-S3 warm
  build passed with ESP-IDF 6.1.0, esptool 4.11.0, and toolchain
  15.2.0+20251204.
- The CI e2e launcher loop passed with its container `--network none`:
  both example verdicts passed all contract, pin, netlist, power, build,
  memory, static-analysis, and QEMU checks; the desk-lamp GDB self-test
  stopped at `lamp_step` with a passing advisory result.
- No `6.10.0` references remain under `src/firmware/` or `tests/`.
- Full command output: `/home/ubuntu/work/verify/firmware-deps.log`.
