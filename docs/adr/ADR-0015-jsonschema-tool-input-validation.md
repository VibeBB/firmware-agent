# ADR-0015: jsonschema restores mcp tool input validation

## Status

Accepted

## Context

mcp 1.x validated `call_tool` arguments against each tool's
`inputSchema` with jsonschema on the request layer. mcp 2.x routes
`CallToolRequest` straight to `on_call_tool` unvalidated, so
schema-invalid arguments reached the tool implementations as late
failures (or silent coercion) instead of a protocol-level error.

The repo had pinned `mcp>=1.29,<2`; SDK 1.62.0's `fastmcp-slim[client]`
extra pins `mcp>=2`, making the old cap unsatisfiable, so the server
migrated to the mcp 2.x API in this sweep. The validation behavior is
part of the plugin contract the tests and sisters rely on
(`Input validation error` results with the offending key and value in
the message).

## Decision

Add `jsonschema>=4` as a runtime dependency. `call_tool` validates
`arguments` against the tool's `input_schema` with
`Draft202012Validator` before dispatch; on failure it returns a
`CallToolResult` carrying `Input validation error: '<key>': <message>`
(`is_error=True`), preserving the v1 contract surface.

## Consequences

- Schema-invalid arguments fail closed at the boundary again; tests
  asserting validation messages keep working unchanged in shape.
- Direct (non-transport) `call_tool` invocations in tests must pass
  schema-valid arguments, same as the wire path always required.
- `jsonschema` is a small, widely used MIT-licensed library already
  pulled in transitively by the SDK dependency tree; the direct pin
  makes the contract explicit.
