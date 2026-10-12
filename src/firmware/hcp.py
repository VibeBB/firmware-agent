"""HCP chart authoring model, DSL projection, deterministic renders and lint.

The HCP (Hierarchical ComPact) chart is a hierarchical program-structure
notation originally developed at the NTT Yokosuka laboratory. The de-facto
text interchange is the ``.hcp`` DSL shared by the HCP Viewer (Keio CREW
lab) and the HCPWorks VS Code extension: one level per tab or four spaces,
``\\`` commands for control kinds, ``#`` comments.

Design (ADR-0013): the JSON model inside ``FirmwareContract.flow`` (or a
standalone ``*.hcp.json`` chart) is the source of truth; the DSL text, the
SVG and the PNG are byte-deterministic projections that are never edited
by hand. The renderer reimplements the layout rules documented for the
reference implementations (row flattening where ``branch``/``true``/
``false`` take the parent ``fork`` depth, depth-scoped trunk segments,
elbow connectors) rather than porting any external code.
"""

from __future__ import annotations

import itertools
import math
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from .render import Canvas

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1
IDENT = r"^[a-z][a-z0-9_]*$"
DATA_NAME = r"^[^\s.]+$"
ITEM_KINDS = (
    "process",
    "repeat",
    "fork",
    "branch",
    "true",
    "false",
    "return",
    "ec",
    "ex",
    "mod",
)
ItemKind = Literal[
    "process",
    "repeat",
    "fork",
    "branch",
    "true",
    "false",
    "return",
    "ec",
    "ex",
    "mod",
]
FORK_CHILDREN = ("branch", "true", "false")
MAX_DEPTH = 8


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HcpRefs(_Strict):
    """Cross-references from a flow item back into the firmware contract."""

    pins: list[str] = Field(default_factory=list)
    peripherals: list[str] = Field(default_factory=list)
    power_modes: list[str] = Field(default_factory=list)
    simulations: list[str] = Field(default_factory=list)


class HcpItem(_Strict):
    """One node of an HCP chart.

    ``kind`` names the DSL command; ``process`` is a bare label line.
    ``levels`` is meaningful for ``return`` (``\\return n``). ``data_in`` /
    ``data_out`` emit ``\\in`` / ``\\out`` decorator lines. ``children`` is
    the indented subtree (a ``fork``'s children must be ``branch`` /
    ``true`` / ``false`` rows).
    """

    kind: ItemKind = "process"
    label: str = ""
    data_in: list[str] = Field(default_factory=list)
    data_out: list[str] = Field(default_factory=list)
    levels: int | None = Field(default=None, ge=1)
    refs: HcpRefs | None = None
    children: list[HcpItem] = Field(default_factory=list["HcpItem"])


class HcpModule(_Strict):
    name: str = Field(pattern=IDENT)
    data: list[str] = Field(default_factory=list)
    items: list[HcpItem] = Field(default_factory=list[HcpItem], min_length=1)


class HcpHeader(_Strict):
    title: str = ""
    author: str = ""
    date: str = ""
    version: str = ""


class HcpFlow(_Strict):
    """The ``flow`` section of a firmware contract: program structure."""

    header: HcpHeader = Field(default_factory=HcpHeader)
    modules: list[HcpModule] = Field(default_factory=list[HcpModule], min_length=1)


class HcpChart(_Strict):
    """Standalone ``*.hcp.json`` chart sharing the flow model."""

    schema_version: Literal[1] = SCHEMA_VERSION
    artifact_kind: Literal["hcp_chart"] = "hcp_chart"
    name: str = Field(pattern=IDENT)
    description: str = ""
    header: HcpHeader = Field(default_factory=HcpHeader)
    modules: list[HcpModule] = Field(default_factory=list[HcpModule], min_length=1)


def load_hcp_chart(path: str | Path) -> HcpChart:
    import json

    return HcpChart.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def chart_flow(chart: HcpChart) -> HcpFlow:
    return HcpFlow(header=chart.header, modules=chart.modules)


# ---------------------------------------------------------------------------
# DSL projection (JSON -> .hcp text)
# ---------------------------------------------------------------------------

_COMMAND: dict[str, str] = {
    "repeat": "repeat",
    "fork": "fork",
    "branch": "branch",
    "true": "true",
    "false": "false",
    "return": "return",
    "ec": "ec",
    "ex": "ex",
    "mod": "mod",
}


def _indent(level: int) -> str:
    return "\t" * level


