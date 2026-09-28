"""Build runner: fixed argv per backend (never a shell string)."""

from __future__ import annotations

import configparser
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .contract import BuildStep

_PINNED_PLATFORM = re.compile(r"^[A-Za-z0-9_./-]+@\d+\.\d+\.\d+$")


@dataclass
class BuildResult:
    ok: bool
    detail: str
    argv: list[list[str]]
    log: Path | None
    elf: Path
    seconds: float = 0.0


def platformio_pin_error(project_dir: Path, env: str) -> str | None:
    """PlatformIO platforms must be pinned to an exact version per env."""
    ini = project_dir / "platformio.ini"
    if not ini.is_file():
        return f"{ini} not found"
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(ini, encoding="utf-8")
    section = f"env:{env}"
    if not parser.has_section(section):
        return f"platformio.ini has no [{section}]"
    platform = parser.get(section, "platform", fallback=None) or parser.get(
        "env", "platform", fallback=None
    )
    if platform is None:
        return f"[{section}] declares no platform"
    if not _PINNED_PLATFORM.match(platform.strip()):
        return f"[{section}] platform {platform.strip()!r} is not pinned to an exact version"
    return None


def build_argv(step: BuildStep, root: Path) -> list[list[str]]:
    directory = (root / step.dir).as_posix()
    if step.backend == "make":
        return [["make", "-C", directory, *([step.target] if step.target else [])]]
    if step.backend == "cmake":
        build_dir = (root / step.dir / "build").as_posix()
        return [
            ["cmake", "-S", directory, "-B", build_dir, "-G", "Ninja"],
            ["cmake", "--build", build_dir, *(["--target", step.target] if step.target else [])],
        ]
    assert step.env is not None
    return [["pio", "run", "-d", directory, "-e", step.env]]


def run_build(step: BuildStep, root: Path, log: Path) -> BuildResult:
    elf = root / step.elf
    argvs = build_argv(step, root)
    if step.backend == "platformio":
        error = platformio_pin_error(root / step.dir, step.env or "")
        if error:
            return BuildResult(False, error, argvs, None, elf)
    missing = sorted({argv[0] for argv in argvs if shutil.which(argv[0]) is None})
    if missing:
        return BuildResult(
            False, f"build tool(s) not on PATH: {', '.join(missing)}", argvs, None, elf
        )
    log.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "LC_ALL": "C"}
    started = time.monotonic()
    with log.open("w", encoding="utf-8") as handle:
        for argv in argvs:
            handle.write("$ " + " ".join(argv) + "\n")
            handle.flush()
            try:
                proc = subprocess.run(
                    argv,
                    cwd=root,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    env=env,
                    check=False,
                    timeout=step.timeout_s,
                )
            except subprocess.TimeoutExpired:
                return BuildResult(False, f"timed out after {step.timeout_s}s", argvs, log, elf)
            if proc.returncode != 0:
                return BuildResult(
                    False,
                    f"{argv[0]} exited {proc.returncode}",
                    argvs,
                    log,
                    elf,
                    time.monotonic() - started,
                )
    seconds = time.monotonic() - started
    if not elf.is_file():
        return BuildResult(
            False, f"build succeeded but {step.elf} is missing", argvs, log, elf, seconds
        )
    return BuildResult(True, "", argvs, log, elf, seconds)
