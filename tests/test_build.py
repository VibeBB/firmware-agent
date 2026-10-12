"""Build-step argv assembly for the make/cmake/west/platformio backends."""

from __future__ import annotations

from pathlib import Path

import pytest

from firmware.build import SDK_ROOTS, build_argv, platformio_pin_error, run_build
from firmware.contract import BuildStep


def _west(**kw: object) -> BuildStep:
    base: dict[str, object] = {"backend": "west", "dir": "fw", "board": "b/x", "elf": "fw/e.elf"}
    base.update(kw)
    return BuildStep.model_validate(base)


class TestWestArgv:
    def test_zephyr_sdk_gnuarmemb(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FIRMWARE_ZEPHYR_ROOT", "/opt/zephyr")
        # SDK_ROOTS is read at import; refresh by re-evaluating the map entry.
        argv = build_argv(_west(), Path("/root"))
        configure = argv[0]
        assert "-DBOARD=b/x" in configure
        assert any(f.startswith("-DZEPHYR_BASE=") for f in configure)
        assert "-DZEPHYR_TOOLCHAIN_VARIANT=gnuarmemb" in configure
        assert "-DGNUARMEMB_TOOLCHAIN_PATH=/usr" in configure
        assert "-DSYSBUILD=ON" not in configure
        assert argv[1] == ["cmake", "--build", "/root/fw/build"]

    def test_nrf_sdk_root(self) -> None:
        argv = build_argv(_west(sdk="nrf-connect"), Path("/root"))
        assert f"-DZEPHYR_BASE={SDK_ROOTS['nrf-connect']}/zephyr" in argv[0]

    def test_sysbuild_flag(self) -> None:
        argv = build_argv(_west(sysbuild=True), Path("/root"))
        assert "-DSYSBUILD=ON" in argv[0]

    def test_cross_compile(self) -> None:
        step = _west(toolchain="cross-compile", cross_prefix="riscv64-unknown-elf-")
        configure = build_argv(step, Path("/root"))[0]
        assert "-DZEPHYR_TOOLCHAIN_VARIANT=cross-compile" in configure
        assert "-DCROSS_COMPILE=riscv64-unknown-elf-" in configure
        assert "-DZEPHYR_TOOLCHAIN_VARIANT=gnuarmemb" not in configure
        assert not any(f.startswith("-DGNUARMEMB_TOOLCHAIN_PATH") for f in configure)


class TestBuildArgv:
    def test_make(self) -> None:
        step = BuildStep.model_validate(
            {"backend": "make", "dir": "fw", "target": "all", "elf": "fw/fw.elf"}
        )
        assert build_argv(step, Path("/root")) == [["make", "-C", "/root/fw", "all"]]

    def test_cmake(self) -> None:
        step = BuildStep.model_validate({"backend": "cmake", "dir": "fw", "elf": "x"})
        argvs = build_argv(step, Path("/root"))
        assert argvs[0][:2] == ["cmake", "-S"]
        assert "-B/root/fw/build".replace("-B/", "-B") not in argvs[0]
        assert "/root/fw/build" in argvs[0]
        assert argvs[1] == ["cmake", "--build", "/root/fw/build"]

    def test_cmake_target(self) -> None:
        step = BuildStep.model_validate(
            {"backend": "cmake", "dir": "fw", "target": "app", "elf": "x"}
        )
        assert build_argv(step, Path("/root"))[1][-2:] == ["--target", "app"]

    def test_platformio(self) -> None:
        step = BuildStep.model_validate(
            {"backend": "platformio", "dir": "fw", "env": "esp32-s3-devkitc-1", "elf": "x"}
        )
        assert build_argv(step, Path("/root")) == [
            ["pio", "run", "-d", "/root/fw", "-e", "esp32-s3-devkitc-1"]
        ]

    def test_west_dispatch(self) -> None:
        argvs = build_argv(_west(), Path("/root"))
        assert argvs[0][0] == "cmake" and argvs[1][0] == "cmake"


class TestPlatformioPin:
    def test_missing_ini(self, tmp_path: Path) -> None:
        assert "not found" in (platformio_pin_error(tmp_path, "env") or "")

    def test_missing_section(self, tmp_path: Path) -> None:
        (tmp_path / "platformio.ini").write_text("[env:other]\n", encoding="utf-8")
        assert "has no [env:esp32]" in (platformio_pin_error(tmp_path, "esp32") or "")

    def test_no_platform(self, tmp_path: Path) -> None:
        (tmp_path / "platformio.ini").write_text("[env:esp32]\n", encoding="utf-8")
        assert "declares no platform" in (platformio_pin_error(tmp_path, "esp32") or "")

    def test_unpinned_platform(self, tmp_path: Path) -> None:
        (tmp_path / "platformio.ini").write_text(
            "[env:esp32]\nplatform = espressif32\n", encoding="utf-8"
        )
        assert "not pinned" in (platformio_pin_error(tmp_path, "esp32") or "")

    def test_pinned_platform(self, tmp_path: Path) -> None:
        (tmp_path / "platformio.ini").write_text(
            "[env:esp32]\nplatform = espressif32@7.1.3\n", encoding="utf-8"
        )
        assert platformio_pin_error(tmp_path, "esp32") is None


class TestRunBuild:
    def test_missing_tool(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PATH", str(tmp_path / "empty"))
        step = BuildStep.model_validate({"backend": "make", "dir": "fw", "elf": "fw/fw.elf"})
        result = run_build(step, tmp_path, tmp_path / "log.txt")
        assert not result.ok and "not on PATH" in result.detail

    def test_platformio_pin_blocks(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "fw").mkdir()
        step = BuildStep.model_validate(
            {"backend": "platformio", "dir": "fw", "env": "e", "elf": "fw/fw.elf"}
        )
        result = run_build(step, tmp_path, tmp_path / "log.txt")
        assert not result.ok and "platformio.ini" in result.detail
