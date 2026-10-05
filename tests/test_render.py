"""Stdlib PNG renders: encoding validity, determinism, content, MCP inline images."""

from __future__ import annotations

import asyncio
import base64
import json
import struct
import zlib
from pathlib import Path
from typing import Any, cast

import mcp.types
import pytest

from firmware import mcp_server, render, service
from firmware.contract import load_contract
from firmware.gates import Check, GateReport, run_gates
from firmware.profiles import load_profile
from firmware.sim import SimResult

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


def _decode(png: bytes) -> tuple[int, int, list[bytes]]:
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    pos = 8
    width = height = 0
    idat = b""
    seen_iend = False
    while pos < len(png):
        (length,) = struct.unpack(">I", png[pos : pos + 4])
        tag = png[pos + 4 : pos + 8]
        body = png[pos + 8 : pos + 8 + length]
        (crc,) = struct.unpack(">I", png[pos + 8 + length : pos + 12 + length])
        assert crc == zlib.crc32(tag + body) & 0xFFFFFFFF
        if tag == b"IHDR":
            width, height, depth, ctype, _c, _f, _i = struct.unpack(">IIBBBBB", body)
            assert depth == 8 and ctype == 2
        elif tag == b"IDAT":
            idat += body
        elif tag == b"IEND":
            seen_iend = True
        pos += 12 + length
    assert seen_iend
    raw = zlib.decompress(idat)
    stride = width * 3 + 1
    rows = [raw[i * stride : (i + 1) * stride] for i in range(height)]
    for row in rows:
        assert row[0] == 0  # filter byte
    return width, height, [row[1:] for row in rows]


def _has_color(rows: list[bytes], color: tuple[int, int, int]) -> bool:
    needle = bytes(color)
    return any(needle in row for row in rows)


def test_canvas_png_structure() -> None:
    canvas = render.Canvas(40, 30)
    canvas.rect(2, 2, 10, 6, render.RED)
    canvas.line(0, 0, 39, 29, render.BLACK)
    canvas.text(2, 12, "A8?%", render.BLUE)
    width, height, rows = _decode(canvas.to_png())
    assert (width, height) == (40, 30)
    assert _has_color(rows, render.RED) and _has_color(rows, render.BLUE)


def _pinmap(example: str) -> bytes:
    contract_path = next((EXAMPLES / example).glob("*.fw.json"))
    contract = load_contract(contract_path)
    profile = load_profile(contract.mcu.profile, [contract_path.parent])
    return render.render_pinmap(contract, profile, "a" * 64)


@pytest.mark.parametrize("example", ["smart-kettle", "desk-lamp-s3"])
def test_pinmap_example(example: str) -> None:
    png = _pinmap(example)
    width, height, rows = _decode(png)
    assert width > 300 and height > 100
    assert _has_color(rows, render.FUNCTION_COLORS["gpio_out"])
    assert _has_color(rows, render.FUNCTION_COLORS["spi"]) or _has_color(
        rows, render.FUNCTION_COLORS["i2c"]
    )


def test_pinmap_caution_colour() -> None:
    contract_path = EXAMPLES / "desk-lamp-s3" / "desk-lamp.fw.json"
    contract = load_contract(contract_path)
    profile = load_profile(contract.mcu.profile)
    caution_pad = next(p for p in profile.pads if p.caution is not None)
    used = {p.pad for p in contract.pins}
    # any caution pad used by the contract must draw the orange marker box
    png = render.render_pinmap(contract, profile, "b" * 64)
    _, _, rows = _decode(png)
    if caution_pad.name in used:
        assert _has_color(rows, render.ORANGE)
    assert _has_color(rows, render.FUNCTION_COLORS["gpio_out"])


def test_render_deterministic() -> None:
    assert _pinmap("smart-kettle") == _pinmap("smart-kettle")


def test_report_render(tmp_path: Path) -> None:
    contract_path = EXAMPLES / "smart-kettle" / "smart-kettle.fw.json"
    report = run_gates(contract_path, tmp_path, full=False)
    contract = load_contract(contract_path)
    width, height, _rows = _decode(render.render_report(report, contract))
    assert width > 200 and height > 60
    # static scope: no ELF metrics
    assert "flash_bytes" not in report.metrics
    assert report.metrics["average_ua"] > 0