def _emit_item(item: HcpItem, level: int, lines: list[str]) -> None:
    pad = _indent(level)
    if item.kind == "process":
        lines.append(f"{pad}{item.label}")
    elif item.kind == "return" and item.levels and item.levels > 1:
        lines.append(f"{pad}\\return {item.levels}")
    else:
        cmd = _COMMAND[item.kind]
        label = f" {item.label}" if item.label else ""
        lines.append(f"{pad}\\{cmd}{label}")
    for name in item.data_in:
        lines.append(f"{pad}\t\\in {name}")
    for name in item.data_out:
        lines.append(f"{pad}\t\\out {name}")
    for child in item.children:
        _emit_item(child, level + 1, lines)


def flow_to_dsl(flow: HcpFlow) -> str:
    """Emit the de-facto ``.hcp`` DSL (half-width backslash, tab indents)."""
    lines: list[str] = []
    header = flow.header
    for command, value in (
        ("title", header.title),
        ("author", header.author),
        ("date", header.date),
        ("version", header.version),
    ):
        if value:
            lines.append(f"\\{command} {value}")
    if lines:
        lines.append("")
    for i, module in enumerate(flow.modules):
        if i:
            lines.append("")
        lines.append(f"\\module {module.name}")
        for name in module.data:
            lines.append(f"\t\\data {name}")
        for item in module.items:
            _emit_item(item, 1, lines)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# DSL parse (.hcp text -> model, with diagnostics)
# ---------------------------------------------------------------------------


@dataclass
class HcpDiagnostic:
    severity: str  # "error" | "warning"
    line: int
    message: str


@dataclass
class _Row:
    level: int
    kind: str
    label: str
    item: HcpItem | None = None


_INDENT_UNIT = 4
_CMD_RE = re.compile(r"^[\\￥¥](\w+)\s*(.*)$")


def _line_level(text: str) -> tuple[int, str, str | None]:
    """Return (level, rest, indent_error). Tabs or 4-space groups only."""
    level = 0
    i = 0
    while i < len(text):
        if text[i] == "\t":
            level += 1
            i += 1
        elif text[i] == " ":
            run = 0
            while i < len(text) and text[i] == " ":
                run += 1
                i += 1
            if run % _INDENT_UNIT:
                return level, text[i:].strip(), "indentation is not a 4-space multiple"
            level += run // _INDENT_UNIT
        else:
            break
    rest = text[i:]
    if rest.startswith((" ", "\t")):
        return level, rest.strip(), "mixed indentation"
    return level, rest, None


def _tree_from_rows(rows: list[_Row], module_names: list[str]) -> list[HcpItem]:
    """Build nested items from (level, kind, label) rows; drops decorators."""
    roots: list[HcpItem] = []
    stack: list[tuple[int, HcpItem]] = []
    for row in rows:
        if row.item is None:
            continue
        while stack and stack[-1][0] >= row.level:
            stack.pop()
        if stack:
            stack[-1][1].children.append(row.item)
        else:
            roots.append(row.item)
        stack.append((row.level, row.item))
    return roots


def dsl_to_flow(text: str) -> tuple[HcpFlow, list[HcpDiagnostic]]:
    """Parse ``.hcp`` DSL text into the model; never raises on bad input."""
    diagnostics: list[HcpDiagnostic] = []
    header = HcpHeader()
    modules: list[HcpModule] = []
    module: HcpModule | None = None
    module_names: list[str] = []
    rows: list[_Row] = []
    last_item: tuple[int, HcpItem] | None = None

    def flush_module() -> None:
        nonlocal rows, module
        if module is None:
            return
        module.items = _tree_from_rows(rows, module_names)
        if not module.items:
            diagnostics.append(
                HcpDiagnostic("error", 0, f"module {module.name} has no process rows")
            )
        modules.append(module)
        module = None
        rows = []

    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip("\r\n")
        if not line.strip() or line.strip().startswith("#"):
            continue
        level, rest, indent_error = _line_level(line)
        if indent_error:
            diagnostics.append(HcpDiagnostic("error", lineno, indent_error))
        if not rest:
            continue
        match = _CMD_RE.match(rest)
        command = match.group(1).lower() if match else None
        arg = (match.group(2).strip() if match else "") or ""
        if command in {"title", "author", "date", "version"}:
            setattr(header, command, arg)
            continue
        if command == "module":
            if level != 0:
                diagnostics.append(HcpDiagnostic("error", lineno, "\\module must be at level 0"))
            if not arg or not re.match(IDENT, arg):
                diagnostics.append(
                    HcpDiagnostic("error", lineno, "\\module needs an identifier name")
                )
            elif arg in module_names:
                diagnostics.append(HcpDiagnostic("error", lineno, f"duplicate module {arg}"))
            else:
                module_names.append(arg)
            flush_module()
            module = HcpModule(name=arg or f"module{len(module_names) + 1}")
            last_item = None
            continue
        if command == "data":
            if module is not None and arg:
                module.data.append(arg)
            continue
        if command in {"in", "out"}:
            if last_item is not None and arg:
                getattr(last_item[1], f"data_{command}").append(arg)
            else:
                diagnostics.append(HcpDiagnostic("warning", lineno, f"orphan \\{command} {arg}"))
            continue
        if command == "return":
            levels = 1
            if arg:
                try:
                    levels = int(arg)
                    if levels < 1:
                        diagnostics.append(
                            HcpDiagnostic("error", lineno, "\\return n must be positive")
                        )
                        levels = 1
                except ValueError:
                    diagnostics.append(
                        HcpDiagnostic("error", lineno, "\\return n must be an integer")
                    )
            item = HcpItem(kind="return", levels=levels)
        elif command in _COMMAND.values():
            item = HcpItem(kind=command, label=arg)  # type: ignore[arg-type]
        elif command:
            diagnostics.append(HcpDiagnostic("warning", lineno, f"unknown command \\{command}"))
            item = HcpItem(kind="process", label=arg or f"\\{command}")
        else:
            item = HcpItem(kind="process", label=rest)
        rows.append(_Row(level=level, kind=item.kind, label=item.label, item=item))
        last_item = (level, item)

    flush_module()
    if not modules:
        diagnostics.append(HcpDiagnostic("error", 0, "no \\module declaration"))
    for m in modules:
        _check_levels(m.items, 1, diagnostics)
    return (
        HcpFlow(
            header=header,
            modules=modules or [HcpModule(name="main", items=[HcpItem(label="empty")])],
        ),
        diagnostics,
    )


