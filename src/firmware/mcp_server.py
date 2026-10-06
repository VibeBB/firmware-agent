"""Expose the firmware entry points over a stdio MCP transport.

Every tool returns the same JSON payload as the CLI; the transport never
judges the design itself. Tools that write PNGs also return them inline
as ImageContent so a vision-capable model sees the render directly.
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import cast

from mcp import types
from mcp.server import Server
from mcp.server.lowlevel import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server

from . import __version__, service
from .records import DecisionInput, StageImpressionInput, VisionReviewInput
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
    "firmware_cues": (
        "Regenerate the bard cue header from the pinned cues.json",
        _schema(_CONTRACT, ["contract_path"]),
        False,
    ),
    "firmware_power_export": (
        "Export <name>.fw-power.json (peak and average draw on the supply net) "
        "for simulation-agent PDN imports",
        _schema({**_CONTRACT, **_OUT}, ["contract_path"]),
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
        "Write a change request (*.fw-request.json) to a sister agent",
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
                "decision_refs": _STRINGS,
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
    "firmware_render": (
        "Render pin map / gate report / sim timeline PNGs (report view reruns "
        "static gates; sim view re-evaluates existing sim-*.log transcripts and "
        "never runs QEMU)",
        _schema(
            {
                **_CONTRACT,
                **_OUT,
                "views": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["pinmap", "report", "sim"]},
                },
            },
            ["contract_path"],
        ),
        False,
    ),
    "firmware_ux_inbox": (
        "List ux-creator SLP v2 requests: new, stale, blocked or answered",
        _schema({"workspace": {"type": "string"}}, []),
        True,
    ),
    "firmware_ux_respond": (
        "Answer a ux-creator SLP v2 request (writes <id>.ux-response.json)",
        _schema(
            {
                "request": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": [
                        "accepted",
                        "in_progress",
                        "done",
                        "rejected",
                        "deferred",
                        "needs_info",
                    ],
                },
                "reason": {"type": "string"},
                "artifacts": _STRINGS,
                "gate_verdicts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "gate": {"type": "string"},
                            "verdict": {
                                "type": "string",
                                "enum": ["pass", "fail", "unknown"],
                            },
                        },
                        "required": ["gate", "verdict"],
                    },
                },
                "decision_refs": _STRINGS,
                "impression_refs": _STRINGS,
                "questions_for_user": _STRINGS,
                "report_paths": _STRINGS,
                "workspace": {"type": "string"},
            },
            ["request", "status"],
        ),
        False,
    ),
    "firmware_record_decision": (
        "Record a design decision (VibeBB Record Protocol): first principles, at least "
        "two options with pros/cons, the chosen option, a rationale of 200+ chars, "
        "evidence paths (hashed) or references, assumptions, unknowns, risks, revisit "
        "trigger. Record one for every non-trivial choice without being asked.",
        DecisionInput.model_json_schema(),
        False,
    ),
    "firmware_record_impression": (
        "Record the long-form impression that closes a stage (400+ chars, 3+ "
        "sentences): what you noticed, what works, what worries you, how a maker or "
        "user would read it, what to do next. Binds the stage artifacts by sha256; "
        "record it after the final regeneration.",
        StageImpressionInput.model_json_schema(),
        False,
    ),
    "firmware_record_vision_review": (
        "Record what you thought after looking at an image (400+ char impression plus "
        "findings). Bind it to image_path (hashed) or to the source_event_id of an "
        "inspect_image_with_vision event. Required for every image you viewed.",
        VisionReviewInput.model_json_schema(),
        False,
    ),
    "firmware_records_status": (
        "Counts of decision / impression / vision-review records and the last "
        "Stop-hook verdict listing records this session still owes.",
        _schema({}, []),
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
        "firmware_cues": lambda: service.cues_payload(_path(arguments, "contract_path")),
        "firmware_power_export": lambda: service.power_payload(
            _path(arguments, "contract_path"), _opt_path(arguments, "out_dir")
        ),
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
            decision_refs=_strs(arguments, "decision_refs"),
        ),
        "firmware_profile": lambda: service.profile_payload(_str(arguments, "profile")),
        "firmware_record_decision": lambda: service.record_write_payload("decision", arguments),
        "firmware_record_impression": lambda: service.record_write_payload("impression", arguments),
        "firmware_record_vision_review": lambda: service.record_write_payload(
            "vision-review", arguments
        ),
        "firmware_records_status": service.records_status_payload,
        "firmware_ux_inbox": lambda: service.ux_inbox_payload(_opt_path(arguments, "workspace")),
        "firmware_ux_respond": lambda: service.ux_respond_payload(
            _opt_path(arguments, "workspace"), arguments
        ),
        "firmware_render": lambda: service.render_payload(
            _path(arguments, "contract_path"),
            _opt_path(arguments, "out_dir"),
            _strs(arguments, "views"),
        ),
    }
    handler = handlers.get(name)
    if handler is None:
        return {"verdict": "fail", "detail": f"unknown tool {name}"}
    return handler()


_IMAGE_TOOLS = {
    "firmware_gates",
    "firmware_check",
    "firmware_pinmap_export",
    "firmware_sim",
    "firmware_render",
}
_MAX_INLINE_IMAGES = 4
_MAX_IMAGE_BYTES = 4 * 1024 * 1024


def _inline_images(payload: service.Json) -> list[types.ImageContent]:
    """Inline written PNGs as ImageContent so a vision model sees them."""
    written = payload.get("written")
    if not isinstance(written, list):
        return []
    images: list[types.ImageContent] = []
    skipped: list[str] = []
    for entry in cast(list[object], written):
        path = Path(str(entry))
        if path.suffix != ".png":
            continue
        if len(images) >= _MAX_INLINE_IMAGES:
            skipped.append(str(path))
            continue
        try:
            if not path.is_file() or path.stat().st_size > _MAX_IMAGE_BYTES:
                skipped.append(str(path))
                continue
            data = base64.b64encode(path.read_bytes()).decode("ascii")
        except OSError:
            skipped.append(str(path))
            continue
        images.append(types.ImageContent(type="image", data=data, mimeType="image/png"))
    if skipped:
        payload["images_skipped"] = skipped
    return images


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, object]) -> types.CallToolResult:
    is_error = False
    payload: service.Json
    try:
        payload = await asyncio.to_thread(dispatch, name, arguments or {})
        is_error = name not in TOOLS
    except Exception as exc:  # fail-closed transport
        payload = {"verdict": "fail", "detail": f"{name} error: {exc}"}
        is_error = True
    content: list[types.ContentBlock] = []
    if name in _IMAGE_TOOLS:
        content += _inline_images(payload)
    content.insert(
        0,
        types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2)),
    )
    return types.CallToolResult(content=content, isError=is_error)


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
