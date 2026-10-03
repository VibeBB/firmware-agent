from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import scripts.check_dependency_updates as check_dependency_updates_module
from scripts.check_dependency_updates import (
    HTTP_TIMEOUT_SECONDS,
    ROOT,
    SUBPROCESS_TIMEOUT_SECONDS,
    DependencyStatus,
    _github_latest_tag,  # pyright: ignore[reportPrivateUsage]
    check_docker_args,
    check_docker_base,
    check_git_clones,
    docker_base_image,
    main,
)


def test_github_latest_tag_treats_timeout_as_fetch_failure():
    def timed_out(url: str) -> list[str]:
        raise subprocess.TimeoutExpired(["git", "ls-remote", "--tags", url], 1)

    assert _github_latest_tag("actions/checkout", timed_out) == ""


def test_github_latest_tag_matches_prefixed_multi_segment_tags():
    def tags(url: str) -> list[str]:
        return ["jdk-27.0-m1", "jdk-27.0.0.0", "jdk-27.0.0.0-m1a", "jdk-27.0.1.0-m1"]

    latest = _github_latest_tag("ibmruntimes/semeru27-binaries", tags, prefix="jdk-")
    assert latest == "jdk-27.0.0.0"


def test_docker_args_report_fetch_failed_on_timeout():
    def timed_out(url: str) -> list[str]:
        raise subprocess.TimeoutExpired(["git", "ls-remote", "--tags", url], 1)

    def platformio(_url: str) -> dict[str, object]:
        return {"info": {"version": "6.2.0"}}

    statuses = check_docker_args(ROOT, list_remote_tags=timed_out, fetch_json=platformio)
    uv_status = next(status for status in statuses if status.name == "UV_VERSION")
    assert uv_status.latest == "?"
    assert uv_status.note == "fetch failed"
    assert uv_status.outdated is False
    assert uv_status.fetch_failed is True


def test_docker_platformio_pin_uses_pypi_latest() -> None:
    def tags(url: str) -> list[str]:
        return ["0.12.22"]

    def platformio(_url: str) -> dict[str, object]:
        return {"info": {"version": "6.3.0"}}

    statuses = check_docker_args(ROOT, list_remote_tags=tags, fetch_json=platformio)
    status = next(status for status in statuses if status.name == "PLATFORMIO_VERSION")
    assert status.current == "6.2.0"
    assert status.latest == "6.3.0"
    assert status.outdated is True
    assert status.fetch_failed is False


def test_ubuntu_26_04_digest_pin_is_supported(tmp_path: Path) -> None:
    docker_dir = tmp_path / "docker"
    docker_dir.mkdir()
    (docker_dir / "firmware-tools.Dockerfile").write_text(
        "FROM ubuntu:26.04@sha256:" + "a" * 64 + "\n",
        encoding="utf-8",
    )
    assert docker_base_image(tmp_path) == ("ubuntu", "26.04")

    def tags(_url: str) -> dict[str, object]:
        return {"results": [{"name": "24.04"}, {"name": "26.04"}], "next": None}

    statuses = check_docker_base(tmp_path, fetch_json=tags)
    assert len(statuses) == 1
    assert statuses[0].current == "26.04"
    assert statuses[0].latest == "26.04"
    assert statuses[0].outdated is False
    assert statuses[0].fetch_failed is False


def test_lynis_clone_pin_parsed():
    statuses = check_git_clones(ROOT, list_remote_tags=lambda url: ["3.1.7"])
    lynis = next(status for status in statuses if status.name == "CISOfy/lynis")
    assert lynis.current == "3.1.7"
    assert lynis.latest == "3.1.7"
    assert lynis.outdated is False


def test_git_clones_report_outdated_and_fetch_failed():
    statuses = check_git_clones(ROOT, list_remote_tags=lambda url: ["3.1.7", "3.2.0"])
    lynis = next(status for status in statuses if status.name == "CISOfy/lynis")
    assert lynis.latest == "3.2.0"
    assert lynis.outdated is True

    def failed_tags(url: str) -> list[str]:
        raise OSError(url)

    statuses = check_git_clones(ROOT, list_remote_tags=failed_tags)
    lynis = next(status for status in statuses if status.name == "CISOfy/lynis")
    assert lynis.latest == "?"
    assert lynis.fetch_failed is True
    assert lynis.outdated is False


def test_subprocess_timeout_is_bounded():
    assert SUBPROCESS_TIMEOUT_SECONDS >= HTTP_TIMEOUT_SECONDS > 0


def test_main_reports_timeout_as_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    def timed_out(repo_root: Path) -> list[DependencyStatus]:
        raise subprocess.TimeoutExpired(["uv", "lock"], SUBPROCESS_TIMEOUT_SECONDS)

    monkeypatch.setattr(check_dependency_updates_module, "check_dependency_updates", timed_out)
    assert main([]) == 1
    assert "dependency update check failed" in capsys.readouterr().err


def test_main_counts_unknown_fetches_in_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    def fetch_failed(_repo_root: Path) -> list[DependencyStatus]:
        return [
            DependencyStatus(
                "github-actions",
                "actions/checkout",
                "sha-pinned",
                "?",
                ".github/workflows",
                False,
                "fetch failed",
                fetch_failed=True,
            )
        ]

    monkeypatch.setattr(
        check_dependency_updates_module,
        "check_dependency_updates",
        fetch_failed,
    )
    report = tmp_path / "report.json"
    assert main(["--repo-root", str(tmp_path), "--json", str(report)]) == 0
    capsys.readouterr()
    assert json.loads(report.read_text(encoding="utf-8"))["unknown_count"] == 1
