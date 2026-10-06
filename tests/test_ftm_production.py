from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from firmware import cli, mcp_server
from firmware.contract import load_contract
from firmware.gates import Check, GateReport, check_ftm, run_gates

from .conftest import read_json, write_json

SPEC = Path(__file__).parent / "fixtures" / "prodeng" / "smart-kettle.factory-test-spec.json"
HEADER = "fw/include/fw_ftm.h"
ELF = "fw/build/smart-kettle.elf"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _with_ftm(kettle: Path, *, spec: dict[str, Any] | None = None) -> Path:
    target = kettle.parent / "prodeng" / "factory-test-spec.json"
    target.parent.mkdir()
    if spec is None:
        shutil.copyfile(SPEC, target)
    else:
        target.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    data = read_json(kettle)
    data["pins"] += [
        {"signal": "ftm_strap", "pad": "GPIO7", "net": "FTM_STRAP", "function": "gpio_in"},
        {
            "signal": "ftm_tx",
            "pad": "GPIO8",
            "net": "UART_TX",
            "function": "uart_tx",
            "peripheral": "ftm_uart",
        },
        {
            "signal": "ftm_rx",
            "pad": "GPIO9",
            "net": "UART_RX",
            "function": "uart_rx",
            "peripheral": "ftm_uart",
        },
    ]
    data["peripherals"].append({"id": "ftm_uart", "kind": "uart", "instance": 1, "baud": 115200})
    data["ftm"] = {
        "spec": "prodeng/factory-test-spec.json",
        "sha256": _sha(target),
        "header": HEADER,
        "peripheral": "ftm_uart",
    }
    write_json(kettle, data)
    return target


def _edit(kettle: Path, **changes: Any) -> None:
    data = read_json(kettle)
    data["ftm"].update(changes)
    write_json(kettle, data)


def _ftm(kettle: Path) -> Check:
    return check_ftm(load_contract(kettle), kettle)


def test_ftm_header_carries_the_command_table(kettle: Path) -> None:
    _with_ftm(kettle)
    assert cli.main(["ftm", str(kettle)]) == 0
    text = (kettle.parent / HEADER).read_text(encoding="utf-8")
    assert f'#define FW_FTM_SPEC_SHA256 "{_sha(SPEC)}"' in text
    assert '#define FW_FTM_ENTRY "gpio_strap"' in text
    assert '#define FW_FTM_LOCKOUT "nvm_flag"' in text
    assert "#define FW_FTM_PERIPH FW_PERIPH_FTM_UART_INSTANCE" in text
    assert "#define FW_FTM_MAX_DURATION_MS 6000u" in text
    assert "#define FW_FTM_CMD_BOARD_AND_HEATER_SENSOR_CHECK 0u /* TC-01 */" in text
    assert '{"TC-01", "TEST SENSORS", "SENSORS PASS", 2000u, 0u}' in text
    assert "#define FW_FTM_PROVISION_SERIAL_NUMBER 1 /* write once */" in text
    check = _ftm(kettle)
    assert check.status == "pass", check.detail
    assert "commands=TC-01,TC-02" in check.evidence


def test_ftm_header_compiles(kettle: Path, tmp_path: Path) -> None:
    gcc = shutil.which("gcc")
    if gcc is None:
        pytest.skip("gcc not installed")
    import subprocess

    _with_ftm(kettle)
    assert cli.main(["pins", str(kettle)]) == 0
    assert cli.main(["ftm", str(kettle)]) == 0
    source = tmp_path / "use.c"
    source.write_text(
        '#include "fw_pins.h"\n#include "fw_ftm.h"\n'
        "static const fw_ftm_command_t table[] = FW_FTM_COMMANDS;\n"
        "int main(void) { return (int)(sizeof table / sizeof table[0]) - "
        "(int)FW_FTM_COMMAND_COUNT + FW_FTM_PERIPH - 1; }\n",
        encoding="utf-8",
    )
    include = kettle.parent / "fw" / "include"
    subprocess.run(
        [
            gcc,
            "-std=c11",
            "-Wall",
            "-Werror",
            "-I",
            str(include),
            str(source),
            "-o",
            str(tmp_path / "use"),
        ],
        check=True,
    )
    assert subprocess.run([str(tmp_path / "use")], check=False).returncode == 0


def test_ftm_gate_runs_in_static_gates(kettle: Path, tmp_path: Path) -> None:
    _with_ftm(kettle)
    report = run_gates(kettle, tmp_path / "out", full=False)
    ftm = next(check for check in report.checks if check.id == "fw.ftm")
    assert ftm.status == "fail"
    assert "missing; run `firmware ftm`" in ftm.detail


