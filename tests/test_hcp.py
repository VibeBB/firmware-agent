from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from firmware import service
from firmware.contract import load_contract
from firmware.gates import check_hcp, check_hcp_lint, run_gates
from firmware.hcp import (
    HcpFlow,
    HcpItem,
    HcpModule,
    HcpRefs,
    chart_flow,
    dsl_to_flow,
    error_mixing_findings,
    flow_to_dsl,
    lint_flow,
    lint_report_json,
    load_hcp_chart,
    render_hcp_png,
    render_hcp_svg,
    validate_flow,
    validate_refs,
    write_hcp_artifacts,
)

from .conftest import read_json, write_json


def _flow() -> HcpFlow:
    return HcpFlow(
        modules=[
            HcpModule(
                name="main",
                data=["state"],
                items=[
                    HcpItem(label="read inputs"),
                    HcpItem(
                        kind="fork",
                        label="mode",
                        children=[
                            HcpItem(kind="true", label="on"),
                            HcpItem(kind="false", label="off"),
                        ],
                    ),
                    HcpItem(kind="repeat", label="loop", children=[HcpItem(label="tick")]),
                    HcpItem(kind="return", levels=2),
                ],
            ),
            HcpModule(name="helper", items=[HcpItem(label="log line")]),
        ]
    )


def test_dsl_projection_shape() -> None:
    dsl = flow_to_dsl(_flow())
    assert "\\module main" in dsl
    assert "\t\\data state" in dsl
    assert "\t\\fork mode" in dsl
    assert "\t\t\\true on" in dsl
    assert "\t\\return 2" in dsl
    assert dsl.endswith("\n")


def test_dsl_round_trip() -> None:
    dsl = flow_to_dsl(_flow())
    parsed, diagnostics = dsl_to_flow(dsl)
    assert [d.message for d in diagnostics if d.severity == "error"] == []
    assert flow_to_dsl(parsed) == dsl


@pytest.mark.parametrize(
    ("text", "severity", "needle"),
    [
        ("read sensor\n", "error", "no \\module"),
        ("\\module m\n\tok\n\\module m\n\tok2\n", "error", "duplicate module"),
        ("\t\\module m\n\tok\n", "error", "level 0"),
        ("\\module m\n   ok\n", "error", "4-space"),
        ("\\module m\n\t\\bogus x\n", "warning", "unknown command"),
        ("\\module m\n\t\\return -1\n", "error", "positive"),
        ("\\module m\n", "error", "no process rows"),
    ],
)
def test_dsl_diagnostics(text: str, severity: str, needle: str) -> None:
    _flow_parsed, diagnostics = dsl_to_flow(text)
    assert any(d.severity == severity and needle in d.message for d in diagnostics), [
        (d.severity, d.message) for d in diagnostics
    ]


def test_validate_flow_structure() -> None:
    flow = _flow()
    assert validate_flow(flow) == []
    flow.modules[0].items[1].children = [HcpItem(kind="process", label="not-a-branch")]
    flow.modules[0].items.append(HcpItem(kind="branch", label="stray"))
    flow.modules[0].items[0].levels = 3
    flow.modules[0].items.append(HcpItem(kind="mod", label="ghost"))
    flow.modules[0].items[0].label = ""
    problems = validate_flow(flow)
    assert any("branch must be a direct child of fork" in p for p in problems)
    assert any("levels only applies to return" in p for p in problems)
    assert any("mod target 'ghost'" in p for p in problems)
    assert any("empty label" in p for p in problems)


def test_validate_flow_duplicate_modules_and_data() -> None:
    flow = _flow()
    flow.modules.append(HcpModule(name="main", items=[HcpItem(label="x")]))
    flow.modules[0].data = ["bad name"]
    flow.modules[0].items[0].data_in = ["has.dot"]
    problems = validate_flow(flow)
    assert "duplicate module names" in problems
    assert sum("data name" in p for p in problems) == 2


