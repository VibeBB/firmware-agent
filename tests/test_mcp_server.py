from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import mcp.types
import pytest

from firmware import mcp_server, service


def _call_result(name: str, arguments: dict[str, object]) -> mcp.types.CallToolResult:
    async def invoke() -> mcp.types.CallToolResult:
        result = await mcp_server.call_tool(name, arguments)
        assert isinstance(result, mcp.types.CallToolResult)
        return result

    return asyncio.run(invoke())


def _payload(result: mcp.types.CallToolResult) -> dict[str, Any]:
    assert isinstance(result.content[0], mcp.types.TextContent)
    return json.loads(result.content[0].text)


def test_unknown_tool_returns_transport_error() -> None:
    result = _call_result("firmware_missing", {})
    assert result.isError is True
    assert _payload(result) == {
        "verdict": "fail",
        "detail": "unknown tool firmware_missing",
    }


def test_handler_exception_returns_transport_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_doctor() -> service.Json:
        raise RuntimeError("handler failed")

    monkeypatch.setattr(service, "doctor_payload", fail_doctor)
    result = _call_result("firmware_doctor", {})
    assert result.isError is True
    assert _payload(result) == {
        "verdict": "fail",
        "detail": "firmware_doctor error: handler failed",
    }


def test_gate_failure_is_not_a_transport_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_validation(_contract_path: Path) -> service.Json:
        return {"verdict": "fail", "stage": "schema", "detail": "invalid"}

    monkeypatch.setattr(service, "validate_payload", fail_validation)
    result = _call_result("firmware_validate", {"contract_path": "contract.fw.json"})
    assert result.isError is False
    assert _payload(result)["verdict"] == "fail"


def test_mcp_rejects_path_outside_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENHANDS_PROJECT_DIR", str(tmp_path))
    result = _call_result("firmware_validate", {"contract_path": "../outside.fw.json"})
    assert result.isError is True
    assert "path is outside the workspace" in _payload(result)["detail"]


def test_mcp_contains_relative_input_and_output_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENHANDS_PROJECT_DIR", str(tmp_path))
    captured: dict[str, Path | None] = {}

    def capture_gates(contract_path: Path, out_dir: Path | None, *, full: bool) -> service.Json:
        captured["contract"] = contract_path
        captured["out_dir"] = out_dir
        assert full is False
        return {"verdict": "unknown"}

    monkeypatch.setattr(service, "gates_payload", capture_gates)
    result = _call_result(
        "firmware_check",
        {"contract_path": "contracts/device.fw.json", "out_dir": "reports"},
    )
    assert result.isError is False
    assert captured == {
        "contract": tmp_path / "contracts" / "device.fw.json",
        "out_dir": tmp_path / "reports",
    }


def test_mcp_resolves_elf_path_from_contract_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENHANDS_PROJECT_DIR", str(tmp_path))
    captured: dict[str, str | None] = {}

    def capture_debug(
        _contract_path: Path,
        _simulation: str,
        elf: str | None,
        _breaks: list[str],
        _prints: list[str],
        _out_dir: Path | None,
    ) -> service.Json:
        captured["elf"] = elf
        return {"verdict": "unknown"}

    monkeypatch.setattr(service, "debug_payload", capture_debug)
    result = _call_result(
        "firmware_debug",
        {
            "contract_path": "projects/device.fw.json",
            "simulation": "startup",
            "elf": "build/device.elf",
        },
    )
    assert result.isError is False
    assert captured == {"elf": str(tmp_path / "projects" / "build" / "device.elf")}