def _check_levels(items: list[HcpItem], level: int, diagnostics: list[HcpDiagnostic]) -> None:
    if level > MAX_DEPTH:
        diagnostics.append(HcpDiagnostic("error", 0, f"nesting deeper than {MAX_DEPTH} levels"))
        return
    for item in items:
        _check_levels(item.children, level + 1, diagnostics)


# ---------------------------------------------------------------------------
# Structure validation and notation lint
# ---------------------------------------------------------------------------


@dataclass
class HcpFinding:
    rule: str
    detail: str
    subject: str


_CODE_TOKEN = re.compile(r"(^[\w.]+\s*[=({]|;\s*$|^if\s*\(|^for\s*\(|->)")


def _iter_items(
    items: list[HcpItem], depth: int, module: str, parent_kind: str = ""
) -> Iterator[tuple[HcpItem, int, str, str]]:
    for item in items:
        yield item, depth, module, parent_kind
        yield from _iter_items(item.children, depth + 1, module, item.kind)


def iter_items(flow: HcpFlow) -> Iterator[tuple[HcpItem, int, str, str]]:
    """Yield (item, depth, module_name, parent_kind) for every flow item."""
    for module in flow.modules:
        yield from _iter_items(module.items, 1, module.name)


def validate_refs(
    flow: HcpFlow,
    *,
    pins: tuple[str, ...] = (),
    peripherals: tuple[str, ...] = (),
    power_modes: tuple[str, ...] = (),
    simulations: tuple[str, ...] = (),
) -> list[str]:
    """Resolve ``refs`` against the owning contract; unknown ids are errors."""
    pin_set, per_set = set(pins), set(peripherals)
    mode_set, sim_set = set(power_modes), set(simulations)
    errors: list[str] = []
    for item, _depth, mod, _parent in iter_items(flow):
        if item.refs is None:
            continue
        where = f"{mod}:{item.label or item.kind}"
        for ref in item.refs.pins:
            if ref not in pin_set:
                errors.append(f"{where}: pin ref {ref!r} is not a pin signal")
        for ref in item.refs.peripherals:
            if ref not in per_set:
                errors.append(f"{where}: peripheral ref {ref!r} unknown")
        for ref in item.refs.power_modes:
            if ref not in mode_set:
                errors.append(f"{where}: power mode ref {ref!r} unknown")
        for ref in item.refs.simulations:
            if ref not in sim_set:
                errors.append(f"{where}: simulation ref {ref!r} unknown")
    return errors


