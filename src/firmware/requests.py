"""Change requests from firmware to a sister agent (``*.fw-request.json``).

Firmware never edits a sister's inputs. When the pin map needs a circuit
change (a different pad, a pull resistor, a level shifter) or a sister
contract change, the firmware agent writes a request the owning agent
triages. Every request is bound to the hashed inputs it rests on and to
the VibeBB Record Protocol decisions that justify it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .interchange import sha256_file
from .liaison import HashedPath
from .records import records_dir
from .workspace import workspace_root


class FirmwareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[2] = 2
    system: Literal["firmware"] = "firmware"
    artifact_kind: Literal["fw_request"] = "fw_request"
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    design: str
    target: Literal[
        "circuit",
        "mech",
        "wire",
        "ux",
        "bard",
        "doc",
        "prodeng",
        "sim",
        "fpga",
        "dashboard",
    ]
    risk: Literal["low", "high"]
    change: str = Field(min_length=8)
    rationale: str = Field(min_length=8)
    nets: list[str] = Field(default_factory=list[str])
    failing_checks: list[str] = Field(default_factory=list[str])
    inputs: list[HashedPath] = Field(default_factory=list[HashedPath])
    decision_refs: list[str] = Field(default_factory=list[str])
    contract_sha256: str

    @model_validator(mode="after")
    def _high_risk_is_recorded(self) -> FirmwareRequest:
        if self.risk == "high" and not self.decision_refs:
            raise ValueError("high-risk requests need at least one decision ref")
        return self


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "request"


def _decision_ids(root: Path) -> set[str]:
    path = records_dir(root) / "decisions.jsonl"
    ids: set[str] = set()
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                event: object = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                event_id = cast(dict[str, object], event).get("event_id")
                if isinstance(event_id, str):
                    ids.add(event_id)
    return ids


def write_request(
    contract_path: Path,
    design: str,
    out_dir: Path,
    *,
    target: str,
    risk: str,
    change: str,
    rationale: str,
    nets: list[str],
    failing_checks: list[str],
    decision_refs: list[str] | None = None,
    connectivity: str | None = None,
    root: Path | None = None,
) -> tuple[FirmwareRequest, Path]:
    resolved_root = (root or workspace_root()).resolve()
    contract_abs = contract_path.resolve()

    def rel(value: Path, fallback: str) -> str:
        try:
            return value.relative_to(resolved_root).as_posix()
        except ValueError:
            return fallback

    inputs = [
        HashedPath(path=rel(contract_abs, contract_path.name), sha256=sha256_file(contract_path)),
    ]
    if connectivity:
        connectivity_path = (contract_abs.parent / connectivity).resolve()
        if connectivity_path.is_file():
            inputs.append(
                HashedPath(
                    path=rel(connectivity_path, connectivity),
                    sha256=sha256_file(connectivity_path),
                )
            )
    known = _decision_ids(root or workspace_root())
    for ref in decision_refs or []:
        if ref not in known:
            raise ValueError(f"unknown decision ref: {ref}")
    request = FirmwareRequest.model_validate(
        {
            "id": f"{target}-{slug(change)}",
            "design": design,
            "target": target,
            "risk": risk,
            "change": change,
            "rationale": rationale,
            "nets": nets,
            "failing_checks": failing_checks,
            "inputs": [item.model_dump(mode="json") for item in inputs],
            "decision_refs": decision_refs or [],
            "contract_sha256": sha256_file(contract_path),
        }
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{design}.{request.id}.fw-request.json"
    path.write_text(
        json.dumps(request.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return request, path
