from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from scripts.measure_image_tools import measure
from scripts.print_locked_image import locked_image
from scripts.pull_locked_image import main as pull_main
from scripts.update_image_digest_lock import update_lock

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "docker" / "image-digests.json"


def test_initial_firmware_lock_entry_is_unpinned() -> None:
    assert json.loads(LOCK.read_text(encoding="utf-8")) == {
        "firmware_tools": {
            "image": "ghcr.io/vibebb/firmware-tools",
            "digest": None,
            "tag": None,
        }
    }


def test_print_locked_image_rejects_initial_null_entry(tmp_path: Path) -> None:
    lock = tmp_path / "image-digests.json"
    lock.write_text(LOCK.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(ValueError, match="not digest-pinned"):
        locked_image(lock, "firmware_tools")


def test_update_initial_null_entry(tmp_path: Path) -> None:
    lock = tmp_path / "image-digests.json"
    lock.write_text(LOCK.read_text(encoding="utf-8"), encoding="utf-8")
    digest = "sha256:" + "b" * 64
    changed = update_lock(
        lock,
        entry="firmware_tools",
        image="ghcr.io/vibebb/firmware-tools",
        tag="abc123-tools",
        digest=digest,
        published_at="2026-09-30T00:00:00Z",
        workflow_run="https://github.com/VibeBB/firmware-agent/actions/runs/1",
        dockerfile="docker/firmware-tools.Dockerfile",
        tools={"python": "python --version: Python 3.12.14"},
    )
    assert changed
    data = json.loads(lock.read_text(encoding="utf-8"))
    assert data["firmware_tools"]["image"] == "ghcr.io/vibebb/firmware-tools"
    assert data["firmware_tools"]["digest"] == digest
    assert data["firmware_tools"]["tag"] == "abc123-tools"
    assert data["firmware_tools"]["tools"] == {"python": "python --version: Python 3.12.14"}


def test_pull_locked_image_uses_digest_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lock = tmp_path / "lock.json"
    digest = "sha256:" + "c" * 64
    lock.write_text(
        json.dumps(
            {
                "firmware_tools": {
                    "image": "ghcr.io/vibebb/firmware-tools",
                    "digest": digest,
                    "tag": "abc123-tools",
                }
            }
        ),
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def run(command: list[str], **_kwargs: object) -> Result:
        calls.append(command)
        return Result()

    monkeypatch.setattr("scripts.pull_locked_image.subprocess.run", run)
    record = tmp_path / "record.json"
    assert (
        pull_main(["--lock", str(lock), "--entry", "firmware_tools", "--record", str(record)]) == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert calls == [["docker", "pull", f"ghcr.io/vibebb/firmware-tools@{digest}"]]
    assert output["status"] == "pulled"
    assert json.loads(record.read_text(encoding="utf-8")) == output


def test_measure_records_required_probe_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout = (
        "Python 3.12.14\n"
        "uv 0.12.21\n"
        "PlatformIO Core, version 6.2.0\n"
        "espressif32=7.1.3\n"
        "Cppcheck 2.13.0\n"
        "QEMU emulator version 8.2.2 (Debian)\n"
        "QEMU emulator version 9.2.2 (Espressif)\n"
        "GNU gdb (Ubuntu 16.2-1ubuntu1) 16.2\n"
        "firmware=0.1.0\n"
    )

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        script = command[-1]
        for probe in (
            "python --version",
            "uv --version",
            "pio --version",
            "platform.json",
            "cppcheck --version",
            "qemu-system-arm --version",
            "qemu-system-xtensa --version",
            "gdb-multiarch --version",
            "import firmware",
        ):
            assert probe in script
        assert "--network" in command
        assert command[command.index("--network") + 1] == "none"
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr("scripts.measure_image_tools.subprocess.run", run)
    values = measure("firmware-tools:local")
    assert set(values) == {
        "cppcheck",
        "espressif32",
        "firmware",
        "gdb_multiarch",
        "platformio",
        "python",
        "qemu_arm",
        "qemu_xtensa",
        "uv",
    }
    assert "3.12.14" in values["python"]
    assert "6.2.0" in values["platformio"]
    assert "7.1.3" in values["espressif32"]
    assert "9.2.2" in values["qemu_xtensa"]
