"""Sister interchange: the circuit export firmware consumes and the pin map
export circuit consumes back. Both are plain JSON files; no sister code is
imported."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CircuitMcuPin(_Strict):
    pin: str = Field(min_length=1)
    function: str | None = None
    net: str | None = None
    signal_class: str | None = None
    voltage_v: float | None = Field(default=None, ge=0)


class CircuitMcu(_Strict):
    ref: str
    lib_id: str
    value: str | None = None
    footprint: str
    pins: list[CircuitMcuPin]


class CircuitFirmwareConnectivity(_Strict):
    """``<design>.firmware.json`` written by electrical-circuit-agent."""

    schema_version: Literal[1]
    system: Literal["circuit"]
    artifact_kind: Literal["circuit_firmware_connectivity"]
    design: str
    source: Literal["brief", "netlist"]
    brief_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    netlist_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    mcus: list[CircuitMcu] = Field(min_length=1)

    def mcu(self, ref: str) -> CircuitMcu | None:
        return next((m for m in self.mcus if m.ref == ref), None)


class PinmapEntry(_Strict):
    signal: str
    pad: str
    pad_aliases: list[str]
    package_pin: str | None
    net: str
    function: str
    peripheral: str | None


class FreePad(_Strict):
    pad: str
    pad_aliases: list[str]
    package_pin: str | None


class FirmwarePinmap(_Strict):
    """``<name>.fw-pinmap.json`` exported for electrical-circuit-agent."""

    schema_version: Literal[1] = 1
    system: Literal["firmware"] = "firmware"
    artifact_kind: Literal["firmware_pinmap"] = "firmware_pinmap"
    design: str
    contract_sha256: str
    mcu_ref: str
    mcu_profile: str
    mcu_part: str
    io_voltage_max_v: float
    supply_net: str
    pins: list[PinmapEntry]
    free_pads: list[FreePad]


class PowerModeExport(_Strict):
    id: str
    kind: str
    current_a: float
    duty: float


class FirmwarePower(_Strict):
    """``<name>.fw-power.json``: the MCU draw on its supply net, for simulation-agent.

    ``peak_current_a`` is the largest authored mode current, the worst case a
    PDN load must carry; ``average_current_a`` is the duty-weighted mean.
    """

    schema_version: Literal[1] = 1
    system: Literal["firmware"] = "firmware"
    artifact_kind: Literal["firmware_power"] = "firmware_power"
    design: str
    contract_sha256: str
    mcu_ref: str
    supply_net: str
    peak_current_a: float
    average_current_a: float
    modes: list[PowerModeExport]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_circuit(path: Path) -> CircuitFirmwareConnectivity:
    return CircuitFirmwareConnectivity.model_validate(json.loads(path.read_text(encoding="utf-8")))


def pad_of(function: str | None) -> str | None:
    """KiCad pin function -> pad name (``GPIO26_ADC0`` -> ``GPIO26``,
    ``IO5`` stays ``IO5``, ``GPIO5/TOUCH5`` -> ``GPIO5``)."""
    if not function:
        return None
    head = function.replace("/", "_").split("_", 1)[0].upper()
    return head or None


class BardFileRef(_Strict):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class BardTone(_Strict):
    start_ms: int = Field(ge=0)
    duration_ms: int = Field(ge=0)
    midi: int | None = Field(default=None, ge=0, le=127)
    freq_hz: float = Field(ge=0)


class BardCue(_Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    purpose: str
    ux_feedback: str | None = None
    loop: bool
    bpm: int
    program: int
    duration_ms: int = Field(gt=0)
    mid: BardFileRef
    mml: BardFileRef
    tones: list[BardTone] = Field(min_length=1)


class BardCueManifest(_Strict):
    """``cues.json`` (``bard_cue_manifest``) rendered by bard-agent."""

    artifact_kind: Literal["bard_cue_manifest"]
    schema_version: Literal["0.1"]
    system: Literal["bard"]
    authority: Literal["none"]
    product: str
    device: Literal["piezo", "speaker"]
    cues: list[BardCue] = Field(min_length=1)
    artifacts: list[str]
    accessibility: dict[str, object] | None = None
    audibility: dict[str, object] | None = None


def load_cue_manifest(path: Path) -> BardCueManifest:
    return BardCueManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))


RegAccess = Literal["ro", "rw", "wo", "w1c"]
REG_NAME = r"^[a-z](?:_?[a-z0-9])*$"


class FpgaRegField(_Strict):
    name: str = Field(pattern=REG_NAME)
    lsb: int = Field(ge=0)
    width: int = Field(ge=1)
    mask: int = Field(ge=1)
    access: RegAccess
    description: str


class FpgaRegister(_Strict):
    name: str = Field(pattern=REG_NAME)
    offset: int = Field(ge=0)
    access: RegAccess
    reset: int = Field(ge=0)
    description: str
    fields: list[FpgaRegField]


class FpgaRegmapSource(_Strict):
    """Strict mirror of fpga-agent's ``<name>.fpga-regmap.json`` (never imported).

    Layout facts are re-checked so a hand-edited or truncated export cannot
    reach the generated header.
    """

    schema_version: Literal[1] = 1
    system: Literal["fpga"] = "fpga"
    artifact_kind: Literal["fpga_regmap"] = "fpga_regmap"
    design: str = Field(min_length=1)
    contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    device_ref: str = Field(min_length=1)
    bus: Literal["spi", "i2c", "uart"]
    i2c_address: int | None = Field(ge=0x08, le=0x77)
    data_width: Literal[8, 16, 32]
    address_width: int = Field(ge=1, le=16)
    registers: list[FpgaRegister] = Field(min_length=1)

    @model_validator(mode="after")
    def _layout(self) -> FpgaRegmapSource:
        if (self.bus == "i2c") != (self.i2c_address is not None):
            raise ValueError("i2c_address is required for i2c and only for i2c")
        offsets = [r.offset for r in self.registers]
        if offsets != sorted(set(offsets)):
            raise ValueError("register offsets must be unique and ascending")
        if len({r.name for r in self.registers}) != len(self.registers):
            raise ValueError("duplicate register name")
        for reg in self.registers:
            if reg.offset >= 1 << self.address_width:
                raise ValueError(f"register {reg.name}: offset exceeds address_width")
            if reg.reset >= 1 << self.data_width:
                raise ValueError(f"register {reg.name}: reset exceeds data_width")
            used = 0
            if len({f.name for f in reg.fields}) != len(reg.fields):
                raise ValueError(f"register {reg.name}: duplicate field name")
            for fld in reg.fields:
                if fld.lsb + fld.width > self.data_width:
                    raise ValueError(f"register {reg.name}.{fld.name}: exceeds data_width")
                if fld.mask != ((1 << fld.width) - 1) << fld.lsb:
                    raise ValueError(
                        f"register {reg.name}.{fld.name}: mask disagrees with lsb/width"
                    )
                if used & fld.mask:
                    raise ValueError(f"register {reg.name}.{fld.name}: overlaps another field")
                used |= fld.mask
        return self


def load_fpga_regmap(path: Path) -> FpgaRegmapSource:
    return FpgaRegmapSource.model_validate(json.loads(path.read_text(encoding="utf-8")))


FtmTransport = Literal["uart", "usb_cdc", "swd", "jtag", "i2c", "spi", "can", "ble", "other"]


class FtmEntrySpec(_Strict):
    method: str = Field(min_length=1)
    detail: str
    conditions: list[str]


class FtmLockoutSpec(_Strict):
    method: str = Field(min_length=1)
    detail: str


class FtmInterfaceSpec(_Strict):
    transport: FtmTransport
    settings: str
    nets: list[str]


class FtmCommandSpec(_Strict):
    id: str = Field(pattern=r"^TC-[0-9]{2,4}$")
    name: str = Field(min_length=1)
    request: str = Field(min_length=1)
    response_pattern: str = Field(min_length=1)
    timeout_ms: int = Field(gt=0)
    measures_nets: list[str]
    covers: list[str]
    destructive: bool


class FtmProvisioningSpec(_Strict):
    item: str = Field(min_length=1)
    source: str
    write_once: bool


class ProdengFtmSpec(_Strict):
    """production-engineering ``factory-test-spec.json`` with a declared FTM."""

    declared: Literal[True]
    entry: FtmEntrySpec
    field_lockout: FtmLockoutSpec
    interface: FtmInterfaceSpec
    commands: list[FtmCommandSpec]
    provisioning: list[FtmProvisioningSpec]
    exit: str
    max_duration_s: float = Field(gt=0)
    command_timeout_budget_s: float = Field(ge=0)


def load_ftm_spec(path: Path) -> ProdengFtmSpec:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and data.get("declared") is False:  # pyright: ignore[reportUnknownMemberType]
        raise ValueError("factory test spec declares no factory_test_mode")
    return ProdengFtmSpec.model_validate(data)


class FirmwareProduction(_Strict):
    """``<name>.fw-production.json``: the gated image for production-engineering.

    ``elf`` is relative to this file. ``ftm_spec_sha256`` is the factory test
    spec the image was gated against (``null`` without an ``ftm`` link).
    """

    schema_version: Literal[1] = 1
    system: Literal["firmware"] = "firmware"
    artifact_kind: Literal["firmware_production"] = "firmware_production"
    design: str
    contract_sha256: str
    gate_report_sha256: str
    mcu_ref: str
    mcu_profile: str
    part: str
    package: str
    elf: str
    elf_sha256: str
    elf_bytes: int = Field(gt=0)
    ftm_spec_sha256: str | None
    ftm_commands: list[str]
