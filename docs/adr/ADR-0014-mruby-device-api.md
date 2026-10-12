# ADR-0014: Device API for mruby/c (UX-authored spec, generated bindings)

## Status

Accepted

## Context

Embedded products define device-specific mruby/c classes and methods in C
(OpenBlink's `src/api` is the reference). Hand-writing the VM-call glue
(argument decode, keyword parsing, return marshalling) is repetitive and
error-prone, and the "Ruby-ness" of the API surface is a UX decision, not a
firmware one.

## Decision

A UX-authored contract `api/<name>.mruby-api.json` (`artifact_kind:
"mruby_api"`, schema_version 1) describes classes, methods (positional and
keyword parameters, `**rest` kwargs, trailing blocks), constants, instance
classes with data/destructor, and access levels (`any`, `system_task`,
`expert`). The contract is hash-pinned into `mrubyc.device_api
{spec, sha256, handlers_header}`.

`firmware mrubyc` regenerates `fw_api_<class>.{c,h}`, `fw_api_symbols.{c,h}`
and `fw_api.{c,h}` under `generated_dir`. Generated C follows the OpenBlink
idiom verbatim: `MRBC_KW_ARG` + `do { ... } while (0)` + `MRBC_KW_DELETE`
guard blocks, symid-to-const dispatch for symbol arguments, bounded array
copies, and `SET_*_RETURN` marshalling. `MRBC_KW_MANDATORY`/`MRBC_KW_END`
raise in place, so generated code checks `mrbc_israised(vm)` before calling
the handler.

Handlers (`fw_hw_*`) live in a hand-written header declared by the contract;
generated bindings only decode/encode. The `fw.mrubyc` gate verifies the
spec sha pin, handler declarations exist word-level in the header, VM flags
(float/string) satisfy the spec, `system_task.vm_id <= max_vm_count`, and
the consumed symbol count fits `MAX_SYMBOLS_COUNT`.

`MrubycConfig` gained `use_unicode_case`, `use_int64`, `use_int16`,
`max_symbols`, and `device_api`; `config_header` emits
`MRBC_USE_UNICODE_CASE`, `MAX_SYMBOLS_COUNT`, and conditional
`MRBC_INT64`/`MRBC_INT16`.

## Consequences

- firmware only ever regenerates; UX owns the API surface and its docs.
- Simulation and dashboard agents generate stubs from the same spec to run
  UX `.rb` logic that calls device APIs under WASM.
- Binding bugs are caught at gate time (sha drift, stale generated files,
  missing handlers, symbol-budget overflow).
