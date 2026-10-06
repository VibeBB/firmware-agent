# Sister cooperation

All interchange is JSON artifacts in the shared workspace; firmware never
imports a sister's code and never edits a sister's inputs — a needed
change becomes a `*.fw-request.json`.

## SLP v2 — ux-creator liaison

UX-creator drops `<id>.ux-request.json` into `liaison/` (strict schema in
[contracts.md](contracts.md)). `firmware ux inbox`
(`firmware_ux_inbox`) classifies every firmware-targeted request:

- `new` — valid request, no response yet
- `stale` — an input's current sha256 differs from the request (or from
  the stored `input_hashes`); `stale_inputs` lists path/expected/actual
- `blocked` — a `depends_on` peer has no valid response file, or the
  request sits on a dependency cycle (`blocked_by`, `circular`)
- `answered` — a valid firmware response exists (`response_status`)

Malformed requests/responses (parse errors, schema errors, id ≠ file
stem, responder mismatch) land in `malformed[]` and count as open work;
requests for other sisters are counted in `other_targets`.

`firmware ux respond` (`firmware_ux_respond` / `ux respond --json`)
refuses when the request is stale (unless status is
needs_info/rejected/deferred with a ≥20-char reason) or `done` while
blocked. `report_paths` merge a `*.fw-report.json`'s checks into
`gate_verdicts` (not_applicable checks are omitted; unknown statuses map
to `unknown`; a stale report → `fw.report_fresh` fail). Status `done`
needs clean verdicts, ≥1 artifact, ≥1 decision ref and ≥1 impression ref
from `observations/firmware/`. Responses write atomically;
`*.ux-response.json` is generated and write-protected. A high-risk
request must cite a snake_case UX job id in `rationale` — a local
heuristic until the UX contract is shared.

## Circuit interchange

`circuit firmware-export` writes `<design>.firmware.json` carrying
`brief_sha256`/`netlist_sha256`; `fw.netlist_match` binds the pin map to
that exact export (`circuit_sha256` in the gate report). Firmware hands
`<name>.fw-pinmap.json` back for `circuit firmware-check`. Re-export
after every circuit change — a pin map checked against a stale export
fails there.

## bard cue interchange

bard-agent renders a cue set to `cues/<slug>/cues.json`
(`bard_cue_manifest`: per cue `id`, `purpose`, `loop`, `duration_ms` and
`tones[]` of `{start_ms, duration_ms, midi, freq_hz}`). The contract's
optional `cues` block binds it:

- `manifest` and `sha256` pin the exact manifest. A re-rendered cue set
  fails `fw.bard_cues` until the new tones are reviewed and the hash is
  re-pinned, so firmware never plays a cue it has not looked at.
- `pin` names the PWM pin that drives the transducer; `min_hz`/`max_hz`
  is the transducer's usable band from its datasheet. Every sounded tone
  must fall inside it.
- `firmware cues` (`firmware_cues`) writes `header` (`fw_cues.h`): one
  centihertz/millisecond tone table per cue, `FW_CUE_<ID>` indices and
  `fw_cue_centihz_at(cue, elapsed_ms)`, a pure lookup the firmware's timer
  tick calls to get the PWM frequency (`0` = silence or done; looping
  cues wrap). `fw.bard_cues` fails when the header is missing or stale.

A cue that needs a frequency the transducer cannot play goes back to bard
as a `firmware request --target bard`.

## Simulation interchange

`firmware power` writes `<name>.fw-power.json`: the authored power modes
in amperes, the peak (largest mode) and duty-weighted average current on
`power.supply_net`, and the contract sha256. simulation-agent imports it
with `system: "firmware"` and a PDN load declared as
`current_a: "import:firmware:<net>"` draws the peak current, so the rail
drop is solved with the MCU's worst case instead of a hand-copied number.
The import is sha256-pinned in simulation's `imports.json`; re-export
after every power-mode change.

## Outbound requests — `fw_request` v2

`firmware request` writes `<design>.<id>.fw-request.json` to `circuit`,
`mech`, `wire`, `ux`, `bard`, `doc`, `prodeng`, `sim`, `fpga` or
`dashboard`. Inputs are hashed (contract always, connectivity when
resolvable, workspace-relative POSIX paths) so the receiver detects a
stale ask; high risk requires a `decision_refs` entry.

## Other sisters

The UX producer plan is read as an input only; firmware's
reports serve as evidence back to them, and `firmware_ux_*` answers
UX-creator directly.
