from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from firmware import cli, mcp_server

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "firmware"
HOOKS = PLUGIN / "hooks" / "scripts"


def _hook(script: str, payload: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOKS / script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )


def test_mcp_tools_registered() -> None:
    names = {tool.name for tool in mcp_server.tool_specs()}
    assert names == {
        "firmware_doctor",
        "firmware_validate",
        "firmware_check",
        "firmware_gates",
        "firmware_pins",
        "firmware_cues",
        "firmware_fpga_regs",
        "firmware_ftm",
        "firmware_production_export",
        "firmware_pinmap_export",
        "firmware_power_export",
        "firmware_sim",
        "firmware_debug",
        "firmware_request",
        "firmware_profile",
        "firmware_render",
        "firmware_record_decision",
        "firmware_record_impression",
        "firmware_record_vision_review",
        "firmware_records_status",
        "firmware_ux_inbox",
        "firmware_ux_respond",
    }


def test_mcp_dispatch_validate(kettle: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENHANDS_PROJECT_DIR", str(kettle.parent))
    payload = mcp_server.dispatch("firmware_validate", {"contract_path": str(kettle)})
    assert payload["verdict"] == "pass"


def test_cli_validate_and_profile(kettle: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["validate", str(kettle)]) == 0
    assert json.loads(capsys.readouterr().out)["verdict"] == "pass"
    assert cli.main(["profile", "esp32s3"]) == 0
    assert json.loads(capsys.readouterr().out)["sim_machine"] == "esp32s3"
    assert cli.main(["profile", "nope"]) != 0


@pytest.mark.parametrize(
    "path",
    [
        "fw/include/fw_pins.h",
        "out/kettle.fw-pinmap.json",
        "fw-reports/k.fw-report.md",
        "observations/firmware/image-observations.jsonl",
        "observations/firmware/vision-tool-events.jsonl",
        "observations/firmware/decisions.jsonl",
        "observations/firmware/impressions.jsonl",
        "observations/firmware/vision-reviews.jsonl",
        "observations/firmware/records-status.json",
        "observations/firmware/.sessions/s1.json",
        "fw-reports/board.pinmap.png",
        "fw-reports/k.fw-report.png",
        "fw-reports/sim-boot.png",
        "intake/attachments/manifest.jsonl",
    ],
)
def test_protect_generated_blocks_edits(path: str) -> None:
    result = _hook(
        "protect_generated.py",
        {"tool_name": "file_editor", "tool_input": {"command": "create", "path": path}},
    )
    assert result.returncode == 2


@pytest.mark.parametrize(
    "header",
    [
        "*** Update File: ",
        "*** Add File: ",
        "*** Delete File: ",
        "*** Move to: ",
        "+++ b/",
        "--- a/",
    ],
)
def test_protect_generated_blocks_vision_patch_paths(header: str) -> None:
    patch = _hook(
        "protect_generated.py",
        {
            "tool_name": "apply_patch",
            "tool_input": {"patch": f"{header}observations/firmware/image-observations.jsonl\n"},
        },
    )
    assert patch.returncode == 2


def test_protect_generated_blocks_vision_redirect() -> None:
    redirect = _hook(
        "protect_generated.py",
        {
            "tool_name": "terminal",
            "tool_input": {"command": "echo x > intake/attachments/manifest.jsonl"},
        },
    )
    assert redirect.returncode == 2


def test_protect_generated_blocks_terminal_redirect() -> None:
    result = _hook(
        "protect_generated.py",
        {"tool_name": "terminal", "tool_input": {"command": "echo x > fw/include/fw_pins.h"}},
    )
    assert result.returncode == 2


@pytest.mark.parametrize(
    "payload",
    [
        {"tool_name": "terminal", "tool_input": {"command": "cat fw/include/fw_pins.h"}},
        {"tool_name": "file_editor", "tool_input": {"command": "create", "path": "fw/src/a.c"}},
        {
            "tool_name": "apply_patch",
            "tool_input": {"patch": "*** Update File: briefs/x.fw.json\n"},
        },
    ],
)
def test_protect_generated_allows(payload: object) -> None:
    assert _hook("protect_generated.py", payload).returncode == 0


def test_report_status_lists_failures(tmp_path: Path) -> None:
    (tmp_path / "k.fw-report.json").write_text(
        json.dumps({"verdict": "fail", "checks": [{"id": "fw.build", "status": "fail"}]})
    )
    result = _hook("report_firmware_status.py", {"working_dir": str(tmp_path)})
    assert result.returncode == 0
    context = json.loads(result.stdout)["additionalContext"]
    assert "verdict=fail" in context
    assert "fw.build" in context


@pytest.mark.parametrize(("warn", "code"), [(False, 1), (True, 0)])
def test_launcher_without_pinned_image_fails_closed(tmp_path: Path, warn: bool, code: int) -> None:
    plugin_root = tmp_path / "isolated" / "plugins" / "firmware"
    shutil.copytree(PLUGIN, plugin_root)
    (plugin_root / "tools-image.json").write_text(
        json.dumps(
            {
                "image": "ghcr.io/vibebb/firmware-tools",
                "digest": None,
                "tag": None,
            }
        ),
        encoding="utf-8",
    )
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "FIRMWARE_SRC": str(ROOT / "src"),
        "PYTHONPATH": ":".join(sys.path),
    }
    argv = [
        sys.executable,
        str(plugin_root / "scripts" / "firmware_launcher.py"),
        "doctor",
    ]
    if warn:
        argv.append("--warn")
    result = subprocess.run(argv, capture_output=True, text=True, env=env, check=False)
    assert result.returncode == code, result.stderr
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "fail"
    assert "no firmware-tools image pinned" in payload["error"]
    assert "Docker-only" in payload["error"]
