from __future__ import annotations

import copy
import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from firmware import mcp_server, service
from firmware.gates import GateReport, run_gates
from firmware.interchange import FpgaRegmapSource

from .conftest import read_json, write_json

REGMAP: dict[str, Any] = {
    "schema_version": 1,
    "system": "fpga",
    "artifact_kind": "fpga_regmap",
    "design": "heater-ctl",
    "contract_sha256": "a" * 64,
    "device_ref": "U5",
    "bus": "i2c",
    "i2c_address": 0x42,
    "data_width": 16,
    "address_width": 4,
    "registers": [
        {
            "name": "status",
            "offset": 0,
            "access": "ro",
            "reset": 1,
            "description": "heater state",
            "fields": [
                {
                    "name": "ready",
                    "lsb": 0,
                    "width": 1,
                    "mask": 1,
                    "access": "ro",
                    "description": "",
                },
                {
                    "name": "fault",
                    "lsb": 1,
                    "width": 2,
                    "mask": 6,
                    "access": "w1c",
                    "description": "",
                },
            ],
        },
        {
            "name": "duty",
            "offset": 3,
            "access": "rw",
            "reset": 0x8000,
            "description": "",
            "fields": [],
        },
    ],
}


def _regmap_path(contract: Path) -> Path:
    return contract.parent / "fpga" / "heater-ctl.fpga-regmap.json"


def _write_regmap(contract: Path, regmap: dict[str, Any]) -> str:
    path = _regmap_path(contract)
    path.parent.mkdir(exist_ok=True)
    write_json(path, regmap)
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def linked(kettle: Path) -> Path:
    sha = _write_regmap(kettle, copy.deepcopy(REGMAP))
    data = read_json(kettle)
    data["fpga"] = {
        "regmap": "fpga/heater-ctl.fpga-regmap.json",
        "sha256": sha,
        "peripheral": "i2c_temp",
        "header": "fw/include/fw_fpga_regs.h",
    }
    write_json(kettle, data)
    return kettle


def _check(contract: Path) -> tuple[str, str]:
    report: GateReport = run_gates(contract, contract.parent / "fw-reports", full=False)
    check = next(c for c in report.checks if c.id == "fw.fpga_regmap")
    return check.status, check.detail


def _header(contract: Path) -> Path:
    return contract.parent / "fw" / "include" / "fw_fpga_regs.h"


def test_header_generated_and_gate_passes(linked: Path) -> None:
    payload = service.fpga_regs_payload(linked)
    assert payload["verdict"] == "pass" and payload["registers"] == 2
    text = _header(linked).read_text(encoding="utf-8")
    assert "#define FW_FPGA_I2C_ADDRESS 0x42u" in text
    assert "#define FW_FPGA_REG_DUTY 0x3u" in text
    assert "#define FW_FPGA_REG_DUTY_RESET 0x8000u" in text
    assert "#define FW_FPGA_REG_STATUS_WRITABLE 0" in text
    assert "#define FW_FPGA_REG_STATUS_FAULT_MASK 0x0006u" in text
    assert _check(linked) == ("pass", "")


def test_header_is_byte_deterministic(linked: Path) -> None:
    service.fpga_regs_payload(linked)
    first = _header(linked).read_bytes()
    service.fpga_regs_payload(linked)
    assert _header(linked).read_bytes() == first


def test_missing_header_fails(linked: Path) -> None:
    status, detail = _check(linked)
    assert status == "fail" and "missing" in detail


def test_changed_map_fails_until_repinned(linked: Path) -> None:
    service.fpga_regs_payload(linked)
    changed = copy.deepcopy(REGMAP)
    changed["registers"][1]["offset"] = 4
    _write_regmap(linked, changed)
    status, detail = _check(linked)
    assert status == "fail" and "re-pin" in detail
    payload = service.fpga_regs_payload(linked)
    assert payload["verdict"] == "fail" and "re-pin" in str(payload["detail"])


def test_hand_edited_header_fails(linked: Path) -> None:
    service.fpga_regs_payload(linked)
    header = _header(linked)
    header.write_text(header.read_text(encoding="utf-8").replace("0x3u", "0x4u"), encoding="utf-8")
    status, detail = _check(linked)
    assert status == "fail" and "stale" in detail


def test_bus_mismatch_fails(linked: Path) -> None:
    data = read_json(linked)
    data["fpga"]["peripheral"] = "debug_uart"
    write_json(linked, data)
    status, detail = _check(linked)
    assert status == "fail" and "uses i2c" in detail