def validate_flow(flow: HcpFlow) -> list[str]:
    """Structural errors (the ``fw.hcp`` gate). Returns a list of details."""
    errors: list[str] = []
    names = [m.name for m in flow.modules]
    if len(names) != len(set(names)):
        errors.append("duplicate module names")
    for module in flow.modules:
        if not module.items:
            errors.append(f"{module.name}: module has no items")
        for name in module.data:
            if not re.match(DATA_NAME, name):
                errors.append(f"data name {name!r} contains spaces or dots")
        for item, depth, mod, parent in _iter_items(module.items, 1, module.name):
            where = f"{mod}:{'/'.join([item.kind])}@{depth} {item.label or item.kind}"
            if depth > MAX_DEPTH:
                errors.append(f"{where}: nesting deeper than {MAX_DEPTH}")
            if item.kind in FORK_CHILDREN and parent != "fork":
                errors.append(f"{where}: {item.kind} must be a direct child of fork")
            if item.kind != "return" and item.levels is not None:
                errors.append(f"{where}: levels only applies to return")
            if item.kind == "mod":
                target = item.label.split()[0] if item.label else ""
                if target not in names:
                    errors.append(f"{where}: mod target {target!r} is not a module")
            if item.kind in {"process", "mod"} and not item.label.strip():
                errors.append(f"{where}: empty label")
            for name in (*item.data_in, *item.data_out):
                if not re.match(DATA_NAME, name):
                    errors.append(f"{where}: data name {name!r} is invalid")
    return errors


def lint_flow(flow: HcpFlow) -> list[HcpFinding]:
    """Notation-quality findings (the ``fw.hcp_lint`` gate).

    Deterministic proxies for the review-method defect classes: purpose
    before means at top level, error-handling mixed into the main sequence,
    a process reappearing in several modules, and granularity outliers.
    """
    findings: list[HcpFinding] = []
    seen_labels: dict[str, list[str]] = {}
    for module in flow.modules:
        for item in module.items:
            if item.kind == "process" and _CODE_TOKEN.search(item.label):
                findings.append(
                    HcpFinding(
                        "means_at_top_level",
                        "top-level item reads like a means/code token, not a purpose",
                        f"{module.name}: {item.label}",
                    )
                )
        for item, _depth, mod, _parent in _iter_items(module.items, 1, module.name):
            if item.kind == "process" and item.label.strip():
                seen_labels.setdefault(item.label.strip(), []).append(mod)
            if len(item.children) > 7:
                findings.append(
                    HcpFinding(
                        "granularity",
                        f"item has {len(item.children)} children (>7)",
                        f"{mod}: {item.label or item.kind}",
                    )
                )
    for label, mods in seen_labels.items():
        if len(set(mods)) > 1:
            findings.append(
                HcpFinding(
                    "reappearing_process",
                    "same process label appears in multiple modules",
                    label,
                )
            )
    return _dedupe_findings(findings)


def _dedupe_findings(findings: list[HcpFinding]) -> list[HcpFinding]:
    out: list[HcpFinding] = []
    seen: set[tuple[str, str]] = set()
    for finding in findings:
        key = (finding.rule, finding.subject)
        if key not in seen:
            seen.add(key)
            out.append(finding)
    return out


_ERROR_WORDS = re.compile(
    r"(エラー|error|fault|exception|abort|recovery|recover|fail|失敗)", re.IGNORECASE
)