def test_ftm_fails_on_a_changed_spec(kettle: Path) -> None:
    spec = _with_ftm(kettle)
    assert cli.main(["ftm", str(kettle)]) == 0
    spec.write_text(spec.read_text(encoding="utf-8").replace("2000", "2500"), encoding="utf-8")
    assert "re-pin ftm.sha256" in _ftm(kettle).detail
    assert cli.main(["ftm", str(kettle)]) == 1


def test_ftm_fails_on_a_stale_header(kettle: Path) -> None:
    _with_ftm(kettle)
    assert cli.main(["ftm", str(kettle)]) == 0
    header = kettle.parent / HEADER
    header.write_text(header.read_text(encoding="utf-8") + "/* edit */\n", encoding="utf-8")
    assert "stale" in _ftm(kettle).detail


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"peripheral": None}, "needs ftm.peripheral"),
        ({"peripheral": "ghost"}, "ftm peripheral ghost is not declared"),
        ({"peripheral": "i2c_temp"}, "ftm peripheral i2c_temp is i2c"),
        (
            {"peripheral": "debug_uart"},
            "no factory test net is routed to ftm peripheral debug_uart",
        ),
    ],
)
def test_ftm_fails_on_a_wrong_peripheral(
    kettle: Path, change: dict[str, Any], message: str
) -> None:
    _with_ftm(kettle)
    _edit(kettle, **change)
    check = _ftm(kettle)
    assert check.status == "fail"
    assert message in check.detail


def test_ftm_fails_on_unwired_nets_and_a_missing_strap(kettle: Path) -> None:
    _with_ftm(kettle)
    data = read_json(kettle)
    data["pins"] = [pin for pin in data["pins"] if pin["signal"] != "ftm_strap"]
    write_json(kettle, data)
    detail = _ftm(kettle).detail
    assert "factory test nets not on an MCU pin: FTM_STRAP" in detail
    assert "gpio_strap entry needs a gpio_in pin" in detail


@pytest.mark.parametrize(
    ("transport", "peripheral", "message"),
    [
        ("can", "ftm_uart", "ftm transport can has no firmware peripheral"),
        ("swd", "ftm_uart", "ftm transport swd is a debug port; drop ftm.peripheral"),
        ("swd", None, ""),
    ],
)
def test_ftm_transport_rules(
    kettle: Path, transport: str, peripheral: str | None, message: str
) -> None:
    spec = read_json(SPEC)
    spec["interface"]["transport"] = transport
    _with_ftm(kettle, spec=spec)
    _edit(kettle, peripheral=peripheral)
    if not message:
        assert cli.main(["ftm", str(kettle)]) == 0
        assert _ftm(kettle).status == "pass"
    else:
        assert message in _ftm(kettle).detail


def _mutated(kind: str) -> dict[str, Any]:
    spec = read_json(SPEC)
    first = spec["commands"][0]
    if kind == "undeclared":
        return {"declared": False, "reason": "none"}
    if kind == "extra":
        return {**spec, "extra": 1}
    if kind == "no_commands":
        return {**spec, "commands": []}
    if kind == "non_ascii":
        return {**spec, "commands": [{**first, "request": "TEST\u00b0"}]}
    return {**spec, "commands": [first, first]}


@pytest.mark.parametrize(
    ("kind", "message"),
    [
        ("undeclared", "declares no factory_test_mode"),
        ("extra", "unreadable factory test spec"),
        ("no_commands", "declares no commands"),
        ("non_ascii", "not printable ASCII"),
        ("duplicate", "duplicate C macro"),
    ],
)
def test_ftm_rejects_unusable_specs(kettle: Path, kind: str, message: str) -> None:
    _with_ftm(kettle, spec=_mutated(kind))
    check = _ftm(kettle)
    assert check.status == "fail"
    assert message in check.detail
    assert cli.main(["ftm", str(kettle)]) == 1


def test_ftm_command_needs_an_ftm_link(kettle: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["ftm", str(kettle)]) == 1
    assert "no ftm link" in capsys.readouterr().out