def test_undeclared_peripheral_fails(linked: Path) -> None:
    data = read_json(linked)
    data["fpga"]["peripheral"] = "fpga_spi"
    write_json(linked, data)
    assert "not declared" in _check(linked)[1]
    assert service.fpga_regs_payload(linked)["verdict"] == "fail"


def test_missing_regmap_fails(linked: Path) -> None:
    _regmap_path(linked).unlink()
    status, detail = _check(linked)
    assert status == "fail" and "unreadable" in detail


def test_no_fpga_link(kettle: Path) -> None:
    report = run_gates(kettle, kettle.parent / "fw-reports", full=False)
    assert "fw.fpga_regmap" not in {c.id for c in report.checks}
    assert service.fpga_regs_payload(kettle)["verdict"] == "fail"


def _target(regmap: dict[str, Any], where: str) -> dict[str, Any]:
    if where == "map":
        return regmap
    if where == "field1":
        target: dict[str, Any] = regmap["registers"][0]["fields"][1]
        return target
    reg: dict[str, Any] = regmap["registers"][int(where.removeprefix("reg"))]
    return reg


@pytest.mark.parametrize(
    ("where", "key", "value", "message"),
    [
        ("map", "system", "firmware", "system"),
        ("map", "artifact_kind", "fpga_pinmap", "artifact_kind"),
        ("map", "extra", 1, "Extra inputs"),
        ("map", "i2c_address", None, "i2c_address"),
        ("map", "bus", "spi", "i2c_address"),
        ("map", "data_width", 12, "data_width"),
        ("map", "registers", [], "registers"),
        ("reg1", "offset", 0, "ascending"),
        ("reg1", "offset", 16, "address_width"),
        ("reg1", "reset", 0x10000, "reset exceeds"),
        ("reg1", "name", "status", "duplicate register"),
        ("field1", "mask", 4, "mask disagrees"),
        ("field1", "lsb", 0, "mask disagrees"),
        ("field1", "access", "rc", "access"),
    ],
)
def test_malformed_regmap_rejected(where: str, key: str, value: object, message: str) -> None:
    regmap = copy.deepcopy(REGMAP)
    _target(regmap, where)[key] = value
    with pytest.raises(ValidationError) as exc:
        FpgaRegmapSource.model_validate(regmap)
    assert message in str(exc.value)


def test_overlapping_fields_rejected() -> None:
    regmap = copy.deepcopy(REGMAP)
    regmap["registers"][0]["fields"][1].update(lsb=0, mask=3)
    with pytest.raises(ValidationError, match="overlaps"):
        FpgaRegmapSource.model_validate(regmap)


def test_colliding_macros_fail_the_gate(linked: Path) -> None:
    regmap = copy.deepcopy(REGMAP)
    regmap["registers"][1]["name"] = "status_reset"
    data = read_json(linked)
    data["fpga"]["sha256"] = _write_regmap(linked, regmap)
    write_json(linked, data)
    status, detail = _check(linked)
    assert status == "fail" and "duplicate C macro" in detail
    assert service.fpga_regs_payload(linked)["verdict"] == "fail"


def test_mcp_fpga_regs(linked: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENHANDS_PROJECT_DIR", str(linked.parents[1]))
    payload = mcp_server.dispatch("firmware_fpga_regs", {"contract_path": str(linked)})
    assert payload["verdict"] == "pass"


@pytest.mark.skipif(shutil.which("cc") is None, reason="needs a host C compiler")
def test_header_compiles_with_the_map_values(linked: Path, tmp_path: Path) -> None:
    service.fpga_regs_payload(linked)
    program = tmp_path / "regs.c"
    program.write_text(
        '#include <stdio.h>\n#include "fw_fpga_regs.h"\n'
        "int main(void)\n{\n"
        '    printf("%u %u %u %u %u %u %d\\n", FW_FPGA_REG_DUTY, FW_FPGA_REG_DUTY_RESET,\n'
        "        FW_FPGA_REG_STATUS_FAULT_SHIFT, FW_FPGA_REG_STATUS_FAULT_MASK,\n"
        "        FW_FPGA_I2C_ADDRESS, FW_FPGA_REG_COUNT, FW_FPGA_REG_DUTY_WRITABLE);\n"
        "    return 0;\n}\n",
        encoding="utf-8",
    )
    binary = tmp_path / "regs"
    include = _header(linked).parent
    subprocess.run(
        [
            "cc",
            "-std=c99",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(include),
            str(program),
            "-o",
            str(binary),
        ],
        check=True,
    )
    result = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
    assert result.stdout.split() == ["3", "32768", "1", "6", "66", "2", "1"]
