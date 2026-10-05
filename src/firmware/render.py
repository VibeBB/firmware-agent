"""Stdlib-only PNG renders of firmware projections (zlib + struct, no deps).

The launcher mounts the source tree into the published ``firmware-tools``
image, so this module must run on the image's bare interpreter: it draws
onto an RGB canvas and encodes PNG by hand (8-bit RGB, filter 0, one zlib
IDAT at level 9). Output is byte-deterministic for equal input.

Renders:

* :func:`render_pinmap` — board pin map from the contract + MCU profile,
* :func:`render_report` — gate matrix, memory and power budget bars,
* :func:`render_sim_timeline` — serial/QEMU transcript timeline.

Renders are advisory vision inputs; a failure here never changes a gate
verdict.
"""

from __future__ import annotations

import base64
import math
import struct
import zlib
from dataclasses import dataclass

from .contract import FUNCTION_ROLE, FirmwareContract, Simulation
from .profiles import McuProfile
from .sim import SimResult

# ---------------------------------------------------------------------------
# 5x7 bitmap font, printable ASCII 0x20-0x7E; 5 column bytes per glyph,
# bit y set = pixel at row y. Baked offline from a scalable font; unknown
# characters render as '?'.
_FONT_B64 = (
    "AAAAAAAAAE8AAH9/f39/eF8+GQAuf382AAc3DDs4PklJfAwAf38AAAA+YQAAAAB/AAACDAcMAgQE"
    "HwQEfHx8fHwDAwMDAx8fHx8fAHh/BwA+Y2M+AAACAX8AQGNRTgAyQUk+ABAYFn8wLklJOQA8S0k+"
    "AAFxHQMAPklJPgA+SWkeAAAAQQAAAEAhAAAOHhsRIQkJCQkJIREbHg4GAVkOAB4/IzcOQDwLDnB/"
    "SUk+ABxjQUE2f0FBYxx/SUlBAH8JCQEAHGNBa35/CAgIfwAAfwAAMEBAPwB/HD5BAH9AQEAAPx8w"
    "Dz9/H3h/AB4hISEefwkJDgAeISEhPn8JGX4AJklJOgABf38BAD9AQD8AAQ5wOAcDDAMMD2McPkEA"
    "A3x8AwBhWU1DAAAAfwAAAB9gAAAAAH8AAB4DBw8QQEBAQEAfHx8fH3p5SW9/f0REPAAeISEhEjxE"
    "RH8AHiUlJRYADA0AAD5RUT8AfwQEfAAAAH0AAAAAfAAAfwg4RAAAf0AAAA8BDwEPPwMBAT4eISEh"
    "Hn8RER4AHhERfwB/AwEBAG9vSXl6AAR/RAAfICAwPwMcIBwDBw4HDgc6HBxjAAN8PAMAYXFJR0MA"
    "AH8AAAAAfwAAAAB/AAADAQMCAw=="
)
_FONT = base64.b64decode(_FONT_B64)
GLYPH_W = 5
GLYPH_H = 7
CHAR_ADVANCE = GLYPH_W + 1

Color = tuple[int, int, int]

BLACK: Color = (30, 30, 30)
WHITE: Color = (255, 255, 255)
GREY: Color = (200, 204, 210)
DARK_GREY: Color = (110, 116, 124)
GREEN: Color = (46, 160, 67)
RED: Color = (218, 54, 51)
ORANGE: Color = (240, 136, 20)
BLUE: Color = (9, 105, 218)
PURPLE: Color = (163, 113, 247)
YELLOW: Color = (210, 153, 34)
CYAN: Color = (0, 160, 170)
MAGENTA: Color = (219, 97, 162)
BROWN: Color = (154, 103, 60)
NAVY: Color = (23, 92, 184)
STEEL: Color = (133, 149, 166)

