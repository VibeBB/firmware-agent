from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

import pytest

from firmware import cli, mcp_server


def _export(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_power_export_carries_peak_and_average_supply_draw(
    kettle: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "out"
    assert cli.main(["power", str(kettle), "--out", str(out)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["supply_net"] == "+3V3"
    export = _export(out / "smart-kettle.fw-power.json")
    assert export["artifact_kind"] == "firmware_power"
    assert export["system"] == "firmware"
    assert export["contract_sha256"] == hashlib.sha256(kettle.read_bytes()).hexdigest()
    assert export["mcu_ref"] == "U1"
    assert export["peak_current_a"] == pytest.approx(0.025)
    assert export["average_current_a"] == pytest.approx(
        (25000 * 0.02 + 5000 * 0.08 + 180 * 0.9) / 1e6
    )
    assert len(cast(list[object], export["modes"])) == 3


def test_power_export_follows_the_contract(kettle: Path, tmp_path: Path) -> None:
    data = json.loads(kettle.read_text(encoding="utf-8"))
    data["power"]["modes"][0]["current_ua"] = 40000
    kettle.write_text(json.dumps(data), encoding="utf-8")
    out = tmp_path / "out"
    assert cli.main(["power", str(kettle), "--out", str(out)]) == 0
    export = _export(out / "smart-kettle.fw-power.json")
    assert export["peak_current_a"] == pytest.approx(0.04)
    assert export["contract_sha256"] == hashlib.sha256(kettle.read_bytes()).hexdigest()


def test_power_export_is_byte_deterministic(kettle: Path, tmp_path: Path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    assert cli.main(["power", str(kettle), "--out", str(first)]) == 0
    assert cli.main(["power", str(kettle), "--out", str(second)]) == 0
    name = "smart-kettle.fw-power.json"
    assert (first / name).read_bytes() == (second / name).read_bytes()


def test_power_export_fails_closed_on_a_bad_contract(tmp_path: Path) -> None:
    bad = tmp_path / "bad.fw.json"
    bad.write_text("{}", encoding="utf-8")
    assert cli.main(["power", str(bad), "--out", str(tmp_path / "out")]) == 1
    assert not (tmp_path / "out").exists()


def test_mcp_power_export(kettle: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENHANDS_PROJECT_DIR", str(kettle.parent))
    payload = mcp_server.dispatch("firmware_power_export", {"contract_path": str(kettle)})
    assert payload["verdict"] == "pass"
    assert (kettle.parent / "fw-reports" / "smart-kettle.fw-power.json").is_file()
