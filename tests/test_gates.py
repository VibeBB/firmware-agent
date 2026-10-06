from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from firmware import service
from firmware.gates import GateReport, run_gates

from .conftest import read_json, write_json

type Mutation = Callable[[dict[str, Any]], None]


def _static(contract: Path) -> GateReport:
    return run_gates(contract, contract.parent / "fw-reports", full=False)


def _status(report: GateReport) -> dict[str, str]:
    return {check.id: check.status for check in report.checks}


def _detail(report: GateReport, gate: str) -> str:
    return next(check.detail for check in report.checks if check.id == gate)


@pytest.mark.parametrize("example", ["kettle", "lamp"])
def test_static_gates_pass(example: str, request: pytest.FixtureRequest) -> None:
    contract: Path = request.getfixturevalue(example)
    report = _static(contract)
    assert report.verdict == "pass", report.model_dump_json(indent=2)
    cue_gate = {"fw.bard_cues"} if example == "kettle" else set[str]()
    assert set(_status(report)) == {
        "fw.contract",
        "fw.pin_functions",
        "fw.netlist_match",
        "fw.power_modes",
        "fw.pins_header",
        *cue_gate,
    }


def _pin(data: dict[str, Any], signal: str) -> dict[str, Any]:
    return next(p for p in data["pins"] if p["signal"] == signal)


def _wrong_function(d: dict[str, Any]) -> None:
    _pin(d, "temp_sda")["pad"] = "GPIO7"


def _reserved_pad(d: dict[str, Any]) -> None:
    _pin(d, "boil_button")["pad"] = "QSPI_SS"


def _unknown_pad(d: dict[str, Any]) -> None:
    _pin(d, "boil_button")["pad"] = "GPIO99"


def _bus_without_peripheral(d: dict[str, Any]) -> None:
    del _pin(d, "temp_sda")["peripheral"]


def _missing_instance(d: dict[str, Any]) -> None:
    next(p for p in d["peripherals"] if p["kind"] == "i2c")["instance"] = 7


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        (_wrong_function, "cannot route"),
        (_reserved_pad, "reserved"),
        (_unknown_pad, "GPIO99"),
        (_missing_instance, "i2c7"),
        (_bus_without_peripheral, "needs a i2c peripheral"),
    ],
)
def test_pin_functions_fail(kettle: Path, mutate: Mutation, needle: str) -> None:
    data = read_json(kettle)
    mutate(data)
    write_json(kettle, data)
    report = _static(kettle)
    assert _status(report)["fw.pin_functions"] == "fail"
    assert needle in _detail(report, "fw.pin_functions")
    assert report.verdict == "fail"


def test_netlist_wrong_net(kettle: Path) -> None:
    data = read_json(kettle)
    _pin(data, "heater_en")["net"] = "HEATER_OTHER"
    write_json(kettle, data)
    report = _static(kettle)
    assert _status(report)["fw.netlist_match"] == "fail"
    assert "HEATER_OTHER" in _detail(report, "fw.netlist_match")


def test_netlist_wrong_mcu_ref(kettle: Path) -> None:
    data = read_json(kettle)
    data["mcu"]["ref"] = "U9"
    write_json(kettle, data)
    assert _status(_static(kettle))["fw.netlist_match"] == "fail"


def test_netlist_unassigned_active_pad(kettle: Path) -> None:
    data = read_json(kettle)
    data["pins"] = [p for p in data["pins"] if p["signal"] != "lid_switch"]
    for mode in data["power"]["modes"]:
        mode["wake"] = [w for w in mode.get("wake", []) if w != "lid_switch"]
    write_json(kettle, data)
    report = _static(kettle)
    assert _status(report)["fw.netlist_match"] == "fail"
    assert "LID_SW" in _detail(report, "fw.netlist_match")