FUNCTION_COLORS: dict[str, Color] = {
    "gpio_out": GREEN,
    "gpio_in": BLUE,
    "pwm": PURPLE,
    "adc": YELLOW,
    "i2c": CYAN,
    "spi": MAGENTA,
    "uart": BROWN,
    "usb": NAVY,
    "other": STEEL,
}
STATUS_COLORS: dict[str, Color] = {
    "pass": GREEN,
    "fail": RED,
    "not_applicable": GREY,
}

LABEL_MAX = 40
SCALE = 2


def _clip(label: str) -> str:
    return label if len(label) <= LABEL_MAX else label[: LABEL_MAX - 3] + "..."


def _glyph(ch: str) -> bytes:
    code = ord(ch)
    if not 0x20 <= code <= 0x7E:
        code = ord("?")
    start = (code - 0x20) * GLYPH_W
    return _FONT[start : start + GLYPH_W]


def text_width(text: str, scale: int = SCALE) -> int:
    return len(text) * CHAR_ADVANCE * scale


@dataclass
class Canvas:
    """In-memory RGB8 canvas."""

    width: int
    height: int
    background: Color = WHITE

    def __post_init__(self) -> None:
        r, g, b = self.background
        self._rows = [bytearray([r, g, b]) * self.width for _ in range(self.height)]

    def pixel(self, x: int, y: int, color: Color) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            row = self._rows[y]
            row[3 * x : 3 * x + 3] = bytes(color)

    def rect(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        fill: Color | None,
        outline: Color | None = None,
    ) -> None:
        if fill is not None:
            for yy in range(max(0, y), min(self.height, y + h)):
                row = self._rows[yy]
                for xx in range(max(0, x), min(self.width, x + w)):
                    row[3 * xx : 3 * xx + 3] = bytes(fill)
        if outline is not None:
            for xx in range(x, x + w):
                self.pixel(xx, y, outline)
                self.pixel(xx, y + h - 1, outline)
            for yy in range(y, y + h):
                self.pixel(x, yy, outline)
                self.pixel(x + w - 1, yy, outline)

    def line(self, x0: int, y0: int, x1: int, y1: int, color: Color, width: int = 1) -> None:
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        x, y = x0, y0
        while True:
            for ox in range(width):
                for oy in range(width):
                    self.pixel(x + ox, y + oy, color)
            if x == x1 and y == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x += sx
            if e2 <= dx:
                err += dx
                y += sy

    def text(self, x: int, y: int, text: str, color: Color, scale: int = SCALE) -> None:
        cursor = x
        for ch in text:
            glyph = _glyph(ch)
            for col in range(GLYPH_W):
                bits = glyph[col]
                for row in range(GLYPH_H):
                    if bits >> row & 1:
                        self.rect(
                            cursor + col * scale,
                            y + row * scale,
                            scale,
                            scale,
                            color,
                        )
            cursor += CHAR_ADVANCE * scale

    def to_png(self) -> bytes:
        raw = b"".join(b"\x00" + bytes(row) for row in self._rows)

        def chunk(tag: bytes, body: bytes) -> bytes:
            return (
                struct.pack(">I", len(body))
                + tag
                + body
                + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)
            )

        ihdr = struct.pack(">IIBBBBB", self.width, self.height, 8, 2, 0, 0, 0)
        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b"")
        )


