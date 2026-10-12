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
    backend: Literal["make", "cmake", "platformio", "west"]
    dir: str
    target: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.\-]+$")
    env: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.\-]+$")
    board: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.\-/]+$")
    sdk: Literal["zephyr", "nrf-connect"] | None = None
    sysbuild: bool | None = None
    toolchain: Literal["gnuarmemb", "cross-compile"] | None = None
    cross_prefix: str | None = Field(default=None, pattern=r"^[a-z0-9_\-]+-$")
    elf: str
    timeout_s: int = Field(default=600, gt=0, le=7200)

    @model_validator(mode="after")
    def _backend_fields(self) -> BuildStep:
        if self.backend == "platformio" and self.env is None:
            raise ValueError("platformio builds must name the env")
        if self.backend != "platformio" and self.env is not None:
            raise ValueError("env applies to platformio builds only")
        if self.backend == "west":
            if self.board is None:
                raise ValueError(
                    "west builds must name the board target (e.g. nrf52840dk/nrf52840)"
                )
            if self.target is not None:
                raise ValueError("target applies to make/cmake builds only; west names a board")
        else:
            if self.board is not None:
                raise ValueError("board applies to west builds only")
            if self.sdk is not None:
                raise ValueError("sdk applies to west builds only")
            if self.sysbuild is not None:
                raise ValueError("sysbuild applies to west builds only")
            if self.toolchain is not None:
                raise ValueError("toolchain applies to west builds only")
            if self.cross_prefix is not None:
                raise ValueError("cross_prefix applies to west builds only")
        if self.backend == "west" and (
            (self.toolchain == "cross-compile") != (self.cross_prefix is not None)
        ):
            raise ValueError(
                "cross-compile builds must name cross_prefix (e.g. riscv64-unknown-elf-)"
            )
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
    runner: Literal["qemu-arm", "qemu-esp", "node"]
    machine: str | None = Field(default=None, pattern=r"^[a-z0-9_.\-]+$")
    fidelity: Literal["mcu", "core"]
    image: str
    args: list[str] = Field(default_factory=list[str])
    build: BuildStep | None = None
    expect: list[str] = Field(min_length=1)
    forbid: list[str] = Field(default_factory=list[str])
    exit_code: int | None = None
    timeout_s: float = Field(default=20, gt=0, le=600)

    @model_validator(mode="after")
    def _exit_semantics(self) -> Simulation:
        if self.runner in ("qemu-arm", "node") and self.exit_code is None:
            raise ValueError(f"simulation {self.id}: {self.runner} runs must declare exit_code")
        if self.runner == "qemu-esp" and self.exit_code is not None:
            raise ValueError(f"simulation {self.id}: qemu-esp runs cannot assert an exit code")
        if self.runner != "node" and self.args:
            raise ValueError(f"simulation {self.id}: args apply to the node runner only")
        if self.runner == "node" and self.machine is not None:
            raise ValueError(f"simulation {self.id}: machine applies to qemu runners only")
        if self.runner in ("qemu-arm", "qemu-esp") and self.machine is None:
            raise ValueError(f"simulation {self.id}: {self.runner} runs must name the machine")
        return self


class UnitTests(_Strict):
    """Host C unit tests of product code; ``sources`` are measured, ``tests`` hold main()."""

    sources: list[str] = Field(min_length=1)
    tests: list[str] = Field(min_length=1)
    includes: list[str] = Field(default_factory=list[str])
    defines: list[str] = Field(default_factory=list[str])
    std: Literal["c99", "c11", "c17"] = "c11"
    min_line_pct: float = Field(ge=0, le=100)
    min_branch_pct: float = Field(ge=0, le=100)
    timeout_s: int = Field(default=120, gt=0, le=1800)
    rationale: str = Field(min_length=12)

    @model_validator(mode="after")
    def _disjoint(self) -> UnitTests:
        both = sorted(set(self.sources) & set(self.tests))
        if both:
            raise ValueError(f"unit_tests: files are both sources and tests: {both}")
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


class FtmLink(_Strict):
    """production-engineering factory test spec the firmware must serve.

    ``sha256`` pins the exact ``factory-test-spec.json`` so a changed spec is
    reviewed before the generated header changes. ``peripheral`` is the
    firmware peripheral carrying the factory transport (none for SWD/JTAG).
    """

    spec: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    header: str
    peripheral: str | None = Field(default=None, pattern=IDENT)
    rationale: str = ""


MrubycHal = Literal[
    "avr",
    "emscripten",
    "esp32",
    "pic24",
    "posix",
    "psoc5lp",
    "rp2040",
    "stm32",
    "zephyr",
]


