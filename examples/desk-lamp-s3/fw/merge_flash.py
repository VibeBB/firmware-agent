"""PlatformIO post-build step: merge bootloader, partition table and app into
``flash.bin`` (a full 8 MB raw image) for Espressif QEMU."""

import subprocess
from pathlib import Path

Import("env")  # noqa: F821  # pyright: ignore[reportUndefinedVariable]


def merge_flash(source, target, env):
    build = Path(env.subst("$BUILD_DIR"))
    esptool = Path(env.PioPlatform().get_package_dir("tool-esptoolpy")) / "esptool.py"
    parts: list[str] = []
    for offset, image in env.get("FLASH_EXTRA_IMAGES", []):
        parts += [str(env.subst(offset)), str(env.subst(image))]
    parts += [str(env.subst("$ESP32_APP_OFFSET")), str(build / "firmware.bin")]
    subprocess.run(
        [
            str(env.subst("$PYTHONEXE")),
            str(esptool),
            "--chip",
            "esp32s3",
            "merge_bin",
            "--fill-flash-size",
            "8MB",
            "-o",
            str(build / "flash.bin"),
            *parts,
        ],
        check=True,
    )


env.AddPostAction("$BUILD_DIR/${PROGNAME}.bin", merge_flash)  # noqa: F821  # pyright: ignore[reportUndefinedVariable]