def _check_mark(canvas: Canvas, x: int, y: int, size: int, color: Color) -> None:
    canvas.line(x, y + size // 2, x + size // 3, y + size, color, 2)
    canvas.line(x + size // 3, y + size, x + size, y, color, 2)


def _hatch(canvas: Canvas, x: int, y: int, w: int, h: int, color: Color) -> None:
    for offset in range(-h, w + h, 5):
        canvas.line(x + offset, y + h - 1, x + offset + h, y, color)


def _function_class(function: str) -> str:
    if function in ("gpio_out", "gpio_in", "pwm", "adc"):
        return function
    kind = FUNCTION_ROLE.get(function, ("other", ""))[0]
    return kind if kind in FUNCTION_COLORS else "other"


# ---------------------------------------------------------------------------
# Pin map


def render_pinmap(contract: FirmwareContract, profile: McuProfile, contract_sha256: str) -> bytes:
    """Chip-centred pin map: every profile pad on the four sides, labels outward."""
    by_pad: dict[str, object] = {}
    for pin in contract.pins:
        pad = profile.pad(pin.pad)
        if pad is not None:
            by_pad[pad.name] = pin

    def label_of(pad_name: str) -> str:
        pad = profile.pad(pad_name)
        assert pad is not None
        pin = by_pad.get(pad_name)
        if pin is None:
            if pad.reserved is not None:
                return _clip(f"{pad.name} reserved:{pad.reserved}")
            return _clip(pad.name)
        return _clip(f"{pad.name} {pin.signal} {pin.function} {pin.net}")  # type: ignore[union-attr]

    pads = [pad.name for pad in profile.pads]
    count = len(pads)
    left_n = right_n = (count + 3) // 4
    top_n = (count - left_n - right_n + 1) // 2
    bottom_n = count - left_n - right_n - top_n
    top_pads = pads[:top_n]
    right_pads = pads[top_n : top_n + right_n]
    bottom_pads = list(reversed(pads[top_n + right_n : top_n + right_n + bottom_n]))
    left_pads = list(reversed(pads[top_n + right_n + bottom_n :]))

    labels = {name: label_of(name) for name in pads}
    row_h = 7 * SCALE + 4
    col_w_min = 6 * SCALE + 8
    chip_w = max(360, max(top_n, bottom_n) * col_w_min)
    chip_h = max(120, max(left_n, right_n) * row_h)
    top_spacing = chip_w / max(top_n, 1)
    bottom_spacing = chip_w / max(bottom_n, 1)
    top_label_max = max((text_width(labels[p]) for p in top_pads), default=0)
    bottom_label_max = max((text_width(labels[p]) for p in bottom_pads), default=0)
    top_lanes = int(top_label_max / top_spacing) + 1 if top_pads else 0
    bottom_lanes = int(bottom_label_max / bottom_spacing) + 1 if bottom_pads else 0

    margin = 12
    title = f"{contract.name} pin map  contract sha256 {contract_sha256[:12]}"
    chip_label = f"{contract.mcu.ref} {profile.part} {profile.package}"
    title_h = 7 * SCALE + 10
    top_margin = title_h + margin + top_lanes * (row_h + 2) + 8
    bottom_margin = margin + bottom_lanes * (row_h + 2) + 8
    legend_h = (len(FUNCTION_COLORS) + 3) * row_h + margin
    left_margin = margin + max((text_width(labels[p]) for p in left_pads), default=0) + 26
    right_margin = margin + max((text_width(labels[p]) for p in right_pads), default=0) + 26

    width = left_margin + chip_w + right_margin
    height = top_margin + chip_h + bottom_margin + legend_h
    canvas = Canvas(width, height, WHITE)
    canvas.text(margin, margin, title, BLACK)

    box_x, box_y = left_margin, top_margin
    canvas.rect(box_x, box_y, chip_w, chip_h, (245, 246, 248), outline=BLACK)
    canvas.text(
        box_x + (chip_w - text_width(chip_label)) // 2,
        box_y + chip_h // 2 - 7,
        chip_label,
        BLACK,
    )

    def pad_fill(name: str) -> Color:
        pad = profile.pad(name)
        assert pad is not None
        if pad.reserved is not None:
            return DARK_GREY
        pin = by_pad.get(name)
        if pin is None:
            return GREY
        return FUNCTION_COLORS[_function_class(pin.function)]  # type: ignore[union-attr]

    def draw_pad(name: str, tick: tuple[int, int, int, int], label_xy: tuple[int, int]) -> None:
        pad = profile.pad(name)
        assert pad is not None
        pin = by_pad.get(name)
        fill = pad_fill(name)
        tx, ty, tw, th = tick
        canvas.rect(tx, ty, tw, th, fill, outline=BLACK)
        if pad.reserved is not None:
            _hatch(canvas, tx, ty, tw, th, BLACK)
        lx, ly = label_xy
        caution = pad.caution is not None
        acknowledged = bool(
            pin is not None and pad.caution is not None and pad.caution in pin.acknowledge  # type: ignore[union-attr]
        )
        canvas.text(lx, ly, labels[name], RED if caution and not acknowledged else BLACK)
        if caution:
            bx = tx - 12 if lx < tx else tx + tw + 4
            canvas.rect(bx, ty, 8, th, None, outline=ORANGE)
            if acknowledged:
                _check_mark(canvas, bx + 1, ty + 2, 6, GREEN)
            else:
                canvas.text(bx + 2, ty - 1, "!", RED, scale=1)
        if pad.reserved is not None:
            pass  # hatch already drawn

    tick = 10
    for i, name in enumerate(left_pads):
        y = box_y + round((i + 0.5) * chip_h / left_n)
        draw_pad(
            name,
            (box_x - tick, y - 4, tick, 8),
            (box_x - tick - 6 - text_width(labels[name]), y - 7),
        )
    for i, name in enumerate(right_pads):
        y = box_y + round((i + 0.5) * chip_h / right_n)
        draw_pad(name, (box_x + chip_w, y - 4, tick, 8), (box_x + chip_w + tick + 6, y - 7))
    for i, name in enumerate(top_pads):
        x = box_x + round((i + 0.5) * top_spacing)
        lane = i % top_lanes
        ly = box_y - tick - 8 - (top_lanes - 1 - lane) * (row_h + 2) - 7
        lx = max(margin, x - text_width(labels[name]))
        canvas.line(x, box_y - tick - 4 - (top_lanes - 1 - lane) * (row_h + 2), x, box_y, STEEL)
        draw_pad(name, (x - 4, box_y - tick, 8, tick), (lx, ly))
    for i, name in enumerate(bottom_pads):
        x = box_x + round((i + 0.5) * bottom_spacing)
        lane = i % bottom_lanes
        ly = box_y + chip_h + tick + 8 + lane * (row_h + 2) - 7
        lx = max(margin, x - text_width(labels[name]))
        canvas.line(x, box_y + chip_h, x, box_y + chip_h + tick + 4 + lane * (row_h + 2), STEEL)
        draw_pad(name, (x - 4, box_y + chip_h, 8, tick), (lx, ly))

    legend_y = box_y + chip_h + bottom_margin
    canvas.text(margin, legend_y, "legend:", BLACK)
    lx = margin + text_width("legend: ")
    ly = legend_y
    for name, color in FUNCTION_COLORS.items():
        canvas.rect(lx, ly + 3, 10, 10, color, outline=BLACK)
        canvas.text(lx + 14, ly, name, BLACK)
        lx += 14 + text_width(name) + 18
        if lx > width - 140:
            lx = margin
            ly += row_h
    canvas.text(
        margin, ly + row_h, "grey = unused  hatched = reserved  orange box = caution pad", BLACK
    )
    canvas.text(
        margin,
        ly + 2 * row_h,
        "red label = caution pad not acknowledged in the contract",
        BLACK,
    )
    return canvas.to_png()


# ---------------------------------------------------------------------------
# Gate report


def _bar(
    canvas: Canvas,
    x: int,
    y: int,
    w: int,
    h: int,
    fraction: float,
    fill: Color,
    markers: list[tuple[float, Color]],
) -> None:
    canvas.rect(x, y, w, h, (235, 237, 240), outline=BLACK)
    used = min(w, max(0, round(w * fraction)))
    if used:
        canvas.rect(x, y, used, h, fill)
    for frac, color in markers:
        mx = x + min(w, max(0, round(w * frac)))
        canvas.line(mx, y - 3, mx, y + h + 2, color, 2)


def render_report(report: object, contract: FirmwareContract) -> bytes:
    """Gate matrix + memory/power budget bars for a GateReport."""
    from .gates import GateReport  # local import: render must not load gates eagerly

    rep = report if isinstance(report, GateReport) else GateReport.model_validate(report)
    scale = SCALE
    row_h = 7 * scale + 6
    margin = 12
    check_rows = [
        f"{c.id}  {c.status}  {_clip((c.detail or '; '.join(c.evidence))[:80])}" for c in rep.checks
    ]
    detail_w = max((text_width(row) for row in check_rows), default=400)
    bar_w = 420
    width = max(margin * 2 + detail_w, margin * 2 + 560 + bar_w)
    metrics = rep.metrics

    has_memory = "flash_bytes" in metrics
    power_modes = contract.power.modes
    height = margin + row_h + len(rep.checks) * row_h + margin
    if has_memory:
        height += 3 * (row_h + 14) + margin
    else:
        height += row_h + margin
    height += (len(power_modes) + 2) * (row_h + 6) + margin + row_h
    canvas = Canvas(width, height, WHITE)
    canvas.text(
        margin, margin, f"{rep.design} gate report ({rep.scope}) verdict={rep.verdict}", BLACK
    )
    y = margin + row_h + 4
    for check, row in zip(rep.checks, check_rows, strict=True):
        canvas.rect(margin, y, 12, row_h - 6, STATUS_COLORS[check.status], outline=BLACK)
        canvas.text(margin + 18, y, row, BLACK)
        y += row_h
    y += margin

    if has_memory:
        flash_cap = metrics.get("flash_capacity_bytes", 0)
        ram_cap = metrics.get("ram_capacity_bytes", 0)
        for label, used_key, cap_key, budget_key in (
            ("flash", "flash_bytes", "flash_capacity_bytes", "flash_budget_bytes"),
            ("ram", "ram_bytes", "ram_capacity_bytes", "ram_budget_bytes"),
        ):
            used = metrics.get(used_key, 0.0)
            cap = metrics.get(cap_key, 0.0) or 1.0
            budget = metrics.get(budget_key)
            canvas.text(
                margin,
                y,
                f"{label}: {int(used)} B / {int(cap)} B",
                BLACK,
            )
            markers = [] if budget is None else [(budget / cap, ORANGE)]
            _bar(canvas, margin + 260, y, bar_w, 12, used / cap, BLUE, markers)
            canvas.text(margin + 260 + bar_w + 10, y, "orange=budget", DARK_GREY, scale=1)
            y += row_h + 14
        canvas.text(
            margin,
            y,
            f"capacity: flash {int(flash_cap)} B, ram {int(ram_cap)} B",
            DARK_GREY,
            scale=1,
        )
        y += row_h
    else:
        canvas.text(margin, y, "no ELF metrics (static scope)", DARK_GREY)
        y += row_h
    y += margin

    canvas.text(margin, y, "power modes (log10 uA):", BLACK)
    y += row_h + 4
    currents = [m.current_ua for m in power_modes]
    budget_ua = contract.power.average_budget_ua
    if budget_ua is not None:
        currents.append(budget_ua)
    log_max = max(math.log10(max(c, 1.0)) for c in currents) or 1.0
    for mode in power_modes:
        frac = math.log10(max(mode.current_ua, 1.0)) / log_max
        canvas.text(
            margin,
            y,
            f"{mode.id} {mode.kind} {mode.current_ua:.1f}uA duty={mode.duty:.2f}",
            BLACK,
        )
        _bar(canvas, margin + 300, y, bar_w, 12, frac, PURPLE, [])
        y += row_h + 6
    average = sum(m.current_ua * m.duty for m in power_modes)
    markers: list[tuple[float, Color]] = []
    if budget_ua is not None:
        markers.append((math.log10(max(budget_ua, 1.0)) / log_max, ORANGE))
    canvas.text(
        margin,
        y,
        f"average {average:.1f}uA"
        + (f" budget {float(budget_ua):.1f}uA" if budget_ua is not None else ""),
        BLACK,
    )
    _bar(
        canvas, margin + 300, y, bar_w, 12, math.log10(max(average, 1.0)) / log_max, GREEN, markers
    )
    return canvas.to_png()


# ---------------------------------------------------------------------------
# Simulation timeline


def _match_indices(lines: list[str], expect: list[str]) -> list[int | None]:
    """Line index where each ``expect`` entry matched, in order (sim._progress semantics)."""
    indices: list[int | None] = []
    cursor = 0
    for wanted in expect:
        found: int | None = None
        for index in range(cursor, len(lines)):
            if wanted in lines[index]:
                found = index
                cursor = index + 1
                break
        indices.append(found)
    return indices


def render_sim_timeline(
    sim: Simulation, transcript_lines: list[str], result: SimResult | None
) -> bytes:
    """Serial/QEMU output plot: expect markers in order, forbid hits, footer."""
    lines = transcript_lines
    matched_at = _match_indices(lines, sim.expect)
    forbidden_at = {
        needle: [i for i, line in enumerate(lines) if needle in line] for needle in sim.forbid
    }
    margin = 12
    row_h = 7 * SCALE + 8
    label_w = max((text_width(_clip(e)) for e in [*sim.expect, *sim.forbid]), default=200)
    plot_w = 640
    width = margin * 2 + label_w + 24 + plot_w + 140
    rows = len(sim.expect) + len(sim.forbid)
    height = margin * 2 + row_h + rows * row_h + row_h + row_h
    canvas = Canvas(width, height, WHITE)
    canvas.text(margin, margin, f"sim {sim.id}: {sim.runner} {sim.machine} transcript", BLACK)

    x0 = margin + label_w + 24
    n = max(len(lines), 1)
    dx = plot_w / n

    def x_of(index: float) -> int:
        return x0 + round(index * dx)

    y = margin + row_h + 6
    for wanted, at in zip(sim.expect, matched_at, strict=True):
        canvas.text(margin, y, _clip(wanted), BLACK)
        canvas.rect(x0, y, plot_w, row_h - 8, (245, 246, 248), outline=GREY)
        if at is None:
            canvas.rect(x0 + plot_w - 8, y + 1, 8, row_h - 10, RED)
            canvas.text(x0 + plot_w + 12, y, "MISSING", RED)
        else:
            canvas.rect(x_of(at), y + 1, 6, row_h - 10, GREEN)
            canvas.text(x0 + plot_w + 12, y, f"line {at}", DARK_GREY)
        y += row_h
    for needle, hits in forbidden_at.items():
        canvas.text(margin, y, _clip(needle), BLACK)
        canvas.rect(x0, y, plot_w, row_h - 8, (245, 246, 248), outline=GREY)
        for index in hits:
            canvas.rect(x_of(index), y + 1, 6, row_h - 10, RED)
        canvas.text(x0 + plot_w + 12, y, f"forbid x{len(hits)}", RED if hits else DARK_GREY)
        y += row_h

    if result is not None:
        actual = result.exit_code
        seconds = f"{result.seconds:.1f}s"
        verdict = "pass" if result.ok else "fail"
    else:
        actual = None
        seconds = "n/a"
        verdict = (
            "pass"
            if all(at is not None for at in matched_at) and not any(forbidden_at.values())
            else "fail"
        )
    canvas.text(
        margin,
        y + 6,
        f"runner={sim.runner} machine={sim.machine} fidelity={sim.fidelity} "
        f"exit_code expected={sim.exit_code} actual={actual} seconds={seconds} verdict={verdict}",
        BLACK,
    )
    return canvas.to_png()