def test_validate_refs_resolution() -> None:
    flow = _flow()
    flow.modules[0].items[0].refs = HcpRefs(
        pins=["sw1"], peripherals=["pwm0"], power_modes=["lit"], simulations=["sim0"]
    )
    assert (
        validate_refs(
            flow,
            pins=("sw1",),
            peripherals=("pwm0",),
            power_modes=("lit",),
            simulations=("sim0",),
        )
        == []
    )
    problems = validate_refs(flow, pins=("other",))
    assert len(problems) == 4
    assert "pin ref 'sw1' is not a pin signal" in problems[0]


def test_lint_rules() -> None:
    flow = HcpFlow(
        modules=[
            HcpModule(
                name="a",
                items=[
                    HcpItem(label="set x = 1;"),
                    HcpItem(kind="ec", label="escape ok"),  # exits are fine
                    HcpItem(label="log error to console"),  # inline error handling
                    HcpItem(label="wide", children=[HcpItem(label=f"c{i}") for i in range(8)]),
                ],
            ),
            HcpModule(name="b", items=[HcpItem(label="dup")]),
            HcpModule(name="c", items=[HcpItem(label="dup")]),
        ]
    )
    rules = {f.rule for f in lint_flow(flow) + error_mixing_findings(flow)}
    assert "means_at_top_level" in rules
    assert "error_handling_inline" in rules
    assert "reappearing_process" in rules
    assert "granularity" in rules


def test_lint_report_json() -> None:
    report = lint_report_json(_flow(), "demo")
    assert report["artifact_kind"] == "hcp_lint_report"
    assert report["verdict"] == "pass"
    assert report["findings"] == []


def test_svg_render_deterministic() -> None:
    flow = _flow()
    one = render_hcp_svg(flow, "demo", "ab" * 32)
    assert render_hcp_svg(flow, "demo", "ab" * 32) == one
    assert "<svg" in one and "sha256:abababababab" in one
    assert one.count("<circle") > 4  # trunk symbols drawn
    assert "main" in one and "helper" in one


def test_png_render_deterministic() -> None:
    flow = _flow()
    png = render_hcp_png(flow, "demo", "ab" * 32)
    assert png.startswith(b"\x89PNG")
    assert render_hcp_png(flow, "demo", "ab" * 32) == png


def test_write_hcp_artifacts(tmp_path: Path) -> None:
    written = write_hcp_artifacts(_flow(), "demo", tmp_path, "ab" * 32)
    names = {p.name for p in written}
    assert names == {"demo.hcp", "demo.hcp.svg", "demo.hcp.png", "demo.hcp-lint.json"}
    assert (tmp_path / "demo.hcp").read_text(encoding="utf-8").startswith("\\module")
    report = json.loads((tmp_path / "demo.hcp-lint.json").read_text(encoding="utf-8"))
    assert report["artifact_kind"] == "hcp_lint_report"


def test_standalone_chart(tmp_path: Path) -> None:
    chart = {
        "schema_version": 1,
        "artifact_kind": "hcp_chart",
        "name": "stand",
        "modules": [{"name": "m", "items": [{"label": "step"}]}],
    }
    path = tmp_path / "stand.hcp.json"
    path.write_text(json.dumps(chart), encoding="utf-8")
    loaded = load_hcp_chart(path)
    assert chart_flow(loaded).modules[0].name == "m"
    payload = service.hcp_payload(path, tmp_path / "out")
    assert payload["verdict"] == "pass"
    written = cast(list[object], payload["written"])
    assert {Path(str(p)).name for p in written} == {
        "stand.hcp",
        "stand.hcp.svg",
        "stand.hcp.png",
        "stand.hcp-lint.json",
    }


