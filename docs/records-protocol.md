# VibeBB Record Protocol (VRP) v1

Every VibeBB plugin leaves the same three kinds of records in the
workspace, so the reasoning behind a product survives the session that
produced it and every sister plugin (and the UX producer) can read it the same
way. This file is the canonical specification; `wire-agent` holds the
reference implementation and the other plugins copy the shared hook
files byte-for-byte (locked by `scripts/check_shared_hooks.py`).

## Logs

All logs are append-only JSONL under `observations/<plugin>/` in the
workspace (`records_dir` in `plugins/<plugin>/hooks/records-policy.json`).

| File | Kind | Written when |
|---|---|---|
| `decisions.jsonl` | `decision` | every non-trivial design choice, without being asked |
| `impressions.jsonl` | `stage_impression` | at the end of every stage, after the final regeneration |
| `vision-reviews.jsonl` | `vision_review` | every time the model looks at an image |
| `vision-tool-events.jsonl` | (hook) | `inspect_image_with_vision` answers, written by `record_vision_tool_event.py` |
| `image-observations.jsonl` | (hook) | images returned by plugin tools, written by `record_image_observation.py` |
| `records-status.json` | (hook) | last Stop-hook verdict and the list of records still owed |
| `.sessions/<session>.json` | (hook) | session start time and Stop refusal count |

Every record carries the envelope `schema_version` (1), `kind`,
`plugin`, `sequence` (1-based line number), `event_id` (sha256 of the
canonical record identity) and `recorded_at` (ISO-8601 with timezone).
Paths are workspace-relative; the writer rejects paths outside the
workspace or through symlinks.

## Decision

| Field | Rule |
|---|---|
| `id`, `stage` | lowercase slug |
| `question` | ≥ 10 characters |
| `principles[]` | ≥ 1 entry, each ≥ 12 characters: the first principle, physical law or standard the choice rests on |
| `options[]` | ≥ 2, unique `name`, each with ≥ 1 `pros` and ≥ 1 `cons` |
| `chosen` | one of the option names |
| `rationale` | ≥ 200 characters |
| `evidence[]` | ≥ 1; `{path, sha256}` (hashed by the writer; directories hash as a tree) or `{reference}` (datasheet, standard, measurement) |
| `assumptions[]`, `unknowns[]` | lists (empty only when truly none) |
| `risks[]` | ≥ 1 residual risk of the chosen option |
| `revisit_when` | the observation that would reopen the decision |
| `decided_by` | `agent` or `user` (a user trade-off answer is recorded as `user`) |

## Stage impression

`stage` (slug), `artifacts[]` (`{path, sha256}`, ≥ 1; files or
directories) and `impression`.

## Vision review

`image_path` + `image_sha256` (hashed by the writer) or
`source_event_id` (the `event_id` of a vision tool event or image
observation), `model`, `checklist` (slug), `findings[]`
(`{category, severity: info|warning|error, note}`) and `impression`.

## Impression rule

An impression is a long-form reading, not a status line: at least 400
characters and 3 sentences (`。！？` always end a sentence; `.!?` only when
followed by whitespace or the end, so `3.3 V` is not a sentence end), with
at least 3 distinct sentences. It should say what was noticed, what works,
what worries the reader, how a maker or user would read the result, and
what to do next. For drawings it judges accuracy, ambiguity and whether
the design intent reaches the shop floor — not only legibility.

## Enforcement

`hooks/scripts/require_records.py` runs on `session_start` (writes the
session marker) and first on `stop`. At Stop it lists everything this
session still owes:

- a vision tool event or viewed image (deduplicated by sha256) without a
  `vision_review` bound to it;
- an artifact matching `artifact_globs` (minus `ignore_globs`) modified
  since the session started that no fresh `stage_impression` covers — an
  impression is fresh only while its recorded sha256 equals the current
  file or tree;
- changed artifacts but no `decision` recorded this session;
- any malformed or invalid record line this session.

If anything is owed, the hook returns exit 2 with
`{"decision": "deny", "reason", "additionalContext"}` so the SDK keeps the
agent running with the list as feedback. After `max_stop_denials`
refusals (default 2) it allows the stop with a warning telling the agent
to report the gaps to the user. Every verdict is written to
`records-status.json`. Hook errors never block.

Records are advisory evidence (L2). They never change a deterministic
gate verdict, and results need not be identical between runs — the
reasoning must be recorded every run.

## Writers

- MCP: `<plugin>_record_decision`, `<plugin>_record_impression`,
  `<plugin>_record_vision_review`, `<plugin>_records_status`. The input
  schemas are the Pydantic models in `src/<package>/records.py`.
- CLI: `python -m <package> record decision|impression|vision-review --json <file>`
  and `record status`.
- `protect_generated.py` blocks direct edits to the logs so every line
  goes through the validated writer; the Stop hook re-validates anyway
  with the stdlib mirror in `hooks/scripts/_records.py`.

## Porting checklist (per plugin)

1. Copy `hooks/scripts/_records.py` and `require_records.py` unchanged;
   add both to `EXPECTED`/`REQUIRED` in `scripts/check_shared_hooks.py`.
2. Write `hooks/records-policy.json` with the plugin's artifact globs and
   a `record_hint` naming its MCP tools.
3. Register `require_records.py session-start` in `session_start` and
   `require_records.py stop` first in `stop` in `hooks/hooks.json`.
4. Copy `src/wire/records.py` as `src/<package>/records.py`, changing only
   `PLUGIN` and the `plugin` literal; expose the four MCP tools and the
   `record` CLI subcommand.
5. Add the "Records you must leave" section to every agent and the main
   workflow skill, and the log names to `protect_generated.py`.
6. Port `tests/test_records.py`.
