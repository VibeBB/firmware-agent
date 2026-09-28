"""Entry points shared by the CLI and the MCP server. Each returns a JSON
payload with a fail-closed ``verdict``."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from . import doctor
from .contract import Simulation, load_contract, resolve
from .debug import run_debug
from .gates import FAIL, PASS, run_gates, write_outputs
from .interchange import sha256_file
from .profiles import load_profile
from .projections import pinmap_export, pinmap_markdown, pins_header, write_text
from .requests import write_request
from .sim import run_simulation

type Json = dict[str, object]


def _default_out(contract_path: Path) -> Path:
    return contract_path.resolve().parent / "fw-reports"


def doctor_payload() -> Json:
    results = doctor.checks()
    ok = all(item.status != "fail" for item in results)
    return {
        "verdict": PASS if ok else FAIL,
        "checks": [item.model_dump(mode="json") for item in results],
    }


def validate_payload(contract_path: Path) -> Json:
    try:
        contract = load_contract(contract_path)
        profile = load_profile(contract.mcu.profile, [contract_path.parent])
    except (OSError, ValueError, ValidationError) as exc:
        return {"verdict": FAIL, "stage": "validate", "detail": str(exc)}
    return {
        "verdict": PASS,
        "stage": "validate",
        "design": contract.name,
        "profile": profile.id,
        "pins": len(contract.pins),
        "peripherals": len(contract.peripherals),
        "simulations": [s.id for s in contract.simulations],
    }


def gates_payload(contract_path: Path, out_dir: Path | None, *, full: bool) -> Json:
    out = out_dir or _default_out(contract_path)
    report = run_gates(contract_path, out, full=full)
    written = write_outputs(contract_path, report, out)
    payload: Json = json.loads(report.model_dump_json())
    payload["written"] = [str(p) for p in written]
    return payload


def pins_payload(contract_path: Path) -> Json:
    try:
        contract = load_contract(contract_path)
        profile = load_profile(contract.mcu.profile, [contract_path.parent])
    except (OSError, ValueError, ValidationError) as exc:
        return {"verdict": FAIL, "stage": "pins", "detail": str(exc)}
    header = write_text(
        resolve(contract_path, contract.build.pins_header), pins_header(contract, profile)
    )
    return {"verdict": PASS, "stage": "pins", "written": [str(header)]}


def pinmap_payload(contract_path: Path, out_dir: Path | None) -> Json:
    try:
        contract = load_contract(contract_path)
        profile = load_profile(contract.mcu.profile, [contract_path.parent])
    except (OSError, ValueError, ValidationError) as exc:
        return {"verdict": FAIL, "stage": "pinmap", "detail": str(exc)}
    out = out_dir or _default_out(contract_path)
    pinmap = pinmap_export(contract, profile, sha256_file(contract_path))
    json_path = write_text(
        out / f"{contract.name}.fw-pinmap.json",
        json.dumps(pinmap.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
    )
    md_path = write_text(out / f"{contract.name}.pinmap.md", pinmap_markdown(pinmap))
    return {"verdict": PASS, "stage": "pinmap", "written": [str(json_path), str(md_path)]}


def sim_payload(contract_path: Path, sim_id: str, out_dir: Path | None) -> Json:
    try:
        contract = load_contract(contract_path)
    except (OSError, ValueError, ValidationError) as exc:
        return {"verdict": FAIL, "stage": "sim", "detail": str(exc)}
    sim = next((s for s in contract.simulations if s.id == sim_id), None)
    if sim is None:
        return {"verdict": FAIL, "stage": "sim", "detail": f"unknown simulation {sim_id}"}
    out = out_dir or _default_out(contract_path)
    root = contract_path.resolve().parent
    result = run_simulation(sim, root / sim.image, out / f"sim-{sim.id}.log")
    return {
        "verdict": PASS if result.ok else FAIL,
        "stage": "sim",
        "simulation": sim.id,
        "detail": result.detail,
        "argv": result.argv,
        "exit_code": result.exit_code,
        "matched": result.matched,
        "missing": result.missing,
        "forbidden": result.forbidden,
        "transcript": str(result.transcript) if result.transcript else None,
    }


def _symbol_file(firmware_elf: str, sim: Simulation) -> str:
    """ELF carrying debug symbols for ``sim``: its own build, the image, or the firmware."""
    if sim.build is not None:
        return sim.build.elf
    if sim.image.endswith(".elf"):
        return sim.image
    return firmware_elf


def debug_payload(
    contract_path: Path,
    sim_id: str,
    elf: str | None,
    breaks: list[str],
    prints: list[str],
    out_dir: Path | None,
) -> Json:
    try:
        contract = load_contract(contract_path)
    except (OSError, ValueError, ValidationError) as exc:
        return {"verdict": FAIL, "stage": "debug", "detail": str(exc)}
    sim = next((s for s in contract.simulations if s.id == sim_id), None)
    if sim is None:
        return {"verdict": FAIL, "stage": "debug", "detail": f"unknown simulation {sim_id}"}
    root = contract_path.resolve().parent
    symbols = root / (elf or _symbol_file(contract.build.elf, sim))
    try:
        session = run_debug(sim, root / sim.image, symbols, breaks, prints)
    except ValueError as exc:
        return {"verdict": FAIL, "stage": "debug", "detail": str(exc)}
    out = out_dir or _default_out(contract_path)
    record = write_text(
        out / f"debug-{sim.id}.advisory.json", session.model_dump_json(indent=2) + "\n"
    )
    payload: Json = json.loads(session.model_dump_json())
    payload["verdict"] = PASS if session.ok else FAIL
    payload["stage"] = "debug"
    payload["written"] = [str(record)]
    return payload


def request_payload(
    contract_path: Path,
    out_dir: Path | None,
    *,
    target: str,
    risk: str,
    change: str,
    rationale: str,
    nets: list[str],
    failing_checks: list[str],
) -> Json:
    try:
        contract = load_contract(contract_path)
        request, path = write_request(
            contract_path,
            contract.name,
            out_dir or _default_out(contract_path),
            target=target,
            risk=risk,
            change=change,
            rationale=rationale,
            nets=nets,
            failing_checks=failing_checks,
        )
    except (OSError, ValueError, ValidationError) as exc:
        return {"verdict": FAIL, "stage": "request", "detail": str(exc)}
    return {"verdict": PASS, "stage": "request", "id": request.id, "written": [str(path)]}


def profile_payload(profile_id: str) -> Json:
    try:
        profile = load_profile(profile_id)
    except (OSError, ValueError, ValidationError) as exc:
        return {"verdict": FAIL, "stage": "profile", "detail": str(exc)}
    payload: Json = json.loads(profile.model_dump_json())
    payload["verdict"] = PASS
    return payload
