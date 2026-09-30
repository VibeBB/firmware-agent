from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "firmware"
LAUNCHER = PLUGIN_ROOT / "scripts" / "firmware_launcher.py"


def _load_launcher() -> ModuleType:
    spec = importlib.util.spec_from_file_location("firmware_launcher_test", LAUNCHER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _empty_cache_dirs(_pattern: str) -> list[Path]:
    return []


def _docker_on_path(_name: str) -> str:
    return "docker"


def test_docker_argv_passes_workspace_root_for_subdirectory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subdirectory = tmp_path / "nested"
    subdirectory.mkdir()
    monkeypatch.setenv("OPENHANDS_PROJECT_DIR", str(tmp_path))
    monkeypatch.chdir(subdirectory)
    argv = _load_launcher().docker_argv("img", None, ["mcp_server"])
    env_pairs = [argv[index + 1] for index, arg in enumerate(argv) if arg == "-e"]
    assert f"OPENHANDS_PROJECT_DIR={tmp_path}" in env_pairs
    assert argv[argv.index("-w") + 1] == str(subdirectory)
    assert argv[argv.index("--network") + 1] == "none"


def test_null_image_locks_are_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_launcher()
    plugin_root = tmp_path / "plugins" / "firmware"
    plugin_root.mkdir(parents=True)
    (plugin_root / "tools-image.json").write_text(
        json.dumps({"image": "ghcr.io/vibebb/firmware-tools", "digest": None, "tag": None}),
        encoding="utf-8",
    )
    lock_dir = tmp_path / "docker"
    lock_dir.mkdir()
    (lock_dir / "image-digests.json").write_text(
        json.dumps(
            {
                "firmware_tools": {
                    "image": "ghcr.io/vibebb/firmware-tools",
                    "digest": None,
                    "tag": None,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("FIRMWARE_TOOLS_IMAGE", raising=False)
    monkeypatch.setattr(module, "_cache_dirs", _empty_cache_dirs)
    assert module.image_ref(plugin_root) is None


def test_plugin_image_digest_pin_precedes_repository_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_launcher()
    plugin_root = tmp_path / "plugins" / "firmware"
    plugin_root.mkdir(parents=True)
    plugin_digest = "sha256:" + "a" * 64
    (plugin_root / "tools-image.json").write_text(
        json.dumps(
            {
                "image": "ghcr.io/vibebb/firmware-tools",
                "digest": plugin_digest,
                "tag": "plugin",
            }
        ),
        encoding="utf-8",
    )
    lock_dir = tmp_path / "docker"
    lock_dir.mkdir()
    (lock_dir / "image-digests.json").write_text(
        json.dumps(
            {
                "firmware_tools": {
                    "image": "ghcr.io/vibebb/firmware-tools",
                    "digest": "sha256:" + "b" * 64,
                    "tag": "repository",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("FIRMWARE_TOOLS_IMAGE", raising=False)
    monkeypatch.setattr(module, "_cache_dirs", _empty_cache_dirs)
    assert module.image_ref(plugin_root) == (f"ghcr.io/vibebb/firmware-tools@{plugin_digest}")


def test_inspect_timeout_fails_without_pulling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_launcher()
    monkeypatch.setattr(module.shutil, "which", _docker_on_path)
    calls: list[tuple[list[str], object]] = []

    def timeout_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        timeout = kwargs["timeout"]
        calls.append((args, timeout))
        raise subprocess.TimeoutExpired(args, timeout)

    monkeypatch.setattr(module.subprocess, "run", timeout_run)
    with pytest.raises(RuntimeError, match="docker image inspect timed out after 30s"):
        module._ensure_image("image:tag", pull=True)
    assert calls == [(["docker", "image", "inspect", "image:tag"], 30)]


def test_pull_timeout_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_launcher()
    monkeypatch.setattr(module.shutil, "which", _docker_on_path)
    calls: list[tuple[list[str], object]] = []

    def timeout_pull(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        timeout = kwargs["timeout"]
        calls.append((args, timeout))
        if args[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(args, 1)
        raise subprocess.TimeoutExpired(args, timeout)

    monkeypatch.setattr(module.subprocess, "run", timeout_pull)
    with pytest.raises(RuntimeError, match="docker pull timed out after 900s"):
        module._ensure_image("image:tag", pull=True)
    assert calls == [
        (["docker", "image", "inspect", "image:tag"], 30),
        (["docker", "pull", "image:tag"], 900),
    ]