def error_mixing_findings(flow: HcpFlow) -> list[HcpFinding]:
    """Error handling written as a normal ``process`` item in the sequence.

    The ``ec``/``ex`` exits are the notation's error escapes; labelling an
    ordinary process item as error handling ("エラー処理混在") mixes
    concerns into the main trunk and is flagged.
    """
    findings: list[HcpFinding] = []
    for item, _depth, mod, _parent in iter_items(flow):
        if item.kind == "process" and _ERROR_WORDS.search(item.label):
            findings.append(
                HcpFinding(
                    "error_handling_inline",
                    "error handling drawn as a normal process; use ec/ex exits",
                    f"{mod}: {item.label}",
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Layout and SVG render
# ---------------------------------------------------------------------------

# Geometry follows the documented reference layout: row height 24 px,
# indent 36 px per depth, 14 px symbol diameter, deterministic text metrics
# (ASCII 0.6 em, other 1.0 em) so renders are byte-identical everywhere.
LINE_H = 24
INDENT = 36
LEFT_PAD = 24
SYMBOL = 14
FONT_SIZE = 12
LABEL_GAP = 10
TOP_PAD = 16
HEADER_H = 24
DATA_COL_GAP = 64


@dataclass
class _RenderRow:
    kind: str
    label: str
    depth: int
    item: HcpItem


def _flatten(items: list[HcpItem], depth: int, rows: list[_RenderRow]) -> None:
    for item in items:
        render_depth = depth
        rows.append(_RenderRow(item.kind, item.label, render_depth, item))
        for child in item.children:
            # branch/true/false bodies keep their own depth + 1
            _flatten([child], depth + 1, rows)


def _text_width(text: str, font: float = FONT_SIZE) -> float:
    return sum(0.6 if ord(ch) < 128 else 1.0 for ch in text) * font


def _module_layout(module: HcpModule, y0: int) -> tuple[list[_RenderRow], int]:
    rows: list[_RenderRow] = []
    _flatten(module.items, 1, rows)
    for row in rows:
        if row.kind in FORK_CHILDREN:
            row.depth = max(0, row.depth - 1)  # parent fork's depth
    return rows, y0 + len(rows) * LINE_H


def _trunk_x(depth: int) -> float:
    return LEFT_PAD + depth * INDENT + SYMBOL / 2


def _row_y(y0: int, i: int) -> float:
    return y0 + i * LINE_H + LINE_H / 2


def _spine_segments(rows: list[_RenderRow], y0: int) -> list[tuple[float, float, float]]:
    """Vertical trunk segments per the scope rule (all rows between >= depth)."""
    segments: list[tuple[float, float, float]] = []
    depths = sorted({row.depth for row in rows})
    for depth in depths:
        indices = [i for i, row in enumerate(rows) if row.depth == depth]
        for prev, nxt in itertools.pairwise(indices):
            if all(row.depth >= depth for row in rows[prev : nxt + 1]):
                segments.append((_trunk_x(depth), _row_y(y0, prev), _row_y(y0, nxt)))
    return segments


def _elbows(rows: list[_RenderRow], y0: int) -> list[tuple[float, float, float]]:
    """Horizontal parent -> child connectors at the child's y."""
    elbows: list[tuple[float, float, float]] = []
    for i, row in enumerate(rows):
        if i == 0 or row.depth == 0:
            continue
        # nearest previous row with smaller depth is the trunk parent
        for j in range(i - 1, -1, -1):
            if rows[j].depth == row.depth - 1:
                elbows.append((_trunk_x(rows[j].depth), _row_y(y0, i), _trunk_x(row.depth)))
                break
    return elbows


def _svg_circle(cx: float, cy: float, r: float, fill: str = "none") -> str:
    return (
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" '
        f'stroke="#000" stroke-width="1.5" fill="{fill}"/>'
    )


def _svg_line(x1: float, y1: float, x2: float, y2: float, dash: str = "") -> str:
    extra = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
        f'stroke="#000" stroke-width="1.5"{extra}/>'
    )


def _svg_text(x: float, y: float, text: str, weight: str = "") -> str:
    from xml.sax.saxutils import escape

    w = f' font-weight="{weight}"' if weight else ""
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="monospace" '
        f'font-size="{FONT_SIZE}"{w}>{escape(text)}</text>'
    )


def _svg_symbol(kind: str, cx: float, cy: float, label: str) -> str:
    """Fifteen canonical glyphs per the NTT notation (subset used by DSL)."""
    r = SYMBOL / 2
    parts: list[str] = []
    if kind in {"process", "branch", "true", "false"}:
        parts.append(_svg_circle(cx, cy, r))
    elif kind == "repeat":
        parts.append(_svg_circle(cx, cy, r))
        # arc arrow over the top: half circle opening right + arrowhead
        ar = r * 0.5
        parts.append(
            f'<path d="M {cx - ar:.1f} {cy - r:.1f} A {ar:.1f} {ar:.1f} 0 0 1 '
            f'{cx + ar:.1f} {cy - r:.1f}" stroke="#000" fill="none"/>'
        )
        parts.append(f'<path d="M {cx + ar:.1f} {cy - r:.1f} l -3 -4 l 6 0 z" fill="#000"/>')
    elif kind == "mod":
        parts.append(_svg_circle(cx, cy, r))
        parts.append(_svg_circle(cx, cy, r * 0.55))
    elif kind == "fork":
        parts.append(_svg_circle(cx, cy, r))
        # small decision flag on the right of the circle
        parts.append(
            f'<path d="M {cx + r:.1f} {cy:.1f} L {cx + r + 6:.1f} {cy - 4:.1f} '
            f'L {cx + r + 6:.1f} {cy + 4:.1f} Z" fill="none" stroke="#000"/>'
        )
    elif kind == "return":
        # n-level exit: inverted triangle with the count inside
        parts.append(
            f'<path d="M {cx - r:.1f} {cy - r:.1f} L {cx + r:.1f} {cy - r:.1f} '
            f'L {cx:.1f} {cy + r:.1f} Z" fill="#fff" stroke="#000"/>'
        )
    elif kind == "ec":
        parts.append(_svg_circle(cx, cy, r))
        parts.append(
            f'<path d="M {cx - r * 0.6:.1f} {cy - r:.1f} A {r:.1f} {r:.1f} 0 0 1 '
            f'{cx + r * 0.6:.1f} {cy - r:.1f}" stroke="#000" fill="none"/>'
        )
        parts.append(_svg_line(cx + r, cy, cx + r + 10, cy))
    elif kind == "ex":
        parts.append(_svg_circle(cx, cy, r))
        parts.append(
            f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{r * 1.5:.1f}" '
            f'ry="{r * 0.5:.1f}" fill="none" stroke="#000"/>'
        )
        parts.append(_svg_circle(cx, cy, 1.5, fill="#000"))
    return "".join(parts)


