"""QEMU simulation runs.

``qemu-arm`` boots an ELF on an upstream Cortex-M machine with semihosting;
the firmware prints through SYS_WRITE0 and ends with SYS_EXIT, so the run
has an exit code. ``qemu-esp`` boots a merged flash image on Espressif's
QEMU (``esp32s3``); it never exits, so the run ends once every expected line
was seen or the timeout elapses.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .contract import Simulation

BINARIES = {"qemu-arm": "qemu-system-arm", "qemu-esp": "qemu-system-xtensa"}


@dataclass
class SimResult:
    ok: bool
    detail: str
    argv: list[str]
    exit_code: int | None = None
    matched: list[str] = field(default_factory=list[str])
    missing: list[str] = field(default_factory=list[str])
    forbidden: list[str] = field(default_factory=list[str])
    transcript: Path | None = None
    seconds: float = 0.0


def qemu_argv(sim: Simulation, image: Path, gdb_port: int | None = None) -> list[str]:
    binary = BINARIES[sim.runner]
    if sim.runner == "qemu-arm":
        argv = [
            binary,
            "-M",
            sim.machine,
            "-display",
            "none",
            "-monitor",
            "none",
            "-serial",
            "stdio",
            "-semihosting-config",
            "enable=on,target=native",
            "-kernel",
            image.as_posix(),
        ]
    else:
        argv = [
            binary,
            "-M",
            sim.machine,
            # Espressif machines only route UART0 to stdio through the -nographic mux.
            "-nographic",
            "-no-reboot",
            "-drive",
            f"file={image.as_posix()},if=mtd,format=raw",
        ]
    if gdb_port is not None:
        argv += ["-S", "-gdb", f"tcp:127.0.0.1:{gdb_port}"]
    return argv


def _progress(lines: list[str], expect: list[str]) -> int:
    """Number of ``expect`` entries matched in order (substring per line)."""
    index = 0
    for line in lines:
        if index < len(expect) and expect[index] in line:
            index += 1
    return index


def run_simulation(sim: Simulation, image: Path, transcript: Path) -> SimResult:
    argv = qemu_argv(sim, image)
    if shutil.which(argv[0]) is None:
        return SimResult(False, f"{argv[0]} not found on PATH", argv)
    if not image.is_file():
        return SimResult(False, f"simulation image {image} is missing", argv)
    lines: list[str] = []
    lock = threading.Lock()
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )

    def _reader() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            with lock:
                lines.append(line.rstrip("\r\n"))

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()
    started = time.monotonic()
    timed_out = False
    while proc.poll() is None:
        if time.monotonic() - started > sim.timeout_s:
            timed_out = True
            break
        if sim.exit_code is None:
            with lock:
                done = _progress(lines, sim.expect) == len(sim.expect)
            if done:
                break
        time.sleep(0.05)
    if proc.poll() is None:
        proc.kill()
    proc.wait()
    reader.join(timeout=5)
    seconds = time.monotonic() - started
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("\n".join(lines) + "\n", encoding="utf-8")
    count = _progress(lines, sim.expect)
    result = SimResult(
        True,
        "",
        argv,
        exit_code=None if sim.exit_code is None else proc.returncode,
        matched=sim.expect[:count],
        missing=sim.expect[count:],
        forbidden=[f for f in sim.forbid if any(f in line for line in lines)],
        transcript=transcript,
        seconds=seconds,
    )
    problems: list[str] = []
    if result.missing:
        problems.append(f"expected output not seen: {result.missing[0]!r}")
    if result.forbidden:
        problems.append(f"forbidden output seen: {', '.join(map(repr, result.forbidden))}")
    if sim.exit_code is not None:
        if timed_out:
            problems.append(f"no semihosting exit within {sim.timeout_s}s")
        elif proc.returncode != sim.exit_code:
            problems.append(f"exit code {proc.returncode} != expected {sim.exit_code}")
    elif timed_out and result.missing:
        problems.append(f"timed out after {sim.timeout_s}s")
    result.ok = not problems
    result.detail = "; ".join(problems)
    return result
