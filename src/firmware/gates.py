"""Deterministic firmware gates. Unknown evidence fails; nothing passes on
an agent's word.

Static gates (no toolchain): ``fw.contract``, ``fw.pin_functions``,
``fw.netlist_match``, ``fw.power_modes``, ``fw.pins_header``, ``fw.ftm``.
Toolchain gates: ``fw.build``, ``fw.memory_budget``, ``fw.static_analysis``,
``fw.sim.<id>``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .analysis import run_cppcheck
from .build import run_build
from .contract import (
    FUNCTION_ROLE,
    REQUIRED_ROLES,
    FirmwareContract,
    load_contract,
    resolve,
)
from .elf import ElfError, account, read_elf
from .interchange import (
    CircuitFirmwareConnectivity,
    CircuitMcuPin,
    load_circuit,
    load_cue_manifest,
    load_fpga_regmap,
    load_ftm_spec,
    pad_of,
    sha256_file,
)
from .profiles import McuProfile, load_profile
from .projections import (
    cues_header,
    fpga_regs_header,
    ftm_header,
    pinmap_export,
    pinmap_markdown,
    pins_header,
    write_bytes,
    write_text,
)
from .render import render_pinmap, render_report
from .sim import run_simulation

Status = Literal["pass", "fail", "not_applicable"]
Verdict = Literal["pass", "fail"]
PASS: Verdict = "pass"
FAIL: Verdict = "fail"
POWER_CLASSES = frozenset({"power", "ground"})
FTM_TRANSPORT_KIND = {"uart": "uart", "usb_cdc": "usb", "i2c": "i2c", "spi": "spi"}
DEBUG_TRANSPORTS = frozenset({"swd", "jtag"})
CORE_MACHINE = {"cortex": "arm", "xtensa": "xtensa", "riscv": "riscv"}


class Check(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    subject: str = ""
    status: Status
    detail: str = ""
    evidence: list[str] = Field(default_factory=list[str])


class GateReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    system: Literal["firmware"] = "firmware"
    artifact_kind: Literal["firmware_gate_report"] = "firmware_gate_report"
    design: str
    scope: Literal["static", "full"]
    contract_sha256: str
    circuit_sha256: str | None
    profile: str | None
    verdict: Verdict
    checks: list[Check]
    metrics: dict[str, float] = Field(default_factory=dict[str, float])
    elf_sha256: str | None = None


def _check(
    check_id: str, subject: str, problems: list[str], evidence: list[str] | None = None
) -> Check:
    return Check(
        id=check_id,
        subject=subject,
        status="fail" if problems else "pass",
        detail="; ".join(problems),
        evidence=evidence or [],
    )


def check_pin_functions(contract: FirmwareContract, profile: McuProfile) -> Check:
    problems: list[str] = []
    for peripheral in contract.peripherals:
        allowed = profile.peripherals.get(peripheral.kind)
        if allowed is None:
            problems.append(f"{peripheral.id}: {profile.part} has no {peripheral.kind}")
        elif peripheral.instance not in allowed:
            problems.append(
                f"{peripheral.id}: {peripheral.kind}{peripheral.instance} does not exist "
                f"on {profile.part} (instances {allowed})"
            )
    roles: dict[str, list[str]] = {p.id: [] for p in contract.peripherals}
    channels: dict[str, str] = {}
    for pin in contract.pins:
        pad = profile.pad(pin.pad)
        if pad is None:
            problems.append(f"{pin.signal}: pad {pin.pad} is not on {profile.part}")
            continue
        if pad.reserved is not None:
            problems.append(f"{pin.signal}: pad {pin.pad} is reserved ({pad.reserved})")
            continue
        if pad.caution is not None and pad.caution not in pin.acknowledge:
            problems.append(
                f"{pin.signal}: pad {pin.pad} is a {pad.caution} pin; acknowledge it "
                "with a rationale or move the signal"
            )
        if pin.function in ("gpio_in", "gpio_out"):
            if pin.peripheral is not None:
                problems.append(f"{pin.signal}: GPIO pins take no peripheral")
            if "gpio" not in pad.functions:
                problems.append(f"{pin.signal}: pad {pin.pad} has no GPIO function")
            continue
        kind, role = FUNCTION_ROLE[pin.function]
        peripheral = contract.peripheral(pin.peripheral) if pin.peripheral else None
        if pin.peripheral is not None and peripheral is None:
            problems.append(f"{pin.signal}: unknown peripheral {pin.peripheral}")
            continue
        if peripheral is None and kind in ("i2c", "spi", "uart", "usb"):
            problems.append(f"{pin.signal}: {pin.function} needs a {kind} peripheral")
            continue
        if peripheral is not None and peripheral.kind != kind:
            problems.append(
                f"{pin.signal}: {pin.function} bound to "
                f"{peripheral.kind} peripheral {peripheral.id}"
            )
            continue
        instance = peripheral.instance if peripheral is not None else None
        if not pad.supports(kind, instance, role):
            label = f"{kind}{'' if instance is None else instance}{'.' + role if role else ''}"
            problems.append(f"{pin.signal}: pad {pin.pad} cannot route {label}")
            continue
        if peripheral is not None:
            roles[peripheral.id].append(role)
        for channel in pad.fixed_channels(kind) if kind == "pwm" else []:
            if instance is not None and not channel.startswith(f"pwm{instance}."):
                continue
            if channel in channels:
                problems.append(f"{pin.signal}: {channel} already drives {channels[channel]}")
            channels[channel] = pin.signal
    for peripheral in contract.peripherals:
        used = roles[peripheral.id]
        if not used and peripheral.kind in ("i2c", "spi", "uart", "usb"):
            problems.append(f"{peripheral.id}: no pins bound")
            continue
        for any_of in REQUIRED_ROLES[peripheral.kind]:
            if not any(role in used for role in any_of):
                problems.append(f"{peripheral.id}: missing {' or '.join(any_of)} pin")
        doubled = sorted({r for r in used if r and r != "cs" and used.count(r) > 1})
        if doubled:
            problems.append(f"{peripheral.id}: role(s) bound twice: {', '.join(doubled)}")
    return _check("fw.pin_functions", profile.part, problems)


def _circuit_pin(
    circuit_pins: list[CircuitMcuPin], names: frozenset[str], package_pin: str | None
) -> CircuitMcuPin | None:
    by_function = [p for p in circuit_pins if pad_of(p.function) in names]
    if len(by_function) == 1:
        return by_function[0]
    if package_pin is not None:
        return next((p for p in circuit_pins if p.pin == package_pin), None)
    return None


def check_netlist_match(
    contract: FirmwareContract, profile: McuProfile, circuit: CircuitFirmwareConnectivity
) -> Check:
    mcu = circuit.mcu(contract.mcu.ref)
    if mcu is None:
        refs = ", ".join(m.ref for m in circuit.mcus)
        return _check(
            "fw.netlist_match",
            contract.mcu.ref,
            [f"circuit has no MCU {contract.mcu.ref} ({refs})"],
        )
    problems: list[str] = []
    evidence: list[str] = [f"circuit source={circuit.source}"]
    claimed: set[str] = set()
    for pin in contract.pins:
        pad = profile.pad(pin.pad)
        package_pin = pin.package_pin or (pad.pin if pad is not None else None)
        names = pad.names if pad is not None else frozenset([pin.pad])
        found = _circuit_pin(mcu.pins, names, package_pin)
        if found is None:
            problems.append(
                f"{pin.signal}: {pin.pad} not found on {mcu.ref} (no matching pin function"
                f"{'' if package_pin else ' and no package pin'})"
            )
            continue
        claimed.add(found.pin)
        if found.net != pin.net:
            problems.append(
                f"{pin.signal}: {pin.pad} ({mcu.ref}.{found.pin}) is on net "
                f"{found.net or 'unconnected'}, contract says {pin.net}"
            )
            continue
        if found.signal_class in POWER_CLASSES:
            problems.append(f"{pin.signal}: net {pin.net} is a {found.signal_class} net")
        if found.voltage_v is not None and found.voltage_v > profile.io_voltage_max_v:
            problems.append(
                f"{pin.signal}: net {pin.net} at {found.voltage_v} V exceeds "
                f"{profile.part} I/O maximum {profile.io_voltage_max_v} V"
            )
        evidence.append(f"{pin.signal}={mcu.ref}.{found.pin}/{pin.net}")
    for circuit_pin in mcu.pins:
        if circuit_pin.pin in claimed or circuit_pin.net is None:
            continue
        if circuit_pin.signal_class in POWER_CLASSES:
            continue
        pad = profile.pad(pad_of(circuit_pin.function) or "") or profile.pad_by_pin(circuit_pin.pin)
        if pad is None:
            problems.append(
                f"{mcu.ref}.{circuit_pin.pin} on net {circuit_pin.net} does not resolve to a "
                f"{profile.part} pad"
            )
        elif pad.reserved is None:
            problems.append(
                f"{mcu.ref}.{circuit_pin.pin} ({pad.name}) drives net {circuit_pin.net} but the "
                "firmware assigns nothing to it"
            )
    supply = [p for p in mcu.pins if p.net == contract.power.supply_net]
    if not supply:
        problems.append(f"supply net {contract.power.supply_net} does not reach {mcu.ref}")
    return _check("fw.netlist_match", mcu.ref, problems, evidence)


def check_power_modes(contract: FirmwareContract, profile: McuProfile) -> Check:
    problems: list[str] = []
    total = sum(mode.duty for mode in contract.power.modes)
    if abs(total - 1.0) > 1e-6:
        problems.append(f"mode duties sum to {total:.6f}, not 1")
    if not any(mode.kind == "run" for mode in contract.power.modes):
        problems.append("no run mode")
    for mode in contract.power.modes:
        for peripheral_id in mode.peripherals_on:
            if contract.peripheral(peripheral_id) is None:
                problems.append(f"{mode.id}: unknown peripheral {peripheral_id}")
        if mode.kind in ("sleep", "deep_sleep") and not mode.wake:
            problems.append(f"{mode.id}: {mode.kind} without a wake source never returns")
        for source in mode.wake:
            if source == "timer":
                continue
            pin = contract.pin(source)
            if pin is None:
                problems.append(f"{mode.id}: wake source {source} is not a pin signal or 'timer'")
                continue
            if pin.function != "gpio_in":
                problems.append(f"{mode.id}: wake pin {source} is not gpio_in")
            pad = profile.pad(pin.pad)
            if mode.kind == "deep_sleep" and (pad is None or not pad.wake_deep_sleep):
                problems.append(f"{mode.id}: {pin.pad} cannot wake {profile.part} from deep sleep")
    average = sum(mode.current_ua * mode.duty for mode in contract.power.modes)
    evidence = [f"average={average:.1f}uA"]
    budget = contract.power.average_budget_ua
    if budget is not None and average > budget:
        problems.append(f"average current {average:.1f} uA exceeds budget {budget:.1f} uA")
    return _check("fw.power_modes", contract.name, problems, evidence)


def check_pins_header(
    contract: FirmwareContract, profile: McuProfile, contract_path: Path
) -> Check:
    header = resolve(contract_path, contract.build.pins_header)
    expected = pins_header(contract, profile)
    if not header.is_file():
        return _check(
            "fw.pins_header", contract.build.pins_header, ["missing; run `firmware pins`"]
        )
    if header.read_text(encoding="utf-8") != expected:
        return _check(
            "fw.pins_header", contract.build.pins_header, ["stale; regenerate with `firmware pins`"]
        )
    return _check("fw.pins_header", contract.build.pins_header, [])


def check_bard_cues(contract: FirmwareContract, contract_path: Path) -> Check:
    """bard cue manifest pinned, playable on the declared pin, header current."""
    link = contract.cues
    if link is None:
        raise ValueError("contract declares no cues")
    manifest_path = resolve(contract_path, link.manifest)
    try:
        manifest = load_cue_manifest(manifest_path)
        manifest_sha = sha256_file(manifest_path)
    except (OSError, ValueError, ValidationError) as exc:
        return _check("fw.bard_cues", link.manifest, [f"unreadable bard cue manifest: {exc}"])
    problems: list[str] = []
    if manifest_sha != link.sha256:
        problems.append(
            f"manifest sha256 {manifest_sha} differs from pinned {link.sha256}; "
            "review the new cues and re-pin cues.sha256"
        )
    pin = contract.pin(link.pin)
    if pin is None:
        problems.append(f"cue pin {link.pin} is not declared")
    elif pin.function != "pwm" or pin.peripheral is None:
        problems.append(f"cue pin {link.pin} must be a pwm pin with a peripheral")
    tones = 0
    sounded: list[float] = []
    for cue in manifest.cues:
        if cue.loop and cue.purpose not in ("warning", "error"):
            problems.append(f"cue {cue.id}: only warning/error cues may loop")
        clock = 0
        for tone in cue.tones:
            tones += 1
            if tone.start_ms != clock:
                problems.append(f"cue {cue.id}: tone at {tone.start_ms} ms leaves a gap or overlap")
            clock = tone.start_ms + tone.duration_ms
            if (tone.midi is None) != (tone.freq_hz == 0):
                problems.append(f"cue {cue.id}: tone at {tone.start_ms} ms mixes rest and pitch")
            elif tone.freq_hz > 0:
                sounded.append(tone.freq_hz)
                if not link.min_hz <= tone.freq_hz <= link.max_hz:
                    problems.append(
                        f"cue {cue.id}: {tone.freq_hz} Hz outside the transducer band "
                        f"{link.min_hz}-{link.max_hz} Hz"
                    )
        if clock != cue.duration_ms:
            problems.append(f"cue {cue.id}: tones last {clock} ms, cue says {cue.duration_ms} ms")
    header = resolve(contract_path, link.header)
    if not header.is_file():
        problems.append(f"{link.header} missing; run `firmware cues`")
    elif header.read_text(encoding="utf-8") != cues_header(contract, manifest, manifest_sha):
        problems.append(f"{link.header} stale; regenerate with `firmware cues`")
    evidence = [f"cues={len(manifest.cues)}", f"tones={tones}", f"sha256={manifest_sha}"]
    if sounded:
        evidence.append(f"band={min(sounded)}-{max(sounded)}Hz")
    return _check("fw.bard_cues", link.manifest, problems, evidence)


def check_fpga_regmap(contract: FirmwareContract, contract_path: Path) -> Check:
    """fpga register map pinned, reached over a matching bus, header current."""
    link = contract.fpga
    if link is None:
        raise ValueError("contract declares no fpga link")
    regmap_path = resolve(contract_path, link.regmap)
    try:
        regmap = load_fpga_regmap(regmap_path)
        regmap_sha = sha256_file(regmap_path)
    except (OSError, ValueError, ValidationError) as exc:
        return _check("fw.fpga_regmap", link.regmap, [f"unreadable fpga register map: {exc}"])
    problems: list[str] = []
    if regmap_sha != link.sha256:
        problems.append(
            f"register map sha256 {regmap_sha} differs from pinned {link.sha256}; "
            "review the new map and re-pin fpga.sha256"
        )
    peripheral = next((p for p in contract.peripherals if p.id == link.peripheral), None)
    if peripheral is None:
        problems.append(f"fpga peripheral {link.peripheral} is not declared")
    elif peripheral.kind != regmap.bus:
        problems.append(
            f"fpga peripheral {link.peripheral} is {peripheral.kind}; "
            f"the FPGA map uses {regmap.bus}"
        )
    else:
        header = resolve(contract_path, link.header)
        try:
            expected = fpga_regs_header(contract, regmap, regmap_sha)
        except ValueError as exc:
            problems.append(str(exc))
        else:
            if not header.is_file():
                problems.append(f"{link.header} missing; run `firmware fpga-regs`")
            elif header.read_text(encoding="utf-8") != expected:
                problems.append(f"{link.header} stale; regenerate with `firmware fpga-regs`")
    evidence = [
        f"design={regmap.design}",
        f"bus={regmap.bus}",
        f"registers={len(regmap.registers)}",
        f"sha256={regmap_sha}",
    ]
    return _check("fw.fpga_regmap", link.regmap, problems, evidence)


def _ftm_wiring(
    contract: FirmwareContract, transport: str, nets: list[str], entry: str
) -> list[str]:
    link = contract.ftm
    if link is None:
        raise ValueError("contract declares no ftm link")
    if transport in DEBUG_TRANSPORTS:
        if link.peripheral is not None:
            return [f"ftm transport {transport} is a debug port; drop ftm.peripheral"]
        return []
    kind = FTM_TRANSPORT_KIND.get(transport)
    if kind is None:
        return [f"ftm transport {transport} has no firmware peripheral to check against"]
    problems: list[str] = []
    peripheral = contract.peripheral(link.peripheral) if link.peripheral else None
    if link.peripheral is None:
        problems.append(f"ftm transport {transport} needs ftm.peripheral (a {kind} peripheral)")
    elif peripheral is None:
        problems.append(f"ftm peripheral {link.peripheral} is not declared")
    elif peripheral.kind != kind:
        problems.append(
            f"ftm peripheral {link.peripheral} is {peripheral.kind}; "
            f"the factory test spec uses {transport}"
        )
    by_net = {pin.net: pin for pin in contract.pins}
    missing = sorted(net for net in nets if net not in by_net)
    if missing:
        problems.append(f"factory test nets not on an MCU pin: {', '.join(missing)}")
    wired = [by_net[net] for net in nets if net in by_net]
    if peripheral is not None and not any(pin.peripheral == peripheral.id for pin in wired):
        problems.append(f"no factory test net is routed to ftm peripheral {peripheral.id}")
    if entry == "gpio_strap" and not any(pin.function == "gpio_in" for pin in wired):
        problems.append("gpio_strap entry needs a gpio_in pin on a factory test net")
    return problems


def check_ftm(contract: FirmwareContract, contract_path: Path) -> Check:
    """prodeng factory test spec pinned, transport wired, header current."""
    link = contract.ftm
    if link is None:
        raise ValueError("contract declares no ftm link")
    spec_path = resolve(contract_path, link.spec)
    try:
        spec = load_ftm_spec(spec_path)
        spec_sha = sha256_file(spec_path)
    except (OSError, ValueError, ValidationError) as exc:
        return _check("fw.ftm", link.spec, [f"unreadable factory test spec: {exc}"])
    problems: list[str] = []
    if spec_sha != link.sha256:
        problems.append(
            f"factory test spec sha256 {spec_sha} differs from pinned {link.sha256}; "
            "review the new spec and re-pin ftm.sha256"
        )
    problems += _ftm_wiring(
        contract, spec.interface.transport, spec.interface.nets, spec.entry.method
    )
    if not problems:
        header = resolve(contract_path, link.header)
        try:
            expected = ftm_header(contract, spec, spec_sha)
        except ValueError as exc:
            problems.append(str(exc))
        else:
            if not header.is_file():
                problems.append(f"{link.header} missing; run `firmware ftm`")
            elif header.read_text(encoding="utf-8") != expected:
                problems.append(f"{link.header} stale; regenerate with `firmware ftm`")
    evidence = [
        f"transport={spec.interface.transport}",
        f"entry={spec.entry.method}",
        f"commands={','.join(command.id for command in spec.commands)}",
        f"sha256={spec_sha}",
    ]
    return _check("fw.ftm", link.spec, problems, evidence)


def _memory_check(
    contract: FirmwareContract, profile: McuProfile, elf_path: Path
) -> tuple[Check, dict[str, float]]:
    try:
        image = read_elf(elf_path)
    except (ElfError, OSError) as exc:
        return _check("fw.memory_budget", contract.build.elf, [str(exc)]), {}
    problems: list[str] = []
    expected = next((m for k, m in CORE_MACHINE.items() if profile.core.startswith(k)), None)
    if expected is not None and image.machine != expected:
        problems.append(f"ELF machine {image.machine} does not match {profile.core}")
    usage = account(image, profile.memory_regions)
    if usage.unplaced:
        problems.append(f"segments outside every memory region: {', '.join(usage.unplaced)}")
    flash_kb = contract.mcu.flash_kb or profile.flash_kb
    ram_kb = contract.mcu.ram_kb or profile.ram_kb
    flash_limit = flash_kb * 1024 * contract.build.budget.flash_pct / 100
    ram_limit = ram_kb * 1024 * contract.build.budget.ram_pct / 100
    if usage.flash > flash_limit:
        problems.append(
            f"flash {usage.flash} B exceeds {contract.build.budget.flash_pct}% of {flash_kb} KiB"
        )
    if usage.ram > ram_limit:
        problems.append(
            f"RAM {usage.ram} B exceeds {contract.build.budget.ram_pct}% of {ram_kb} KiB"
        )
    for region in profile.memory_regions:
        used = usage.per_region.get(region.name, 0)
        if used > region.length_kb * 1024:
            problems.append(f"region {region.name} overflows: {used} B > {region.length_kb} KiB")
    evidence = [
        f"flash={usage.flash}B ({100 * usage.flash / (flash_kb * 1024):.2f}% of {flash_kb}KiB)",
        f"ram={usage.ram}B ({100 * usage.ram / (ram_kb * 1024):.2f}% of {ram_kb}KiB)",
        *(f"{name}={size}B" for name, size in sorted(usage.per_region.items())),
    ]
    metrics = {
        "flash_bytes": float(usage.flash),
        "flash_capacity_bytes": float(flash_kb * 1024),
        "flash_budget_bytes": float(flash_limit),
        "ram_bytes": float(usage.ram),
        "ram_capacity_bytes": float(ram_kb * 1024),
        "ram_budget_bytes": float(ram_limit),
    }
    return _check("fw.memory_budget", contract.build.elf, problems, evidence), metrics


def check_memory(contract: FirmwareContract, profile: McuProfile, elf_path: Path) -> Check:
    check, _metrics = _memory_check(contract, profile, elf_path)
    return check


def _load_inputs(
    contract_path: Path, profile_dirs: list[Path]
) -> tuple[
    FirmwareContract, McuProfile, CircuitFirmwareConnectivity | None, str | None, list[Check]
]:
    contract = load_contract(contract_path)
    checks: list[Check] = []
    profile = load_profile(contract.mcu.profile, [contract_path.parent, *profile_dirs])
    circuit_path = resolve(contract_path, contract.circuit.connectivity)
    circuit: CircuitFirmwareConnectivity | None = None
    circuit_sha: str | None = None
    problems: list[str] = []
    try:
        circuit = load_circuit(circuit_path)
        circuit_sha = sha256_file(circuit_path)
    except (OSError, ValueError, ValidationError) as exc:
        problems.append(f"circuit connectivity {contract.circuit.connectivity}: {exc}")
    checks.append(_check("fw.contract", contract.name, problems, [f"profile={profile.id}"]))
    return contract, profile, circuit, circuit_sha, checks


def run_gates(
    contract_path: Path,
    out_dir: Path,
    *,
    full: bool = True,
    profile_dirs: list[Path] | None = None,
) -> GateReport:
    contract_path = contract_path.resolve()
    contract_sha = sha256_file(contract_path)
    try:
        contract, profile, circuit, circuit_sha, checks = _load_inputs(
            contract_path, profile_dirs or []
        )
    except (OSError, ValueError, ValidationError) as exc:
        return GateReport(
            design=contract_path.stem.removesuffix(".fw"),
            scope="full" if full else "static",
            contract_sha256=contract_sha,
            circuit_sha256=None,
            profile=None,
            verdict=FAIL,
            checks=[Check(id="fw.contract", status="fail", detail=str(exc))],
        )
    root = contract_path.parent
    checks.append(check_pin_functions(contract, profile))
    if circuit is None:
        checks.append(_check("fw.netlist_match", contract.mcu.ref, ["no circuit connectivity"]))
    else:
        checks.append(check_netlist_match(contract, profile, circuit))
    checks.append(check_power_modes(contract, profile))
    checks.append(check_pins_header(contract, profile, contract_path))
    if contract.cues is not None:
        checks.append(check_bard_cues(contract, contract_path))
    if contract.fpga is not None:
        checks.append(check_fpga_regmap(contract, contract_path))
    if contract.ftm is not None:
        checks.append(check_ftm(contract, contract_path))
    metrics: dict[str, float] = {
        "average_ua": sum(mode.current_ua * mode.duty for mode in contract.power.modes),
    }
    if contract.power.average_budget_ua is not None:
        metrics["average_budget_ua"] = contract.power.average_budget_ua
    elf_sha: str | None = None
    if full:
        build = run_build(contract.build, root, out_dir / "build.log")
        checks.append(
            _check(
                "fw.build",
                contract.build.backend,
                [] if build.ok else [build.detail],
                [" ".join(argv) for argv in build.argv] + [f"seconds={build.seconds:.1f}"],
            )
        )
        if build.ok:
            elf_sha = sha256_file(build.elf)
            memory, memory_metrics = _memory_check(contract, profile, build.elf)
            checks.append(memory)
            metrics.update(memory_metrics)
        else:
            checks.append(_check("fw.memory_budget", contract.build.elf, ["build failed"]))
        analysis = run_cppcheck(contract.analysis, root)
        checks.append(
            _check(
                "fw.static_analysis",
                analysis.tool_version or "cppcheck",
                []
                if analysis.ok
                else [analysis.detail]
                + [
                    f"{f.file}:{f.line} [{f.severity}/{f.id}] {f.message}"
                    for f in analysis.blocking
                ],
                [analysis.detail]
                + [f"suppressed {f.file}:{f.line} {f.id}" for f in analysis.suppressed]
                + [f"advisory {f.file}:{f.line} [{f.severity}/{f.id}]" for f in analysis.advisory],
            )
        )
        checks.extend(_simulation_checks(contract, profile, root, out_dir))
    verdict: Verdict = PASS if all(c.status != "fail" for c in checks) else FAIL
    return GateReport(
        design=contract.name,
        scope="full" if full else "static",
        contract_sha256=contract_sha,
        circuit_sha256=circuit_sha,
        profile=profile.id,
        verdict=verdict,
        checks=checks,
        metrics=metrics,
        elf_sha256=elf_sha,
    )


def _simulation_checks(
    contract: FirmwareContract, profile: McuProfile, root: Path, out_dir: Path
) -> list[Check]:
    if not contract.simulations:
        return [
            Check(
                id="fw.sim",
                status="not_applicable",
                detail="contract declares no simulation runs",
            )
        ]
    checks: list[Check] = []
    for sim in contract.simulations:
        check_id = f"fw.sim.{sim.id}"
        subject = f"{sim.runner}:{sim.machine} ({sim.fidelity})"
        if sim.fidelity == "mcu" and sim.machine != profile.sim_machine:
            checks.append(
                _check(
                    check_id,
                    subject,
                    [
                        f"{profile.part} has no emulated machine"
                        if profile.sim_machine is None
                        else f"mcu-fidelity runs must use machine {profile.sim_machine}"
                    ],
                )
            )
            continue
        if sim.build is not None:
            build = run_build(sim.build, root, out_dir / f"sim-{sim.id}.build.log")
            if not build.ok:
                checks.append(_check(check_id, subject, [f"simulation build: {build.detail}"]))
                continue
        result = run_simulation(sim, root / sim.image, out_dir / f"sim-{sim.id}.log")
        checks.append(
            _check(
                check_id,
                subject,
                [] if result.ok else [result.detail],
                [
                    f"matched={len(result.matched)}/{len(sim.expect)}",
                    f"seconds={result.seconds:.1f}",
                ]
                + ([f"exit={result.exit_code}"] if result.exit_code is not None else []),
            )
        )
    return checks


def report_markdown(report: GateReport) -> str:
    lines = [
        f"# Firmware gate report: {report.design}",
        "",
        f"- verdict: **{report.verdict}** ({report.scope})",
        f"- profile: {report.profile}",
        f"- contract sha256: `{report.contract_sha256}`",
        f"- circuit sha256: `{report.circuit_sha256}`",
        "",
        "| Check | Subject | Status | Detail |",
        "| --- | --- | --- | --- |",
    ]
    for check in report.checks:
        detail = check.detail.replace("|", "\\|") or "; ".join(check.evidence[:3])
        lines.append(f"| {check.id} | {check.subject} | {check.status} | {detail} |")
    return "\n".join(lines) + "\n"


def write_outputs(
    contract_path: Path,
    report: GateReport,
    out_dir: Path,
    render_errors: list[str] | None = None,
) -> list[Path]:
    """Write the report plus the pin map export, Markdown view and PNG renders.

    Render failures are advisory: they append to ``render_errors`` and never
    change the report verdict.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written = [
        write_text(
            out_dir / f"{report.design}.fw-report.json", report.model_dump_json(indent=2) + "\n"
        ),
        write_text(out_dir / f"{report.design}.fw-report.md", report_markdown(report)),
    ]
    try:
        contract = load_contract(contract_path)
        profile = load_profile(contract.mcu.profile, [contract_path.parent])
    except (OSError, ValueError, ValidationError):
        return written
    pinmap = pinmap_export(contract, profile, sha256_file(contract_path))
    written.append(
        write_text(
            out_dir / f"{contract.name}.fw-pinmap.json",
            json.dumps(pinmap.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        )
    )
    written.append(write_text(out_dir / f"{contract.name}.pinmap.md", pinmap_markdown(pinmap)))
    try:
        written.append(
            write_bytes(
                out_dir / f"{contract.name}.pinmap.png",
                render_pinmap(contract, profile, report.contract_sha256),
            )
        )
    except Exception as exc:
        if render_errors is not None:
            render_errors.append(f"pinmap.png: {exc}")
    try:
        written.append(
            write_bytes(
                out_dir / f"{report.design}.fw-report.png",
                render_report(report, contract),
            )
        )
    except Exception as exc:
        if render_errors is not None:
            render_errors.append(f"fw-report.png: {exc}")
    return written
