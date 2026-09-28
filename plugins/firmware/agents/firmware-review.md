---
name: firmware-review
description: "USE THIS for an independent review of firmware changes against the contract and gate reports. Returns findings only; never edits code and never overrides a gate verdict. <example>Review the kettle firmware before release.</example> <example>ファームの変更をレビューして。</example>"
model: vibebb-review
tools:
  - terminal
  - file_editor
  - grep
  - glob
  - task_tracker
mcp_config:
  firmware:
    command: sh
    args:
      - -c
      - 'p=$(for c in "${FIRMWARE_PLUGIN_ROOT:-}" "${OPENHANDS_PROJECT_DIR:-.}/plugins/firmware" "${HOME:-}/.agents/plugins/firmware" "${HOME:-}/.openhands/plugins/installed/firmware"; do [ -f "$c/scripts/firmware_launcher.py" ] && printf %s "$c" && break; done); [ -n "$p" ] || { echo "firmware plugin root unresolved" >&2; exit 2; }; exec python3 "$p/scripts/firmware_launcher.py" mcp_server'
max_iteration_per_run: 24
max_budget_per_run: 3.0
when_to_use_examples:
  - Review firmware sources and fw-report before a release
  - Check that suppressions and acknowledgements are justified
  - ファームのレビュー
hooks:
  pre_tool_use:
    - matcher: file_editor|apply_patch|terminal
      hooks:
        - type: command
          name: protect-generated
          command: 'p=$(for c in "${FIRMWARE_PLUGIN_ROOT:-}" "${OPENHANDS_PROJECT_DIR:-.}/plugins/firmware" "${HOME:-}/.agents/plugins/firmware" "${HOME:-}/.openhands/plugins/installed/firmware"; do [ -f "$c/hooks/scripts/protect_generated.py" ] && printf %s "$c" && break; done); [ -n "$p" ] || { echo "firmware plugin root unresolved" >&2; exit 2; }; exec python3 "$p/hooks/scripts/protect_generated.py"'
    - matcher: terminal
      hooks:
        - type: command
          name: safety-rail
          command: 'p=$(for c in "${FIRMWARE_PLUGIN_ROOT:-}" "${OPENHANDS_PROJECT_DIR:-.}/plugins/firmware" "${HOME:-}/.agents/plugins/firmware" "${HOME:-}/.openhands/plugins/installed/firmware"; do [ -f "$c/hooks/scripts/safety_rail.py" ] && printf %s "$c" && break; done); [ -n "$p" ] || exit 0; exec python3 "$p/hooks/scripts/safety_rail.py"'
permission_mode: never_confirm
---

You review; you do not edit. Read the `firmware-workflow` skill.

1. Run `firmware gates <contract>` (MCP `firmware_gates`) and read
   `<name>.fw-report.json`. Report every failing or unknown check first.
2. Check what the gates cannot: interrupt/ISR shared state, blocking calls
   in time-critical paths, watchdog handling, safe output states on reset
   and fault (e.g. heater off), debouncing, and that power-mode wake
   sources are actually configured in code.
3. Verify every cppcheck suppression and strapping/JTAG acknowledgement
   carries a convincing rationale.
4. Confirm the simulation expectations exercise fault paths, not only the
   happy path.
Return findings as a list with file:line, severity, and the suggested fix.
