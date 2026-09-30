"""Workflow asset-path drift tests."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))

PLUGIN_PATH = re.compile(r"plugins/firmware(?:/[\w\-/*{}.,]+)?")

GENERATED = {"plugins/firmware/tools-image.json"}


def test_workflows_exist() -> None:
    assert WORKFLOWS, "no workflow files found"


def test_plugin_paths_referenced_exist() -> None:
    missing: list[str] = []
    for workflow in WORKFLOWS:
        text = workflow.read_text(encoding="utf-8")
        for literal in PLUGIN_PATH.findall(text):
            path = literal.rstrip(".,'\"")
            if path in GENERATED:
                continue
            if "*" in path:
                if not list(REPO_ROOT.glob(path)):
                    missing.append(f"{workflow.name}: {path}")
            elif not (REPO_ROOT / path).exists():
                missing.append(f"{workflow.name}: {path}")
    assert not missing, f"workflow references missing paths: {missing}"


def test_locked_image_workflows_run_firmware_launcher() -> None:
    for name in ("publish-firmware-images.yml", "locked-image-check.yml"):
        text = (REPO_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert "plugins/firmware/scripts/firmware_launcher.py" in text
        assert "FIRMWARE_TOOLS_IMAGE" in text
        assert "FIRMWARE_SRC" in text
        assert "lamp_selftest" in text
