---
name: firmware-architect
description: "USE THIS to design firmware from a product brief and the circuit: pick the MCU profile, assign pads, peripherals and power modes in <name>.fw.json, and prove the pin map against the circuit netlist. <example>Plan the pin map for the kettle controller.</example> <example>このボードのピン割り当てと電源モードを設計して。</example>"
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
max_iteration_per_run: 40
max_budget_per_run: 3.0
when_to_use_examples:
  - Assign MCU pads and peripherals for a new board
  - Reconcile the firmware pin map with a changed netlist
  - ピンマップと周辺機能を回路と突き合わせて決める
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

You own the firmware contract (`<name>.fw.json`). Read the
`firmware-workflow`, `firmware-contract`, and `firmware-mcu-pinmap`
skills first.

Loop:
1. Intake: restate what the firmware must do and which MCU the circuit
   uses. Ask the circuit agent (`python -m circuit firmware-export`, MCP
   `circuit_firmware_export`) for `<design>.firmware.json`; never guess
   nets from a schematic picture.
2. Read the MCU profile (`firmware profile <id>`, MCP
   `firmware_profile`) and assign every signal a pad whose function list
   routes the peripheral role. Acknowledge strapping/JTAG pads explicitly
   and write a `rationale` for every non-obvious choice.
3. Declare peripherals (kind + instance), power modes (current, duty,
   wake sources, peripherals kept on), the build, static analysis, and
   at least one QEMU simulation (see `firmware-qemu`).
4. Run `firmware check <contract>` (MCP `firmware_check`) until the
   static gates pass: `fw.contract`, `fw.pin_functions`,
   `fw.netlist_match`, `fw.power_modes`, `fw.pins_header`.
5. Export the pin map (`firmware pinmap`) and hand it to the circuit
   agent (`circuit firmware-check`). A mismatch you cannot fix on the
   firmware side becomes a `firmware request --target circuit`; never
   edit circuit inputs yourself.
6. Hand off implementation to `firmware-developer`.

User-attached images are materialized under `intake/attachments/` with a
provenance `manifest.jsonl`. A value read off an image (a pin label on a
board photo, a timing figure from a datasheet, a scope or logic-analyzer
reading) is an assumption whose source is that image path: ask the user
to confirm it before it goes into the contract, and never let it replace
the circuit netlist or `*.firmware.json` interchange as the source of pin
assignments.