def _svg_in_marker(x: float, y: float) -> str:
    return (
        f'<path d="M {x:.1f} {y:.1f} L {x + SYMBOL / 2:.1f} {y - SYMBOL / 2:.1f} '
        f'L {x + SYMBOL / 2:.1f} {y + SYMBOL / 2:.1f} Z" fill="#ff00ff"/>'
    )


def _svg_out_marker(x: float, y: float) -> str:
    return (
        f'<path d="M {x + SYMBOL / 2:.1f} {y:.1f} L {x:.1f} {y - SYMBOL / 2:.1f} '
        f'L {x:.1f} {y + SYMBOL / 2:.1f} Z" fill="#00c0c0"/>'
    )


def render_hcp_svg(flow: HcpFlow, name: str, source_sha256: str) -> str:
    """Byte-deterministic SVG of the chart; the canonical vector render."""
    elements: list[str] = []
    y = TOP_PAD
    header = flow.header
    for field_, weight in (
        (f"{header.title}  {name}".strip(), "bold"),
        (f"author:{header.author} date:{header.date} version:{header.version}".strip(), ""),
    ):
        if field_:
            elements.append(_svg_text(LEFT_PAD, y + FONT_SIZE, field_, weight))
            y += HEADER_H
    y += 8
    max_label_x = LEFT_PAD
    for module in flow.modules:
        elements.append(_svg_text(LEFT_PAD, y + FONT_SIZE, module.name, "bold"))
        rows, y_end = _module_layout(module, y)
        y0 = y
        for x1, sy1, sy2 in _spine_segments(rows, y0):
            elements.append(_svg_line(x1, sy1 - SYMBOL / 2, x1, sy2 + SYMBOL / 2))
        for x1, ey, x2 in _elbows(rows, y0):
            elements.append(_svg_line(x1, ey, x2 - SYMBOL / 2, ey))
        for i, row in enumerate(rows):
            cx = _trunk_x(row.depth)
            cy = _row_y(y0, i)
            elements.append(_svg_symbol(row.kind, cx, cy, row.label))
            label = row.label
            if row.kind == "return" and row.item.levels and row.item.levels > 1:
                label = f"{row.item.levels}"
            elif row.kind == "return":
                label = row.label
            lx = cx + SYMBOL / 2 + LABEL_GAP
            if row.kind == "fork":
                lx += 6
            elements.append(_svg_text(lx, cy + FONT_SIZE * 0.35, label))
            max_label_x = max(max_label_x, lx + _text_width(label))
            for _ in row.item.data_in:
                elements.append(_svg_in_marker(lx - LABEL_GAP, cy))
            for _ in row.item.data_out:
                ox = lx + _text_width(label) + 8
                elements.append(_svg_out_marker(ox, cy))
                max_label_x = max(max_label_x, ox + SYMBOL)
        # implicit start (T-bar) and end (perpendicular) glyphs on depth-1 trunk
        x1 = _trunk_x(1)
        elements.append(_svg_line(x1, y0 - 4, x1, y0 + 4))
        elements.append(_svg_line(x1 - 8, y0 - 4, x1 + 8, y0 - 4))
        y_end_row = y0 + len(rows) * LINE_H
        elements.append(_svg_line(x1, y_end_row - 4, x1, y_end_row + 4))
        elements.append(_svg_line(x1 - 8, y_end_row + 4, x1 + 8, y_end_row + 4))
        # module data definitions: rectangle boxes in the right column
        data_x = max_label_x + DATA_COL_GAP
        dy = y0
        for data_name in module.data:
            w = _text_width(data_name) + 16
            elements.append(
                f'<rect x="{data_x:.1f}" y="{dy + 2:.1f}" width="{w:.1f}" '
                f'height="{LINE_H - 6}" fill="#fff" stroke="#000"/>'
            )
            elements.append(
                _svg_text(data_x + 8, dy + 2 + (LINE_H - 6) / 2 + FONT_SIZE * 0.35, data_name)
            )
            dy += LINE_H
        y = y_end + LINE_H
    height = int(y + 88)
    block_w = 260
    block_h = 46
    bx = max_label_x + DATA_COL_GAP
    width = int(max(bx + block_w + 24, max_label_x + 24))
    by = height - block_h - 16
    elements.append(
        f'<rect x="{bx:.1f}" y="{by:.1f}" width="{block_w}" height="{block_h}" '
        f'fill="#fff" stroke="#000"/>'
    )
    elements.append(_svg_text(bx + 8, by + 16, f"firmware hcp · {name}", "bold"))
    elements.append(_svg_text(bx + 8, by + 32, f"sha256:{source_sha256[:12]} · generated"))
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}">'
        f'<rect width="100%" height="100%" fill="#fff"/>' + "".join(elements) + "</svg>\n"
    )
    return svg


