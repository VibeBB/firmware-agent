"""Boundary, decision-table and fail-closed tests for the deterministic gates.

Techniques follow docs/test-coverage.md: 3-value boundaries (below / on /
above) for the memory budget, region capacity, power budget and duty-sum
tolerance; equivalence classes and corrupted inputs for the ELF reader; and
decision tables for flash charging and build-backend options.
"""

from __future__ import annotations

import math
import struct
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from firmware.contract import BuildStep, FirmwareContract, load_contract
from firmware.elf import ElfError, ElfImage, Segment, account, read_elf
from firmware.gates import check_memory, check_power_modes
from firmware.profiles import MemoryRegion, load_profile

from .conftest import read_json, write_json

FLASH = 0x10000000
RAM = 0x20000000
# smart-kettle: flash_kb 2048 at 25 %, RP2040 SRAM 264 KiB at 50 %.
FLASH_LIMIT = 2048 * 1024 * 25 // 100
RAM_LIMIT = 264 * 1024 * 50 // 100
SRAM_BYTES = 264 * 1024


def _elf32(
    segments: list[tuple[int, int, int, int]],
    *,
    machine: int = 40,
    endian: int = 1,
    elf_class: int = 1,
    p_type: int = 1,
    trim: int = 0,
) -> bytes:
    order = "<" if endian == 1 else ">"
    header = bytearray(52)
    header[:4] = b"\x7fELF"
    header[4], header[5], header[6] = elf_class, endian, 1
    struct.pack_into(order + "HHI", header, 16, 2, machine, 1)
    struct.pack_into(order + "I", header, 28, 52)
    struct.pack_into(order + "HHH", header, 40, 52, 32, len(segments))
    body = bytearray(header)
    for vaddr, paddr, filesz, memsz in segments:
        body += struct.pack(order + "8I", p_type, 0, vaddr, paddr, filesz, memsz, 5, 4)
    return bytes(body[: len(body) - trim])


def _elf64(segments: list[tuple[int, int, int, int]]) -> bytes:
    header = bytearray(64)
    header[:4] = b"\x7fELF"
    header[4], header[5], header[6] = 2, 1, 1
    struct.pack_into("<HHI", header, 16, 2, 243, 1)
    struct.pack_into("<Q", header, 32, 64)
    struct.pack_into("<HHH", header, 52, 64, 56, len(segments))
    body = bytearray(header)
    for vaddr, paddr, filesz, memsz in segments:
        body += struct.pack("<IIQQQQQQ", 1, 5, 0, vaddr, paddr, filesz, memsz, 4)
    return bytes(body)


def _write(tmp_path: Path, data: bytes) -> Path:
    path = tmp_path / "image.elf"
    path.write_bytes(data)
    return path


# ------------------------------------------------------------- ELF reader


@pytest.mark.parametrize(("size", "ok"), [(51, False), (52, True), (53, True)])
def test_elf_minimum_header_size(tmp_path: Path, size: int, ok: bool) -> None:
    data = (_elf32([]) + b"\0")[:size]
    if ok:
        assert read_elf(_write(tmp_path, data)).segments == ()
    else:
        with pytest.raises(ElfError, match="not an ELF"):
            read_elf(_write(tmp_path, data))


@pytest.mark.parametrize(
    ("fields", "ok"),
    [
        ({"elf_class": 0}, False),
        ({"elf_class": 3}, False),
        ({"endian": 0}, False),
        ({"endian": 3}, False),
        ({"endian": 2}, True),
        ({}, True),
    ],
)
def test_elf_class_and_endianness(tmp_path: Path, fields: dict[str, int], ok: bool) -> None:
    data = _elf32([(FLASH, FLASH, 16, 16)], **fields)
    if ok:
        assert read_elf(_write(tmp_path, data)).segments == (Segment(FLASH, FLASH, 16, 16),)
    else:
        with pytest.raises(ElfError, match="class/endianness"):
            read_elf(_write(tmp_path, data))


def test_elf64_program_headers(tmp_path: Path) -> None:
    image = read_elf(_write(tmp_path, _elf64([(RAM, FLASH, 8, 32)])))
    assert image.machine == "riscv"
    assert image.segments == (Segment(RAM, FLASH, 8, 32),)


@pytest.mark.parametrize(("trim", "ok"), [(1, False), (0, True)])
def test_truncated_program_header_table(tmp_path: Path, trim: int, ok: bool) -> None:
    data = _elf32([(FLASH, FLASH, 16, 16)], trim=trim)
    if ok:
        assert len(read_elf(_write(tmp_path, data)).segments) == 1
    else:
        with pytest.raises(ElfError, match="truncated"):
            read_elf(_write(tmp_path, data))


