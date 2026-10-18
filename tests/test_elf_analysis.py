from __future__ import annotations

import struct
import subprocess
from pathlib import Path

import pytest

from firmware import analysis as analysis_module
from firmware.analysis import Finding, parse_findings, run_cppcheck
from firmware.contract import load_contract
from firmware.elf import ElfError, account, read_elf, read_image
from firmware.profiles import load_profile


def _elf32(path: Path, segments: list[tuple[int, int, int, int]]) -> None:
    """Write a minimal little-endian ELF32 with PT_LOAD program headers."""
    phoff = 52
    header = bytearray(52)
    header[:4] = b"\x7fELF"
    header[4], header[5], header[6] = 1, 1, 1
    struct.pack_into("<HHI", header, 16, 2, 40, 1)
    struct.pack_into("<I", header, 28, phoff)
    struct.pack_into("<HHH", header, 40, 52, 32, len(segments))
    body = bytearray(header)
    for vaddr, paddr, filesz, memsz in segments:
        body += struct.pack("<IIIIIIII", 1, 0, vaddr, paddr, filesz, memsz, 5, 4)
    path.write_bytes(bytes(body))


def test_rejects_non_elf(tmp_path: Path) -> None:
    path = tmp_path / "x.bin"
    path.write_bytes(b"not an elf" * 10)
    with pytest.raises(ElfError):
        read_elf(path)


def test_accounts_flash_and_ram(tmp_path: Path) -> None:
    path = tmp_path / "a.elf"
    # text in flash; data loaded from flash into RAM (+bss)
    _elf32(path, [(0x10000000, 0x10000000, 4096, 4096), (0x20000000, 0x10001000, 256, 1024)])
    usage = account(read_elf(path), load_profile("rp2040").memory_regions)
    assert usage.flash == 4096 + 256
    assert usage.ram == 1024
    assert not usage.unplaced


def test_unplaced_segment_reported(tmp_path: Path) -> None:
    path = tmp_path / "a.elf"
    _elf32(path, [(0x90000000, 0x90000000, 16, 16)])
    usage = account(read_elf(path), load_profile("rp2040").memory_regions)
    assert usage.unplaced


def test_cppcheck_xml_parse(tmp_path: Path) -> None:
    xml = f"""<?xml version="1.0"?>
<results version="2"><cppcheck version="2.7"/><errors>
<error id="nullPointer" severity="error" msg="Null pointer">
<location file="{tmp_path}/src/a.c" line="7"/></error>
</errors></results>"""
    findings = parse_findings(xml, tmp_path)
    assert [(f.id, f.severity, f.line) for f in findings] == [("nullPointer", "error", 7)]
    assert findings[0].file.endswith("src/a.c")


def test_cppcheck_suppression_matches_exact_file_and_line(kettle: Path) -> None:
    contract = load_contract(kettle)
    assert contract.analysis is not None
    matches = analysis_module._suppressed  # pyright: ignore[reportPrivateUsage]
    assert matches(
        Finding("syntaxError", "error", "syntax error", "fw/sim/sim_main.c", 15),
        contract.analysis,
    )
    assert not matches(
        Finding("syntaxError", "error", "syntax error", "fw/sim/sim_main.c", 16),
        contract.analysis,
    )
    assert not matches(
        Finding("syntaxError", "error", "syntax error", "fw/sim/other.c", 15),
        contract.analysis,
    )


def test_cppcheck_xml_unparseable(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        parse_findings("<results", tmp_path)


def test_cppcheck_version_timeout(kettle: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    contract = load_contract(kettle)
    assert contract.analysis is not None

    def cppcheck_on_path(_name: str) -> str:
        return "cppcheck"

    monkeypatch.setattr(analysis_module.shutil, "which", cppcheck_on_path)

    def timeout_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert argv == ["cppcheck", "--version"]
        assert kwargs["timeout"] == 20
        raise subprocess.TimeoutExpired(argv, 20)

    monkeypatch.setattr(analysis_module.subprocess, "run", timeout_run)
    result = run_cppcheck(contract.analysis, kettle.parent)
    assert result.ok is False
    assert result.detail == "cppcheck --version timed out after 20s"


# ------------------------------------------------------------- Intel HEX reader


def _ihex_record(address: int, rectype: int, data: bytes) -> str:
    row = bytes((len(data), address >> 8, address & 0xFF, rectype)) + data
    return ":" + row.hex().upper() + f"{(-sum(row)) & 0xFF:02X}"


def _ihex(path: Path, records: list[str]) -> Path:
    path.write_text("\n".join([*records, _ihex_record(0, 1, b"")]) + "\n")
    return path


def test_ihex_accounts_flash_and_config(tmp_path: Path) -> None:
    # PIC16HV753 gpasm output shape: code at 0x0000+, config word at 0x400E.
    path = _ihex(
        tmp_path / "a.hex",
        [
            _ihex_record(0x0000, 0, bytes(range(16))),
            _ihex_record(0x0010, 0, bytes(range(16))),
            _ihex_record(0x400E, 0, b"\xff\x3f"),
        ],
    )
    image = read_image(path)
    assert image.machine == "ihex"
    usage = account(image, load_profile("pic16hv753").memory_regions)
    assert usage.flash == 34
    assert usage.per_region["config"] == 2
    assert not usage.unplaced


def test_ihex_gap_splits_runs_and_reports_unplaced(tmp_path: Path) -> None:
    path = _ihex(
        tmp_path / "a.hex",
        [_ihex_record(0x0000, 0, b"\x00" * 4), _ihex_record(0x6000, 0, b"\x00" * 4)],
    )
    image = read_image(path)
    assert len(image.segments) == 2
    usage = account(image, load_profile("pic16hv753").memory_regions)
    assert usage.flash == 4
    assert usage.unplaced == ["0x00006000+4"]


def test_ihex_extended_linear_base(tmp_path: Path) -> None:
    path = _ihex(
        tmp_path / "a.hex",
        [_ihex_record(0, 4, b"\x00\x02"), _ihex_record(0x0000, 0, b"\x00" * 8)],
    )
    usage = account(read_image(path), load_profile("pic16hv753").memory_regions)
    assert usage.unplaced == ["0x00020000+8"]


def test_ihex_rejects_bad_checksum(tmp_path: Path) -> None:
    path = tmp_path / "a.hex"
    path.write_text(":10000000000102030405060708090A0B0C0D0E0F0F00\n:00000001FF\n")
    with pytest.raises(ElfError, match="checksum"):
        read_image(path)


def test_ihex_rejects_length_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "a.hex"
    path.write_text(":08000000AABBFF\n:00000001FF\n")
    with pytest.raises(ElfError, match="checksum/length"):
        read_image(path)


def test_ihex_rejects_empty(tmp_path: Path) -> None:
    path = _ihex(tmp_path / "a.hex", [])
    with pytest.raises(ElfError, match="no data records"):
        read_image(path)


def test_ihex_rejects_malformed_base_record(tmp_path: Path) -> None:
    path = _ihex(tmp_path / "a.hex", [_ihex_record(0, 4, b"")])
    with pytest.raises(ElfError, match="base-address"):
        read_image(path)


def test_read_image_dispatches_on_magic(tmp_path: Path) -> None:
    elf_path = tmp_path / "a.elf"
    _elf32(elf_path, [(0x10000000, 0x10000000, 16, 16)])
    assert read_image(elf_path).machine == "arm"
