"""Feed captured Trivy fixtures through the workflows' inline Python steps.

The audit/report logic lives in `python3 - <<'PY'` heredocs inside the
workflow YAML, so the tests extract the shipped code verbatim and run it
against fixtures instead of re-implementing it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTAINER_AUDIT = REPO_ROOT / ".github" / "workflows" / "container-audit.yml"
PUBLISH = REPO_ROOT / ".github" / "workflows" / "publish-firmware-images.yml"

_HEREDOC = re.compile(
    r"(?m)^(?P<indent>[ ]*)python3 - <<'PY'[^\n]*\n(?P<body>[\s\S]*?)^(?P=indent)PY[ ]*$"
)


def step_python_block(workflow: Path, step_name: str) -> str:
    text = workflow.read_text(encoding="utf-8")
    marker = text.index(step_name)
    match = _HEREDOC.search(text, marker)
    assert match is not None, f"no python3 heredoc after {step_name!r}"
    return textwrap.dedent(match.group("body"))


def run_block(body: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    merged = {**os.environ, **env}
    return subprocess.run(
        [sys.executable, "-c", body],
        cwd=cwd,
        env=merged,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


TRIVY_JSON = {
    "Results": [
        {
            "Target": "firmware-tools",
            "Vulnerabilities": [
                {
                    "VulnerabilityID": "CVE-2024-0001",
                    "PkgName": "openssl",
                    "Severity": "CRITICAL",
                    "FixedVersion": "3.0.1",
                },
                {
                    "VulnerabilityID": "CVE-2024-0002",
                    "PkgName": "curl",
                    "Severity": "HIGH",
                    "FixedVersion": "8.1.0",
                },
                {"VulnerabilityID": "CVE-2024-0003", "PkgName": "zlib", "Severity": "HIGH"},
                {
                    "VulnerabilityID": "CVE-2024-0004",
                    "PkgName": "busybox",
                    "Severity": "MEDIUM",
                    "FixedVersion": "1.2",
                },
            ],
            "Misconfigurations": [{"Status": "PASS"}, {"Status": "FAIL"}],
            "Secrets": [{"Severity": "CRITICAL"}],
            "Licenses": [{"Name": "GPL-3.0-only"}],
        }
    ]
}

TRIVY_CIS = {
    "Results": [
        {
            "ID": "4",
            "Title": "Image",
            "Results": [
                {
                    "ID": "4.1",
                    "MisconfSummary": {"Successes": 0, "Failures": 1},
                    "Misconfigurations": [
                        {"ID": "AVD-DS-0002", "Status": "FAIL", "Severity": "HIGH"},
                        {"ID": "AVD-DS-0001", "Status": "PASS", "Severity": "LOW"},
                    ],
                },
                {
                    "ID": "4.6",
                    "MisconfSummary": {"Successes": 3, "Failures": 1},
                    "Misconfigurations": [
                        {"ID": "AVD-DS-0026", "Status": "FAIL", "Severity": "LOW"},
                        {"ID": "AVD-DS-0008", "Status": "PASS", "Severity": "LOW"},
                    ],
                },
            ],
        }
    ]
}


def write_audit_fixtures(tmp_path: Path, cis: object = TRIVY_CIS) -> dict[str, str]:
    lynis = tmp_path / "lynis-out"
    lynis.mkdir()
    (lynis / "lynis-report.dat").write_text("hardening_index=71\nwarning[]\n", encoding="utf-8")
    (tmp_path / "trivy-image.json").write_text(json.dumps(TRIVY_JSON), encoding="utf-8")
    (tmp_path / "trivy-cis.json").write_text(json.dumps(cis), encoding="utf-8")
    return {
        "TRIVY_JSON": "trivy-image.json",
        "TRIVY_CIS": str(tmp_path / "trivy-cis.json"),
        "LYNIS_OUT": str(lynis),
        "REPORT_JSON": "container-hardening.json",
        "PINNED_IMAGE": "ghcr.io/vibebb/firmware-tools@sha256:" + "a" * 64,
    }


def test_audit_report_aggregates_cis_failures_and_controls(tmp_path: Path) -> None:
    body = step_python_block(CONTAINER_AUDIT, "Compute container-hardening report")
    result = run_block(body, tmp_path, write_audit_fixtures(tmp_path))
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "container-hardening.json").read_text(encoding="utf-8"))
    assert report["cis_docker"]["passed"] == 3
    assert report["cis_docker"]["failed"] == 2
    assert report["cis_docker"]["failed_checks"] == ["AVD-DS-0002", "AVD-DS-0026"]
    assert report["gate"]["fixable_high_or_critical"] == 2
    assert report["trivy"]["critical"] == 1
    assert report["trivy"]["misconfig_pass"] == 1
    assert report["trivy"]["secrets"] == 1
    assert report["lynis"]["hardening_index"] == "71"


def test_audit_report_fails_closed_on_empty_cis_payload(tmp_path: Path) -> None:
    body = step_python_block(CONTAINER_AUDIT, "Compute container-hardening report")
    result = run_block(body, tmp_path, write_audit_fixtures(tmp_path, cis={"Results": []}))
    assert result.returncode != 0
    assert "Docker CIS scan produced no results" in result.stderr


def test_publish_gate_summary_lists_fixable_high_critical(tmp_path: Path) -> None:
    (tmp_path / "trivy-image.json").write_text(json.dumps(TRIVY_JSON), encoding="utf-8")
    body = step_python_block(PUBLISH, "Report gating CVEs")
    result = run_block(body, tmp_path, {})
    assert result.returncode == 0, result.stderr
    assert "CVE-2024-0001" in result.stdout
    assert "openssl" in result.stdout
    assert "CVE-2024-0002" in result.stdout
    # Unfixed HIGH and fixed MEDIUM must not be listed.
    assert "CVE-2024-0003" not in result.stdout
    assert "CVE-2024-0004" not in result.stdout
