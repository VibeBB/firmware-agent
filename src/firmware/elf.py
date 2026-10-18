"""Minimal ELF/Intel HEX reader for flash/RAM accounting (stdlib only).

Loadable segments are charged by address: a segment whose virtual address
lies in a RAM region costs ``p_memsz`` of RAM, and its file-backed bytes
(``p_filesz``) also cost flash when the load address is in flash or the RAM
region is marked ``image_backed`` (copied from the flash image at boot).

Intel HEX images (sdcc/gputils ``.hex`` output) carry only file-backed
bytes, so each contiguous address run becomes one segment with
``filesz == memsz`` and the pseudo machine ``ihex``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

from .profiles import MemoryRegion

PT_LOAD = 1
MACHINES: dict[int, str] = {40: "arm", 94: "xtensa", 243: "riscv"}


@dataclass(frozen=True)
class Segment:
    vaddr: int
    paddr: int
    filesz: int
    memsz: int


@dataclass(frozen=True)
class ElfImage:
    machine: str
    segments: tuple[Segment, ...]


@dataclass
class Usage:
    flash: int = 0
    ram: int = 0
    per_region: dict[str, int] = field(default_factory=dict[str, int])
    unplaced: list[str] = field(default_factory=list[str])


class ElfError(ValueError):
    pass


def read_elf(path: Path) -> ElfImage:
    data = path.read_bytes()
    if len(data) < 52 or data[:4] != b"\x7fELF":
        raise ElfError(f"{path}: not an ELF file")
    elf_class, endian = data[4], data[5]
    if elf_class not in (1, 2) or endian not in (1, 2):
        raise ElfError(f"{path}: unsupported ELF class/endianness")
    order = "<" if endian == 1 else ">"
    (machine,) = struct.unpack_from(order + "H", data, 18)
    if elf_class == 1:
        phoff, phentsize, phnum = (
            struct.unpack_from(order + "I", data, 28)[0],
            struct.unpack_from(order + "H", data, 42)[0],
            struct.unpack_from(order + "H", data, 44)[0],
        )
    else:
        phoff, phentsize, phnum = (
            struct.unpack_from(order + "Q", data, 32)[0],
            struct.unpack_from(order + "H", data, 54)[0],
            struct.unpack_from(order + "H", data, 56)[0],
        )
    segments: list[Segment] = []
    for index in range(phnum):
        offset = phoff + index * phentsize
        if offset + phentsize > len(data):
            raise ElfError(f"{path}: truncated program header table")
        if elf_class == 1:
            p_type, _off, vaddr, paddr, filesz, memsz, _flags, _align = struct.unpack_from(
                order + "8I", data, offset
            )
        else:
            p_type, _flags, _off, vaddr, paddr, filesz, memsz, _align = struct.unpack_from(
                order + "IIQQQQQQ", data, offset
            )
        if p_type == PT_LOAD and memsz > 0:
            segments.append(Segment(vaddr, paddr, filesz, memsz))
    return ElfImage(MACHINES.get(machine, f"e_machine={machine}"), tuple(segments))


def read_ihex(path: Path) -> ElfImage:
    """Intel HEX image: contiguous data runs become loadable segments.

    Type-02/04 records set the base address; other record types carry no
    payload. ``machine`` reports ``ihex`` so gates can check the artifact
    kind a profile expects.
    """
    try:
        text = path.read_text(encoding="ascii")
    except UnicodeDecodeError as exc:
        raise ElfError(f"{path}: not an Intel HEX file") from exc
    segments: list[Segment] = []
    base = 0
    run_start: int | None = None
    run_end = 0
    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        if not line.startswith(":") or len(line) < 11:
            raise ElfError(f"{path}:{lineno}: malformed Intel HEX record")
        try:
            raw = bytes.fromhex(line[1:])
        except ValueError:
            raise ElfError(f"{path}:{lineno}: malformed Intel HEX record") from None
        count, offset, rectype = raw[0], (raw[1] << 8) | raw[2], raw[3]
        if len(raw) != count + 5 or sum(raw) & 0xFF:
            raise ElfError(f"{path}:{lineno}: Intel HEX checksum/length mismatch")
        if rectype == 0x00 and count:
            start = base + offset
            if run_start is None:
                run_start, run_end = start, start + count
            elif start == run_end:
                run_end += count
            else:
                segments.append(
                    Segment(run_start, run_start, run_end - run_start, run_end - run_start)
                )
                run_start, run_end = start, start + count
        elif rectype == 0x01:  # end of file
            break
        elif rectype in (0x02, 0x04):  # extended segment/linear address
            if count != 2:
                raise ElfError(f"{path}:{lineno}: Intel HEX base-address record malformed")
            shift = 4 if rectype == 0x02 else 16
            base = ((raw[4] << 8) | raw[5]) << shift
    if run_start is not None:
        segments.append(Segment(run_start, run_start, run_end - run_start, run_end - run_start))
    if not segments:
        raise ElfError(f"{path}: Intel HEX carries no data records")
    return ElfImage("ihex", tuple(segments))


def read_image(path: Path) -> ElfImage:
    """Dispatch on magic: ELF program headers or Intel HEX records."""
    with path.open("rb") as stream:
        if stream.read(4) == b"\x7fELF":
            return read_elf(path)
    return read_ihex(path)


def _region(regions: list[MemoryRegion], address: int) -> MemoryRegion | None:
    return next((r for r in regions if r.contains(address)), None)


def account(image: ElfImage, regions: list[MemoryRegion]) -> Usage:
    usage = Usage()
    for segment in image.segments:
        home = _region(regions, segment.vaddr)
        if home is None:
            usage.unplaced.append(f"0x{segment.vaddr:08x}+{segment.memsz}")
            continue
        usage.per_region[home.name] = usage.per_region.get(home.name, 0) + segment.memsz
        if home.kind == "flash":
            usage.flash += segment.memsz
            continue
        usage.ram += segment.memsz
        if segment.filesz == 0:
            continue
        load = _region(regions, segment.paddr)
        if (load is not None and load.kind == "flash" and load is not home) or home.image_backed:
            usage.flash += segment.filesz
    return usage