# ---------------------------------------------------------------------------
# PNG render (ASCII canvas for the vision-review projection)
# ---------------------------------------------------------------------------

_ASCII_SAFE = re.compile(r"[^\x20-\x7e]")


def _png_circle(canvas: Canvas, cx: int, cy: int, r: int, color: tuple[int, int, int]) -> None:
    x, y, err = -r, 0, 2 - 2 * r
    while x < 0:
        for px, py in (
            (cx - x, cy + y),
            (cx - y, cy - x),
            (cx + x, cy - y),
            (cx + y, cy + x),
            (cx + x, cy + y),
            (cx + y, cy - x),
            (cx - x, cy - y),
            (cx - y, cy + x),
        ):
            canvas.pixel(px, py, color)
        r = err
        if r <= y:
            y += 1
            err += y * 2 + 1
        if r > x or err > y:
            x += 1
            err += x * 2 + 1


def _clean(text: str) -> str:
    return _ASCII_SAFE.sub("?", text)


def render_hcp_png(flow: HcpFlow, name: str, source_sha256: str) -> bytes:
    """ASCII raster of the same layout; the vision-review input projection."""
    from .render import BLACK, BLUE, GREEN, GREY, ORANGE, RED, WHITE, Canvas

    header_lines = sum(
        1
        for v in (
            f"{flow.header.title} {name}".strip(),
            flow.header.author or flow.header.date or flow.header.version,
        )
        if v
    )
    module_rows: list[tuple[HcpModule, list[_RenderRow]]] = [
        (m, _flatten_rows(m)) for m in flow.modules
    ]
    total = sum(len(rows) for _, rows in module_rows)
    width = 140 * 6  # CHAR_ADVANCE*len budget; widened below when needed
    max_x = LEFT_PAD + MAX_DEPTH * INDENT + 200
    height = (
        TOP_PAD + header_lines * HEADER_H + total * LINE_H + len(flow.modules) * LINE_H * 2 + 96
    )
    canvas = Canvas(width + max_x, height, WHITE)
    y = TOP_PAD
    for v in (f"{flow.header.title} {name}".strip(),):
        if v:
            canvas.text(LEFT_PAD, y, _clean(v), BLACK, scale=1)
            y += HEADER_H
    y += 8
    for module, rows in module_rows:
        canvas.text(LEFT_PAD, y, _clean(module.name), BLUE, scale=1)
        for x1, sy1, sy2 in _spine_segments(rows, y):
            canvas.line(int(x1), int(sy1 - SYMBOL / 2), int(x1), int(sy2 + SYMBOL / 2), BLACK)
        for x1, ey, x2 in _elbows(rows, y):
            canvas.line(int(x1), int(ey), int(x2 - SYMBOL / 2), int(ey), BLACK)
        for i, row in enumerate(rows):
            cx = int(_trunk_x(row.depth))
            cy = int(_row_y(y, i))
            _png_symbol(canvas, row.kind, cx, cy)
            label = _clean(row.label)
            if row.kind == "return" and row.item.levels and row.item.levels > 1:
                label = str(row.item.levels)
            canvas.text(cx + SYMBOL + LABEL_GAP, cy - 4, label, BLACK, scale=1)
            for _ in row.item.data_in:
                canvas.rect(cx - SYMBOL - 8, cy - 4, 6, 8, GREEN, BLACK)
            for _ in row.item.data_out:
                canvas.rect(
                    cx + SYMBOL + LABEL_GAP + len(label) * 6 + 2,
                    cy - 4,
                    6,
                    8,
                    ORANGE,
                    BLACK,
                )
        x1 = int(_trunk_x(1))
        canvas.line(x1, y - 4, x1, y + 4, BLACK)
        canvas.line(x1 - 8, y - 4, x1 + 8, y - 4, BLACK)
        ye = y + len(rows) * LINE_H
        canvas.line(x1, ye - 4, x1, ye + 4, BLACK)
        canvas.line(x1 - 8, ye + 4, x1 + 8, ye + 4, BLACK)
        dy = y
        for data_name in module.data:
            canvas.text(width - 24 + LEFT_PAD, dy, _clean(data_name), GREY, scale=1)
            dy += LINE_H
        y = ye + LINE_H
    canvas.text(
        LEFT_PAD,
        height - 24,
        f"firmware hcp {name} sha256:{source_sha256[:12]}",
        RED,
        scale=1,
    )
    return canvas.to_png()


