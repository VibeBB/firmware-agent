from __future__ import annotations

from pathlib import Path

import pytest

from firmware.workspace import workspace_path


def test_workspace_path_rejects_parent_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="outside the workspace"):
        workspace_path("../outside.txt", tmp_path)


def test_workspace_path_rejects_absolute_outside_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="outside the workspace"):
        workspace_path(tmp_path.parent / "outside.txt", tmp_path)


def test_workspace_path_rejects_symlinked_component(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (tmp_path / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="contains a symlink"):
        workspace_path("linked/file.json", tmp_path)


def test_workspace_path_accepts_normal_relative_path(tmp_path: Path) -> None:
    assert workspace_path("artifacts/result.json", tmp_path) == (
        tmp_path / "artifacts" / "result.json"
    )
