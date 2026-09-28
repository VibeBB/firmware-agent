from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture
def kettle(tmp_path: Path) -> Path:
    """Copy of the smart-kettle example; returns the contract path."""
    target = tmp_path / "smart-kettle"
    shutil.copytree(
        EXAMPLES / "smart-kettle",
        target,
        ignore=shutil.ignore_patterns("build", "fw-reports"),
    )
    return target / "smart-kettle.fw.json"


@pytest.fixture
def lamp(tmp_path: Path) -> Path:
    """Copy of the ESP32-S3 desk-lamp example; returns the contract path."""
    target = tmp_path / "desk-lamp-s3"
    shutil.copytree(
        EXAMPLES / "desk-lamp-s3",
        target,
        ignore=shutil.ignore_patterns(".pio", "fw-reports", "sdkconfig.esp32s3"),
    )
    return target / "desk-lamp.fw.json"


def read_json(path: Path) -> dict[str, Any]:
    value: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
