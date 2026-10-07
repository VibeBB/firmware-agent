# Skills

`plugins/firmware/skills/` — reference material the agents load on demand.

| skill | content |
| --- | --- |
| `firmware-workflow` | end-to-end stage list: circuit export → contract → static gates → pin header → implementation → full gates → render+vision → circuit confirmation → debug → liaison; the `fw.*` gate table |
| `firmware-contract` | `<name>.fw.json` field-by-field authoring guide: MCU/profile, pins, peripherals, power modes, build, analysis, simulations |
| `firmware-mcu-pinmap` | pad functions, strapping/JTAG acknowledgment, peripheral routing rules for the bundled profiles |
| `firmware-power-modes` | duty cycles, wake sources, average-current budgeting |
| `firmware-qemu` | QEMU runners (`qemu-arm` core fidelity, `qemu-esp` full image), expect/forbid transcripts, advisory GDB |
| `firmware-sister-cooperation` | JSON artifact interchange with sister plugins: circuit `*.firmware.json` / `*.fw-pinmap.json`, `fw_request` v2, SLP v2 liaison, bard cues, UX producer plan |
| `firmware-contract-rules` | path rule on `*.fw.json` / `*.firmware.json` — contract schema and provenance reminders injected when a contract or connectivity file is touched |
| `firmware-out-rules` | path rule on `**/out/**` — generated artifacts are read-only projections; change the contract and regenerate (the `protect-generated` hook enforces) |
