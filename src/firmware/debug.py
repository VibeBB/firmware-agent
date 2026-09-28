"""Scripted GDB session against QEMU's gdbstub (advisory, never a gate).

The run is batch-only: QEMU starts halted with ``-S -gdb``, GDB attaches,
sets the requested breakpoints, and at every stop records the backtrace,
registers and requested expressions. The transcript is evidence for the
agent's diagnosis; pass/fail stays with ``fw.sim``.
"""

from __future__ import annotations

import re
import shutil
import socket
import subprocess
import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .contract import Simulation
from .sim import qemu_argv

GDB = {"qemu-arm": "gdb-multiarch", "qemu-esp": "xtensa-esp32s3-elf-gdb"}
_LOCATION = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_]*|[A-Za-z0-9_./-]+:[0-9]+|\*0x[0-9a-fA-F]+)$")
_EXPRESSION = re.compile(r"^[*&(]*[A-Za-z_][A-Za-z0-9_.\[\]\->*&()+ ]*$")
_STOP = re.compile(r"^(?:Thread \d+ hit )?(?:Temporary )?[Bb]reakpoint \d+, (?P<where>.+)$")


class DebugStop(BaseModel):
    model_config = ConfigDict(extra="forbid")
    where: str
    output: list[str]


class DebugSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authority: str = "advisory"
    simulation: str
    ok: bool
    detail: str = ""
    qemu_argv: list[str]
    gdb_argv: list[str]
    stops: list[DebugStop] = Field(default_factory=list[DebugStop])
    transcript: list[str] = Field(default_factory=list[str])


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def gdb_argv(
    gdb: str,
    port: int,
    breaks: list[str],
    prints: list[str],
    elf: Path,
    hardware: bool = False,
) -> list[str]:
    for location in breaks:
        if not _LOCATION.match(location):
            raise ValueError(f"invalid breakpoint location {location!r}")
    for expression in prints:
        if not _EXPRESSION.match(expression):
            raise ValueError(f"invalid expression {expression!r}")
    commands = ["set pagination off", "set confirm off", f"target remote 127.0.0.1:{port}"]
    # Flash-mapped code on Espressif targets needs hardware breakpoints.
    verb = "hbreak" if hardware else "break"
    commands += [f"{verb} {location}" for location in breaks]
    for _ in breaks or [""]:
        commands += ["continue", "backtrace 8", "info registers"]
        commands += [f"print {expression}" for expression in prints]
    commands.append("kill")
    argv = [gdb, "-batch", "-nx"]
    for command in commands:
        argv += ["-ex", command]
    argv.append(elf.as_posix())
    return argv


def _stops(lines: list[str]) -> list[DebugStop]:
    stops: list[DebugStop] = []
    for line in lines:
        match = _STOP.match(line)
        if match:
            stops.append(DebugStop(where=match["where"], output=[]))
        elif stops:
            stops[-1].output.append(line)
    return stops


def run_debug(
    sim: Simulation,
    image: Path,
    elf: Path,
    breaks: list[str],
    prints: list[str],
    timeout_s: float = 60,
) -> DebugSession:
    port = _free_port()
    qemu = qemu_argv(sim, image, gdb_port=port)
    gdb = gdb_argv(GDB[sim.runner], port, breaks, prints, elf, hardware=sim.runner == "qemu-esp")
    missing = [argv[0] for argv in (qemu, gdb) if shutil.which(argv[0]) is None]
    if missing:
        return DebugSession(
            simulation=sim.id,
            ok=False,
            detail=f"not on PATH: {', '.join(missing)}",
            qemu_argv=qemu,
            gdb_argv=gdb,
        )
    emulator = subprocess.Popen(
        qemu, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                if probe.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.05)
        proc = subprocess.run(
            gdb, capture_output=True, text=True, errors="replace", timeout=timeout_s, check=False
        )
        lines = (proc.stdout + proc.stderr).splitlines()
        stops = _stops(lines)
        ok = bool(stops) or not breaks
        detail = "" if ok else "no breakpoint was hit"
        return DebugSession(
            simulation=sim.id,
            ok=ok,
            detail=detail,
            qemu_argv=qemu,
            gdb_argv=gdb,
            stops=stops,
            transcript=lines,
        )
    except subprocess.TimeoutExpired as exc:
        partial = [
            stream.decode(errors="replace") if isinstance(stream, bytes) else stream or ""
            for stream in (exc.stdout, exc.stderr)
        ]
        lines = "".join(partial).splitlines()
        return DebugSession(
            simulation=sim.id,
            ok=False,
            detail=f"gdb timed out after {timeout_s}s",
            qemu_argv=qemu,
            gdb_argv=gdb,
            stops=_stops(lines),
            transcript=lines,
        )
    finally:
        emulator.kill()
        emulator.wait()