class MrubySource(_Strict):
    """One mruby/c Ruby source compiled into bytecode the firmware image links.

    ``file`` is the authored ``.rb`` (typically written by ux-creator-agent),
    ``bytecode`` is the generated C source the build compiles and ``symbol`` is
    the ``mrbc -B`` identifier the product C code passes to ``mrbc_create_task``.
    """

    file: str
    bytecode: str
    symbol: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")


class MrubyUxManifest(_Strict):
    """ux-creator mruby manifest pinning which .rb files ship in this image.

    ``sha256`` pins the exact ``*.mruby-manifest.json`` so a re-authored UX
    script set is reviewed before the generated bytecode changes.
    """

    manifest: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class MrubycConfig(_Strict):
    """Embedded mruby/c VM configuration.

    Values mirror the ``MRBC_*`` macros in ``src/vm_config.h`` of upstream
    mruby/c and are emitted verbatim into ``config_header`` by
    ``firmware mrubyc``; the gate compares generated artifacts byte-for-byte.
    ``ref`` is the upstream mruby/c commit the tools image pins (master
    ``2dec4802`` is the minimum ref carrying the avr, esp32 and rp2040 HALs
    plus ``MRBC_USE_STRING=0``/``MRBC_USE_FLOAT=0``).
    """

    ref: str = Field(pattern=r"^[0-9a-f]{40}$")
    hal: MrubycHal
    memory_size: int = Field(default=40 * 1024, ge=1024)
    tick_unit_ms: int = Field(default=1, ge=1, le=10)
    no_timer: bool = False
    use_float: Literal[0, 1, 2] = 2
    use_math: bool = False
    use_string: bool = True
    use_utf8: bool = False
    max_vm_count: int = Field(default=5, ge=1, le=255)
    sources: list[MrubySource] = Field(min_length=1)
    ux_manifest: MrubyUxManifest | None = None
    generated_dir: str = "fw/generated"
    config_header: str = "fw/include/fw_mruby.h"

    @model_validator(mode="after")
    def _utf8_needs_string(self) -> MrubycConfig:
        if self.use_utf8 and not self.use_string:
            raise ValueError("mrubyc: use_utf8 requires use_string")
        symbols = [s.symbol for s in self.sources]
        if len(set(symbols)) != len(symbols):
            raise ValueError("mrubyc: duplicate source symbols")
        return self


class Security(_Strict):
    """Product security and field-update requirements checked against the build config.

    ``sdkconfig`` is the contract-relative ESP-IDF ``sdkconfig.defaults`` the
    build applies; the gate reads it, it never infers a setting.
    """

    sdkconfig: str = Field(min_length=1)
    secure_boot: bool
    flash_encryption: bool
    ota_rollback: bool
    jtag_disabled: bool
    rationale: str = Field(min_length=12)


class Component(_Strict):
    """Third-party (or reused first-party) code compiled into the image."""

    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.+\-]*$")
    version: str = Field(min_length=1)
    supplier: str = Field(min_length=1)
    license: str = Field(
        pattern=r"^[A-Za-z0-9.+\-]+( (AND|OR|WITH) [A-Za-z0-9.+\-]+)*$",
        description="SPDX license expression",
    )
    source: str = Field(min_length=1)
    paths: list[str] = Field(min_length=1)


class Fault(_Strict):
    """A fault the firmware reports in its runtime status (code 0 means no fault)."""

    code: int = Field(ge=1, le=65535)
    name: str = Field(pattern=IDENT)
    severity: Literal["info", "warning", "error", "critical"]
    action: str = Field(min_length=1, description="what the user or service technician does")


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
    ftm: FtmLink | None = None
    faults: list[Fault] = Field(default_factory=list[Fault])
    security: Security | None = None
    mrubyc: MrubycConfig | None = None
    components: list[Component] = Field(default_factory=list[Component])
    unit_tests: UnitTests | None = None

    @model_validator(mode="after")
    def _unique(self) -> FirmwareContract:
        for label, values in (
            ("pin signal", [p.signal for p in self.pins]),
            ("pad", [p.pad for p in self.pins]),
            ("peripheral id", [p.id for p in self.peripherals]),
            ("power mode id", [m.id for m in self.power.modes]),
            ("simulation id", [s.id for s in self.simulations]),
            ("fault code", [str(f.code) for f in self.faults]),
            ("fault name", [f.name for f in self.faults]),
            ("component", [c.name for c in self.components]),
            (
                "mruby source file",
                [s.file for s in self.mrubyc.sources] if self.mrubyc else [],
            ),
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
