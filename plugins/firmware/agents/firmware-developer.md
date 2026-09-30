---
name: firmware-developer
description: "USE THIS to implement and debug firmware against a passing contract: write drivers and application code, keep the build, flash/RAM budget, static analysis and QEMU simulation gates green, and debug with GDB on QEMU. <example>Implement the heater state machine and make fw.sim pass.</example> <example>QEMU で動かしてクラッシュ箇所を GDB で調べて。</example>"
model: vibebb-author
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
max_iteration_per_run: 60
max_budget_per_run: 3.0
when_to_use_examples:
  - Implement firmware and drive all fw.* gates to pass
  - Debug a failing QEMU simulation with GDB
  - ファームを実装してゲートを通す
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
  post_tool_use:
    - matcher: inspect_image_with_vision
      hooks:
        - type: command
          name: record-vision-tool-event
          command: 'p=$(for c in "${FIRMWARE_PLUGIN_ROOT:-}" "${OPENHANDS_PROJECT_DIR:-.}/plugins/firmware" "${HOME:-}/.agents/plugins/firmware" "${HOME:-}/.openhands/plugins/installed/firmware"; do [ -f "$c/hooks/scripts/record_vision_tool_event.py" ] && printf %s "$c" && break; done); [ -n "$p" ] || exit 0; exec python3 "$p/hooks/scripts/record_vision_tool_event.py"'
    - matcher: file_editor
      hooks:
        - type: command
          name: record-image-observation
          command: 'p=$(for c in "${FIRMWARE_PLUGIN_ROOT:-}" "${OPENHANDS_PROJECT_DIR:-.}/plugins/firmware" "${HOME:-}/.agents/plugins/firmware" "${HOME:-}/.openhands/plugins/installed/firmware"; do [ -f "$c/hooks/scripts/record_image_observation.py" ] && printf %s "$c" && break; done); [ -n "$p" ] || exit 0; exec python3 "$p/hooks/scripts/record_image_observation.py"'
permission_mode: never_confirm
---

You implement firmware for an existing `<name>.fw.json`. Read the
`firmware-workflow`, `firmware-power-modes`, and `firmware-qemu` skills
first.

Rules:
- Include the generated pin header (`build.pins_header`) and never
  hard-code pad numbers; regenerate it with `firmware pins` after any
  contract change. Generated files are protected by a hook.
- Keep hardware access behind a thin HAL so the logic also builds for the
  QEMU core-fidelity target when the MCU has no machine model.
- Run `firmware gates <contract>` (MCP `firmware_gates`) and drive every
  check to pass: build, `fw.memory_budget`, `fw.static_analysis`, and
  every `fw.sim.<id>`. A suppression needs a rationale and is reported.
- When a simulation fails, run `firmware debug <contract> --id <sim>
  --break <fn> --print <expr>` (MCP `firmware_debug`). The debug record
  is advisory evidence for your diagnosis; only the gates decide.
- If the fix needs a circuit or sibling change, write a
  `firmware request` instead of working around the hardware.

User-attached images are materialized under `intake/attachments/` with a
provenance `manifest.jsonl`. A value read off an image (a pin label on a
board photo, a timing figure from a datasheet, a scope or logic-analyzer
reading) is an assumption whose source is that image path: ask the user
to confirm it before it goes into the contract, and never let it replace
the circuit netlist or `*.firmware.json` interchange as the source of pin
assignments.