def test_report_render_with_metrics() -> None:
    contract = load_contract(EXAMPLES / "smart-kettle" / "smart-kettle.fw.json")
    report = GateReport(
        design="x",
        scope="full",
        contract_sha256="c" * 64,
        circuit_sha256=None,
        profile="esp32s3",
        verdict="pass",
        checks=[Check(id="fw.memory_budget", status="pass")],
        metrics={
            "flash_bytes": 100_000.0,
            "flash_capacity_bytes": 1_000_000.0,
            "flash_budget_bytes": 800_000.0,
            "ram_bytes": 50_000.0,
            "ram_capacity_bytes": 500_000.0,
            "ram_budget_bytes": 400_000.0,
            "average_ua": 42.0,
            "average_budget_ua": 100.0,
        },
    )
    _, _, rows = _decode(render.render_report(report, contract))
    assert _has_color(rows, render.BLUE)  # memory bar fill


def _sim() -> Any:
    from firmware.contract import Simulation

    return Simulation.model_validate(
        {
            "id": "boot",
            "runner": "qemu-arm",
            "machine": "mps2-an385",
            "fidelity": "core",
            "image": "build/x.elf",
            "expect": ["boot ok", "sensor ready", "never"],
            "forbid": ["panic"],
            "exit_code": 0,
        }
    )


def test_sim_timeline() -> None:
    sim = _sim()
    lines = ["noise", "boot ok", "more noise", "sensor ready", "panic!"]
    result = SimResult(ok=False, detail="x", argv=[], exit_code=7, seconds=1.5)
    _, _, rows = _decode(render.render_sim_timeline(sim, lines, result))
    assert _has_color(rows, render.RED) and _has_color(rows, render.GREEN)


def _call(name: str, arguments: dict[str, object]) -> mcp.types.CallToolResult:
    async def invoke() -> mcp.types.CallToolResult:
        result = await mcp_server.call_tool(name, arguments)
        assert isinstance(result, mcp.types.CallToolResult)
        return result

    return asyncio.run(invoke())


def test_mcp_inline_image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENHANDS_PROJECT_DIR", str(tmp_path))
    png = render.Canvas(10, 10).to_png()
    image_path = tmp_path / "x.pinmap.png"
    image_path.write_bytes(png)

    def fake_render(_c: Path, _o: Path | None, _v: list[str] | None) -> service.Json:
        return {"verdict": "pass", "written": [str(image_path), str(tmp_path / "other.md")]}

    monkeypatch.setattr(service, "render_payload", fake_render)
    result = _call("firmware_render", {"contract_path": "c.fw.json"})
    assert result.isError is False
    kinds = [type(c) for c in result.content]
    assert mcp.types.ImageContent in kinds
    image = next(c for c in result.content if isinstance(c, mcp.types.ImageContent))
    assert image.mimeType == "image/png"
    assert base64.b64decode(image.data) == png


def test_mcp_inline_image_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENHANDS_PROJECT_DIR", str(tmp_path))
    png = render.Canvas(8, 8).to_png()
    paths: list[str] = []
    for i in range(6):
        p = tmp_path / f"r{i}.png"
        p.write_bytes(png)
        paths.append(str(p))

    def fake_render(_c: Path, _o: Path | None, _v: list[str] | None) -> service.Json:
        return {"verdict": "pass", "written": paths}

    monkeypatch.setattr(service, "render_payload", fake_render)
    result = _call("firmware_render", {"contract_path": "c.fw.json"})
    images = [c for c in result.content if isinstance(c, mcp.types.ImageContent)]
    assert len(images) == 4
    first = result.content[0]
    assert isinstance(first, mcp.types.TextContent)
    skipped = cast(list[object], json.loads(first.text)["images_skipped"])
    assert len(skipped) == 2


