#!/usr/bin/env python3
"""Report deterministic fw-report verdicts when an agent stops."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

SKIP_DIRECTORIES = {".git", ".venv", ".pio", "node_modules"}
MAX_DEPTH = 5


def _load_report(path: Path) -> tuple[str, str, list[str]]:
    value: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"not an object: {path}")
    verdict = value.get("verdict")
    if not isinstance(verdict, str):
        raise ValueError(f"missing verdict in {path}")
    failed: list[str] = []
    checks = value.get("checks")
    if isinstance(checks, list):
        for check in checks:
            if (
                isinstance(check, dict)
                and check.get("status") in ("fail", "unknown")
                and isinstance(check.get("id"), str)
            ):
                failed.append(str(check["id"]))
    return str(path), verdict, failed


def _find_reports(root: Path) -> list[Path]:
    reports: list[Path] = []
    for path in root.rglob("*.fw-report.json"):
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if len(relative.parts) > MAX_DEPTH:
            continue
        if any(part in SKIP_DIRECTORIES for part in relative.parts):
            continue
        if path.is_file():
            reports.append(path)
    return sorted(reports)


def main() -> int:
    try:
        event = json.load(sys.stdin)
        working_dir = Path(event.get("working_dir") or os.getcwd()).resolve()
        statuses = [_load_report(path) for path in _find_reports(working_dir)]
        if statuses:
            lines = [f"{path}: verdict={verdict}" for path, verdict, _f in statuses]
            failed = [(p, f) for p, _v, f in statuses if f]
            if failed:
                lines.append(
                    "Before finishing, state each failing firmware gate explicitly: "
                    + "; ".join(f"{path}: {', '.join(gates)}" for path, gates in failed)
                )
            context = "\n".join(lines)
        else:
            context = f"No firmware reports found under {working_dir}."
        print(json.dumps({"decision": "allow", "additionalContext": context}))
        return 0
    except Exception as exc:
        print(f"report_firmware_status: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
