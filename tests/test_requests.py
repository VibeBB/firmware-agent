"""fw-request schema v2: hashed inputs and decision refs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from firmware import service
from firmware.requests import write_request

REPO = Path(__file__).resolve().parent.parent
KETTLE = REPO / "examples" / "smart-kettle" / "smart-kettle.fw.json"


def _decision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    event_id = "e" * 64
    records = tmp_path / "observations" / "firmware"
    records.mkdir(parents=True)
    (records / "decisions.jsonl").write_text(
        json.dumps({"event_id": event_id}) + "\n", encoding="utf-8"
    )
    monkeypatch.setenv("OPENHANDS_PROJECT_DIR", str(tmp_path))
    return event_id


def test_schema_v2_and_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENHANDS_PROJECT_DIR", str(tmp_path))
    payload = service.request_payload(
        KETTLE,
        tmp_path,
        target="prodeng",
        risk="low",
        change="Document the heater pad choice",
        rationale="production test needs the assignment",
        nets=[],
        failing_checks=[],
    )
    assert payload["verdict"] == "pass"
    written = next(tmp_path.glob("*.fw-request.json"))
    body: dict[str, Any] = json.loads(written.read_text(encoding="utf-8"))
    assert body["schema_version"] == 2
    assert body["target"] == "prodeng"
    inputs = cast(list[dict[str, str]], body["inputs"])
    assert inputs[0]["path"] == "smart-kettle.fw.json"
    assert {i["path"] for i in inputs} == {
        "smart-kettle.fw.json",
        "circuit/smart-kettle.firmware.json",
    }


def test_connectivity_input_hashed(tmp_path: Path) -> None:
    connectivity = tmp_path / "board.firmware.json"
    connectivity.write_text("{}", encoding="utf-8")
    contract = tmp_path / "board.fw.json"
    contract.write_text("{}", encoding="utf-8")
    request, _ = write_request(
        contract,
        "board",
        tmp_path,
        target="circuit",
        risk="low",
        change="move pad assignment",
        rationale="net name changed",
        nets=[],
        failing_checks=[],
        connectivity="board.firmware.json",
    )
    paths = [i.path for i in request.inputs]
    assert paths == ["board.fw.json", "board.firmware.json"]


def test_high_risk_needs_decision_ref(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENHANDS_PROJECT_DIR", str(tmp_path))
    payload = service.request_payload(
        KETTLE,
        tmp_path,
        target="circuit",
        risk="high",
        change="Change the heater pad",
        rationale="a different pad is needed",
        nets=[],
        failing_checks=[],
    )
    assert payload["verdict"] == "fail"
    event_id = _decision(tmp_path, monkeypatch)
    payload = service.request_payload(
        KETTLE,
        tmp_path,
        target="circuit",
        risk="high",
        change="Change the heater pad",
        rationale="a different pad is needed",
        nets=[],
        failing_checks=[],
        decision_refs=[event_id],
    )
    assert payload["verdict"] == "pass"


def test_unknown_decision_ref_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _decision(tmp_path, monkeypatch)
    payload = service.request_payload(
        KETTLE,
        tmp_path,
        target="circuit",
        risk="low",
        change="Move the LED pad",
        rationale="pin conflict",
        nets=[],
        failing_checks=[],
        decision_refs=["0" * 64],
    )
    assert payload["verdict"] == "fail" and "unknown decision ref" in str(payload["detail"])
