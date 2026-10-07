"""Production handoff: the gated firmware image for production-engineering-agent.

Nothing here touches hardware; the export only binds the ELF the last
passing full gate run built to the contract, report and factory test spec.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from .contract import load_contract, resolve
from .gates import PASS, GateReport
from .interchange import FirmwareProduction, load_ftm_spec, sha256_file
from .profiles import load_profile


def production_export(contract_path: Path, out_dir: Path) -> FirmwareProduction:
    contract_path = contract_path.resolve()
    out_dir = out_dir.resolve()
    contract = load_contract(contract_path)
    profile = load_profile(contract.mcu.profile, [contract_path.parent])
    report_path = out_dir / f"{contract.name}.fw-report.json"
    try:
        raw = report_path.read_bytes()
    except OSError as exc:
        raise ValueError(f"no gate report at {report_path}; run `firmware gates` first") from exc
    report = GateReport.model_validate_json(raw)
    if report.scope != "full" or report.verdict != PASS:
        raise ValueError(
            f"last gate report is a {report.verdict}ing {report.scope} run; "
            "the image needs a passing `firmware gates` run"
        )
    contract_sha = sha256_file(contract_path)
    if report.contract_sha256 != contract_sha:
        raise ValueError("contract changed after the last gate run; rerun `firmware gates`")
    if report.elf_sha256 is None:
        raise ValueError("gate report records no ELF sha256; rerun `firmware gates`")
    elf = resolve(contract_path, contract.build.elf)
    if not elf.is_file():
        raise ValueError(f"{contract.build.elf} missing; rerun `firmware gates`")
    elf_sha = sha256_file(elf)
    if elf_sha != report.elf_sha256:
        raise ValueError(
            f"{contract.build.elf} sha256 {elf_sha} differs from the gated {report.elf_sha256}; "
            "rerun `firmware gates`"
        )
    ftm_sha: str | None = None
    commands: list[str] = []
    if contract.ftm is not None:
        ftm = next((check for check in report.checks if check.id == "fw.ftm"), None)
        if ftm is None or ftm.status != PASS:
            raise ValueError("fw.ftm did not pass in the last gate run")
        spec_path = resolve(contract_path, contract.ftm.spec)
        spec = load_ftm_spec(spec_path)
        if sha256_file(spec_path) != contract.ftm.sha256:
            raise ValueError("factory test spec changed after the gate run; rerun `firmware gates`")
        ftm_sha = contract.ftm.sha256
        commands = sorted(command.id for command in spec.commands)
    return FirmwareProduction(
        design=contract.name,
        contract_sha256=contract_sha,
        gate_report_sha256=hashlib.sha256(raw).hexdigest(),
        mcu_ref=contract.mcu.ref,
        mcu_profile=profile.id,
        part=profile.part,
        package=profile.package,
        elf=Path(os.path.relpath(elf, out_dir)).as_posix(),
        elf_sha256=elf_sha,
        elf_bytes=elf.stat().st_size,
        ftm_spec_sha256=ftm_sha,
        ftm_commands=commands,
    )
