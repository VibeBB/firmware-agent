"""Expose the firmware entry points over a stdio MCP transport.

Every tool returns the same JSON payload as the CLI; the transport never
judges the design itself.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from pathlib import Path

from mcp import types
from mcp.server import Server
from mcp.server.lowlevel import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server

from . import __version__, service
from .workspace import workspace_path

server: Server = Server(f"firmware-mcp/{__version__}")

_CONTRACT = {"contract_path": {"type": "string"}}
_OUT = {"out_dir": {"type": "string"}}
_STRINGS = {"type": "array", "items": {"type": "string"}}


def _schema(properties: Mapping[str, object], required: list[str]) -> dict[str, object]:
    return {
        "type": "object",
        "properties": dict(properties),
        "required": required,
        "additionalProperties": False,
    }


TOOLS: dict[str, tuple[str, dict[str, object], bool]] = {
    "firmware_doctor": ("Probe the firmware toolchain", _schema({}, []), True),
    "firmware_validate": (
        "Validate a <name>.fw.json contract and resolve its MCU profile",
        _schema(_CONTRACT, ["contract_path"]),
        True,
    ),
    "firmware_check": (
        "Static gates: pin functions, netlist match, power modes, pin header",
        _schema({**_CONTRACT, **_OUT}, ["contract_path"]),
        False,
    ),
    "firmware_gates": (
        "All gates: static + build, flash/RAM budget, cppcheck, QEMU simulation",
        _schema({**_CONTRACT, **_OUT}, ["contract_path"]),
        False,
    ),
    "firmware_pins": (
        "Regenerate the contract's generated pin header",
        _schema(_CONTRACT, ["contract_path"]),
        False,
    ),
    "firmware_pinmap_export": (
        "Export <name>.fw-pinmap.json for electrical-circuit-agent",
        _schema({**_CONTRACT, **_OUT}, ["contract_path"]),
        False,
    ),
    "firmware_sim": (
        "Run one declared QEMU simulation",
        _schema(
            {**_CONTRACT, **_OUT, "simulation": {"type": "string"}}, ["contract_path", "simulation"]
        ),
        False,
    ),
    "firmware_debug": (
        "Scripted GDB session on a QEMU simulation (advisory evidence only)",
        _schema(
            {
                **_CONTRACT,
                **_OUT,
                "simulation": {"type": "string"},
                "elf": {"type": "string"},
                "breaks": _STRINGS,
                "prints": _STRINGS,
            },
            ["contract_path", "simulation"],
        ),
        False,
    ),
    "firmware_request": (
        "Write a change request (*.fw-request.json) to a sibling agent",
        _schema(
            {
                **_CONTRACT,
                **_OUT,
                "target": {"type": "string"},
                "risk": {"type": "string", "enum": ["low", "high"]},
                "change": {"type": "string"},
                "rationale": {"type": "string"},
                "nets": _STRINGS,
                "failing_checks": _STRINGS,
            },
            ["contract_path", "target", "risk", "change", "rationale"],
        ),
        False,
    ),
    "firmware_profile": (
        "Show a bundled MCU profile (pads, functions, memory regions)",
        _schema({"profile": {"type": "string"}}, ["profile"]),
        True,
    ),
}


def tool_specs() -> list[types.Tool]:
    return [
        types.Tool(
            name=name,
            description=description,
            inputSchema=schema,
            annotations=types.ToolAnnotations(readOnlyHint=read_only),
        )
        for name, (description, schema, read_only) in TOOLS.items()
    ]


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return tool_specs()


def _str(arguments: dict[str, object], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _path(arguments: dict[str, object], key: str) -> Path:
    return workspace_path(_str(arguments, key))


def _opt_path(arguments: dict[str, object], key: str) -> Path | None:
    value = arguments.get(key)
    return workspace_path(value) if isinstance(value, str) and value else None


def _opt_path_str(arguments: dict[str, object], key: str, base: Path | None = None) -> str | None:
    value = arguments.get(key)
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if base is not None and not path.is_absolute():
        path = base / path
    return str(workspace_path(path))


def _strs(arguments: dict[str, object], key: str) -> list[str]:
    value = arguments.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list of strings")
    items: list[str] = []
    for item in value:  # pyright: ignore[reportUnknownVariableType]
        if not isinstance(item, str):
            raise ValueError(f"{key} must be a list of strings")
        items.append(item)
    return items


def dispatch(name: str, arguments: dict[str, object]) -> service.Json:
    handlers: dict[str, Callable[[], service.Json]] = {
        "firmware_doctor": service.doctor_payload,
        "firmware_validate": lambda: service.validate_payload(_path(arguments, "contract_path")),
        "firmware_check": lambda: service.gates_payload(
            _path(arguments, "contract_path"), _opt_path(arguments, "out_dir"), full=False
        ),
        "firmware_gates": lambda: service.gates_payload(
            _path(arguments, "contract_path"), _opt_path(arguments, "out_dir"), full=True
        ),
        "firmware_pins": lambda: service.pins_payload(_path(arguments, "contract_path")),
        "firmware_pinmap_export": lambda: service.pinmap_payload(
            _path(arguments, "contract_path"), _opt_path(arguments, "out_dir")
        ),
        "firmware_sim": lambda: service.sim_payload(
            _path(arguments, "contract_path"),
            _str(arguments, "simulation"),
            _opt_path(arguments, "out_dir"),
        ),
        "firmware_debug": lambda: service.debug_payload(
            _path(arguments, "contract_path"),
            _str(arguments, "simulation"),
            _opt_path_str(arguments, "elf", _path(arguments, "contract_path").parent),
            _strs(arguments, "breaks"),
            _strs(arguments, "prints"),
            _opt_path(arguments, "out_dir"),
        ),
        "firmware_request": lambda: service.request_payload(
            _path(arguments, "contract_path"),
            _opt_path(arguments, "out_dir"),
            target=_str(arguments, "target"),
            risk=_str(arguments, "risk"),
            change=_str(arguments, "change"),
            rationale=_str(arguments, "rationale"),
            nets=_strs(arguments, "nets"),
            failing_checks=_strs(arguments, "failing_checks"),
        ),
        "firmware_profile": lambda: service.profile_payload(_str(arguments, "profile")),
    }
    handler = handlers.get(name)
    if handler is None:
        return {"verdict": "fail", "detail": f"unknown tool {name}"}
    return handler()


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, object]) -> types.CallToolResult:
    is_error = False
    try:
        payload = await asyncio.to_thread(dispatch, name, arguments or {})
        is_error = name not in TOOLS
    except Exception as exc:  # fail-closed transport
        payload = {"verdict": "fail", "detail": f"{name} error: {exc}"}
        is_error = True
    return types.CallToolResult(
        content=[
            types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))
        ],
        isError=is_error,
    )


async def _run() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name=f"firmware-mcp/{__version__}",
                server_version=__version__,
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
