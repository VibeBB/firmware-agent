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

Launcher-side verification uses FIRMWARE_VERIFY_ATTESTATION=auto|require|off.
It verifies lock provenance before pulls and on every prewarm; normal use
does not re-verify an image that is already present locally.
"""

from __future__ import annotations

import json
import os
import pwd
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, TypedDict, cast

_MODULES = {"mcp_server": "firmware.mcp_server"}
_CONTAINER_SRC = "/plugin-src"
_ENV_PREFIXES = ("OPENHANDS_", "FIRMWARE_")
_ENV_KEYS = ("TMPDIR",)
_INSPECT_TIMEOUT_S = 30
_PULL_TIMEOUT_S = 900
_CONTAINER_ENV = {
    "HOME": "/tmp",
    "TMPDIR": "/tmp",
    "XDG_CACHE_HOME": "/tmp/.cache",
    "XDG_CONFIG_HOME": "/tmp/.config",
}
_LOCK_KEY = "firmware_tools"
_ATTEST_TIMEOUT_S = 120
_GH_AUTH_TIMEOUT_S = 15
_VERIFY_ENV = "FIRMWARE_VERIFY_ATTESTATION"
_REPOSITORY = "VibeBB/firmware-agent"
_PUBLISH_FILE = ".github/workflows/publish-firmware-images.yml"


class ImagePin(TypedDict):
    ref: str
    image: str | None
    digest: str | None
    attestation: str | None


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


def _lock_entry_ref(lock_path: Path, key: str | None) -> ImagePin | None:
    try:
        data: Any = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    data = cast(dict[str, Any], data)
    entry = data.get(key) if key else data
    if not isinstance(entry, dict):
        return None
    entry = cast(dict[str, Any], entry)
    image = entry.get("image")
    if not isinstance(image, str) or not image:
        return None
    digest = entry.get("digest")
    digest = digest if isinstance(digest, str) and digest else None
    tag = entry.get("tag")
    tag = tag if isinstance(tag, str) and tag else None
    if digest is None and tag is None:
        return None
    attestation = entry.get("attestation")
    return {
        "ref": f"{image}@{digest}" if digest else f"{image}:{tag}",
        "image": image,
        "digest": digest,
        "attestation": attestation if isinstance(attestation, str) and attestation else None,
    }


def image_pin(plugin_root: Path) -> ImagePin | None:
    explicit = os.environ.get("FIRMWARE_TOOLS_IMAGE")
    if explicit:
        return {"ref": explicit, "image": None, "digest": None, "attestation": None}
    pin = _lock_entry_ref(plugin_root / "tools-image.json", None)
    if pin:
        return pin
    repo_dirs = [plugin_root.parent.parent, *_cache_dirs("firmware-agent-*")]
    for repo_dir in repo_dirs:
        pin = _lock_entry_ref(repo_dir / "docker" / "image-digests.json", _LOCK_KEY)
        if pin:
            return pin
    return None


def image_ref(plugin_root: Path) -> str | None:
    pin = image_pin(plugin_root)
    return pin["ref"] if pin is not None else None


def _attestation_mode() -> str:
    mode = os.environ.get(_VERIFY_ENV, "auto")
    if mode not in {"auto", "require", "off"}:
        raise ValueError(
            f"{_VERIFY_ENV} must be auto, require, or off (got {mode!r}); "
            f"usage: {_VERIFY_ENV}=auto|require|off"
        )
    return mode


def _run_timed(
    command: list[str],
    operation: str,
    timeout: int,
    **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    try:
        return cast(
            subprocess.CompletedProcess[str],
            subprocess.run(command, timeout=timeout, **kwargs),
        )
    except OSError as exc:
        raise RuntimeError(f"{operation} failed: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{operation} timed out after {timeout}s") from exc


def _verify_attestation(pin: ImagePin, *, override: bool) -> None:
    mode = _attestation_mode()
    if mode == "off":
        return
    reason: str | None = None
    gh = shutil.which("gh")
    if override:
        reason = "tools image override has no lock attestation context"
    elif not pin["attestation"]:
        reason = "lock entry has no attestation"
    elif not pin["image"] or not pin["digest"]:
        reason = "lock entry has no digest"
    elif gh is None:
        reason = "gh is not on PATH"
    else:
        try:
            auth = _run_timed(
                [gh, "auth", "status"],
                "gh auth status",
                _GH_AUTH_TIMEOUT_S,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except RuntimeError:
            reason = "gh auth status failed"
        else:
            if auth.returncode != 0:
                reason = "gh auth status failed"
    if reason is not None:
        if mode == "require":
            raise RuntimeError(f"attestation verification required but {reason}")
        print(f"firmware_launcher: attestation verification skipped: {reason}", file=sys.stderr)
        return
    assert gh is not None
    assert pin["image"] is not None and pin["digest"] is not None
    result = _run_timed(
        [
            gh,
            "attestation",
            "verify",
            f"oci://{pin['image']}@{pin['digest']}",
            "--repo",
            _REPOSITORY,
            "--signer-workflow",
            f"{_REPOSITORY}/{_PUBLISH_FILE}",
        ],
        "gh attestation verify",
        _ATTEST_TIMEOUT_S,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"attestation verification failed for {pin['image']}@{pin['digest']}")


def _ensure_image(
    image: ImagePin | str,
    *,
    pull: bool,
    prewarm: bool = False,
    override: bool = False,
) -> None:
    if isinstance(image, str):
        pin: ImagePin = {"ref": image, "image": None, "digest": None, "attestation": None}
        override = True
    else:
        pin = image
    ref = pin["ref"]
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError(f"docker not found on PATH (tools image {ref} is pinned)")
    if prewarm:
        _verify_attestation(pin, override=override)
    try:
        inspect = subprocess.run(
            [docker, "image", "inspect", ref],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=_INSPECT_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"docker image inspect timed out after {_INSPECT_TIMEOUT_S}s") from exc
    if inspect.returncode == 0:
        return
    if not pull:
        raise RuntimeError(
            f"firmware tools image {ref} not pulled locally; "
            "run 'firmware_launcher.py prewarm' to fetch it"
        )
    if not prewarm:
        _verify_attestation(pin, override=override)
    print(f"firmware_launcher: pulling tools image {ref}", file=sys.stderr)
    try:
        pulled = subprocess.run(
            [docker, "pull", ref],
            check=False,
            stdout=subprocess.DEVNULL,
            timeout=_PULL_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"docker pull timed out after {_PULL_TIMEOUT_S}s") from exc
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
    argv += ["-e", f"OPENHANDS_PROJECT_DIR={workdir}"]
    if source is not None:
        argv += ["-v", f"{source}:{_CONTAINER_SRC}:ro", "-e", f"PYTHONPATH={_CONTAINER_SRC}"]
    for key, value in os.environ.items():
        if key == "OPENHANDS_PROJECT_DIR":
            continue
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
    try:
        _attestation_mode()
    except ValueError as exc:
        print(f"firmware_launcher: {exc}", file=sys.stderr)
        return 2
    plugin_root = Path(__file__).resolve().parents[1]
    source = resolve_source(plugin_root)
    pin = image_pin(plugin_root)
    ref = pin["ref"] if pin is not None else None
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
    assert pin is not None
    try:
        _ensure_image(
            pin,
            pull="--warn" not in argv,
            prewarm=argv[0] == "prewarm",
            override=bool(os.environ.get("FIRMWARE_TOOLS_IMAGE")),
        )
    except RuntimeError as exc:
        return _warn_or_die(str(exc), argv)
    if argv[0] == "prewarm":
        print(f"firmware_launcher: tools image ready: {ref}")
        return 0
    os.execvp("docker", docker_argv(ref, source, inner_argv(argv)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
