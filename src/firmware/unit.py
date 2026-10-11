"""Host C unit tests of the product firmware, measured with gcov.

Every source and test file is compiled with the host ``gcc --coverage`` at
``-O0``, linked into one test binary and run; ``gcov --json-format`` then
reports line (C0) and branch (C1) coverage of the declared ``sources``
only. Missing tools, compile or link errors, a failing or timed-out test
binary and unreadable gcov output are failures.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from .contract import UnitTests

TOOLS = ("gcc", "gcov")


@dataclass
class UnitResult:
    ok: bool
    detail: str
    line_pct: float | None = None
    branch_pct: float | None = None
    lines: tuple[int, int] = (0, 0)
    branches: tuple[int, int] = (0, 0)
    log: Path | None = None
    evidence: list[str] = field(default_factory=list[str])


def compile_argv(unit: UnitTests, root: Path, source: str, obj: Path) -> list[str]:
    return [
        "gcc",
        f"-std={unit.std}",
        "-O0",
        "-g",
        "--coverage",
        *[f"-I{(root / inc).as_posix()}" for inc in unit.includes],
        *[f"-D{define}" for define in unit.defines],
        "-c",
        (root / source).as_posix(),
        "-o",
        obj.as_posix(),
    ]


def _run(argv: list[str], cwd: Path, log: Path, timeout: float) -> str | None:
    with log.open("a", encoding="utf-8") as handle:
        handle.write("$ " + " ".join(argv) + "\n")
        handle.flush()
        try:
            proc = subprocess.run(
                argv,
                cwd=cwd,
                stdout=handle,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return f"{Path(argv[0]).name} timed out after {timeout}s"
    return None if proc.returncode == 0 else f"{Path(argv[0]).name} exited {proc.returncode}"


def coverage_counts(
    reports: list[dict[str, Any]], sources: set[Path]
) -> tuple[tuple[int, int], tuple[int, int]]:
    """(covered, total) lines and branches over files in ``sources``."""
    lines = [0, 0]
    branches = [0, 0]
    for report in reports:
        files: Any = report.get("files")
        if not isinstance(files, list):
            raise ValueError("gcov JSON has no files list")
        for raw in cast(list[Any], files):
            entry = cast(dict[str, Any], raw) if isinstance(raw, dict) else {}
            name: Any = entry.get("file")
            if not isinstance(name, str):
                raise ValueError("gcov JSON file entry without a name")
            if Path(name).resolve() not in sources:
                continue
            for line in cast(list[dict[str, Any]], entry.get("lines", [])):
                lines[1] += 1
                lines[0] += 1 if line["count"] > 0 else 0
                for branch in cast(list[dict[str, Any]], line.get("branches", [])):
                    branches[1] += 1
                    branches[0] += 1 if branch["count"] > 0 else 0
    return (lines[0], lines[1]), (branches[0], branches[1])


def _gcov_reports(objects: list[Path], cwd: Path, timeout: float) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for obj in objects:
        proc = subprocess.run(
            ["gcov", "--json-format", "--stdout", "--branch-probabilities", obj.as_posix()],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=timeout,
        )
        if proc.returncode != 0:
            raise ValueError(f"gcov exited {proc.returncode} on {obj.name}")
        for text in proc.stdout.splitlines():
            if text.strip():
                reports.append(json.loads(text))
    return reports


def _pct(covered: int, total: int) -> float:
    return 100.0 if total == 0 else 100.0 * covered / total


def run_unit_tests(unit: UnitTests, root: Path, out_dir: Path) -> UnitResult:
    missing = [tool for tool in TOOLS if shutil.which(tool) is None]
    if missing:
        return UnitResult(False, f"unit-test tool(s) not on PATH: {', '.join(missing)}")
    absent = [p for p in [*unit.sources, *unit.tests] if not (root / p).is_file()]
    if absent:
        return UnitResult(False, f"unit-test file(s) not found: {', '.join(absent)}")
    work = out_dir / "unit"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    log = out_dir / "unit-tests.log"
    log.write_text("", encoding="utf-8")
    objects: list[Path] = []
    for index, source in enumerate([*unit.sources, *unit.tests]):
        obj = work / f"{index:03d}-{Path(source).stem}.o"
        error = _run(compile_argv(unit, root, source, obj), root, log, unit.timeout_s)
        if error:
            return UnitResult(False, f"compile {source}: {error}", log=log)
        objects.append(obj)
    binary = work / "unit-tests"
    link = ["gcc", "--coverage", *[o.as_posix() for o in objects], "-o", binary.as_posix()]
    error = _run(link, root, log, unit.timeout_s)
    if error:
        return UnitResult(False, f"link: {error}", log=log)
    error = _run([binary.as_posix()], root, log, unit.timeout_s)
    if error:
        return UnitResult(False, f"unit tests failed: {error}", log=log)
    measured = objects[: len(unit.sources)]
    try:
        reports = _gcov_reports(measured, work, unit.timeout_s)
        sources = {(root / s).resolve() for s in unit.sources}
        lines, branches = coverage_counts(reports, sources)
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        return UnitResult(False, f"gcov output unreadable: {exc}", log=log)
    if lines[1] == 0:
        return UnitResult(False, "gcov reported no lines for the declared sources", log=log)
    line_pct = _pct(*lines)
    branch_pct = _pct(*branches)
    problems: list[str] = []
    if line_pct < unit.min_line_pct:
        problems.append(f"line coverage {line_pct:.2f}% < {unit.min_line_pct}%")
    if branch_pct < unit.min_branch_pct:
        problems.append(f"branch coverage {branch_pct:.2f}% < {unit.min_branch_pct}%")
    return UnitResult(
        not problems,
        "; ".join(problems),
        line_pct,
        branch_pct,
        lines,
        branches,
        log,
        [
            f"lines={lines[0]}/{lines[1]} ({line_pct:.2f}%)",
            f"branches={branches[0]}/{branches[1]} ({branch_pct:.2f}%)",
        ],
    )
