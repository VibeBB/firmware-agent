"""Sister Liaison Protocol (SLP) v2: answer ux-creator requests.

A strict local mirror of the UX-creator liaison contract — this module
never imports from a sister plugin. Requests land as
``liaison/<id>.ux-request.json`` beside the workspace root; firmware
answers with ``liaison/<id>.ux-response.json`` written atomically by
:func:`respond`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, cast

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator

from .records import records_dir
from .workspace import workspace_path, workspace_root

Stage = Literal[
    "requirements", "design", "manufacturing_handoff", "build", "evaluation", "revision"
]
Target = Literal[
    "bard", "circuit", "dashboard", "doc", "firmware", "fpga", "mech", "prodeng", "sim", "wire"
]
_SLUG = r"^[a-z0-9][a-z0-9-]*$"
_SHA256 = r"^[0-9a-f]{64}$"
_JOB_TOKEN = re.compile(r"\b[a-z][a-z0-9]*_[a-z0-9_]+\b")
_NON_EMPTY = Annotated[str, Field(min_length=1)]


class HashedPath(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=_SHA256)


class UxRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[2] = 2
    system: Literal["ux-creator"] = "ux-creator"
    id: str = Field(pattern=_SLUG)
    target_agent: Target
    stage: Stage
    risk: Literal["low", "high"]
    purpose: str = Field(min_length=20)
    rationale: str = Field(min_length=1)
    requested_changes: list[_NON_EMPTY] = Field(min_length=1)
    inputs: list[HashedPath] = Field(default_factory=list[HashedPath])
    expected_deliverables: list[_NON_EMPTY] = Field(min_length=1)
    acceptance: list[_NON_EMPTY] = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list[str])
    created_at: AwareDatetime

    @model_validator(mode="after")
    def _consistent(self) -> UxRequest:
        # The UX contract is not visible here, so this is a local heuristic:
        # a high-risk request must cite a snake_case UX job id (e.g.
        # "boil_water"). UX-creator checks the real ids on its side.
        if self.risk == "high" and not _JOB_TOKEN.search(self.rationale):
            raise ValueError("high-risk requests must cite a snake_case UX job id")
        if self.id in self.depends_on:
            raise ValueError("depends_on must not contain the request id")
        return self


class GateVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gate: str = Field(min_length=1)
    verdict: Literal["pass", "fail", "unknown"]


Status = Literal["accepted", "in_progress", "done", "rejected", "deferred", "needs_info"]

REFUSABLE = frozenset({"needs_info", "rejected", "deferred"})


class UxResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[2] = 2
    system: Literal["ux-creator"] = "ux-creator"
    request: str = Field(pattern=_SLUG)
    responder: Target
    status: Status
    reason: str = ""
    input_hashes: dict[str, str] = Field(default_factory=dict[str, str])
    artifacts: list[HashedPath] = Field(default_factory=list[HashedPath])
    gate_verdicts: list[GateVerdict] = Field(default_factory=list[GateVerdict])
    decision_refs: list[str] = Field(default_factory=list[str])
    impression_refs: list[str] = Field(default_factory=list[str])
    questions_for_user: list[str] = Field(default_factory=list[str])
    responded_at: AwareDatetime

    @model_validator(mode="after")
    def _consistent(self) -> UxResponse:
        if self.status not in {"accepted", "in_progress"} and len(self.reason) < 20:
            raise ValueError("reason must be at least 20 characters for this status")
        if self.status == "done":
            if any(v.verdict in {"fail", "unknown"} for v in self.gate_verdicts):
                raise ValueError("status done is impossible with fail/unknown gate verdicts")
            if not self.gate_verdicts:
                raise ValueError("status done needs at least one gate verdict")
            if not self.artifacts:
                raise ValueError("status done needs at least one artifact")
        return self


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve(workspace: Path, value: str) -> Path:
    """Resolve a workspace-relative POSIX path; reject absolute/escapes."""
    candidate = Path(value)
    if candidate.is_absolute():
        raise ValueError(f"path escapes the workspace: {value}")
    resolved = workspace_path(value, workspace)
    if not str(resolved).startswith(str(workspace.resolve()) + os.sep) and resolved != workspace:
        raise ValueError(f"path escapes the workspace: {value}")
    return resolved


def _liaison(workspace: Path) -> Path:
    return workspace / "liaison"


def _load_request(path: Path) -> tuple[UxRequest | None, str | None]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        request = UxRequest.model_validate(raw)
    except (OSError, ValueError, ValidationError) as exc:
        return None, str(exc)
    if request.id != path.name.removesuffix(".ux-request.json"):
        return None, "request id does not match the file stem"
    return request, None


def _load_response(
    path: Path, responder: str | None = None
) -> tuple[UxResponse | None, str | None]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        response = UxResponse.model_validate(raw)
    except (OSError, ValueError, ValidationError) as exc:
        return None, str(exc)
    if response.request != path.name.removesuffix(".ux-response.json"):
        return None, "response request does not match the file stem"
    if responder is not None and response.responder != responder:
        return None, f"response responder is {response.responder}, expected {responder}"
    return response, None


def _event_ids(kind: str, root: Path) -> set[str]:
    path = records_dir(root) / f"{kind}.jsonl"
    ids: set[str] = set()
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                event: object = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                event_id = cast(dict[str, Any], event).get("event_id")
                if isinstance(event_id, str):
                    ids.add(event_id)
    return ids


def _record_refs(root: Path) -> tuple[set[str], set[str]]:
    return (
        _event_ids("decisions", root),
        _event_ids("impressions", root) | _event_ids("vision-reviews", root),
    )


def _response_for(
    workspace: Path, request_id: str, responder: str | None = None
) -> tuple[UxResponse | None, str | None]:
    path = _liaison(workspace) / f"{request_id}.ux-response.json"
    if not path.is_file():
        return None, None
    return _load_response(path, responder)


def _firmware_graph(requests: dict[str, UxRequest]) -> dict[str, list[str]]:
    return {rid: [d for d in req.depends_on if d in requests] for rid, req in requests.items()}


def _on_cycle(graph: dict[str, list[str]], node: str) -> bool:
    """True when ``node`` sits on a dependency cycle."""
    state: dict[str, int] = {}

    def visit(n: str, trail: list[str]) -> bool:
        if n in trail:
            return node in trail[trail.index(n) :]
        if state.get(n):
            return state[n] == 2
        state[n] = 1
        for dep in graph.get(n, []):
            if visit(dep, [*trail, n]):
                state[n] = 2
                return True
        state[n] = 0
        return False

    return visit(node, [])


def _evaluate(
    workspace: Path,
    request: UxRequest,
    all_requests: dict[str, UxRequest],
    firmware_ids: set[str],
) -> dict[str, object]:
    """State for one firmware request: stale > answered > blocked > new."""
    response, _response_error = _response_for(workspace, request.id, "firmware")
    stale_inputs: list[dict[str, object]] = []
    for item in request.inputs:
        try:
            resolved = _resolve(workspace, item.path)
        except ValueError:
            stale_inputs.append({"path": item.path, "expected": item.sha256, "actual": "escape"})
            continue
        actual = _sha(resolved) if resolved.is_file() else None
        expected_response = response.input_hashes.get(item.path) if response else None
        if actual != item.sha256 or (response is not None and actual != expected_response):
            stale_inputs.append({"path": item.path, "expected": item.sha256, "actual": actual})
    if stale_inputs:
        return {"state": "stale", "stale_inputs": stale_inputs}
    if response is not None:
        return {"state": "answered", "response_status": response.status}
    graph = _firmware_graph({rid: r for rid, r in all_requests.items() if rid in firmware_ids})
    blocked_by = [dep for dep in request.depends_on if _response_for(workspace, dep)[0] is None]
    circular = request.id in graph and _on_cycle(graph, request.id)
    if blocked_by or circular:
        state: dict[str, object] = {"state": "blocked", "blocked_by": blocked_by}
        if circular:
            state["circular"] = True
        return state
    return {"state": "new"}


def inbox(workspace: Path | None = None) -> dict[str, object]:
    """Scan ``liaison/*.ux-request.json`` and classify every firmware request."""
    root = (workspace or workspace_root()).resolve()
    liaison = _liaison(root)
    malformed: list[dict[str, str]] = []
    all_requests: dict[str, UxRequest] = {}
    for path in sorted(liaison.glob("*.ux-request.json")) if liaison.is_dir() else []:
        request, error = _load_request(path)
        if error or request is None:
            malformed.append({"path": str(path), "error": error or "invalid request"})
        else:
            all_requests[request.id] = request
    firmware_ids = {rid for rid, r in all_requests.items() if r.target_agent == "firmware"}
    other_targets = len(all_requests) - len(firmware_ids)
    for rid in firmware_ids:
        response_path = liaison / f"{rid}.ux-response.json"
        if response_path.is_file():
            _, response_error = _load_response(response_path, "firmware")
            if response_error:
                malformed.append({"path": str(response_path), "error": response_error})
    entries: list[dict[str, object]] = []
    for rid in sorted(firmware_ids):
        request = all_requests[rid]
        evaluation = _evaluate(root, request, all_requests, firmware_ids)
        entry: dict[str, object] = {
            "id": rid,
            "stage": request.stage,
            "risk": request.risk,
            "purpose": request.purpose,
            "requested_changes": request.requested_changes,
            "expected_deliverables": request.expected_deliverables,
            "acceptance": request.acceptance,
            "depends_on": request.depends_on,
            **evaluation,
        }
        entries.append(entry)
    open_count = sum(1 for e in entries if e["state"] != "answered")
    payload: dict[str, object] = {
        "verdict": "pass" if not malformed and open_count == 0 else "fail",
        "stage": "ux_inbox",
        "requests": entries,
        "other_targets": other_targets,
    }
    if malformed:
        payload["malformed"] = malformed
    if open_count:
        payload["open"] = open_count
    return payload


def _merge_report_checks(
    workspace: Path, report_paths: list[str]
) -> tuple[list[GateVerdict], list[HashedPath], str | None]:
    verdicts: list[GateVerdict] = []
    artifacts: list[HashedPath] = []
    for value in report_paths:
        try:
            path = _resolve(workspace, value)
        except ValueError as exc:
            return [], [], str(exc)
        if not path.name.endswith(".fw-report.json") or not path.is_file():
            return [], [], f"not a firmware gate report: {value}"
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            checks = report["checks"]
            contract_sha = report["contract_sha256"]
        except (OSError, ValueError, KeyError) as exc:
            return [], [], f"unreadable report {value}: {exc}"
        for check in checks:
            status = check.get("status")
            if status == "not_applicable":
                continue
            merged: Literal["pass", "fail", "unknown"] = cast(
                "Literal['pass', 'fail', 'unknown']",
                {"pass": "pass", "fail": "fail"}.get(status, "unknown"),
            )
            verdicts.append(GateVerdict(gate=str(check.get("id", "fw.report")), verdict=merged))
        contract = path.parent / f"{path.name.removesuffix('.fw-report.json')}.fw.json"
        if contract.is_file() and _sha(contract) != contract_sha:
            verdicts.append(GateVerdict(gate="fw.report_fresh", verdict="fail"))
        artifacts.append(HashedPath(path=value, sha256=_sha(path)))
    return verdicts, artifacts, None


def respond(
    workspace: Path | None,
    request_id: str,
    status: Status,
    reason: str = "",
    artifacts: list[str] | None = None,
    gate_verdicts: list[dict[str, str]] | None = None,
    decision_refs: list[str] | None = None,
    impression_refs: list[str] | None = None,
    questions_for_user: list[str] | None = None,
    report_paths: list[str] | None = None,
) -> dict[str, object]:
    """Validate and atomically write ``liaison/<id>.ux-response.json``."""
    root = (workspace or workspace_root()).resolve()
    request_path = _liaison(root) / f"{request_id}.ux-request.json"
    if not request_path.is_file():
        return {
            "verdict": "fail",
            "stage": "ux_respond",
            "detail": f"no request {request_path}",
        }
    request, error = _load_request(request_path)
    if request is None:
        return {"verdict": "fail", "stage": "ux_respond", "detail": error}
    if request.target_agent != "firmware":
        return {
            "verdict": "fail",
            "stage": "ux_respond",
            "detail": f"request {request_id} targets {request.target_agent}, not firmware",
        }
    all_requests: dict[str, UxRequest] = {}
    for p in _liaison(root).glob("*.ux-request.json"):
        loaded = _load_request(p)[0]
        if loaded is not None:
            all_requests[loaded.id] = loaded
    firmware_ids = {rid for rid, r in all_requests.items() if r.target_agent == "firmware"}
    evaluation = _evaluate(root, request, all_requests, firmware_ids)
    state = evaluation["state"]
    if state == "stale" and status not in REFUSABLE:
        return {
            "verdict": "fail",
            "stage": "ux_respond",
            "detail": f"request {request_id} is stale; answer with needs_info/rejected/deferred",
        }
    if state == "blocked" and status == "done":
        return {
            "verdict": "fail",
            "stage": "ux_respond",
            "detail": f"request {request_id} is blocked; done is impossible",
        }
    extra_verdicts, report_artifacts, report_error = _merge_report_checks(root, report_paths or [])
    if report_error:
        return {"verdict": "fail", "stage": "ux_respond", "detail": report_error}
    input_hashes: dict[str, str] = {}
    missing_inputs: list[str] = []
    for item in request.inputs:
        try:
            resolved = _resolve(root, item.path)
        except ValueError as exc:
            return {"verdict": "fail", "stage": "ux_respond", "detail": str(exc)}
        if resolved.is_file():
            input_hashes[item.path] = _sha(resolved)
        else:
            missing_inputs.append(item.path)
    if missing_inputs and status not in REFUSABLE:
        return {
            "verdict": "fail",
            "stage": "ux_respond",
            "detail": f"missing inputs: {', '.join(missing_inputs)}",
        }
    hashed_artifacts = list(report_artifacts)
    for value in artifacts or []:
        try:
            path = _resolve(root, value)
        except ValueError as exc:
            return {"verdict": "fail", "stage": "ux_respond", "detail": str(exc)}
        if not path.is_file():
            return {
                "verdict": "fail",
                "stage": "ux_respond",
                "detail": f"artifact does not exist: {value}",
            }
        hashed_artifacts.append(HashedPath(path=value, sha256=_sha(path)))
    decision_ref_set, impression_ref_set = _record_refs(root)
    for ref in decision_refs or []:
        if ref not in decision_ref_set:
            return {
                "verdict": "fail",
                "stage": "ux_respond",
                "detail": f"unknown decision ref: {ref}",
            }
    for ref in impression_refs or []:
        if ref not in impression_ref_set:
            return {
                "verdict": "fail",
                "stage": "ux_respond",
                "detail": f"unknown impression ref: {ref}",
            }
    if status == "done" and (not decision_refs or not impression_refs):
        return {
            "verdict": "fail",
            "stage": "ux_respond",
            "detail": "status done needs at least one decision ref and one impression ref",
        }
    try:
        response = UxResponse.model_validate(
            {
                "request": request_id,
                "responder": "firmware",
                "status": status,
                "reason": reason,
                "input_hashes": input_hashes,
                "artifacts": [a.model_dump(mode="json") for a in hashed_artifacts],
                "gate_verdicts": [
                    *(v.model_dump(mode="json") for v in extra_verdicts),
                    *(gate_verdicts or []),
                ],
                "decision_refs": decision_refs or [],
                "impression_refs": impression_refs or [],
                "questions_for_user": questions_for_user or [],
                "responded_at": datetime.now(UTC).isoformat(),
            }
        )
    except ValidationError as exc:
        return {"verdict": "fail", "stage": "ux_respond", "detail": str(exc)}
    out = _liaison(root) / f"{request_id}.ux-response.json"
    replaced = out.exists()
    tmp = out.with_suffix(".ux-response.json.tmp")
    tmp.write_text(
        json.dumps(response.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, out)
    payload: dict[str, object] = {
        "verdict": "pass",
        "stage": "ux_respond",
        "written": [str(out)],
        "response": response.model_dump(mode="json"),
    }
    if replaced:
        payload["replaced"] = True
    return payload
