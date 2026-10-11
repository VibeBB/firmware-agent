# ADR-0011: Product unit tests with host gcc and gcov

Status: Accepted

## Context

The firmware the agent designs was only verified by building it, running
cppcheck and booting it in QEMU against `expect` lines. Nothing showed
which branches of the product's own logic (state machines, limits,
protocol parsers) any test exercised, so a gate could pass with the
safety-relevant paths never run. ADR-0010 covers the agent's Python code,
not the product it writes.

## Decision

- Add an optional `unit_tests` contract block and the gate
  `fw.unit_coverage`. Declared `sources` and `tests` are compiled with
  host `gcc --coverage -O0`, linked and run; a non-zero exit fails.
- Coverage is read from `gcov --json-format --stdout` for the declared
  `sources` only (test files are excluded) and compared with the authored
  `min_line_pct` (C0) and `min_branch_pct` (C1). Missing tools, compile or
  link errors, timeouts and unreadable gcov output fail closed.
- Add Ubuntu `gcc` and `libc6-dev` to the firmware-tools image; gcov ships
  with gcc. No Python dependency and no test framework are added: a test
  is a C file whose `main()` returns non-zero on failure.
- Condition/MC/DC coverage (`-fcondition-coverage`) is not gated yet; it
  needs a later GCC than every target toolchain guarantees and would add a
  second report format.

## Consequences

Contracts without `unit_tests` are unchanged. Product code must keep
hardware access behind the HAL for its logic to build on the host.
