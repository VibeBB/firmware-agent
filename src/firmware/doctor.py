"""Probe the firmware toolchain (JSON verdict)."""

from __future__ import annotations

import shutil
import subprocess
from typing import Literal

from pydantic import BaseModel, ConfigDict

REQUIRED: tuple[tuple[str, list[str]], ...] = (
    ("make", ["make", "--version"]),
    ("cppcheck", ["cppcheck", "--version"]),
    ("arm-none-eabi-gcc", ["arm-none-eabi-gcc", "--version"]),
    ("qemu-system-arm", ["qemu-system-arm", "--version"]),
)
OPTIONAL: tuple[tuple[str, list[str]], ...] = (
    ("cmake", ["cmake", "--version"]),
    ("ninja", ["ninja", "--version"]),
    ("pio", ["pio", "--version"]),
    ("qemu-system-xtensa", ["qemu-system-xtensa", "--version"]),
    ("gdb-multiarch", ["gdb-multiarch", "--version"]),
    ("xtensa-esp32s3-elf-gdb", ["xtensa-esp32s3-elf-gdb", "--version"]),
)


class ToolCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    status: Literal["ok", "warn", "fail"]
    version: str = ""


def _probe(argv: list[str]) -> str | None:
    if shutil.which(argv[0]) is None:
        return None
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (proc.stdout or proc.stderr).strip().splitlines()
    return text[0] if text else ""


def checks() -> list[ToolCheck]:
    results: list[ToolCheck] = []
    for required, table in ((True, REQUIRED), (False, OPTIONAL)):
        for name, argv in table:
            version = _probe(argv)
            if version is None:
                results.append(ToolCheck(name=name, status="fail" if required else "warn"))
            else:
                results.append(ToolCheck(name=name, status="ok", version=version))
    return results
