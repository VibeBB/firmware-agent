from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from firmware import unit
from firmware.contract import UnitTests
from firmware.unit import coverage_counts, run_unit_tests

needs_gcc = pytest.mark.skipif(
    shutil.which("gcc") is None or shutil.which("gcov") is None, reason="host gcc/gcov missing"
)

CLAMP = """#include "clamp.h"
int clamp(int value, int low, int high) {
    if (value < low) {
        return low;
    }
    if (value > high) {
        return high;
    }
    return value;
}
"""
HEADER = "int clamp(int value, int low, int high);\n"
FULL = """#include "clamp.h"
int main(void) {
    if (clamp(-1, 0, 9) != 0) return 1;
    if (clamp(10, 0, 9) != 9) return 1;
    return clamp(5, 0, 9) == 5 ? 0 : 1;
}
"""
PARTIAL = '#include "clamp.h"\nint main(void) { return clamp(5, 0, 9) == 5 ? 0 : 1; }\n'


def _project(root: Path, test: str, **fields: Any) -> UnitTests:
    (root / "fw").mkdir(parents=True, exist_ok=True)
    (root / "fw/clamp.c").write_text(CLAMP, encoding="utf-8")
    (root / "fw/clamp.h").write_text(HEADER, encoding="utf-8")
    (root / "fw/test_clamp.c").write_text(test, encoding="utf-8")
    spec: dict[str, Any] = {
        "sources": ["fw/clamp.c"],
        "tests": ["fw/test_clamp.c"],
        "includes": ["fw"],
        "min_line_pct": 100,
        "min_branch_pct": 100,
        "rationale": "clamp guards the heater duty cycle",
    }
    spec.update(fields)
    return UnitTests.model_validate(spec)


@needs_gcc
def test_full_suite_meets_floors(tmp_path: Path) -> None:
    result = run_unit_tests(_project(tmp_path, FULL), tmp_path, tmp_path / "out")
    assert result.ok, result.detail
    assert result.line_pct == 100.0
    assert result.branch_pct == 100.0
    assert result.lines[1] > 0 and result.branches == (4, 4)


@needs_gcc
def test_partial_suite_fails_branch_floor(tmp_path: Path) -> None:
    result = run_unit_tests(_project(tmp_path, PARTIAL), tmp_path, tmp_path / "out")
    assert not result.ok
    assert "branch coverage 50.00% < 100" in result.detail
    assert result.branch_pct == 50.0


@needs_gcc
@pytest.mark.parametrize(("floor", "ok"), [(49.0, True), (50.0, True), (51.0, False)])
def test_branch_floor_boundary(tmp_path: Path, floor: float, ok: bool) -> None:
    spec = _project(tmp_path, PARTIAL, min_line_pct=0, min_branch_pct=floor)
    assert run_unit_tests(spec, tmp_path, tmp_path / "out").ok is ok


@needs_gcc
def test_failing_test_binary_fails(tmp_path: Path) -> None:
    spec = _project(tmp_path, "int main(void) { return 3; }\n", min_line_pct=0, min_branch_pct=0)
    result = run_unit_tests(spec, tmp_path, tmp_path / "out")
    assert not result.ok
    assert result.detail == "unit tests failed: unit-tests exited 3"


@needs_gcc
def test_compile_error_fails(tmp_path: Path) -> None:
    spec = _project(tmp_path, "int main(void) { return }\n")
    result = run_unit_tests(spec, tmp_path, tmp_path / "out")
    assert not result.ok
    assert result.detail.startswith("compile fw/test_clamp.c: gcc exited")


def test_missing_tool_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def which(_name: str) -> None:
        return None

    monkeypatch.setattr(unit.shutil, "which", which)
    result = run_unit_tests(_project(tmp_path, FULL), tmp_path, tmp_path / "out")
    assert result.detail == "unit-test tool(s) not on PATH: gcc, gcov"


def test_missing_file_fails(tmp_path: Path) -> None:
    spec = _project(tmp_path, FULL)
    (tmp_path / "fw/clamp.c").unlink()
    result = run_unit_tests(spec, tmp_path, tmp_path / "out")
    assert result.detail == "unit-test file(s) not found: fw/clamp.c"


def test_counts_only_declared_sources(tmp_path: Path) -> None:
    source = (tmp_path / "a.c").resolve()
    report: dict[str, object] = {
        "files": [
            {"file": str(source), "lines": [{"count": 1, "branches": [{"count": 0}]}]},
            {"file": str(tmp_path / "test.c"), "lines": [{"count": 0}]},
        ]
    }
    assert coverage_counts([report], {source}) == ((1, 1), (0, 1))


MALFORMED: list[dict[str, object]] = [{}, {"files": [{"lines": []}]}]


@pytest.mark.parametrize("report", MALFORMED)
def test_malformed_gcov_json_raises(report: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        coverage_counts([report], set())


@pytest.mark.parametrize(
    "fields",
    [
        {"min_line_pct": 101},
        {"min_branch_pct": -1},
        {"rationale": "too short"},
        {"tests": ["fw/clamp.c"]},
        {"timeout_s": 0},
    ],
)
def test_contract_rejects_invalid_unit_tests(tmp_path: Path, fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _project(tmp_path, FULL, **fields)
