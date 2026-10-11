from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from firmware import cli, mcp_server
from firmware.contract import FirmwareContract, load_contract
from firmware.gates import check_sbom
from firmware.sbom import tree_sha256

COMPONENT: dict[str, Any] = {
    "name": "tinyprintf",
    "version": "1.2.0",
    "supplier": "Example Labs",
    "license": "BSD-3-Clause",
    "source": "https://example.org/tinyprintf.git",
    "paths": ["fw/third_party/tinyprintf"],
}


def _vendor(contract: Path) -> Path:
    lib = contract.parent / "fw" / "third_party" / "tinyprintf"
    lib.mkdir(parents=True)
    (lib / "tinyprintf.c").write_text("int tfp(void) { return 0; }\n", encoding="utf-8")
    (lib / "LICENSE").write_text("BSD-3-Clause\n", encoding="utf-8")
    return lib


def _declare(contract: Path, *components: dict[str, Any]) -> None:
    data = json.loads(contract.read_text(encoding="utf-8"))
    data["components"] = list(components)
    contract.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def test_sbom_gate_passes_without_vendored_code(kettle: Path) -> None:
    check = check_sbom(load_contract(kettle), kettle)
    assert check.status == "pass"
    assert check.evidence == ["no third-party components declared or vendored"]


def test_sbom_gate_fails_on_undeclared_vendored_code(kettle: Path) -> None:
    _vendor(kettle)
    check = check_sbom(load_contract(kettle), kettle)
    assert check.status == "fail"
    assert "fw/third_party/tinyprintf/LICENSE is not covered" in check.detail


def test_sbom_gate_passes_declared_component(kettle: Path) -> None:
    lib = _vendor(kettle)
    _declare(kettle, COMPONENT)
    check = check_sbom(load_contract(kettle), kettle)
    assert check.status == "pass"
    assert check.evidence == [f"tinyprintf 1.2.0 fw/third_party/tinyprintf {tree_sha256(lib)}"]


def test_sbom_gate_fails_on_missing_component_path(kettle: Path) -> None:
    _declare(kettle, COMPONENT)
    check = check_sbom(load_contract(kettle), kettle)
    assert check.status == "fail"
    assert "component tinyprintf: fw/third_party/tinyprintf missing" in check.detail


def test_sbom_gate_ignores_build_and_hidden_dirs(kettle: Path) -> None:
    for skipped in ("build/lib", ".pio/libdeps"):
        target = kettle.parent / "fw" / skipped
        target.mkdir(parents=True)
        (target / "x.c").write_text("int x;\n", encoding="utf-8")
    assert check_sbom(load_contract(kettle), kettle).status == "pass"


def test_tree_hash_tracks_content_and_names(kettle: Path) -> None:
    lib = _vendor(kettle)
    before = tree_sha256(lib)
    (lib / "tinyprintf.c").write_text("int tfp(void) { return 1; }\n", encoding="utf-8")
    edited = tree_sha256(lib)
    (lib / "tinyprintf.c").rename(lib / "printf.c")
    assert len({before, edited, tree_sha256(lib)}) == 3


@pytest.mark.parametrize(
    ("field", "value"),
    [("license", "BSD 3 Clause"), ("license", ""), ("supplier", ""), ("paths", [])],
)
def test_component_rejects_malformed_facts(kettle: Path, field: str, value: object) -> None:
    data = json.loads(kettle.read_text(encoding="utf-8"))
    data["components"] = [{**COMPONENT, field: value}]
    with pytest.raises(ValidationError):
        FirmwareContract.model_validate(data)


def test_component_rejects_duplicates_and_extra_fields(kettle: Path) -> None:
    data = json.loads(kettle.read_text(encoding="utf-8"))
    data["components"] = [COMPONENT, COMPONENT]
    with pytest.raises(ValidationError, match="duplicate component"):
        FirmwareContract.model_validate(data)
    data["components"] = [{**COMPONENT, "purl": "pkg:generic/x"}]
    with pytest.raises(ValidationError):
        FirmwareContract.model_validate(data)


def test_sbom_export_is_deterministic_cyclonedx(kettle: Path, tmp_path: Path) -> None:
    lib = _vendor(kettle)
    _declare(kettle, COMPONENT)
    out = tmp_path / "out"
    assert cli.main(["sbom", str(kettle), "--out", str(out)]) == 0
    path = out / "smart-kettle.fw-sbom.cdx.json"
    first = path.read_bytes()
    assert cli.main(["sbom", str(kettle), "--out", str(out)]) == 0
    assert path.read_bytes() == first
    bom = json.loads(first)
    assert (bom["bomFormat"], bom["specVersion"]) == ("CycloneDX", "1.5")
    assert "timestamp" not in bom["metadata"] and "serialNumber" not in bom
    (component,) = bom["components"]
    assert component["licenses"] == [{"expression": "BSD-3-Clause"}]
    assert component["hashes"] == [{"alg": "SHA-256", "content": tree_sha256(lib)}]
    assert bom["dependencies"] == [{"ref": "smart-kettle", "dependsOn": ["tinyprintf"]}]


def test_sbom_export_fails_closed(kettle: Path, tmp_path: Path) -> None:
    _vendor(kettle)
    out = tmp_path / "out"
    assert cli.main(["sbom", str(kettle), "--out", str(out)]) != 0
    assert not (out / "smart-kettle.fw-sbom.cdx.json").exists()


def test_mcp_sbom_export(kettle: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENHANDS_PROJECT_DIR", str(tmp_path))
    payload = mcp_server.dispatch(
        "firmware_sbom_export", {"contract_path": str(kettle), "out_dir": str(tmp_path)}
    )
    assert payload["verdict"] == "pass" and payload["components"] == 0
