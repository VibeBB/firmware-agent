# Agents

Three agents in `plugins/firmware/agents/`; all work through the launcher
and the firmware MCP server.

## firmware-architect

Designs the contract: picks the MCU profile, assigns pads, peripherals and
power modes in `<name>.fw.json`, proves the pin map against the circuit
netlist (`firmware check`, `circuit firmware-check` hand-off).
Tools: terminal, file_editor, grep, glob, task_tracker; MCP `firmware`.
At session start calls `firmware_ux_inbox` and answers every ux-creator
request (`new`, `stale`, `blocked` → `needs_info`/`deferred` with reason)
via `firmware_ux_respond` with decision and impression refs.
Records: decision per real choice (MCU, pin assignment, peripheral,
power mode, sim plan); stage impression; vision review per image.

## firmware-developer

Implements sources against the contract and the generated `fw_pins.h`,
keeping hardware access behind a HAL so logic builds for QEMU; reviews the
rendered `*.pinmap.png` / `*.fw-report.png` / `sim-*.png` images.
Records: impressions per stage; vision review for every rendered image.

## firmware-review

Reviews the finished work: contract, gate report, rendered images
("vision review checklist"), records completeness, sister requests.
Records: vision reviews of the images it inspects; a closing stage
impression.

All three must leave the records described in
[records-and-vision.md](records-and-vision.md); the Stop hook enforces it.
