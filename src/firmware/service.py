"""Entry points shared by the CLI and the MCP server. Each returns a JSON
payload with a fail-closed ``verdict``."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from pydantic import ValidationError

from . import doctor, liaison
from .contract import Simulation, load_contract, resolve
from .debug import run_debug
from .gates import FAIL, PASS, run_gates, write_outputs
from .interchange import load_cue_manifest, load_ftm_spec, sha256_file
from .production import production_export
from .profiles import load_profile
from .projections import (
    cues_header,
    ftm_header,
    pinmap_export,
    pinmap_markdown,
    pins_header,
    power_export,
    write_bytes,
    write_text,
)
from .records import RECORDERS, records_summary
from .render import render_pinmap, render_sim_timeline
from .requests import write_request
from .sim import SimResult, run_simulation

type Json = dict[str, object]

VISION_HINT = (
    "Inspect each PNG with inspect_image_with_vision (or view the inline image) and "
    "record firmware_record_vision_review with a >=400-char, >=3-sentence impression "
    "judging accuracy against the contract, ambiguity, design intent and usefulness "
    "to the maker; vision is advisory and never overrides gates."
)


def _attach_image_meta(payload: Json) -> Json:
    """Advertise which written PNGs still need a vision review."""
    written = payload.get("written")
    entries = cast(list[object], written) if isinstance(written, list) else []
    pngs = [str(p) for p in entries if str(p).endswith(".png")]
    if pngs:
        payload["vision_review_required"] = cast(object, pngs)
        payload["vision_hint"] = VISION_HINT
    return payload


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
    render_errors: list[str] = []
    written = write_outputs(contract_path, report, out, render_errors)
    payload: Json = json.loads(report.model_dump_json())
    payload["written"] = [str(p) for p in written]
    if render_errors:
        payload["render_errors"] = render_errors
    return _attach_image_meta(payload)


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


def cues_payload(contract_path: Path) -> Json:
    """Regenerate ``cues.header`` from the pinned bard cue manifest."""
    try:
        contract = load_contract(contract_path)
        if contract.cues is None:
            return {"verdict": FAIL, "stage": "cues", "detail": "contract declares no cues"}
        manifest_path = resolve(contract_path, contract.cues.manifest)
        manifest = load_cue_manifest(manifest_path)
        manifest_sha = sha256_file(manifest_path)
    except (OSError, ValueError, ValidationError) as exc:
        return {"verdict": FAIL, "stage": "cues", "detail": str(exc)}
    if manifest_sha != contract.cues.sha256:
        return {
            "verdict": FAIL,
            "stage": "cues",
            "detail": f"manifest sha256 {manifest_sha} differs from pinned {contract.cues.sha256}; "
            "review the new cues and re-pin cues.sha256",
        }
    header = write_text(
        resolve(contract_path, contract.cues.header),
        cues_header(contract, manifest, manifest_sha),
    )
    return {"verdict": PASS, "stage": "cues", "written": [str(header)], "cues": len(manifest.cues)}


def ftm_payload(contract_path: Path) -> Json:
    """Regenerate ``ftm.header`` from the pinned prodeng factory test spec."""
    try:
        contract = load_contract(contract_path)
        if contract.ftm is None:
            return {"verdict": FAIL, "stage": "ftm", "detail": "contract declares no ftm link"}
        spec_path = resolve(contract_path, contract.ftm.spec)
        spec = load_ftm_spec(spec_path)
        spec_sha = sha256_file(spec_path)
        if spec_sha != contract.ftm.sha256:
            return {
                "verdict": FAIL,
                "stage": "ftm",
                "detail": f"factory test spec sha256 {spec_sha} differs from pinned "
                f"{contract.ftm.sha256}; review the new spec and re-pin ftm.sha256",
            }
        text = ftm_header(contract, spec, spec_sha)
    except (OSError, ValueError, ValidationError) as exc:
        return {"verdict": FAIL, "stage": "ftm", "detail": str(exc)}
    header = write_text(resolve(contract_path, contract.ftm.header), text)
    return {
        "verdict": PASS,
        "stage": "ftm",
        "written": [str(header)],
        "commands": len(spec.commands),
    }


def production_payload(contract_path: Path, out_dir: Path | None) -> Json:
    """Export ``<name>.fw-production.json`` for the last passing full gate run."""
    out = out_dir or _default_out(contract_path)
    try:
        export = production_export(contract_path, out)
    except (OSError, ValueError, ValidationError) as exc:
        return {"verdict": FAIL, "stage": "production", "detail": str(exc)}
    path = write_text(
        out / f"{export.design}.fw-production.json",
        json.dumps(export.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
    )
    return {
        "verdict": PASS,
        "stage": "production",
        "elf_sha256": export.elf_sha256,
        "ftm_spec_sha256": export.ftm_spec_sha256,
        "written": [str(path)],
    }


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
    written = [str(json_path), str(md_path)]
    render_errors: list[str] = []
    try:
        written.append(
            str(
                write_bytes(
                    out / f"{contract.name}.pinmap.png",
                    render_pinmap(contract, profile, sha256_file(contract_path)),
                )
            )
        )
    except Exception as exc:
        render_errors.append(f"pinmap.png: {exc}")
    payload: Json = {"verdict": PASS, "stage": "pinmap", "written": written}
    if render_errors:
        payload["render_errors"] = render_errors
    return _attach_image_meta(payload)


def power_payload(contract_path: Path, out_dir: Path | None) -> Json:
    """Export ``<name>.fw-power.json`` (supply-net draw) for simulation-agent imports."""
    try:
        contract = load_contract(contract_path)
    except (OSError, ValueError, ValidationError) as exc:
        return {"verdict": FAIL, "stage": "power", "detail": str(exc)}
    out = out_dir or _default_out(contract_path)
    export = power_export(contract, sha256_file(contract_path))
    path = write_text(
        out / f"{contract.name}.fw-power.json",
        json.dumps(export.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
    )
    return {
        "verdict": PASS,
        "stage": "power",
        "supply_net": export.supply_net,
        "peak_current_a": export.peak_current_a,
        "average_current_a": export.average_current_a,
        "written": [str(path)],
    }


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
    transcript = out / f"sim-{sim.id}.log"
    result = run_simulation(sim, root / sim.image, transcript)
    written: list[str] = []
    render_errors: list[str] = []
    if result.transcript is not None and result.transcript.is_file():
        written.append(str(result.transcript))
        try:
            written.append(
                str(
                    write_bytes(
                        out / f"sim-{sim.id}.png",
                        render_sim_timeline(
                            sim, result.transcript.read_text(encoding="utf-8").splitlines(), result
                        ),
                    )
                )
            )
        except Exception as exc:
            render_errors.append(f"sim-{sim.id}.png: {exc}")
    payload: Json = {
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
        "written": written,
    }
    if render_errors:
        payload["render_errors"] = render_errors
    return _attach_image_meta(payload)


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
    decision_refs: list[str] | None = None,
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
            decision_refs=decision_refs,
            connectivity=contract.circuit.connectivity,
        )
    except (OSError, ValueError, ValidationError) as exc:
        return {"verdict": FAIL, "stage": "request", "detail": str(exc)}
    return {"verdict": PASS, "stage": "request", "id": request.id, "written": [str(path)]}


def ux_inbox_payload(workspace: Path | None) -> Json:
    try:
        return liaison.inbox(workspace)
    except OSError as exc:
        return {"verdict": FAIL, "stage": "ux_inbox", "detail": str(exc)}


def ux_respond_payload(workspace: Path | None, fields: Mapping[str, object]) -> Json:
    try:
        payload = dict(fields)
        payload.pop("workspace", None)
        return cast(
            Json,
            liaison.respond(
                workspace,
                str(payload.pop("request")),
                **payload,  # type: ignore[arg-type]
            ),
        )
    except (TypeError, OSError) as exc:
        return {"verdict": FAIL, "stage": "ux_respond", "detail": str(exc)}


RENDER_VIEWS = ("pinmap", "report", "sim")


def render_payload(contract_path: Path, out_dir: Path | None, views: list[str] | None) -> Json:
    """Render pin map / gate report / sim timeline PNGs; never runs QEMU."""
    selected = views if views else list(RENDER_VIEWS)
    unknown = [view for view in selected if view not in RENDER_VIEWS]
    if unknown:
        return {"verdict": FAIL, "stage": "render", "detail": f"unknown view {unknown[0]}"}
    try:
        contract = load_contract(contract_path)
        profile = load_profile(contract.mcu.profile, [contract_path.parent])
    except (OSError, ValueError, ValidationError) as exc:
        return {"verdict": FAIL, "stage": "render", "detail": str(exc)}
    out = out_dir or _default_out(contract_path)
    out.mkdir(parents=True, exist_ok=True)
    contract_sha = sha256_file(contract_path)
    written: list[Path] = []
    render_errors: list[str] = []
    if "pinmap" in selected:
        try:
            written.append(
                write_bytes(
                    out / f"{contract.name}.pinmap.png",
                    render_pinmap(contract, profile, contract_sha),
                )
            )
        except Exception as exc:
            render_errors.append(f"pinmap.png: {exc}")
    if "report" in selected:
        report = run_gates(contract_path, out, full=False)
        written += write_outputs(contract_path, report, out, render_errors)
    if "sim" in selected:
        for sim in contract.simulations:
            log = out / f"sim-{sim.id}.log"
            if not log.is_file():
                render_errors.append(f"sim-{sim.id}.png: no transcript {log}")
                continue
            lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
            try:
                result = SimResult(
                    ok=False,
                    detail="re-evaluated from transcript (QEMU not re-run)",
                    argv=[],
                    transcript=log,
                )
                png = render_sim_timeline(sim, lines, result)
                written.append(write_bytes(out / f"sim-{sim.id}.png", png))
            except Exception as exc:
                render_errors.append(f"sim-{sim.id}.png: {exc}")
    payload: Json = {
        "verdict": PASS,
        "stage": "render",
        "views": selected,
        "written": [str(p) for p in written],
    }
    if render_errors:
        payload["render_errors"] = render_errors
    return _attach_image_meta(payload)


def record_write_payload(kind: str, payload: Mapping[str, object]) -> Json:
    """Append one VibeBB Record Protocol record; fail-closed on invalid input."""
    try:
        return cast(Json, RECORDERS[kind](dict(payload)))
    except (KeyError, ValueError) as exc:
        return {"verdict": FAIL, "stage": "record", "detail": str(exc)}


def record_file_payload(kind: str, json_path: Path) -> Json:
    try:
        raw = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"verdict": FAIL, "stage": "record", "detail": str(exc)}
    if not isinstance(raw, dict):
        return {"verdict": FAIL, "stage": "record", "detail": "record JSON must be an object"}
    return record_write_payload(kind, cast(Mapping[str, object], raw))


def records_status_payload() -> Json:
    return cast(Json, records_summary())


def profile_payload(profile_id: str) -> Json:
    try:
        profile = load_profile(profile_id)
    except (OSError, ValueError, ValidationError) as exc:
        return {"verdict": FAIL, "stage": "profile", "detail": str(exc)}
    payload: Json = json.loads(profile.model_dump_json())
    payload["verdict"] = PASS
    return payload
