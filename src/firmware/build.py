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

# Zephyr-family SDK roots inside the tools image; environment variables allow
# host-side verification runs to point at a local checkout instead.
SDK_ROOTS: dict[str, str] = {
    "zephyr": os.environ.get("FIRMWARE_ZEPHYR_ROOT", "/opt/zephyr"),
    "nrf-connect": os.environ.get("FIRMWARE_NCS_ROOT", "/opt/nrf"),
}


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


def _zephyr_module_dirs(sdk_root: str) -> list[str]:
    """Module roots under an SDK workspace (dirs holding zephyr/module.yml).

    Tarball-pinned SDK trees have no ``.west`` workspace, so ``west list``
    finds nothing and cmake would leave every module out (e.g. hal_nordic
    under nRF Connect). Enumerating module.yml files and passing them via
    ``-DZEPHYR_MODULES`` makes module discovery deterministic.
    """
    root = Path(sdk_root)
    if not root.is_dir():
        return []
    candidates: list[Path] = []
    for depth in range(1, 5):
        pattern = "/".join(["*"] * depth + ["zephyr", "module.yml"])
        candidates.extend(root.glob(pattern))
    return sorted(
        yml.parent.parent.as_posix()
        for yml in candidates
        if yml.parent.parent != root / "zephyr"
    )


def _west_argv(step: BuildStep, directory: str) -> list[list[str]]:
    """Zephyr-family build driven by cmake directly (west CLI is a wrapper).

    ``sdk`` selects the SDK root: upstream Zephyr LTS under ``/opt/zephyr`` or
    the nRF Connect SDK workspace under ``/opt/nrf``. ``sysbuild`` adds
    ``-DSYSBUILD=ON`` for boards whose boot firmware is a sibling image.
    """
    assert step.board is not None
    sdk_root = SDK_ROOTS[step.sdk or "zephyr"]
    build_dir = (Path(directory) / "build").as_posix()
    module_dirs = _zephyr_module_dirs(sdk_root)
    configure = [
        "cmake",
        "-S",
        directory,
        "-B",
        build_dir,
        "-G",
        "Ninja",
        f"-DBOARD={step.board}",
        f"-DZephyr_DIR={sdk_root}/zephyr/share/zephyr-package/cmake",
        f"-DZEPHYR_BASE={sdk_root}/zephyr",
        "-DZEPHYR_TOOLCHAIN_VARIANT=gnuarmemb",
        "-DGNUARMEMB_TOOLCHAIN_PATH=/usr",
    ]
    if module_dirs:
        configure.append(f"-DZEPHYR_MODULES={';'.join(module_dirs)}")
    if step.sysbuild:
        configure.append("-DSYSBUILD=ON")
    if step.toolchain == "cross-compile":
        assert step.cross_prefix is not None
        configure += [
            "-DZEPHYR_TOOLCHAIN_VARIANT=cross-compile",
            f"-DCROSS_COMPILE={step.cross_prefix}",
        ]
        # gnuarmemb flags conflict with the cross-compile variant.
        configure = [
            f
            for f in configure
            if not f.startswith("-DZEPHYR_TOOLCHAIN_VARIANT=gnuarmemb")
            and not f.startswith("-DGNUARMEMB_TOOLCHAIN_PATH")
        ]
    return [configure, ["cmake", "--build", build_dir]]


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
    if step.backend == "west":
        return _west_argv(step, directory)
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
