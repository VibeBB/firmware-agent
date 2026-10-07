from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import scripts.check_dependency_updates as check_dependency_updates_module
from scripts.check_dependency_updates import (
    _ACTION,  # pyright: ignore[reportPrivateUsage]
    HTTP_TIMEOUT_SECONDS,
    ROOT,
    SUBPROCESS_TIMEOUT_SECONDS,
    DependencyStatus,
    _action_repo,  # pyright: ignore[reportPrivateUsage]
    _github_latest_tag,  # pyright: ignore[reportPrivateUsage]
    check_docker_args,
    check_docker_base,
    check_docker_debs,
    check_git_clones,
    check_github_actions,
    check_workflow_downloads,
    docker_base_image,
    main,
    workflow_files,
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
        return ["0.12.23"]

    def platformio(_url: str) -> dict[str, object]:
        return {"info": {"version": "6.3.0"}}

    statuses = check_docker_args(ROOT, list_remote_tags=tags, fetch_json=platformio)
    status = next(status for status in statuses if status.name == "PLATFORMIO_VERSION")
    assert status.current == "6.2.0"
    assert status.latest == "6.3.0"
    assert status.outdated is True
    assert status.fetch_failed is False


def test_docker_debs_track_debian_sid() -> None:
    def fetch_json(url: str):
        assert url == "https://sources.debian.org/api/src/cppcheck/"
        return {
            "versions": [
                {"version": "2.17.1-2", "suites": ["trixie"]},
                {"version": "2.22.0-1", "suites": ["sid"]},
            ]
        }

    statuses = check_docker_debs(ROOT, fetch_json=fetch_json)
    rows = [(s.name, s.current, s.latest, s.outdated) for s in statuses]
    assert rows == [("CPPCHECK_VERSION", "2.22.0-1", "2.22.0-1", False)]


def test_docker_debs_flag_newer_sid_release() -> None:
    def fetch_json(url: str):
        return {"versions": [{"version": "9.99.0-1", "suites": ["sid"]}]}

    statuses = check_docker_debs(ROOT, fetch_json=fetch_json)
    assert statuses[0].outdated is True
    assert statuses[0].latest == "9.99.0-1"


def test_docker_debs_report_fetch_failed_on_error() -> None:
    def fetch_json(url: str):
        raise OSError("network down")

    statuses = check_docker_debs(ROOT, fetch_json=fetch_json)
    assert statuses[0].latest == "?"
    assert statuses[0].note == "fetch failed"
    assert statuses[0].fetch_failed is True


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


def test_action_statuses_strip_subpath_actions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workflow = tmp_path / "lint.yml"
    sha = "2892aa5e19bbd11bc0cff5427e3b750a04d9e3c2"
    workflow.write_text(
        f"- uses: github/codeql-action/upload-sarif@{sha} # v4.38.2\n"
        "- uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1\n",
        encoding="utf-8",
    )

    def fake_workflow_files(_root: Path) -> list[Path]:
        return [workflow]

    monkeypatch.setattr(check_dependency_updates_module, "workflow_files", fake_workflow_files)
    urls: list[str] = []

    def tags(url: str) -> list[str]:
        urls.append(url)
        return []

    statuses = check_github_actions(tmp_path, list_remote_tags=tags)
    assert {s.name for s in statuses} == {
        "github/codeql-action",
        "actions/checkout",
    }
    assert set(urls) == {
        "https://github.com/github/codeql-action",
        "https://github.com/actions/checkout",
    }


def test_every_sha_pinned_workflow_action_is_tracked() -> None:
    def no_tags(_url: str) -> list[str]:
        return []

    statuses = check_github_actions(ROOT, list_remote_tags=no_tags)
    tracked = {s.name for s in statuses if s.surface == "github-actions"}
    pinned: set[str] = set()
    for workflow in workflow_files(ROOT):
        for uses_path, _sha, _comment in _ACTION.findall(workflow.read_text(encoding="utf-8")):
            pinned.add(_action_repo(uses_path))
    assert pinned <= tracked
    assert "github/codeql-action" in tracked


def test_workflow_downloads_track_wheel_tarball_and_trivy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workflow = tmp_path / "lint.yml"
    workflow.write_text(
        "- name: actionlint\n"
        "  run: |\n"
        '    curl "https://github.com/rhysd/actionlint/releases/download/v1.7.12/actionlint_1.7.12_linux_amd64.tar.gz"\n'
        "- name: wheel\n"
        "  run: |\n"
        '    wheel="zizmor-1.30.1-py3-none-manylinux_2_28_x86_64.whl"\n'
        '    curl "https://files.pythonhosted.org/packages/ab/cd/$wheel"\n'
        "- uses: aquasecurity/trivy-action@2892aa5e19bbd11bc0cff5427e3b750a04d9e3c2\n"
        "  with:\n"
        "    version: 0.58.0\n"
        "- uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1\n",
        encoding="utf-8",
    )

    def fake_workflow_files(_root: Path) -> list[Path]:
        return [workflow]

    monkeypatch.setattr(check_dependency_updates_module, "workflow_files", fake_workflow_files)

    def fetch_json(_url: str) -> object:
        return {"info": {"version": "9.9.9"}}

    def tags(url: str) -> list[str]:
        return {
            "https://github.com/rhysd/actionlint": ["v1.7.12"],
            "https://github.com/aquasecurity/trivy": ["v0.58.0"],
        }.get(url, [])

    statuses = check_workflow_downloads(tmp_path, fetch_json=fetch_json, list_remote_tags=tags)
    assert {(s.name, s.current) for s in statuses} == {
        ("zizmor", "1.30.1"),
        ("rhysd/actionlint", "v1.7.12"),
        ("aquasecurity/trivy", "0.58.0"),
    }
    assert all(s.surface == "direct-download" for s in statuses)


def test_workflow_downloads_cover_repo_pins() -> None:
    def fetch_json(_url: str) -> object:
        return {"info": {"version": "9.9.9"}}

    def latest_nines(_url: str) -> list[str]:
        return ["v9.9.9"]

    statuses = check_workflow_downloads(ROOT, fetch_json=fetch_json, list_remote_tags=latest_nines)
    rows = {(s.name, s.current) for s in statuses}
    assert ("zizmor", "1.30.1") in rows
    assert ("rhysd/actionlint", "v1.7.12") in rows
    assert ("aquasecurity/trivy", "0.75.0") in rows


def test_uvx_statuses_deduplicated_on_name_and_pin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workflow = tmp_path / "lint.yml"
    workflow.write_text(
        "- run: uvx zizmor@1.30.1 --format sarif .\n"
        "- run: uvx zizmor@1.30.1 --format plain .\n"
        "- run: uvx zizmor@1.29.0 --format plain .\n"
        "- run: uvx ruff@0.1.0 check .\n",
        encoding="utf-8",
    )

    def fake_workflow_files(_root: Path) -> list[Path]:
        return [workflow]

    def fake_fetch_json(_url: str) -> object:
        return {"info": {"version": "9.9.9"}}

    def no_tags(_url: str) -> list[str]:
        return []

    monkeypatch.setattr(check_dependency_updates_module, "workflow_files", fake_workflow_files)
    monkeypatch.setattr(
        check_dependency_updates_module,
        "_default_fetch_json",
        fake_fetch_json,
    )
    statuses = check_github_actions(tmp_path, list_remote_tags=no_tags)
    uvx = [(s.name, s.current) for s in statuses if s.surface == "pypi-uvx"]
    assert uvx == [("zizmor", "1.30.1"), ("zizmor", "1.29.0"), ("ruff", "0.1.0")]


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