@pytest.mark.parametrize(
    ("p_type", "memsz", "kept"), [(1, 0, 0), (1, 1, 1), (1, 2, 1), (2, 16, 0), (6, 16, 0)]
)
def test_only_nonempty_load_segments_are_kept(
    tmp_path: Path, p_type: int, memsz: int, kept: int
) -> None:
    data = _elf32([(FLASH, FLASH, 0, memsz)], p_type=p_type)
    assert len(read_elf(_write(tmp_path, data)).segments) == kept


@pytest.mark.parametrize(
    ("machine", "name"), [(40, "arm"), (94, "xtensa"), (243, "riscv"), (3, "e_machine=3")]
)
def test_machine_names(tmp_path: Path, machine: int, name: str) -> None:
    assert read_elf(_write(tmp_path, _elf32([], machine=machine))).machine == name


# ------------------------------------------------------- flash accounting

REGIONS = [
    MemoryRegion(name="flash", kind="flash", origin=FLASH, length_kb=64),
    MemoryRegion(name="ram", kind="ram", origin=RAM, length_kb=16),
    MemoryRegion(name="iram", kind="ram", origin=0x40000000, length_kb=16, image_backed=True),
]


# A RAM segment's file bytes cost flash only when loaded from flash or when
# its region is image-backed.
@pytest.mark.parametrize(
    ("vaddr", "paddr", "filesz", "flash", "ram"),
    [
        (FLASH, FLASH, 100, 100, 0),
        (RAM, FLASH, 100, 100, 200),
        (RAM, FLASH, 0, 0, 200),
        (RAM, RAM, 100, 0, 200),
        (RAM, 0x90000000, 100, 0, 200),
        (0x40000000, 0x40000000, 100, 100, 200),
        (0x40000000, 0x40000000, 0, 0, 200),
    ],
)
def test_flash_charging_decision_table(
    vaddr: int, paddr: int, filesz: int, flash: int, ram: int
) -> None:
    memsz = 100 if vaddr == FLASH else 200
    usage = account(ElfImage("arm", (Segment(vaddr, paddr, filesz, memsz),)), REGIONS)
    assert (usage.flash, usage.ram, usage.unplaced) == (flash, ram, [])


@pytest.mark.parametrize(
    ("vaddr", "placed"),
    [(RAM - 1, False), (RAM, True), (RAM + 16 * 1024 - 1, True), (RAM + 16 * 1024, False)],
)
def test_region_address_boundaries(vaddr: int, placed: bool) -> None:
    usage = account(ElfImage("arm", (Segment(vaddr, vaddr, 0, 4),)), REGIONS)
    assert (not usage.unplaced) == placed


# ----------------------------------------------------------- memory gate


def _with(kettle: Path, mutate: dict[str, Any] | None = None) -> FirmwareContract:
    data = read_json(kettle)
    for key, value in (mutate or {}).items():
        data["build"]["budget"][key] = value
    write_json(kettle, data)
    return load_contract(kettle)


def _memory(
    kettle: Path, tmp_path: Path, segments: list[tuple[int, int, int, int]], **budget: Any
) -> tuple[str, str]:
    contract = _with(kettle, budget)
    result = check_memory(contract, load_profile("rp2040"), _write(tmp_path, _elf32(segments)))
    return result.status, result.detail


@pytest.mark.parametrize(
    ("size", "status"),
    [(FLASH_LIMIT - 1, "pass"), (FLASH_LIMIT, "pass"), (FLASH_LIMIT + 1, "fail")],
)
def test_flash_budget_three_value_boundary(
    kettle: Path, tmp_path: Path, size: int, status: str
) -> None:
    assert _memory(kettle, tmp_path, [(FLASH, FLASH, size, size)])[0] == status


@pytest.mark.parametrize(
    ("size", "status"), [(RAM_LIMIT - 1, "pass"), (RAM_LIMIT, "pass"), (RAM_LIMIT + 1, "fail")]
)
def test_ram_budget_three_value_boundary(
    kettle: Path, tmp_path: Path, size: int, status: str
) -> None:
    assert _memory(kettle, tmp_path, [(RAM, RAM, 0, size)])[0] == status


@pytest.mark.parametrize(
    ("size", "overflow"), [(SRAM_BYTES - 1, False), (SRAM_BYTES, False), (SRAM_BYTES + 1, True)]
)
def test_region_capacity_three_value_boundary(
    kettle: Path, tmp_path: Path, size: int, overflow: bool
) -> None:
    status, detail = _memory(kettle, tmp_path, [(RAM, RAM, 0, size)], ram_pct=100)
    assert ("sram overflows" in detail) == overflow
    assert status == ("fail" if overflow else "pass")


@pytest.mark.parametrize(("machine", "status"), [(40, "pass"), (94, "fail"), (0, "fail")])
def test_elf_machine_must_match_core(
    kettle: Path, tmp_path: Path, machine: int, status: str
) -> None:
    contract = _with(kettle)
    elf = _write(tmp_path, _elf32([(FLASH, FLASH, 16, 16)], machine=machine))
    assert check_memory(contract, load_profile("rp2040"), elf).status == status