def test_hcp_payload_fails_closed(lamp: Path, tmp_path: Path) -> None:
    data = read_json(lamp)
    del data["flow"]
    noflow = tmp_path / "noflow.fw.json"
    write_json(noflow, data)
    assert service.hcp_payload(noflow, tmp_path)["verdict"] == "fail"
    data = read_json(lamp)
    data["flow"]["modules"][0]["items"][0]["refs"] = {"pins": ["ghost"]}
    badref = tmp_path / "badref.fw.json"
    write_json(badref, data)
    payload = service.hcp_payload(badref, tmp_path)
    assert payload["verdict"] == "fail"
    problems = cast(list[object], payload["problems"])
    assert any("ghost" in str(p) for p in problems)


def test_numeric_boundary_sites() -> None:
    """Exercise numeric comparisons at exact boundary neighbours."""
    # ``levels > 1`` in emit/svg/png: on (1) alongside above1 (2).
    flow = HcpFlow(
        modules=[
            HcpModule(
                name="m",
                items=[
                    HcpItem(kind="return", levels=1),
                    HcpItem(kind="return", levels=2),
                    # ``ord(ch) < 128`` exact neighbours 127/128/129.
                    HcpItem(label="neigh" + chr(127) + chr(128) + chr(129)),
                ],
            )
        ]
    )
    assert "\\return 2" in flow_to_dsl(flow)
    assert render_hcp_svg(flow, "bound", "sha")
    assert render_hcp_png(flow, "bound", "sha")

    # Parser ``levels < 1``: below1 (0, error) and on (1, valid).
    _parsed, diags = dsl_to_flow("\\module m\n\t\\return 0\n\t\\return 1\n")
    assert any("must be positive" in d.message for d in diags)

    # Parser ``level > MAX_DEPTH``: levels 1-9 via tab indents.
    deep_dsl = "\\module m\n" + "\n".join("\t" * n + "x" for n in range(1, 10))
    _p2, deep_diags = dsl_to_flow(deep_dsl)
    assert any("nesting deeper" in d.message for d in deep_diags)

    # ``depth > MAX_DEPTH``: chains of depth 8 (ok) and 9 (error).
    def chain(n: int) -> HcpItem:
        item = HcpItem(label="leaf")
        for _ in range(n - 1):
            item = HcpItem(label="p", children=[item])
        return item

    assert not validate_flow(HcpFlow(modules=[HcpModule(name="m", items=[chain(8)])]))
    assert any(
        "nesting deeper" in p
        for p in validate_flow(HcpFlow(modules=[HcpModule(name="m", items=[chain(9)])]))
    )

    # ``len(children) > 7``: 6 and 7 are clean, 8 is a finding (existing test).
    for n in (6, 7):
        wide = HcpFlow(
            modules=[
                HcpModule(
                    name="m",
                    items=[HcpItem(label="w", children=[HcpItem(label=f"c{i}") for i in range(n)])],
                )
            ]
        )
        assert all(f.rule != "granularity" for f in lint_flow(wide))

    # Indent-scan loops: tab-only and space-only lines hit below/on.
    dsl_to_flow("\\module m\n\t\n \n\tok\n")


def test_gates_hcp_checks(lamp: Path) -> None:
    contract = load_contract(lamp)
    assert contract.flow is not None
    assert check_hcp(contract).status == "pass"
    assert check_hcp_lint(contract).status == "pass"
    report = run_gates(lamp, lamp.parent / "fw-reports", full=False)
    status = {c.id: c.status for c in report.checks}
    assert status["fw.hcp"] == "pass" and status["fw.hcp_lint"] == "pass"


def test_gates_hcp_fails_on_corrupt(lamp: Path, tmp_path: Path) -> None:
    data = read_json(lamp)
    data["flow"]["modules"][0]["items"].append({"kind": "branch", "label": "outside fork"})
    corrupted = tmp_path / "bad.fw.json"
    write_json(corrupted, data)
    report = run_gates(corrupted, tmp_path / "out", full=False)
    status = {c.id: c.status for c in report.checks}
    assert status["fw.hcp"] == "fail"
    assert report.verdict == "fail"
