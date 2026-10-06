# Hooks

`plugins/firmware/hooks/hooks.json`. Failure modes are listed per hook;
every command resolves the plugin root the same way
(`$FIRMWARE_PLUGIN_ROOT`, `$OPENHANDS_PROJECT_DIR/plugins/firmware`,
`~/.agents/plugins/firmware`, `~/.openhands/plugins/installed/firmware`).

| event | matcher | name | script | behavior |
| --- | --- | --- | --- | --- |
| session_start | `*` | `firmware-doctor` | `firmware_launcher.py doctor --warn` | toolchain probe; always exit 0, prints the payload |
| session_start | `*` | `intake-attachments` | `intake_attachments.py` | materialize user-attached images under `intake/attachments/` + `manifest.jsonl` |
| session_start | `*` | `ensure-llm-profiles` | `ensure_llm_profiles.py` (shared, byte-equal) | provision LLM profile config |
| session_start | `*` | `require-records` | `require_records.py session-start` (shared) | seed the records session ledger |
| user_prompt_submit | `*` | `intake-attachments` | `intake_attachments.py` | pick up attachments sent mid-session |
| pre_tool_use | `file_editor\|apply_patch\|terminal` | `protect-generated` | `protect_generated.py` | deny writes to generated artifacts (`fw_pins.h`, `*.fw-pinmap.json`, `*.fw-power.json`, `*.pinmap.*`, `*.fw-report.*`, `sim-*.{log,png}`, `debug-*.advisory.json`, `*.ux-response.json`, `observations/firmware/*`, `intake/attachments/manifest.jsonl`); exit 2 = deny |
| pre_tool_use | `terminal` | `safety-rail` | `safety_rail.py` (shared, byte-equal) | block dangerous shell commands |
| stop | `*` | `require-records` | `require_records.py` (shared) | refuse to finish while VRP records are owed (`records-policy.json`, `max_stop_denials` 2) |
| stop | `*` | `report-firmware-status` | `report_firmware_status.py` | print the session's firmware status |
| stop | `*` | `intake-attachments` | `intake_attachments.py` | final attachment sweep |
| post_tool_use | `inspect_image_with_vision` | `record-vision-tool-event` | `record_vision_tool_event.py` | log each vision call to the session ledger (vision reviews bind via `source_event_id`) |
| post_tool_use | `file_editor\|firmware_render\|firmware_gates\|firmware_check\|firmware_pinmap_export\|firmware_sim` | `record-image-observation` | `record_image_observation.py` | log every image path an observed tool touched/viewed |

`ensure_llm_profiles.py`, `safety_rail.py`, `_records.py` and
`require_records.py` are canonical across the plugin family;
`scripts/check_shared_hooks.py` locks their normalized-AST sha256.
`intake_attachments.py` and the `record_*` hooks are firmware-specific.
