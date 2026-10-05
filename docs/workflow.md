# Workflow

Stages of a firmware design session and the records each must leave
(see [records-protocol.md](records-protocol.md) and
[records-and-vision.md](records-and-vision.md)).

1. **Intake / liaison inbox** — `firmware ux inbox` (MCP `firmware_ux_inbox`)
   lists ux-creator SLP v2 requests; user-attached images are materialized
   under `intake/attachments/` by the intake hook.
2. **MCU & pin design** — pick the bundled profile (`firmware profile`),
   assign pads, peripherals and power modes in `<name>.fw.json`.
   Record a **decision** for the MCU/profile choice and every non-obvious
   pad, peripheral or power-mode choice.
3. **Contract validation** — `firmware validate` parses the contract and
   resolves the profile.
4. **Pin header** — `firmware pins` regenerates `build.pins_header`
   (`fw_pins.h`); implementations include it.
5. **Static gates** — `firmware check` runs `fw.contract`,
   `fw.pin_functions`, `fw.netlist_match`, `fw.power_modes`,
   `fw.pins_header` and writes `fw-report.*`, the pin map export and
   `*.pinmap.png`.
6. **Build / memory / static analysis** — `firmware gates` additionally
   runs `fw.build`, `fw.memory_budget`, `fw.static_analysis` inside the
   tools image.
7. **Simulation** — `firmware gates` runs every declared `fw.sim.<id>`;
   `firmware sim` reruns one. Transcripts land as `sim-*.log`.
8. **Debug** — `firmware debug` (advisory GDB) when a simulation fails.
9. **Render + vision review** — `firmware render` or the gate writers
   produce PNGs; every PNG appears under `vision_review_required`.
   Inspect it and record a **vision review** (≥400 chars, 3+ sentences).
10. **Review** — `firmware-review` agent re-reads the contract, gates and
    renders. Record a stage **impression** per finished stage.
11. **Liaison response / sister requests** — answer each inbox request
    via `firmware ux respond` (done needs clean gate verdicts, artifacts,
    a decision ref and an impression ref). Anything that belongs to a
    sister becomes a `firmware request` (`*.fw-request.json`), never an
    edit to a sister's inputs.

The Stop hook (`require-records`) refuses to finish while mandatory
records are still owed.
