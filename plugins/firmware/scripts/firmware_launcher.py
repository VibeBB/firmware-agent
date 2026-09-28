#!/usr/bin/env python3
"""Resolve the firmware package and tools image, then exec the entry point.

Plugin installs update the assets under plugins/firmware but do not install
the ``firmware`` Python package or the embedded toolchain. The launcher runs
every entry point inside the pinned firmware-tools image, mounting the
resolved source tree and the workspace so paths stay identical inside the
container. The container runs with ``--network none``: the image carries the
toolchains, PlatformIO platform and QEMU builds the gates need.

Source resolution order (first directory containing firmware/__init__.py wins):
  1. $FIRMWARE_SRC
  2. newest ~/.openhands/cache/extensions/firmware-agent-*/src
  3. /opt/firmware/src (firmware-tools image)
  4. <repo>/src when running from a repository checkout

Image resolution order (first hit wins):
  1. $FIRMWARE_TOOLS_IMAGE (full ref, e.g. ghcr.io/.../firmware-tools@sha256:...)
  2. <plugin>/tools-image.json or repo docker/image-digests.json
     (image + digest, falling back to image + tag)
  3. none resolvable -> host mode: the package runs on the host interpreter
     and every missing tool fails its gate (``doctor`` reports which)

Usage: mcp_server | prewarm | <firmware cli args...>. When ``--warn`` is
present (SessionStart doctor mode), launcher failures print a warning and
exit 0.
"""

from __future__ import annotations

import json
import os
import pwd
import shutil
import subprocess
import sys
from pathlib import Path

_MODULES = {"mcp_server": "firmware.mcp_server"}
_CONTAINER_SRC = "/plugin-src"
_ENV_PREFIXES = ("OPENHANDS_", "FIRMWARE_")
_ENV_KEYS = ("TMPDIR",)
_CONTAINER_ENV = {
    "HOME": "/tmp",
    "TMPDIR": "/tmp",
    "XDG_CACHE_HOME": "/tmp/.cache",
    "XDG_CONFIG_HOME": "/tmp/.config",
}
_LOCK_KEY = "firmware_tools"


def _homes() -> list[Path]:
    homes = [Path.home()]
    try:
        real = Path(pwd.getpwuid(os.getuid()).pw_dir)
    except (KeyError, OSError):
        return homes
    if real != homes[0]:
        homes.append(real)
    return homes


def _cache_dirs(pattern: str) -> list[Path]:
    found: list[Path] = []
    for home in _homes():
        cache = home / ".openhands" / "cache" / "extensions"
        try:
            if cache.is_dir():
                found.extend(
                    sorted(cache.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
                )
        except OSError:
            pass
    return found


def _candidates(plugin_root: Path) -> list[Path]:
    candidates: list[Path] = []
    env_src = os.environ.get("FIRMWARE_SRC")
    if env_src:
        candidates.append(Path(env_src))
    candidates += _cache_dirs("firmware-agent-*/src")
    candidates.append(Path("/opt/firmware/src"))
    candidates.append(plugin_root.parent.parent / "src")
    return candidates


def resolve_source(plugin_root: Path) -> Path | None:
    for candidate in _candidates(plugin_root):
        try:
            if (candidate / "firmware" / "__init__.py").is_file():
                return candidate.resolve()
        except OSError:
            continue
    return None


def _lock_entry_ref(lock_path: Path, key: str | None) -> str | None:
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    entry = data.get(key) if key else data
    if not isinstance(entry, dict) or not entry.get("image"):
        return None
    if entry.get("digest"):
        return f"{entry['image']}@{entry['digest']}"
    if entry.get("tag"):
        return f"{entry['image']}:{entry['tag']}"
    return None


def image_ref(plugin_root: Path) -> str | None:
    explicit = os.environ.get("FIRMWARE_TOOLS_IMAGE")
    if explicit:
        return explicit
    ref = _lock_entry_ref(plugin_root / "tools-image.json", None)
    if ref:
        return ref
    repo_dirs = [plugin_root.parent.parent, *_cache_dirs("firmware-agent-*")]
    for repo_dir in repo_dirs:
        ref = _lock_entry_ref(repo_dir / "docker" / "image-digests.json", _LOCK_KEY)
        if ref:
            return ref
    return None


def _ensure_image(ref: str, *, pull: bool) -> None:
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError(f"docker not found on PATH (tools image {ref} is pinned)")
    inspect = subprocess.run(
        [docker, "image", "inspect", ref],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if inspect.returncode == 0:
        return
    if not pull:
        raise RuntimeError(
            f"firmware tools image {ref} not pulled locally; "
            "run 'firmware_launcher.py prewarm' to fetch it"
        )
    print(f"firmware_launcher: pulling tools image {ref}", file=sys.stderr)
    pulled = subprocess.run([docker, "pull", ref], check=False, stdout=subprocess.DEVNULL)
    if pulled.returncode != 0:
        raise RuntimeError(f"firmware tools image {ref} not present locally and pull failed")


def docker_argv(image: str, source: Path | None, inner_argv: list[str]) -> list[str]:
    workdir = os.environ.get("OPENHANDS_PROJECT_DIR") or os.getcwd()
    cwd = Path.cwd()
    inside = cwd == Path(workdir) or Path(workdir) in cwd.parents
    argv = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--network",
        "none",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "-v",
        f"{workdir}:{workdir}",
        "-w",
        str(cwd) if inside else workdir,
    ]
    if source is not None:
        argv += ["-v", f"{source}:{_CONTAINER_SRC}:ro", "-e", f"PYTHONPATH={_CONTAINER_SRC}"]
    for key, value in os.environ.items():
        if key in _ENV_KEYS or any(key.startswith(p) for p in _ENV_PREFIXES):
            argv += ["-e", f"{key}={value}"]
    for key, value in _CONTAINER_ENV.items():
        argv += ["-e", f"{key}={value}"]
    return [*argv, image, *inner_argv]


def inner_argv(argv: list[str], python: str = "python") -> list[str]:
    if argv[0] in _MODULES:
        return [python, "-m", _MODULES[argv[0]], *argv[1:]]
    return [python, "-m", "firmware.cli", *argv]


def _warn_or_die(message: str, argv: list[str]) -> int:
    if "--warn" in argv:
        print(f"warn: {message}", file=sys.stderr)
        print(json.dumps({"verdict": "fail", "detail": message}))
        return 0
    print(f"firmware_launcher: {message}", file=sys.stderr)
    return 1


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        print(
            "usage: firmware_launcher.py {mcp_server|prewarm|<firmware cli args...>}",
            file=sys.stderr,
        )
        return 2
    plugin_root = Path(__file__).resolve().parents[1]
    source = resolve_source(plugin_root)
    ref = image_ref(plugin_root)
    if ref is None:
        if argv[0] == "prewarm":
            return _warn_or_die("no firmware tools image pinned; host mode only", argv)
        if source is None:
            return _warn_or_die("firmware package source not found and no image pinned", argv)
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            p for p in (str(source), env.get("PYTHONPATH", "")) if p
        )
        command = inner_argv(argv, sys.executable)
        os.execvpe(command[0], command, env)
        return 0
    try:
        _ensure_image(ref, pull="--warn" not in argv)
    except RuntimeError as exc:
        return _warn_or_die(str(exc), argv)
    if argv[0] == "prewarm":
        print(f"firmware_launcher: tools image ready: {ref}")
        return 0
    os.execvp("docker", docker_argv(ref, source, inner_argv(argv)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
