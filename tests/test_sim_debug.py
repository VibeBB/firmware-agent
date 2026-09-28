from __future__ import annotations

from pathlib import Path

import pytest

from firmware.contract import Simulation, load_contract
from firmware.debug import _stops, gdb_argv  # pyright: ignore[reportPrivateUsage]
from firmware.service import _symbol_file  # pyright: ignore[reportPrivateUsage]
from firmware.sim import qemu_argv, run_simulation


def _sim(contract: Path) -> Simulation:
    return load_contract(contract).simulations[0]


def test_qemu_arm_argv(kettle: Path) -> None:
    argv = qemu_argv(_sim(kettle), Path("sim.elf"), gdb_port=3333)
    assert argv[:3] == ["qemu-system-arm", "-M", "mps2-an385"]
    assert "-kernel" in argv
    assert any("semihosting" in a for a in argv)
    assert "tcp:127.0.0.1:3333" in " ".join(argv)


def test_qemu_esp_argv(lamp: Path) -> None:
    argv = qemu_argv(_sim(lamp), Path("flash.bin"))
    assert argv[:3] == ["qemu-system-xtensa", "-M", "esp32s3"]
    assert "-nographic" in argv
    assert "file=flash.bin,if=mtd,format=raw" in argv


def test_sim_missing_binary_fails(kettle: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "/nonexistent")
    result = run_simulation(_sim(kettle), kettle.parent / "x.elf", kettle.parent / "t.log")
    assert not result.ok
    assert "not found" in result.detail


def test_sim_missing_image_fails(kettle: Path, tmp_path: Path) -> None:
    fake = tmp_path / "bin"
    fake.mkdir()
    qemu = fake / "qemu-system-arm"
    qemu.write_text("#!/bin/sh\nexit 0\n")
    qemu.chmod(0o755)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("PATH", str(fake))
        result = run_simulation(_sim(kettle), tmp_path / "none.elf", tmp_path / "t.log")
    assert not result.ok
    assert "missing" in result.detail


def _fake_qemu(tmp_path: Path, body: str) -> Path:
    fake = tmp_path / "bin"
    fake.mkdir()
    qemu = fake / "qemu-system-arm"
    qemu.write_text("#!/bin/sh\n" + body)
    qemu.chmod(0o755)
    (tmp_path / "img.elf").write_bytes(b"\x7fELF")
    return fake


@pytest.mark.parametrize(
    ("body", "ok", "needle"),
    [
        ("printf 'BOOT\\nSIM PASS\\n'; exit 0\n", True, ""),
        ("printf 'SIM PASS\\nBOOT\\n'; exit 0\n", False, "expected output"),
        ("printf 'BOOT\\nASSERT x\\nSIM PASS\\n'; exit 0\n", False, "forbidden"),
        ("printf 'BOOT\\nSIM PASS\\n'; exit 3\n", False, "exit code 3"),
    ],
)
def test_sim_transcript_matching(
    kettle: Path, tmp_path: Path, body: str, ok: bool, needle: str
) -> None:
    fake = _fake_qemu(tmp_path, body)
    sim = _sim(kettle).model_copy(update={"expect": ["BOOT", "SIM PASS"], "forbid": ["ASSERT"]})
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("PATH", f"{fake}:/usr/bin:/bin")
        result = run_simulation(sim, tmp_path / "img.elf", tmp_path / "t.log")
    assert result.ok is ok, result.detail
    assert needle in result.detail
    assert (tmp_path / "t.log").is_file()


def test_sim_timeout(kettle: Path, tmp_path: Path) -> None:
    fake = _fake_qemu(tmp_path, "sleep 5\n")
    sim = _sim(kettle).model_copy(update={"timeout_s": 0.5})
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("PATH", f"{fake}:/usr/bin:/bin")
        result = run_simulation(sim, tmp_path / "img.elf", tmp_path / "t.log")
    assert not result.ok


def test_gdb_argv_software_and_hardware() -> None:
    soft = gdb_argv("gdb-multiarch", 3333, ["main"], ["x"], Path("a.elf"))
    hard = gdb_argv("xtensa-esp32s3-elf-gdb", 3333, ["lamp_step"], [], Path("a.elf"), hardware=True)
    assert "break main" in soft
    assert "hbreak lamp_step" in hard
    assert soft[-1] == "a.elf"
    assert "-batch" in soft


@pytest.mark.parametrize("location", ["main; shell rm -rf /", "$(id)", ""])
def test_gdb_rejects_bad_location(location: str) -> None:
    with pytest.raises(ValueError):
        gdb_argv("gdb", 1, [location], [], Path("a.elf"))


def test_gdb_accepts_dereference() -> None:
    assert "print *lamp" in gdb_argv("gdb", 1, ["f"], ["*lamp"], Path("a.elf"))


def test_gdb_rejects_bad_expression() -> None:
    with pytest.raises(ValueError):
        gdb_argv("gdb", 1, ["f"], ["x; shell id"], Path("a.elf"))


def test_stop_parsing_arm_and_xtensa() -> None:
    stops = _stops(
        [
            "Breakpoint 1, kettle_step (k=0x2000) at src/kettle.c:40",
            "40\t  switch (k->state) {",
            "Thread 1 hit Breakpoint 2, lamp_step (lamp=0x3fc9) at src/lamp.c:11",
            "#0  lamp_step (lamp=0x3fc9)",
        ]
    )
    assert [s.where.split(" ")[0] for s in stops] == ["kettle_step", "lamp_step"]
    assert stops[1].output == ["#0  lamp_step (lamp=0x3fc9)"]


def test_symbol_file_selection(kettle: Path, lamp: Path) -> None:
    kettle_contract = load_contract(kettle)
    lamp_contract = load_contract(lamp)
    kettle_sim = kettle_contract.simulations[0]
    lamp_sim = lamp_contract.simulations[0]
    expected = kettle_sim.build.elf if kettle_sim.build is not None else kettle_sim.image
    assert _symbol_file(kettle_contract.build.elf, kettle_sim) == expected
    assert _symbol_file(lamp_contract.build.elf, lamp_sim).endswith(".elf")
