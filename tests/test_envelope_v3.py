"""Interchange envelope v3: firmware sidecars and the bard cue provenance check."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from firmware import service
from firmware._envelope import check_envelope, sidecar_path
from firmware.gates import run_gates


def _check(contract: Path, tmp_path: Path, check_id: str) -> tuple[str, str]:
    report = run_gates(contract, tmp_path / "out", full=False)
    check = next(c for c in report.checks if c.id == check_id)
    return check.status, check.detail


def test_cue_provenance_wrong_producer_fails(kettle: Path, tmp_path: Path) -> None:
    side = kettle.parent / "bard" / "cues.provenance.json"
    body = json.loads(side.read_text(encoding="utf-8"))
    side.write_text(json.dumps(body | {"producer": "ux"}), encoding="utf-8")
    status, detail = _check(kettle, tmp_path, "fw.bard_cues_provenance")
    assert status == "fail" and "producer is 'ux'" in detail


def test_cue_provenance_missing_fails_closed(kettle: Path, tmp_path: Path) -> None:
    (kettle.parent / "bard" / "cues.provenance.json").unlink()
    status, detail = _check(kettle, tmp_path, "fw.bard_cues_provenance")
    assert status == "fail" and detail.startswith("unknown: no envelope v3")


def test_power_export_writes_sidecar(
    kettle: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENHANDS_PROJECT_DIR", str(kettle.parent))
    out = tmp_path / "out"
    assert service.power_payload(kettle, out)["verdict"] == "pass"
    power = out / "smart-kettle.fw-power.json"
    assert check_envelope(power, "firmware", kettle.parent)[0] == "pass"


def test_broken_decision_log_refuses_export(
    kettle: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENHANDS_PROJECT_DIR", str(kettle.parent))
    log = kettle.parent / "observations" / "firmware" / "decisions.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text("{forged\n", encoding="utf-8")
    out = tmp_path / "out"
    payload = service.power_payload(kettle, out)
    assert payload["verdict"] == "fail"
    assert "provenance refused" in str(payload["detail"])
    assert not sidecar_path(out / "smart-kettle.fw-power.json").exists()