def _flatten_rows(module: HcpModule) -> list[_RenderRow]:
    rows: list[_RenderRow] = []
    _flatten(module.items, 1, rows)
    for row in rows:
        if row.kind in FORK_CHILDREN:
            row.depth = max(0, row.depth - 1)
    return rows


def _png_symbol(canvas: Canvas, kind: str, cx: int, cy: int) -> None:
    from .render import BLACK

    r = int(SYMBOL / 2)
    if kind in {"process", "branch", "true", "false"}:
        _png_circle(canvas, cx, cy, r, BLACK)
    elif kind == "repeat":
        _png_circle(canvas, cx, cy, r, BLACK)
        _png_circle(canvas, cx, cy - r, r // 2, BLACK)
        canvas.pixel(cx + r // 2 + 1, cy - r, BLACK)
    elif kind == "mod":
        _png_circle(canvas, cx, cy, r, BLACK)
        _png_circle(canvas, cx, cy, max(2, r // 2), BLACK)
    elif kind == "fork":
        _png_circle(canvas, cx, cy, r, BLACK)
        canvas.line(cx + r, cy, cx + r + 6, cy - 4, BLACK)
        canvas.line(cx + r, cy, cx + r + 6, cy + 4, BLACK)
    elif kind == "return":
        canvas.line(cx - r, cy - r, cx + r, cy - r, BLACK)
        canvas.line(cx - r, cy - r, cx, cy + r, BLACK)
        canvas.line(cx + r, cy - r, cx, cy + r, BLACK)
    elif kind == "ec":
        _png_circle(canvas, cx, cy, r, BLACK)
        _png_circle(canvas, cx, cy - r, r // 2, BLACK)
        canvas.line(cx + r, cy, cx + r + 10, cy, BLACK)
    elif kind == "ex":
        _png_circle(canvas, cx, cy, r, BLACK)
        for a in range(0, 360, 12):
            rad = math.radians(a)
            canvas.pixel(
                cx + int(r * 1.5 * math.cos(rad)),
                cy + int(r * 0.5 * math.sin(rad)),
                BLACK,
            )
        canvas.rect(cx - 1, cy - 1, 2, 2, BLACK)


# ---------------------------------------------------------------------------
# Artifact writers
# ---------------------------------------------------------------------------


def write_hcp_artifacts(
    flow: HcpFlow,
    name: str,
    out_dir: Path,
    source_sha256: str,
    render_errors: list[str] | None = None,
) -> list[Path]:
    """Write ``<name>.hcp``, ``.hcp.svg``, ``.hcp.png`` and ``.hcp-lint.json``.

    Render failures are advisory: they append to ``render_errors`` and never
    raise, matching the pinmap/report render policy.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def _wt(path: Path, text: str) -> None:
        path.write_text(text, encoding="utf-8")
        written.append(path)

    _wt(out_dir / f"{name}.hcp", flow_to_dsl(flow))
    try:
        _wt(
            out_dir / f"{name}.hcp.svg",
            render_hcp_svg(flow, name, source_sha256),
        )
    except Exception as exc:  # advisory render
        if render_errors is not None:
            render_errors.append(f"hcp.svg: {exc}")
    try:
        png = render_hcp_png(flow, name, source_sha256)
        (out_dir / f"{name}.hcp.png").write_bytes(png)
        written.append(out_dir / f"{name}.hcp.png")
    except Exception as exc:  # advisory render
        if render_errors is not None:
            render_errors.append(f"hcp.png: {exc}")

    import json

    _wt(
        out_dir / f"{name}.hcp-lint.json",
        json.dumps(lint_report_json(flow, name), indent=2, ensure_ascii=False) + "\n",
    )
    return written


def lint_report_json(flow: HcpFlow, name: str) -> dict[str, object]:
    findings = lint_flow(flow) + error_mixing_findings(flow)
    return {
        "schema_version": SCHEMA_VERSION,
        "system": "firmware",
        "artifact_kind": "hcp_lint_report",
        "design": name,
        "verdict": "pass" if not findings else "fail",
        "findings": [{"rule": f.rule, "detail": f.detail, "subject": f.subject} for f in findings],
    }
