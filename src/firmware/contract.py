"""The firmware contract (``<name>.fw.json``): the single source of truth.

The contract declares the MCU, the pin map (firmware signal -> MCU pad ->
circuit net), the peripheral instances, the power modes, the build, the
static analysis and the simulation runs. Every gate reads this file; the
generated pin header, pin map export and reports are projections of it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = 1
IDENT = r"^[a-z][a-z0-9_]*$"

PinFunction = Literal[
    "gpio_in",
    "gpio_out",
    "adc",
    "pwm",
    "i2c_sda",
    "i2c_scl",
    "spi_sck",
    "spi_mosi",
    "spi_miso",
    "spi_cs",
    "uart_tx",
    "uart_rx",
    "uart_cts",
    "uart_rts",
    "usb_dp",
    "usb_dm",
]
PeripheralKind = Literal["i2c", "spi", "uart", "pwm", "adc", "usb"]
BUS_KINDS: frozenset[str] = frozenset({"i2c", "spi", "uart", "usb"})

# Pin function -> (peripheral kind, role token used in MCU profile functions).
FUNCTION_ROLE: dict[str, tuple[str, str]] = {
    "i2c_sda": ("i2c", "sda"),
    "i2c_scl": ("i2c", "scl"),
    "spi_sck": ("spi", "sck"),
    "spi_mosi": ("spi", "mosi"),
    "spi_miso": ("spi", "miso"),
    "spi_cs": ("spi", "cs"),
    "uart_tx": ("uart", "tx"),
    "uart_rx": ("uart", "rx"),
    "uart_cts": ("uart", "cts"),
    "uart_rts": ("uart", "rts"),
    "usb_dp": ("usb", "dp"),
    "usb_dm": ("usb", "dm"),
    "pwm": ("pwm", ""),
    "adc": ("adc", ""),
}
# Every role set in the tuple must be present; a nested tuple is "any of".
REQUIRED_ROLES: dict[str, tuple[tuple[str, ...], ...]] = {
    "i2c": (("sda",), ("scl",)),
    "spi": (("sck",), ("mosi", "miso")),
    "uart": (("tx", "rx"),),
    "usb": (("dp",), ("dm",)),
    "pwm": (),
    "adc": (),
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Mcu(_Strict):
    profile: str = Field(pattern=r"^[a-z0-9_-]+$")
    ref: str = Field(pattern=r"^[A-Z][A-Z0-9]*[0-9]+$")
    flash_kb: int | None = Field(default=None, gt=0)
    ram_kb: int | None = Field(default=None, gt=0)
    clock_mhz: float | None = Field(default=None, gt=0)


class Pin(_Strict):
    signal: str = Field(pattern=IDENT)
    pad: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    net: str = Field(pattern=r"^[A-Za-z0-9_+\-./]+$")
    function: PinFunction
    peripheral: str | None = Field(default=None, pattern=IDENT)
    package_pin: str | None = None
    pull: Literal["none", "up", "down"] = "none"
    active: Literal["high", "low"] = "high"
    initial: Literal["low", "high"] | None = None
    acknowledge: list[Literal["strapping", "jtag"]] = Field(
        default_factory=list[Literal["strapping", "jtag"]]
    )
    rationale: str = ""

    @model_validator(mode="after")
    def _initial_only_for_outputs(self) -> Pin:
        if self.initial is not None and self.function not in ("gpio_out", "pwm"):
            raise ValueError(f"pin {self.signal}: initial applies to gpio_out/pwm only")
        return self


class Peripheral(_Strict):
    id: str = Field(pattern=IDENT)
    kind: PeripheralKind
    instance: int = Field(ge=0)
    frequency_hz: int | None = Field(default=None, gt=0)
    baud: int | None = Field(default=None, gt=0)
    rationale: str = ""


class PowerMode(_Strict):
    id: str = Field(pattern=IDENT)
    kind: Literal["run", "idle", "sleep", "deep_sleep"]
    current_ua: float = Field(gt=0)
    duty: float = Field(gt=0, le=1)
    wake: list[str] = Field(default_factory=list[str])
    peripherals_on: list[str] = Field(default_factory=list[str])


class Power(_Strict):
    supply_net: str = Field(pattern=r"^[A-Za-z0-9_+\-./]+$")
    average_budget_ua: float | None = Field(default=None, gt=0)
    modes: list[PowerMode] = Field(min_length=1)


class Budget(_Strict):
    flash_pct: float = Field(gt=0, le=100)
    ram_pct: float = Field(gt=0, le=100)


class BuildStep(_Strict):
    backend: Literal["make", "cmake", "platformio"]
    dir: str
    target: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.\-]+$")
    env: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.\-]+$")
    elf: str
    timeout_s: int = Field(default=600, gt=0, le=7200)

    @model_validator(mode="after")
    def _backend_fields(self) -> BuildStep:
        if self.backend == "platformio" and self.env is None:
            raise ValueError("platformio builds must name the env")
        if self.backend != "platformio" and self.env is not None:
            raise ValueError("env applies to platformio builds only")
        return self


class Build(BuildStep):
    pins_header: str
    budget: Budget


class Suppression(_Strict):
    id: str = Field(min_length=1)
    file: str | None = None
    line: int | None = Field(default=None, ge=1)
    rationale: str = Field(min_length=12)


class Analysis(_Strict):
    tool: Literal["cppcheck"] = "cppcheck"
    std: Literal["c99", "c11", "c17", "c++17", "c++20"] = "c11"
    sources: list[str] = Field(min_length=1)
    includes: list[str] = Field(default_factory=list[str])
    defines: list[str] = Field(default_factory=list[str])
    fail_on: list[Literal["error", "warning", "style", "performance", "portability"]] = Field(
        default_factory=lambda: ["error", "warning"]
    )
    suppressions: list[Suppression] = Field(default_factory=list[Suppression])


class Simulation(_Strict):
    id: str = Field(pattern=IDENT)
    runner: Literal["qemu-arm", "qemu-esp"]
    machine: str = Field(pattern=r"^[a-z0-9_.\-]+$")
    fidelity: Literal["mcu", "core"]
    image: str
    build: BuildStep | None = None
    expect: list[str] = Field(min_length=1)
    forbid: list[str] = Field(default_factory=list[str])
    exit_code: int | None = None
    timeout_s: float = Field(default=20, gt=0, le=600)

    @model_validator(mode="after")
    def _exit_semantics(self) -> Simulation:
        if self.runner == "qemu-arm" and self.exit_code is None:
            raise ValueError(
                f"simulation {self.id}: qemu-arm runs must declare exit_code (semihosting exit)"
            )
        if self.runner == "qemu-esp" and self.exit_code is not None:
            raise ValueError(f"simulation {self.id}: qemu-esp runs cannot assert an exit code")
        return self


class CircuitLink(_Strict):
    connectivity: str


class CueLink(_Strict):
    """bard product sound cues played through one PWM pin.

    ``sha256`` pins the bard ``cues.json`` manifest so a re-rendered cue set
    is reviewed before the generated header changes. ``min_hz``/``max_hz``
    is the transducer's usable band from its datasheet.
    """

    manifest: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pin: str = Field(pattern=IDENT)
    header: str
    min_hz: float = Field(gt=0)
    max_hz: float = Field(gt=0)
    rationale: str = ""

    @model_validator(mode="after")
    def _band(self) -> CueLink:
        if self.min_hz >= self.max_hz:
            raise ValueError("cues: min_hz must be below max_hz")
        return self


class FpgaLink(_Strict):
    """fpga-agent register map the firmware reaches over ``peripheral``.

    ``sha256`` pins the exact ``<design>.fpga-regmap.json`` so a changed map
    is reviewed before the generated header changes.
    """

    regmap: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    peripheral: str = Field(pattern=IDENT)
    header: str
    rationale: str = ""


class FirmwareContract(_Strict):
    schema_version: Literal[1] = SCHEMA_VERSION
    system: Literal["firmware"] = "firmware"
    artifact_kind: Literal["firmware_contract"] = "firmware_contract"
    name: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    description: str = ""
    mcu: Mcu
    circuit: CircuitLink
    pins: list[Pin] = Field(min_length=1)
    peripherals: list[Peripheral] = Field(default_factory=list[Peripheral])
    power: Power
    build: Build
    analysis: Analysis
    simulations: list[Simulation] = Field(default_factory=list[Simulation])
    cues: CueLink | None = None
    fpga: FpgaLink | None = None

    @model_validator(mode="after")
    def _unique(self) -> FirmwareContract:
        for label, values in (
            ("pin signal", [p.signal for p in self.pins]),
            ("pad", [p.pad for p in self.pins]),
            ("peripheral id", [p.id for p in self.peripherals]),
            ("power mode id", [m.id for m in self.power.modes]),
            ("simulation id", [s.id for s in self.simulations]),
        ):
            duplicates = sorted({v for v in values if values.count(v) > 1})
            if duplicates:
                raise ValueError(f"duplicate {label}: {', '.join(duplicates)}")
        instances = [(p.kind, p.instance) for p in self.peripherals if p.kind in BUS_KINDS]
        clashes = sorted({f"{k}{i}" for k, i in instances if instances.count((k, i)) > 1})
        if clashes:
            raise ValueError(f"peripheral instance declared twice: {', '.join(clashes)}")
        return self

    def pin(self, signal: str) -> Pin | None:
        return next((p for p in self.pins if p.signal == signal), None)

    def peripheral(self, peripheral_id: str) -> Peripheral | None:
        return next((p for p in self.peripherals if p.id == peripheral_id), None)


def load_contract(path: str | Path) -> FirmwareContract:
    return FirmwareContract.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def resolve(contract_path: str | Path, relative: str) -> Path:
    """Contract-relative paths resolve against the contract's directory."""
    candidate = Path(relative)
    if candidate.is_absolute():
        return candidate
    return (Path(contract_path).resolve().parent / candidate).resolve()