def _gated(kettle: Path, *, ftm: str | None = None, **report: Any) -> Path:
    elf = kettle.parent / ELF
    elf.parent.mkdir(parents=True, exist_ok=True)
    elf.write_bytes(b"\x7fELF gated image")
    checks = [] if ftm is None else [Check(id="fw.ftm", status="pass" if ftm == "pass" else "fail")]
    fields: dict[str, Any] = {
        "design": "smart-kettle",
        "scope": "full",
        "contract_sha256": _sha(kettle),
        "circuit_sha256": None,
        "profile": "rp2040",
        "verdict": "pass",
        "checks": checks,
        "elf_sha256": _sha(elf),
        **report,
    }
    out = kettle.parent / "fw-reports"
    out.mkdir(exist_ok=True)
    (out / "smart-kettle.fw-report.json").write_text(
        GateReport.model_validate(fields).model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    return out


def test_production_export_binds_the_gated_elf(
    kettle: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _gated(kettle)
    assert cli.main(["production", str(kettle)]) == 0
    payload = json.loads(capsys.readouterr().out)
    export = read_json(out / "smart-kettle.fw-production.json")
    elf = kettle.parent / ELF
    assert payload["elf_sha256"] == export["elf_sha256"] == _sha(elf)
    assert export["artifact_kind"] == "firmware_production"
    assert export["contract_sha256"] == _sha(kettle)
    assert export["gate_report_sha256"] == _sha(out / "smart-kettle.fw-report.json")
    assert export["mcu_ref"] == "U1"
    assert export["mcu_profile"] == "rp2040"
    assert export["part"] == "RP2040"
    assert export["elf"] == "../fw/build/smart-kettle.elf"
    assert export["elf_bytes"] == elf.stat().st_size
    assert export["ftm_spec_sha256"] is None
    assert export["ftm_commands"] == []


def test_production_export_carries_the_ftm_spec(kettle: Path) -> None:
    spec = _with_ftm(kettle)
    out = _gated(kettle, ftm="pass")
    assert cli.main(["production", str(kettle)]) == 0
    export = read_json(out / "smart-kettle.fw-production.json")
    assert export["ftm_spec_sha256"] == _sha(spec)
    assert export["ftm_commands"] == ["TC-01", "TC-02"]


@pytest.mark.parametrize(
    ("report", "message"),
    [
        ({"scope": "static"}, "passing `firmware gates` run"),
        ({"verdict": "fail"}, "passing `firmware gates` run"),
        ({"contract_sha256": "0" * 64}, "contract changed"),
        ({"elf_sha256": None}, "records no ELF sha256"),
        ({"elf_sha256": "1" * 64}, "differs from the gated"),
    ],
)
def test_production_export_refuses_ungated_images(
    kettle: Path, capsys: pytest.CaptureFixture[str], report: dict[str, Any], message: str
) -> None:
    out = _gated(kettle, **report)
    assert cli.main(["production", str(kettle)]) == 1
    assert message in json.loads(capsys.readouterr().out)["detail"]
    assert not (out / "smart-kettle.fw-production.json").exists()


def test_production_export_refuses_missing_evidence(
    kettle: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["production", str(kettle)]) == 1
    assert "run `firmware gates` first" in json.loads(capsys.readouterr().out)["detail"]
    _gated(kettle)
    (kettle.parent / ELF).unlink()
    assert cli.main(["production", str(kettle)]) == 1
    assert "missing" in json.loads(capsys.readouterr().out)["detail"]


@pytest.mark.parametrize("ftm", [None, "fail"])
def test_production_export_needs_a_passing_ftm_gate(kettle: Path, ftm: str | None) -> None:
    _with_ftm(kettle)
    _gated(kettle, ftm=ftm)
    assert cli.main(["production", str(kettle)]) == 1


def test_production_export_refuses_a_changed_spec(kettle: Path) -> None:
    spec = _with_ftm(kettle)
    _gated(kettle, ftm="pass")
    spec.write_text(spec.read_text(encoding="utf-8").replace("2000", "2500"), encoding="utf-8")
    assert cli.main(["production", str(kettle)]) == 1


def test_mcp_ftm_and_production(kettle: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENHANDS_PROJECT_DIR", str(kettle.parent))
    _with_ftm(kettle)
    assert mcp_server.dispatch("firmware_ftm", {"contract_path": str(kettle)})["verdict"] == "pass"
    _gated(kettle, ftm="pass")
    payload = mcp_server.dispatch("firmware_production_export", {"contract_path": str(kettle)})
    assert payload["verdict"] == "pass"
    assert (kettle.parent / "fw-reports" / "smart-kettle.fw-production.json").is_file()


@pytest.mark.skipif(
    not all(shutil.which(tool) for tool in ("make", "arm-none-eabi-gcc", "cppcheck")),
    reason="firmware toolchain not installed",
)
def test_production_export_after_real_full_gates(kettle: Path, tmp_path: Path) -> None:
    out = tmp_path / "reports"
    assert cli.main(["gates", str(kettle), "--out", str(out)]) == 0
    assert cli.main(["production", str(kettle), "--out", str(out)]) == 0
    export = read_json(out / "smart-kettle.fw-production.json")
    report = read_json(out / "smart-kettle.fw-report.json")
    assert export["elf_sha256"] == report["elf_sha256"] == _sha(kettle.parent / ELF)
