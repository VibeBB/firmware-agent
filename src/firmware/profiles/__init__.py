"""MCU profiles: pad function tables, memory regions, peripheral instances."""

from __future__ import annotations

import json
import re
from importlib import resources
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Pad(_Strict):
    name: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    gpio: int | None = Field(default=None, ge=0)
    pin: str | None = None
    aliases: list[str] = Field(default_factory=list[str])
    functions: list[str] = Field(default_factory=list[str])
    wake_deep_sleep: bool = False
    reserved: Literal["power", "flash", "debug", "clock", "reset", "test"] | None = None
    caution: Literal["strapping", "jtag"] | None = None

    @property
    def names(self) -> frozenset[str]:
        return frozenset([self.name, *self.aliases])

    def supports(self, kind: str, instance: int | None, role: str) -> bool:
        """True when a function token (``i2c0.sda``, ``i2c*.sda``, ``adc1.ch3``,
        ``pwm*.a``) grants ``kind``/``instance``/``role``; an empty role
        matches any role and ``instance=None`` matches any instance."""
        for token in self.functions:
            match = _TOKEN.match(token)
            if match is None or match["kind"] != kind:
                continue
            if instance is not None and match["inst"] not in ("*", str(instance)):
                continue
            if role and match["role"] != role:
                continue
            return True
        return False

    def fixed_channels(self, kind: str) -> list[str]:
        """Concrete (non-wildcard) channel tokens for ``kind`` (``pwm3.a``)."""
        return [
            token
            for token in self.functions
            if (m := _TOKEN.match(token)) is not None and m["kind"] == kind and m["inst"] != "*"
        ]


_TOKEN = re.compile(r"^(?P<kind>[a-z][a-z0-9]*?)(?P<inst>\*|[0-9]+)\.(?P<role>[a-z0-9]+)$")


class MemoryRegion(_Strict):
    name: str
    kind: Literal["flash", "ram"]
    origin: int = Field(ge=0)
    length_kb: int = Field(gt=0)
    image_backed: bool = False

    def contains(self, address: int) -> bool:
        return self.origin <= address < self.origin + self.length_kb * 1024


class McuProfile(_Strict):
    schema_version: Literal[1]
    artifact_kind: Literal["mcu_profile"]
    id: str = Field(pattern=r"^[a-z0-9_-]+$")
    vendor: str
    part: str
    core: str
    package: str
    source: str = Field(min_length=1)
    io_voltage_max_v: float = Field(gt=0)
    flash_kb: int = Field(gt=0)
    ram_kb: int = Field(gt=0)
    memory_regions: list[MemoryRegion] = Field(min_length=1)
    peripherals: dict[str, list[int]]
    sim_machine: str | None
    pads: list[Pad] = Field(min_length=1)

    def pad(self, name: str) -> Pad | None:
        return next((p for p in self.pads if name in p.names), None)

    def pad_by_pin(self, pin: str) -> Pad | None:
        return next((p for p in self.pads if p.pin == pin), None)


BUILTIN: tuple[str, ...] = ("esp32s3", "rp2040")


def load_profile(profile: str, search: list[Path] | None = None) -> McuProfile:
    """Load a bundled profile by id, or ``<dir>/<id>.mcu.json`` from ``search``."""
    for directory in search or []:
        candidate = directory / f"{profile}.mcu.json"
        if candidate.is_file():
            return McuProfile.model_validate(json.loads(candidate.read_text(encoding="utf-8")))
    if profile not in BUILTIN:
        raise ValueError(f"unknown MCU profile {profile!r} (bundled: {', '.join(BUILTIN)})")
    text = resources.files(__package__).joinpath(f"{profile}.json").read_text(encoding="utf-8")
    return McuProfile.model_validate(json.loads(text))
