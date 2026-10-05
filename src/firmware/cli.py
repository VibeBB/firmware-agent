"""firmware command line interface.

Subcommands:
  doctor    probe the toolchain
  validate  validate a <name>.fw.json contract against its MCU profile
  check     static gates (pins, peripherals, netlist match, power, header)
  gates     every gate: static + build, memory budget, static analysis, sim
  pins      regenerate the contract's pin header
  pinmap    export <name>.fw-pinmap.json for electrical-circuit-agent
  sim       run one QEMU simulation
  debug     scripted GDB session on a QEMU simulation (advisory)
  request   write a change request to a sister agent
  profile   print a bundled MCU profile
  record    append a VibeBB Record Protocol record (decision, impression,
            vision-review) or print the records status
  render    render pin map / gate report / sim timeline PNGs
  ux        ux-creator liaison: `ux inbox` lists requests,
            `ux respond --json <file>` answers one

Every command prints a JSON payload; exit 0 only when verdict is pass.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from . import service


def _emit(payload: service.Json) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload.get("verdict") == "pass" else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="firmware")
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor")
    doctor.add_argument("--warn", action="store_true", help="always exit 0")
    for name in ("validate", "pins"):
        sub.add_parser(name).add_argument("contract", type=Path)
    for name in ("check", "gates", "pinmap"):
        command = sub.add_parser(name)
        command.add_argument("contract", type=Path)
        command.add_argument("--out", type=Path)
    sim = sub.add_parser("sim")
    sim.add_argument("contract", type=Path)
    sim.add_argument("--id", required=True)
    sim.add_argument("--out", type=Path)
    debug = sub.add_parser("debug")
    debug.add_argument("contract", type=Path)
    debug.add_argument("--id", required=True)
    debug.add_argument(
        "--elf", help="symbol file (default: simulation build ELF, ELF image, or build.elf)"
    )
    debug.add_argument("--break", dest="breaks", action="append", default=[])
    debug.add_argument("--print", dest="prints", action="append", default=[])
    debug.add_argument("--out", type=Path)
    request = sub.add_parser("request")
    request.add_argument("contract", type=Path)
    request.add_argument("--target", required=True)
    request.add_argument("--risk", choices=("low", "high"), required=True)
    request.add_argument("--change", required=True)
    request.add_argument("--rationale", required=True)
    request.add_argument("--net", dest="nets", action="append", default=[])
    request.add_argument("--failing-check", dest="failing_checks", action="append", default=[])
    request.add_argument("--out", type=Path)
    sub.add_parser("profile").add_argument("id")
    record = sub.add_parser("record", help="append a VibeBB Record Protocol record")
    record.add_argument("kind", choices=["decision", "impression", "vision-review", "status"])
    record.add_argument("--json", type=Path, default=None, help="record fields as a JSON file")
    render = sub.add_parser("render", help="render PNG views of the contract")
    render.add_argument("contract", type=Path)
    render.add_argument("--out", type=Path)
    render.add_argument(
        "--view",
        dest="views",
        action="append",
        choices=list(service.RENDER_VIEWS),
        default=None,
    )
    ux = sub.add_parser("ux", help="ux-creator SLP v2 liaison")
    ux.add_argument("action", choices=["inbox", "respond"])
    ux.add_argument("--workspace", type=Path, default=None)
    ux.add_argument("--json", type=Path, default=None, help="respond fields as a JSON file")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    command: str = args.command
    if command == "doctor":
        payload = service.doctor_payload()
        code = _emit(payload)
        return 0 if args.warn else code
    if command == "validate":
        return _emit(service.validate_payload(args.contract))
    if command in ("check", "gates"):
        return _emit(service.gates_payload(args.contract, args.out, full=command == "gates"))
    if command == "pins":
        return _emit(service.pins_payload(args.contract))
    if command == "pinmap":
        return _emit(service.pinmap_payload(args.contract, args.out))
    if command == "sim":
        return _emit(service.sim_payload(args.contract, args.id, args.out))
    if command == "debug":
        return _emit(
            service.debug_payload(
                args.contract, args.id, args.elf, args.breaks, args.prints, args.out
            )
        )
    if command == "request":
        return _emit(
            service.request_payload(
                args.contract,
                args.out,
                target=args.target,
                risk=args.risk,
                change=args.change,
                rationale=args.rationale,
                nets=args.nets,
                failing_checks=args.failing_checks,
            )
        )
    if command == "record":
        if args.kind == "status":
            return _emit(service.records_status_payload())
        if args.json is None:
            parser.error("record decision|impression|vision-review requires --json")
        return _emit(service.record_file_payload(args.kind, args.json))
    if command == "render":
        return _emit(service.render_payload(args.contract, args.out, args.views))
    if command == "ux":
        if args.action == "inbox":
            return _emit(service.ux_inbox_payload(args.workspace))
        if args.json is None:
            parser.error("ux respond requires --json")
        fields: object = json.loads(args.json.read_text(encoding="utf-8"))
        if not isinstance(fields, dict):
            parser.error("ux respond --json must be a JSON object")
        return _emit(service.ux_respond_payload(args.workspace, cast(dict[str, object], fields)))
    return _emit(service.profile_payload(args.id))


if __name__ == "__main__":
    raise SystemExit(main())