def test_unplaced_segment_and_unreadable_elf_fail(kettle: Path, tmp_path: Path) -> None:
    status, detail = _memory(kettle, tmp_path, [(0x90000000, 0x90000000, 16, 16)])
    assert status == "fail"
    assert "outside every memory region" in detail
    contract = _with(kettle)
    missing = check_memory(contract, load_profile("rp2040"), tmp_path / "absent.elf")
    assert missing.status == "fail"


# ------------------------------------------------------------ power gate


def _power(kettle: Path, edit: dict[str, Any]) -> tuple[str, str]:
    data = read_json(kettle)
    power = data["power"]
    for mode_id, fields in edit.items():
        if mode_id == "budget":
            power["average_budget_ua"] = fields
            continue
        mode = next(m for m in power["modes"] if m["id"] == mode_id)
        mode.update(fields)
    write_json(kettle, data)
    result = check_power_modes(load_contract(kettle), load_profile("rp2040"))
    return result.status, result.detail


def _average(kettle: Path) -> float:
    contract = load_contract(kettle)
    return sum(mode.current_ua * mode.duty for mode in contract.power.modes)


def test_average_current_three_value_boundary(kettle: Path) -> None:
    average = _average(kettle)
    statuses = [
        _power(kettle, {"budget": budget})[0]
        for budget in (math.nextafter(average, 0), average, math.nextafter(average, math.inf))
    ]
    assert statuses == ["fail", "pass", "pass"]


def test_no_budget_skips_the_average_check(kettle: Path) -> None:
    data = read_json(kettle)
    del data["power"]["average_budget_ua"]
    data["power"]["modes"][0]["current_ua"] = 1e9
    write_json(kettle, data)
    assert check_power_modes(load_contract(kettle), load_profile("rp2040")).status == "pass"


# Duties must sum to 1 within 1e-6.
@pytest.mark.parametrize(
    ("dormant_duty", "status"),
    [
        (0.9 - 2e-6, "fail"),
        (0.9 - 5e-7, "pass"),
        (0.9, "pass"),
        (0.9 + 5e-7, "pass"),
        (0.9 + 2e-6, "fail"),
    ],
)
def test_duty_sum_tolerance(kettle: Path, dormant_duty: float, status: str) -> None:
    assert _power(kettle, {"budget": 1e6, "dormant": {"duty": dormant_duty}})[0] == status


@pytest.mark.parametrize(
    ("edit", "needle"),
    [
        ({"heating": {"kind": "idle"}}, "no run mode"),
        ({"dormant": {"kind": "sleep", "wake": []}}, "without a wake source"),
        ({"dormant": {"kind": "deep_sleep", "wake": []}}, "without a wake source"),
        ({"dormant": {"wake": ["ghost"]}}, "not a pin signal"),
        ({"standby": {"peripherals_on": ["ghost"]}}, "unknown peripheral"),
    ],
)
def test_power_mode_rules_fail(kettle: Path, edit: dict[str, Any], needle: str) -> None:
    status, detail = _power(kettle, {"budget": 1e6, **edit})
    assert status == "fail"
    assert needle in detail


@pytest.mark.parametrize(
    "edit",
    [
        {"dormant": {"kind": "sleep", "wake": ["timer"]}},
        {"dormant": {"kind": "deep_sleep", "wake": ["timer"]}},
        {"standby": {"kind": "idle", "wake": []}},
    ],
)
def test_power_mode_rules_pass(kettle: Path, edit: dict[str, Any]) -> None:
    assert _power(kettle, {"budget": 1e6, **edit}) == ("pass", "")


# ---------------------------------------------------------- build options


@pytest.mark.parametrize(
    ("backend", "env", "ok"),
    [
        ("platformio", "esp32s3", True),
        ("platformio", None, False),
        ("make", None, True),
        ("make", "esp32s3", False),
        ("cmake", "esp32s3", False),
    ],
)
def test_build_backend_env_decision_table(backend: str, env: str | None, ok: bool) -> None:
    payload: dict[str, Any] = {"backend": backend, "dir": "fw", "elf": "fw/a.elf"}
    if env is not None:
        payload["env"] = env
    if ok:
        BuildStep.model_validate(payload)
    else:
        with pytest.raises(ValidationError):
            BuildStep.model_validate(payload)


@pytest.mark.parametrize(("timeout", "ok"), [(0, False), (1, True), (7200, True), (7201, False)])
def test_build_timeout_bounds(timeout: int, ok: bool) -> None:
    payload = {"backend": "make", "dir": "fw", "elf": "fw/a.elf", "timeout_s": timeout}
    if ok:
        BuildStep.model_validate(payload)
    else:
        with pytest.raises(ValidationError):
            BuildStep.model_validate(payload)
