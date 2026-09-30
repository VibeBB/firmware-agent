"""Static analysis through cppcheck (separate process, XML v2 parsed)."""

from __future__ import annotations

import fnmatch
import shutil
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .contract import Analysis

IGNORED_IDS = frozenset(
    {"checkersReport", "missingIncludeSystem", "unmatchedSuppression", "toomanyconfigs"}
)


@dataclass(frozen=True)
class Finding:
    id: str
    severity: str
    message: str
    file: str
    line: int


@dataclass
class AnalysisResult:
    ok: bool
    detail: str
    tool_version: str = ""
    blocking: list[Finding] = field(default_factory=list[Finding])
    suppressed: list[Finding] = field(default_factory=list[Finding])
    advisory: list[Finding] = field(default_factory=list[Finding])


def cppcheck_argv(analysis: Analysis, root: Path) -> list[str]:
    argv = [
        "cppcheck",
        "--xml",
        "--xml-version=2",
        "--enable=warning,style,performance,portability",
        f"--std={analysis.std}",
        "--quiet",
        "--error-exitcode=0",
    ]
    argv += [f"-I{(root / include).as_posix()}" for include in analysis.includes]
    argv += [f"-D{define}" for define in analysis.defines]
    argv += [(root / source).as_posix() for source in analysis.sources]
    return argv


def parse_findings(xml_text: str, root: Path) -> list[Finding]:
    try:
        tree = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"cppcheck XML unparseable: {exc}") from exc
    findings: list[Finding] = []
    for error in tree.iter("error"):
        finding_id = error.get("id", "")
        severity = error.get("severity", "")
        if finding_id in IGNORED_IDS or severity == "information":
            continue
        location = error.find("location")
        file = location.get("file", "") if location is not None else ""
        line = int(location.get("line", "0")) if location is not None else 0
        path = Path(file)
        if path.is_absolute():
            try:
                file = path.resolve().relative_to(root.resolve()).as_posix()
            except ValueError:
                file = path.as_posix()
        findings.append(Finding(finding_id, severity, error.get("msg", ""), file, line))
    return sorted(findings, key=lambda f: (f.file, f.line, f.id))


def _suppressed(finding: Finding, analysis: Analysis) -> bool:
    return any(
        s.id == finding.id and (s.file is None or fnmatch.fnmatch(finding.file, s.file))
        for s in analysis.suppressions
    )


def run_cppcheck(analysis: Analysis, root: Path, timeout_s: int = 600) -> AnalysisResult:
    if shutil.which("cppcheck") is None:
        return AnalysisResult(False, "cppcheck not found on PATH")
    missing = [s for s in analysis.sources if not (root / s).exists()]
    if missing:
        return AnalysisResult(False, f"analysis sources missing: {', '.join(missing)}")
    try:
        version = subprocess.run(
            ["cppcheck", "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        ).stdout.strip()
    except subprocess.TimeoutExpired:
        return AnalysisResult(False, "cppcheck --version timed out after 20s")
    proc = subprocess.run(
        cppcheck_argv(analysis, root),
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_s,
    )
    if proc.returncode != 0:
        return AnalysisResult(False, f"cppcheck exited {proc.returncode}", version)
    findings = parse_findings(proc.stderr, root)
    result = AnalysisResult(True, "", version)
    for finding in findings:
        if _suppressed(finding, analysis):
            result.suppressed.append(finding)
        elif finding.severity in analysis.fail_on:
            result.blocking.append(finding)
        else:
            result.advisory.append(finding)
    result.ok = not result.blocking
    result.detail = (
        f"{len(result.blocking)} blocking, {len(result.suppressed)} suppressed, "
        f"{len(result.advisory)} advisory finding(s)"
    )
    return result
