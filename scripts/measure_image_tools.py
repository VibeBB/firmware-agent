#!/usr/bin/env python3
"""Measure the runtime metadata required by the image digest lock."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

_IMAGE_REF = re.compile(r"[^@\s]+@sha256:[0-9a-f]{64}\Z")
_LOCAL_IMAGE_REF = re.compile(r"[a-z0-9][a-z0-9_.-]*:[a-z0-9][a-z0-9_.-]*\Z")
_PLATFORMIO_PROBE = (
    "python -c 'import json; "
    "from pathlib import Path; "
    'print("espressif32=" + json.loads(Path('
    '"/opt/platformio/platforms/espressif32/platform.json").read_text())["version"])'
    "'"
)


def measure(image_ref: str) -> dict[str, str]:
    if _IMAGE_REF.fullmatch(image_ref) is None and _LOCAL_IMAGE_REF.fullmatch(image_ref) is None:
        raise ValueError("image ref must be digest-pinned or a local tag")
    script = (
        "set -eu; python --version; uv --version; pio --version; "
        + _PLATFORMIO_PROBE
        + "; cppcheck --version; "
        "qemu-system-arm --version | head -1; "
        "qemu-system-xtensa --version | head -1; "
        "gdb-multiarch --version | head -1; "
        "python -c 'import firmware; print(\"firmware=\" + firmware.__version__)'"
    )
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "",
            image_ref,
            "sh",
            "-c",
            script,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "metadata probe failed")
    values: dict[str, str] = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("Python "):
            values["python"] = f"python --version: {line}"
        elif line.startswith("uv "):
            values["uv"] = f"uv --version: {line.removeprefix('uv ')}"
        elif line.startswith("PlatformIO Core"):
            values["platformio"] = f"pio --version: {line}"
        elif line.startswith("espressif32="):
            values["espressif32"] = f"{_PLATFORMIO_PROBE}: {line.removeprefix('espressif32=')}"
        elif line.startswith("Cppcheck "):
            values["cppcheck"] = f"cppcheck --version: {line}"
        elif line.startswith("QEMU emulator version"):
            if "qemu_arm" not in values:
                values["qemu_arm"] = f"qemu-system-arm --version: {line}"
            else:
                values["qemu_xtensa"] = f"qemu-system-xtensa --version: {line}"
        elif line.startswith("GNU gdb"):
            values["gdb_multiarch"] = f"gdb-multiarch --version: {line}"
        elif line.startswith("firmware="):
            values["firmware"] = (
                "python -c 'import firmware; print(firmware.__version__)': "
                f"{line.removeprefix('firmware=')}"
            )
    required = {
        "python",
        "uv",
        "platformio",
        "espressif32",
        "cppcheck",
        "qemu_arm",
        "qemu_xtensa",
        "gdb_multiarch",
        "firmware",
    }
    if required - values.keys():
        raise ValueError(f"metadata probe omitted: {sorted(required - values.keys())}")
    return dict(sorted(values.items()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-ref", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        value = measure(args.image_ref)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    except (OSError, UnicodeDecodeError, ValueError, RuntimeError) as exc:
        print(f"FAIL: {exc}")
        return 1
    print(f"WROTE {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
