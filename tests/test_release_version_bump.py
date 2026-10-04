"""Rehearse scripts/release_version_bump.sh with stubbed gh/git.

The stubs on PATH record their argv to a log file and emit canned output,
so the full bump state machine — version resolution, tag check, direct
push, PR fallback, gate dispatch, merge wait — runs in milliseconds
without touching GitHub (the tests/test_publish_image_pin_pr.py pattern).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import NamedTuple

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = f"VibeBB/{ROOT.name}"
SCRIPT = ROOT / "scripts/release_version_bump.sh"
PR_URL = f"https://github.com/{REPOSITORY}/pull/123"
HEAD_SHA = "0" * 40
MAIN_SHA = "f" * 40

GH_STUB = """#!/usr/bin/env bash
set -eu
printf '%s\\n' "$*" >> "$GH_STUB_CALLS"
case "${1:-} ${2:-}" in
  "pr create")
    printf '%s\\n' "$GH_STUB_PR_URL"
    ;;
  "workflow run")
    ;;
  "run list")
    case "$*" in
      *pull_request*)
        # Return the gated run id once, then empty so the poll exits.
        if [ "${GH_STUB_GATED:-0}" = "1" ] && \
           [ "$(grep -c 'pull_request' "$GH_STUB_CALLS")" -le 1 ]; then
          printf '777\\n'
        fi
        ;;
      *)
        printf '424242\\n'
        ;;
    esac
    ;;
  "run watch")
    ;;
  "run view")
    case "$GH_STUB_CASE" in
      gate-failure) printf 'failure\\n' ;;
      *) printf 'success\\n' ;;
    esac
    ;;
  "pr merge" | "pr close" | "pr view")
    ;;
  "api "*)
    case "$*" in
      *approve*)
        ;;
      *pulls/*)
        case "$GH_STUB_CASE" in
          merge-stalls) printf '\\n' ;;
          *) printf '2026-10-04T00:00:00Z\\n' ;;
        esac
        ;;
    esac
    ;;
esac
"""

GIT_STUB = """#!/usr/bin/env bash
set -eu
printf '%s\\n' "$*" >> "$GIT_STUB_CALLS"
case "${1:-}" in
  ls-remote)
    if [ "${GIT_STUB_TAG_EXISTS:-0}" = "1" ]; then
      printf 'deadbeef\\trefs/tags/v9.9.9\\n'
      exit 0
    fi
    exit 1
    ;;
  rev-parse)
    case "${2:-}" in
      HEAD) printf '%s\\n' "$GIT_STUB_HEAD_SHA" ;;
      *) printf '%s\\n' "$GIT_STUB_MAIN_SHA" ;;
    esac
    ;;
  push)
    if [ "${3:-}" = "HEAD:main" ] && [ "${GIT_STUB_DIRECT_PUSH_OK:-0}" != "1" ]; then
      printf 'remote: main is protected\\n' >&2
      exit 1
    fi
    ;;
esac
"""

_SKILLS = (
    "firmware-contract",
    "firmware-mcu-pinmap",
    "firmware-power-modes",
    "firmware-qemu",
    "firmware-sibling-cooperation",
    "firmware-workflow",
)


class Fixture(NamedTuple):
    repo: Path
    env: dict[str, str]
    gh_calls: Path
    git_calls: Path
    output: Path
    summary: Path


@pytest.fixture
def release_bump(tmp_path: Path) -> Fixture:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(GH_STUB, encoding="utf-8")
    gh.chmod(0o755)
    git = bin_dir / "git"
    git.write_text(GIT_STUB, encoding="utf-8")
    git.chmod(0o755)

    repo = tmp_path / "repo"
    (repo / "plugins/firmware/.plugin").mkdir(parents=True)
    (repo / "src/firmware").mkdir(parents=True)
    for skill in _SKILLS:
        skill_dir = repo / "plugins/firmware/skills" / skill
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(f"name: {skill}\nversion: 1.2.3\n", encoding="utf-8")
    (repo / "plugins/firmware/.plugin/plugin.json").write_text(
        '{\n  "version": "1.2.3"\n}\n', encoding="utf-8"
    )
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "firmware-agent"\nversion = "1.2.3"\n', encoding="utf-8"
    )
    (repo / "src/firmware/__init__.py").write_text('__version__ = "1.2.3"\n', encoding="utf-8")
    (repo / "CHANGELOG.md").write_text("## 1.2.3 — unreleased\n", encoding="utf-8")
    (repo / "uv.lock").write_text('name = "firmware-agent"\nversion = "1.2.3"\n', encoding="utf-8")

    # Exported bash functions (BASH_FUNC_gh, BASH_ENV shims in this dev
    # environment) shadow the PATH stubs inside the script; drop them.
    env = {
        key: value
        for key, value in os.environ.items()
        if key != "BASH_ENV" and not key.startswith("BASH_FUNC_")
    }
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "GITHUB_WORKSPACE": str(repo),
            "GITHUB_REPOSITORY": REPOSITORY,
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_RUN_ID": "42",
            "GITHUB_OUTPUT": str(tmp_path / "output.txt"),
            "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
            "GH_STUB_CALLS": str(tmp_path / "gh-calls.log"),
            "GH_STUB_PR_URL": PR_URL,
            "GH_STUB_CASE": "",
            "GIT_STUB_CALLS": str(tmp_path / "git-calls.log"),
            "GIT_STUB_HEAD_SHA": HEAD_SHA,
            "GIT_STUB_MAIN_SHA": MAIN_SHA,
            "BUMP": "patch",
            "SET_VERSION": "",
            "DRY_RUN": "false",
            "RELEASE_BUMP_RETRY_ATTEMPTS": "1",
            "RELEASE_BUMP_RETRY_DELAY_SECONDS": "0",
            "RELEASE_BUMP_GATED_POLL_ATTEMPTS": "10",
            "RELEASE_BUMP_GATED_POLL_SECONDS": "0",
            "RELEASE_BUMP_GATED_APPROVE_SECONDS": "0",
            "RELEASE_BUMP_RUN_DISCOVER_ATTEMPTS": "2",
            "RELEASE_BUMP_RUN_DISCOVER_SECONDS": "0",
            "RELEASE_BUMP_RUN_CONCLUSION_ATTEMPTS": "2",
            "RELEASE_BUMP_RUN_CONCLUSION_SECONDS": "0",
            "RELEASE_BUMP_MERGE_WAIT_ATTEMPTS": "2",
            "RELEASE_BUMP_MERGE_WAIT_SECONDS": "0",
        }
    )
    return Fixture(
        repo=repo,
        env=env,
        gh_calls=tmp_path / "gh-calls.log",
        git_calls=tmp_path / "git-calls.log",
        output=tmp_path / "output.txt",
        summary=tmp_path / "summary.md",
    )


def run_bump(fixture: Fixture) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=fixture.env,
        cwd=fixture.repo,
    )


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def test_dry_run_takes_the_no_commit_path(release_bump: Fixture) -> None:
    release_bump.env["DRY_RUN"] = "true"
    result = run_bump(release_bump)

    assert result.returncode == 0, result.stderr
    output = read(release_bump.output)
    assert "version=1.2.3" in output
    assert "tag=v1.2.3" in output
    assert f"sha={HEAD_SHA}" in output
    # A dry run exercises the pipeline at the current version: no tag
    # check, no commit, no push, no gh calls at all.
    git_calls = read(release_bump.git_calls)
    assert "ls-remote" not in git_calls
    assert "commit" not in git_calls
    assert "push" not in git_calls
    assert read(release_bump.gh_calls) == ""
    assert 'version = "1.2.3"' in read(release_bump.repo / "pyproject.toml")


def test_direct_push_releases_at_head(release_bump: Fixture) -> None:
    release_bump.env["GIT_STUB_DIRECT_PUSH_OK"] = "1"
    result = run_bump(release_bump)

    assert result.returncode == 0, result.stderr
    git_calls = read(release_bump.git_calls)
    assert "commit -m Release v1.2.4: update version files" in git_calls
    assert "push origin HEAD:main" in git_calls
    assert "refs/heads/bot/" not in git_calls
    assert read(release_bump.gh_calls) == ""
    output = read(release_bump.output)
    assert "version=1.2.4" in output
    assert "tag=v1.2.4" in output
    assert f"sha={HEAD_SHA}" in output
    assert 'version = "1.2.4"' in read(release_bump.repo / "pyproject.toml")


def test_push_rejection_routes_through_pull_request(release_bump: Fixture) -> None:
    result = run_bump(release_bump)

    assert result.returncode == 0, result.stderr
    gh_calls = read(release_bump.gh_calls)
    git_calls = read(release_bump.git_calls)
    assert "push origin HEAD:main" in git_calls
    assert "push origin HEAD:refs/heads/bot/release-bump-v1.2.4-42" in git_calls
    assert "pr create" in gh_calls
    assert f"workflow run ci.yml --repo {REPOSITORY} --ref bot/release-bump-v1.2.4-42" in gh_calls
    assert (
        f"workflow run workflow-lint.yml --repo {REPOSITORY} "
        "--ref bot/release-bump-v1.2.4-42" in gh_calls
    )
    assert "run watch" in gh_calls
    assert "run view" in gh_calls
    assert f"pr merge --repo {REPOSITORY} --auto --squash --delete-branch {PR_URL}" in gh_calls
    assert f"api repos/{REPOSITORY}/pulls/123" in gh_calls
    assert "fetch -q origin main" in git_calls
    output = read(release_bump.output)
    assert "version=1.2.4" in output
    assert f"sha={MAIN_SHA}" in output
    assert f"version-bump PR: {PR_URL}" in read(release_bump.summary)


def test_gated_pull_request_runs_are_approved(release_bump: Fixture) -> None:
    release_bump.env["GH_STUB_GATED"] = "1"
    result = run_bump(release_bump)

    assert result.returncode == 0, result.stderr
    gh_calls = read(release_bump.gh_calls)
    assert f"api -X POST repos/{REPOSITORY}/actions/runs/777/approve" in gh_calls


def test_existing_tag_fails_before_any_write(release_bump: Fixture) -> None:
    release_bump.env["GIT_STUB_TAG_EXISTS"] = "1"
    result = run_bump(release_bump)

    assert result.returncode == 1
    assert "tag v1.2.4 already exists" in result.stderr
    git_calls = read(release_bump.git_calls)
    assert "commit" not in git_calls
    assert "push" not in git_calls
    assert read(release_bump.gh_calls) == ""


def test_set_version_matching_current_skips_commit(release_bump: Fixture) -> None:
    release_bump.env["SET_VERSION"] = "v1.2.3"
    result = run_bump(release_bump)

    assert result.returncode == 0, result.stderr
    assert read(release_bump.gh_calls) == ""
    git_calls = read(release_bump.git_calls)
    assert "commit" not in git_calls
    assert "push" not in git_calls
    output = read(release_bump.output)
    assert "version=1.2.3" in output
    assert f"sha={HEAD_SHA}" in output


def test_set_version_applies_explicit_bump(release_bump: Fixture) -> None:
    release_bump.env["SET_VERSION"] = "2.0.0"
    release_bump.env["GIT_STUB_DIRECT_PUSH_OK"] = "1"
    result = run_bump(release_bump)

    assert result.returncode == 0, result.stderr
    assert "commit -m Release v2.0.0: update version files" in read(release_bump.git_calls)
    assert "version=2.0.0" in read(release_bump.output)
    assert '"version": "2.0.0"' in read(release_bump.repo / "plugins/firmware/.plugin/plugin.json")


def test_gate_workflow_failure_leaves_pr_open(release_bump: Fixture) -> None:
    release_bump.env["GH_STUB_CASE"] = "gate-failure"
    result = run_bump(release_bump)

    assert result.returncode == 1
    gh_calls = read(release_bump.gh_calls)
    assert "workflow run ci.yml" in gh_calls
    assert "pr merge" not in gh_calls
    assert "version-bump PR checks failed" in read(release_bump.summary)


def test_merge_timeout_fails_and_leaves_pr_open(release_bump: Fixture) -> None:
    release_bump.env["GH_STUB_CASE"] = "merge-stalls"
    result = run_bump(release_bump)

    assert result.returncode == 1
    assert "did not merge" in read(release_bump.summary)
    assert f"pr merge --repo {REPOSITORY}" in read(release_bump.gh_calls)
    assert "re-run Release with version" in result.stderr