def test_render_failure_keeps_verdict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    contract_path = EXAMPLES / "smart-kettle" / "smart-kettle.fw.json"

    def boom(*_args: object, **_kwargs: object) -> bytes:
        raise RuntimeError("renderer exploded")

    monkeypatch.setattr("firmware.gates.render_pinmap", boom)
    monkeypatch.setattr("firmware.gates.render_report", boom)
    monkeypatch.setattr(service, "render_pinmap", boom)
    payload = service.gates_payload(contract_path, tmp_path, full=False)
    assert payload["verdict"] == "pass"
    render_errors = cast(list[str], payload["render_errors"])
    assert len(render_errors) == 2


def test_font_glyphs_unique() -> None:
    rows = render.FONT_ROWS
    assert len(rows) == 95
    assert len(set(rows.values())) == 95


def _pixels(ch: str) -> set[tuple[int, int]]:
    return {
        (x, y)
        for y, row in enumerate(render.FONT_ROWS[ch])
        for x, cell in enumerate(row)
        if cell == "#"
    }


def test_digits_distinct() -> None:
    digits = [str(d) for d in range(10)]
    for a in digits:
        for b in digits:
            if a < b:
                assert len(_pixels(a) ^ _pixels(b)) >= 3, f"{a} vs {b}"


def test_punctuation_sparse() -> None:
    for ch in ".,:-_":
        assert len(_pixels(ch)) <= 4, ch


def test_descender_glyphs_unique() -> None:
    for ch in "fgjpqy":
        assert ch in render.FONT_ROWS
    assert len({frozenset(_pixels(ch)) for ch in "fgjpqy"}) == 6


def _boxes_within(canvas: render.Canvas) -> None:
    for x0, y0, x1, y1 in canvas.text_boxes:
        assert 0 <= x0 <= x1 <= canvas.width
        assert 0 <= y0 <= y1 <= canvas.height


def _boxes_disjoint(boxes: list[tuple[int, int, int, int]]) -> None:
    for i, a in enumerate(boxes):
        for b in boxes[i + 1 :]:
            overlap = not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])
            assert not overlap, f"text boxes intersect: {a} {b}"


@pytest.mark.parametrize("example", ["smart-kettle", "desk-lamp-s3"])
def test_pinmap_layout_collision_free(example: str) -> None:
    contract_path = next((EXAMPLES / example).glob("*.fw.json"))
    contract = load_contract(contract_path)
    profile = load_profile(contract.mcu.profile, [contract_path.parent])
    canvas = render.pinmap_canvas(contract, profile, "c" * 64)
    _boxes_within(canvas)
    _boxes_disjoint(canvas.text_boxes)


def test_report_text_within_canvas() -> None:
    contract = load_contract(EXAMPLES / "smart-kettle" / "smart-kettle.fw.json")
    report = GateReport(
        design="x",
        scope="full",
        contract_sha256="c" * 64,
        circuit_sha256=None,
        profile="esp32s3",
        verdict="pass",
        checks=[Check(id="fw.memory_budget", status="pass")],
        metrics={
            "flash_bytes": 100_000.0,
            "flash_capacity_bytes": 1_000_000.0,
            "flash_budget_bytes": 800_000.0,
            "ram_bytes": 50_000.0,
            "ram_capacity_bytes": 500_000.0,
            "ram_budget_bytes": 400_000.0,
            "average_ua": 42.0,
            "average_budget_ua": 100.0,
        },
    )
    canvas = render.report_canvas(report, contract)
    _boxes_within(canvas)


def test_sim_timeline_text_within_canvas() -> None:
    sim = _sim()
    lines = ["noise", "boot ok", "more noise", "sensor ready", "panic!"]
    for result in (None, SimResult(ok=True, detail="x", argv=[], exit_code=0, seconds=1.0)):
        canvas = render.sim_timeline_canvas(sim, lines, result)
        _boxes_within(canvas)


def test_hatch_stays_inside_pad() -> None:
    canvas = render.Canvas(40, 30)
    render._hatch(canvas, 10, 10, 12, 10, render.BLACK)  # pyright: ignore[reportPrivateUsage]
    rows = canvas._rows  # pyright: ignore[reportPrivateUsage]
    inked = {(x, y) for y, row in enumerate(rows) for x in range(40) if row[3 * x] != 255}
    assert inked
    assert all(10 <= x < 22 and 10 <= y < 20 for x, y in inked)
