# ADR-0006: Development-only pytest coverage gate

- Status: Accepted
- Date: 2026-09-30

## Context

The Python package and plugin hooks need a repeatable regression signal without
adding coverage instrumentation to runtime or the firmware-tools image.

## Decision

Use `pytest-cov==7.1.0` in the development dependency group, collect line
coverage for `src/firmware` without branch coverage, and require at least 75%
coverage in the test command.

## Consequences

Coverage tooling remains development-only; CI enforces the threshold while
runtime dependencies and published images remain unchanged.
