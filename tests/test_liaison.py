"""SLP v2 liaison: inbox classification and respond validation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

import pytest

from firmware import liaison

REPO = Path(__file__).resolve().parent.parent


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _request(request_id: str, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": 2,
        "system": "ux-creator",
        "id": request_id,
        "target_agent": "firmware",
        "stage": "design",
        "risk": "low",
        "purpose": "Decide the button pad and debounce window for the lid.",
        "rationale": "the UX flow needs a single button press",
        "requested_changes": ["assign one GPIO input with pull-up"],
        "inputs": [],
        "expected_deliverables": ["<name>.fw.json pin assignment"],
        "acceptance": ["fw.pin_functions passes"],
        "depends_on": [],
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    body.update(overrides)
    return body


def _write_request(workspace: Path, body: dict[str, Any], name: str | None = None) -> Path:
    liaison_dir = workspace / "liaison"
    liaison_dir.mkdir(parents=True, exist_ok=True)
    path = liaison_dir / f"{name or body['id']}.ux-request.json"
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    return path


def _records(workspace: Path) -> tuple[str, str]:
    """Write one decision and one impression; return their event_ids."""
    records = workspace / "observations" / "firmware"
    records.mkdir(parents=True, exist_ok=True)
    decision = "d" * 64
    impression = "i" * 64
    (records / "decisions.jsonl").write_text(
        json.dumps({"event_id": decision}) + "\n", encoding="utf-8"
    )
    (records / "impressions.jsonl").write_text(
        json.dumps({"event_id": impression}) + "\n", encoding="utf-8"
    )
    return decision, impression


def _states(payload: dict[str, Any]) -> dict[str, str]:
    return {r["id"]: r["state"] for r in cast(list[dict[str, Any]], payload["requests"])}


def test_new_request(tmp_path: Path) -> None:
    _write_request(tmp_path, _request("button-pad"))
    payload = liaison.inbox(tmp_path)
    assert _states(payload) == {"button-pad": "new"}
    assert payload["verdict"] == "fail" and payload["open"] == 1


def test_id_mismatch_and_extra_field_are_malformed(tmp_path: Path) -> None:
    _write_request(tmp_path, _request("real-id"), name="other-stem")
    body = _request("extra-field")
    body["bogus"] = 1
    _write_request(tmp_path, body)
    payload = liaison.inbox(tmp_path)
    assert len(cast(list[object], payload["malformed"])) == 2
    assert payload["requests"] == []


def test_non_firmware_target_ignored(tmp_path: Path) -> None:
    _write_request(tmp_path, _request("for-circuit", target_agent="circuit"))
    _write_request(tmp_path, _request("for-firmware"))
    payload = liaison.inbox(tmp_path)
    assert payload["other_targets"] == 1
    assert _states(payload) == {"for-firmware": "new"}


def test_high_risk_needs_snake_case_job(tmp_path: Path) -> None:
    _write_request(
        tmp_path,
        _request("risky", risk="high", rationale="no job token here"),
    )
    payload = liaison.inbox(tmp_path)
    assert payload["malformed"]
    _write_request(
        tmp_path,
        _request("risky-ok", risk="high", rationale="drives the boil_water job"),
    )
    payload = liaison.inbox(tmp_path)
    assert _states(payload)["risky-ok"] == "new"


def test_input_changed_is_stale(tmp_path: Path) -> None:
    input_file = tmp_path / "brief.md"
    input_file.write_text("v1", encoding="utf-8")
    _write_request(
        tmp_path,
        _request("with-input", inputs=[{"path": "brief.md", "sha256": _sha(input_file)}]),
    )
    assert _states(liaison.inbox(tmp_path))["with-input"] == "new"
    input_file.write_text("v2", encoding="utf-8")
    payload = liaison.inbox(tmp_path)
    entry = cast(list[dict[str, Any]], payload["requests"])[0]
    stale_inputs = cast(list[dict[str, Any]], entry["stale_inputs"])
    assert entry["state"] == "stale" and stale_inputs[0]["path"] == "brief.md"


def test_stale_vs_response_input_hashes(tmp_path: Path) -> None:
    input_file = tmp_path / "brief.md"
    input_file.write_text("v1", encoding="utf-8")
    _write_request(
        tmp_path,
        _request("answered-input", inputs=[{"path": "brief.md", "sha256": _sha(input_file)}]),
    )
    _records(tmp_path)
    out = tmp_path / "liaison" / "answered-input.ux-response.json"
    out.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "system": "ux-creator",
                "request": "answered-input",
                "responder": "firmware",
                "status": "accepted",
                "input_hashes": {"brief.md": _sha(input_file)},
                "responded_at": "2026-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    input_file.write_text("v2", encoding="utf-8")
    assert _states(liaison.inbox(tmp_path))["answered-input"] == "stale"


def test_missing_dependency_is_blocked(tmp_path: Path) -> None:
    _write_request(tmp_path, _request("first"))
    _write_request(tmp_path, _request("second", depends_on=["first"]))
    states = _states(liaison.inbox(tmp_path))
    assert states["second"] == "blocked"
    assert states["first"] == "new"


def test_cycle_is_blocked_and_circular(tmp_path: Path) -> None:
    _write_request(tmp_path, _request("cyc-a", depends_on=["cyc-b"]))
    _write_request(tmp_path, _request("cyc-b", depends_on=["cyc-a"]))
    payload = liaison.inbox(tmp_path)
    for entry in cast(list[dict[str, Any]], payload["requests"]):
        assert entry["state"] == "blocked" and entry["circular"] is True


def _respond_ok(tmp_path: Path, request_id: str, **overrides: Any) -> dict[str, Any]:
    decision, impression = _records(tmp_path)
    fields: dict[str, Any] = {
        "status": "accepted",
        "decision_refs": [decision],
        "impression_refs": [impression],
    }
    fields.update(overrides)
    return liaison.respond(tmp_path, request_id, **fields)


def test_answered_after_respond(tmp_path: Path) -> None:
    _write_request(tmp_path, _request("answer-me"))
    result = _respond_ok(tmp_path, "answer-me")
    assert result["verdict"] == "pass"
    assert (tmp_path / "liaison" / "answer-me.ux-response.json").is_file()
    assert _states(liaison.inbox(tmp_path))["answer-me"] == "answered"
    again = _respond_ok(tmp_path, "answer-me", status="in_progress")
    assert again["verdict"] == "pass" and again["replaced"] is True


def test_done_refusals(tmp_path: Path) -> None:
    _write_request(tmp_path, _request("done-refusals"))
    artifact = tmp_path / "fw.bin"
    artifact.write_text("bin", encoding="utf-8")
    decision, impression = _records(tmp_path)
    base: dict[str, Any] = {
        "status": "done",
        "artifacts": ["fw.bin"],
        "decision_refs": [decision],
        "impression_refs": [impression],
    }
    bad_gate = liaison.respond(
        tmp_path,
        "done-refusals",
        gate_verdicts=[{"gate": "fw.build", "verdict": "fail"}],
        **base,
    )
    assert bad_gate["verdict"] == "fail"
    no_refs = liaison.respond(
        tmp_path,
        "done-refusals",
        gate_verdicts=[{"gate": "g", "verdict": "pass"}],
        status="done",
        artifacts=["fw.bin"],
        reason="",
    )
    assert no_refs["verdict"] == "fail"
    unknown_ref = liaison.respond(
        tmp_path,
        "done-refusals",
        decision_refs=["0" * 64],
        **{k: v for k, v in base.items() if k != "decision_refs"},
        gate_verdicts=[{"gate": "g", "verdict": "pass"}],
    )
    assert "unknown decision ref" in str(unknown_ref["detail"])


def test_needs_info_short_reason_refused(tmp_path: Path) -> None:
    _write_request(tmp_path, _request("needs-info"))
    result = liaison.respond(tmp_path, "needs-info", "needs_info", reason="too short")
    assert result["verdict"] == "fail"


def test_report_paths_merge_and_freshness(tmp_path: Path) -> None:
    contract = tmp_path / "kettle.fw.json"
    contract.write_text("{}", encoding="utf-8")
    report = tmp_path / "kettle.fw-report.json"
    report.write_text(
        json.dumps(
            {
                "contract_sha256": "0" * 64,  # stale: contract has a different sha
                "checks": [{"id": "fw.build", "status": "fail"}],
            }
        ),
        encoding="utf-8",
    )
    _write_request(tmp_path, _request("with-report"))
    decision, impression = _records(tmp_path)
    result = liaison.respond(
        tmp_path,
        "with-report",
        "done",
        decision_refs=[decision],
        impression_refs=[impression],
        report_paths=["kettle.fw-report.json"],
    )
    assert result["verdict"] == "fail"  # fw.build fail + report_fresh fail


def test_path_escape_refused(tmp_path: Path) -> None:
    _write_request(tmp_path, _request("escape"))
    result = _respond_ok(tmp_path, "escape", artifacts=["../outside.bin"])
    assert result["verdict"] == "fail"
    result = _respond_ok(tmp_path, "escape", report_paths=["/etc/passwd"])
    assert result["verdict"] == "fail"


def test_cli_and_mcp_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from firmware import cli, mcp_server

    _write_request(tmp_path, _request("round-trip"))
    monkeypatch.setenv("OPENHANDS_PROJECT_DIR", str(tmp_path))
    assert cli.main(["ux", "inbox", "--workspace", str(tmp_path)]) == 1  # open work
    payload = mcp_server.dispatch("firmware_ux_inbox", {"workspace": str(tmp_path)})
    assert _states(payload)["round-trip"] == "new"
    fields = tmp_path / "answer.json"
    decision, impression = _records(tmp_path)
    fields.write_text(
        json.dumps(
            {
                "request": "round-trip",
                "status": "accepted",
                "decision_refs": [decision],
                "impression_refs": [impression],
            }
        ),
        encoding="utf-8",
    )
    assert cli.main(["ux", "respond", "--workspace", str(tmp_path), "--json", str(fields)]) == 0
    assert cli.main(["ux", "inbox", "--workspace", str(tmp_path)]) == 0