def test_netlist_missing_circuit_file(kettle: Path) -> None:
    (kettle.parent / "circuit" / "smart-kettle.firmware.json").unlink()
    report = _static(kettle)
    assert _status(report)["fw.contract"] == "fail"
    assert _status(report)["fw.netlist_match"] == "fail"


def test_esp_alias_resolution(lamp: Path) -> None:
    report = _static(lamp)
    assert _status(report)["fw.netlist_match"] == "pass"


def _duty(d: dict[str, Any]) -> None:
    d["power"]["modes"][0]["duty"] = 0.5


def _budget(d: dict[str, Any]) -> None:
    d["power"]["average_budget_ua"] = 1


def _no_wake(d: dict[str, Any]) -> None:
    for mode in d["power"]["modes"]:
        if mode["kind"] != "run":
            mode["wake"] = []


def _bad_deep_wake(d: dict[str, Any]) -> None:
    for mode in d["power"]["modes"]:
        if mode["kind"] == "deep_sleep":
            mode["wake"] = ["temp_sda"]


def _unknown_peripheral(d: dict[str, Any]) -> None:
    d["power"]["modes"][0]["peripherals_on"] = ["ghost"]


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        (_duty, "sum to"),
        (_budget, "exceeds budget"),
        (_no_wake, "without a wake source"),
        (_bad_deep_wake, "not gpio_in"),
        (_unknown_peripheral, "unknown peripheral"),
    ],
)
def test_power_modes_fail(kettle: Path, mutate: Mutation, needle: str) -> None:
    data = read_json(kettle)
    mutate(data)
    write_json(kettle, data)
    report = _static(kettle)
    assert _status(report)["fw.power_modes"] == "fail"
    assert needle in _detail(report, "fw.power_modes")


def test_pins_header_stale_then_regenerated(kettle: Path) -> None:
    header = kettle.parent / "fw" / "include" / "fw_pins.h"
    header.write_text(header.read_text() + "/* edited */\n")
    assert _status(_static(kettle))["fw.pins_header"] == "fail"
    assert service.pins_payload(kettle)["verdict"] == "pass"
    assert _status(_static(kettle))["fw.pins_header"] == "pass"


def test_invalid_contract_fails_closed(kettle: Path) -> None:
    kettle.write_text("{not json")
    report = _static(kettle)
    assert report.verdict == "fail"
    assert report.checks[0].id == "fw.contract"


def test_full_gates_fail_closed_without_tools(
    kettle: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", "/nonexistent")
    report = run_gates(kettle, kettle.parent / "fw-reports", full=True)
    status = _status(report)
    assert report.verdict == "fail"
    for gate in ("fw.build", "fw.memory_budget", "fw.static_analysis", "fw.sim.kettle_logic"):
        assert status[gate] == "fail", gate


def test_pinmap_export(kettle: Path, tmp_path: Path) -> None:
    payload = service.pinmap_payload(kettle, tmp_path / "out")
    assert payload["verdict"] == "pass"
    pinmap = read_json(tmp_path / "out" / "smart-kettle.fw-pinmap.json")
    assert pinmap["artifact_kind"] == "firmware_pinmap"
    assert pinmap["mcu_ref"] == "U1"
    assert {p["signal"] for p in pinmap["pins"]} >= {"heater_en", "temp_sda"}
    assert all(p["pad"] not in {q["pad"] for q in pinmap["pins"]} for p in pinmap["free_pads"])


def test_request_artifact(kettle: Path, tmp_path: Path) -> None:
    payload = service.request_payload(
        kettle,
        tmp_path,
        target="circuit",
        risk="low",
        change="Move LED_RING to a PWM-capable pad",
        rationale="PWM slice conflicts with the buzzer",
        nets=["LED_RING"],
        failing_checks=["fw.pin_functions"],
    )
    assert payload["verdict"] == "pass"
    written = list(tmp_path.glob("*.fw-request.json"))
    assert len(written) == 1
    assert read_json(written[0])["target"] == "circuit"
