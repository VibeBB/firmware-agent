from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from firmware.contract import FirmwareContract, load_contract

from .conftest import read_json


def _validate(data: dict[str, Any]) -> FirmwareContract:
    return FirmwareContract.model_validate(data)


def test_examples_load(kettle: Path, lamp: Path) -> None:
    assert load_contract(kettle).mcu.profile == "rp2040"
    assert load_contract(lamp).mcu.profile == "esp32s3"


def test_unknown_key_rejected(kettle: Path) -> None:
    data = read_json(kettle)
    data["mcu"]["speed"] = 1
    with pytest.raises(ValidationError):
        _validate(data)


@pytest.mark.parametrize("field", ["signal", "pad"])
def test_duplicate_pins_rejected(kettle: Path, field: str) -> None:
    data = read_json(kettle)
    data["pins"][1][field] = data["pins"][0][field]
    with pytest.raises(ValidationError, match="duplicate"):
        _validate(data)


def test_duplicate_bus_instance_rejected(kettle: Path) -> None:
    data = read_json(kettle)
    i2c = next(p for p in data["peripherals"] if p["kind"] == "i2c")
    data["peripherals"].append({**i2c, "id": "i2c_other"})
    with pytest.raises(ValidationError):
        _validate(data)


def test_qemu_arm_requires_exit_code(kettle: Path) -> None:
    data = read_json(kettle)
    del data["simulations"][0]["exit_code"]
    with pytest.raises(ValidationError):
        _validate(data)


def test_qemu_esp_rejects_exit_code(lamp: Path) -> None:
    data = read_json(lamp)
    data["simulations"][0]["exit_code"] = 0
    with pytest.raises(ValidationError):
        _validate(data)


def _fault(code: int, name: str) -> dict[str, Any]:
    return {"code": code, "name": name, "severity": "error", "action": "Descale the kettle"}


@pytest.mark.parametrize(("code", "valid"), [(0, False), (1, True), (65535, True), (65536, False)])
def test_fault_code_range(kettle: Path, code: int, valid: bool) -> None:
    data = read_json(kettle)
    data["faults"] = [_fault(code, "dry_boil")]
    if valid:
        assert _validate(data).faults[0].code == code
    else:
        with pytest.raises(ValidationError):
            _validate(data)


@pytest.mark.parametrize(
    "faults",
    [
        [_fault(1, "dry_boil"), _fault(1, "overheat")],
        [_fault(1, "dry_boil"), _fault(2, "dry_boil")],
    ],
)
def test_duplicate_faults_rejected(kettle: Path, faults: list[dict[str, Any]]) -> None:
    data = read_json(kettle)
    data["faults"] = faults
    with pytest.raises(ValidationError, match="duplicate fault"):
        _validate(data)
