"""Sister interchange: the circuit export firmware consumes and the pin map
export circuit consumes back. Both are plain JSON files; no sister code is
imported."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
