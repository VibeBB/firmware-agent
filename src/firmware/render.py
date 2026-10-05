"""Stdlib-only PNG renders of firmware projections (zlib + struct, no deps).

The launcher mounts the source tree into the published ``firmware-tools``
image, so this module must run on the image's bare interpreter: it draws
onto an RGB canvas and encodes PNG by hand (8-bit RGB, filter 0, one zlib
IDAT at level 9). Output is byte-deterministic for equal input.

Renders:

* :func:`render_pinmap` — DIP-style pin map from the contract + MCU profile,
* :func:`render_report` — gate matrix, memory and power budget bars,
* :func:`render_sim_timeline` — serial/QEMU transcript timeline,
* :func:`render_glyph_sheet` — the full 5x7 font for visual review.

Renders are advisory vision inputs; a failure here never changes a gate
verdict.
"""

from __future__ import annotations

import math
import struct
import zlib
from dataclasses import dataclass, field

from .contract import FUNCTION_ROLE, FirmwareContract, Pin, Simulation
from .profiles import McuProfile
from .sim import SimResult

# ---------------------------------------------------------------------------
# 5x7 bitmap font, printable ASCII 0x20-0x7E. Each glyph is authored here as
# seven rows of five "#"/"." pixels so every shape is reviewable in source.
# Unknown characters render as '?'.
GLYPH_W = 5
GLYPH_H = 7
CHAR_ADVANCE = GLYPH_W + 1

FONT_ROWS: dict[str, tuple[str, ...]] = {
    " ": (".....", ".....", ".....", ".....", ".....", ".....", "....."),
    "!": ("..#..", "..#..", "..#..", "..#..", "..#..", ".....", "..#.."),
    '"': (".#.#.", ".#.#.", ".#.#.", ".....", ".....", ".....", "....."),
    "#": (".#.#.", ".#.#.", "#####", ".#.#.", "#####", ".#.#.", ".#.#."),
    "$": ("..#..", ".####", "#.#..", ".###.", "..#.#", "####.", "..#.."),
    "%": ("##...", "##..#", "...#.", "..#..", ".#...", "#..##", "...##"),
    "&": (".#...", "#.#..", "#.#..", ".#...", "#.#.#", "#..#.", ".##.#"),
    "'": ("..##.", "..##.", "..#..", ".#...", ".....", ".....", "....."),
    "(": ("...#.", "..#..", ".#...", ".#...", ".#...", "..#..", "...#."),
    ")": (".#...", "..#..", "...#.", "...#.", "...#.", "..#..", ".#..."),
    "*": ("..#..", "#.#.#", ".###.", "#####", ".###.", "#.#.#", "..#.."),
    "+": (".....", "..#..", "..#..", "#####", "..#..", "..#..", "....."),
    ",": (".....", ".....", ".....", ".....", ".....", "..##.", "..#.."),
    "-": (".....", ".....", ".....", ".###.", ".....", ".....", "....."),
    ".": (".....", ".....", ".....", ".....", ".....", "..##.", "..##."),
    "/": (".....", "....#", "...#.", "..#..", ".#...", "#....", "....."),
    "0": (".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."),
    "1": ("..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "2": (".###.", "#...#", "....#", ".###.", "#....", "#....", "#####"),
    "3": ("#####", "....#", "...#.", "..##.", "....#", "#...#", ".###."),
    "4": ("...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."),
    "5": ("#####", "#....", "####.", "....#", "....#", "#...#", ".###."),
    "6": ("..###", ".#...", "#....", "####.", "#...#", "#...#", ".###."),
    "7": ("#####", "....#", "....#", "...#.", "..#..", ".#...", "#...."),
    "8": (".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."),
    "9": (".###.", "#...#", "#...#", ".####", "....#", "...#.", "###.."),
    ":": (".....", ".....", "..#..", ".....", "..#..", ".....", "....."),
    ";": (".....", ".....", "..#..", ".....", "..#..", "..#..", ".#..."),
    "<": ("....#", "...#.", "..#..", ".#...", "..#..", "...#.", "....#"),
    "=": (".....", ".....", "#####", ".....", "#####", ".....", "....."),
    ">": (".#...", "..#..", "...#.", "....#", "...#.", "..#..", ".#..."),
    "?": (".###.", "#...#", "....#", "..##.", "..#..", ".....", "..#.."),
    "@": (".###.", "#...#", "#.#.#", "#.###", "#.##.", "#....", ".####"),
    "A": ("..#..", ".#.#.", "#...#", "#...#", "#####", "#...#", "#...#"),
    "B": ("####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."),
    "C": (".###.", "#...#", "#....", "#....", "#....", "#...#", ".###."),
    "D": ("####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."),
    "E": ("#####", "#....", "#....", "####.", "#....", "#....", "#####"),
    "F": ("#####", "#....", "#....", "####.", "#....", "#....", "#...."),
    "G": (".####", "#...#", "#....", "#....", "#..##", "#...#", ".####"),
    "H": ("#...#", "#...#", "#####", "#...#", "#...#", "#...#", "#...#"),
    "I": (".###.", "..#..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "J": ("..###", "...#.", "...#.", "...#.", "...#.", "#..#.", ".##.."),
    "K": ("#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"),
    "L": ("#....", "#....", "#....", "#....", "#....", "#....", "#####"),
    "M": ("#...#", "##.##", "#.#.#", "#.#.#", "#.#.#", "#...#", "#...#"),
    "N": ("#...#", "#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#"),
    "O": (".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "P": ("####.", "#...#", "#...#", "####.", "#....", "#....", "#...."),
    "Q": (".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".##.#"),
    "R": ("####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"),
    "S": (".###.", "#...#", "#....", ".###.", "....#", "#...#", ".###."),
    "T": ("#####", "#.#.#", "..#..", "..#..", "..#..", "..#..", "..#.."),
    "U": ("#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "V": ("#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."),
    "W": ("#...#", "#...#", "#.#.#", "#.#.#", "#.#.#", "#.#.#", ".#.#."),
    "X": ("#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"),
    "Y": ("#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."),
    "Z": ("#####", "....#", "...#.", ".###.", ".#...", "#....", "#####"),
    "[": (".####", ".#...", ".#...", ".#...", ".#...", ".#...", ".####"),
    "\\": (".....", "#....", ".#...", "..#..", "...#.", "....#", "....."),
    "]": (".####", "....#", "....#", "....#", "....#", "....#", ".####"),
    "^": ("..#..", ".#.#.", "#...#", ".....", ".....", ".....", "....."),
    "_": (".....", ".....", ".....", ".....", ".....", ".....", ".###."),
    "`": (".##..", ".##..", "..#..", "...#.", ".....", ".....", "....."),
    "a": (".....", ".....", ".##..", "...#.", ".###.", "#..#.", ".####"),
    "b": ("#....", "#....", "#.##.", "##..#", "#...#", "##..#", "#.##."),
    "c": (".....", ".....", ".###.", "#...#", "#....", "#...#", ".###."),
    "d": ("....#", "....#", ".##.#", "#..##", "#...#", "#..##", ".##.#"),
    "e": (".....", ".....", ".###.", "#...#", "#####", "#....", ".###."),
    "f": ("...#.", "..#.#", "..#..", ".###.", "..#..", "..#..", "..#.."),
    "g": (".....", ".....", ".###.", "#..##", "#..##", ".##.#", "....#"),
    "h": ("#....", "#....", "#.##.", "##..#", "#...#", "#...#", "#...#"),
    "i": ("..#..", ".....", ".##..", "..#..", "..#..", "..#..", ".###."),
    "j": ("...#.", ".....", "...#.", "...#.", "...#.", "#..#.", ".##.."),
    "k": ("#....", "#....", "#..#.", "#.#..", "##...", "#.#..", "#..#."),
    "l": (".##..", "..#..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "m": (".....", ".....", "##.#.", "#.#.#", "#.#.#", "#.#.#", "#.#.#"),
    "n": (".....", ".....", "#.##.", "##..#", "#...#", "#...#", "#...#"),
    "o": (".....", ".....", ".###.", "#...#", "#...#", "#...#", ".###."),
    "p": (".....", ".....", "#.##.", "##..#", "##..#", "#.##.", "#...."),
    "q": (".....", ".....", ".##.#", "#..##", "#..##", ".##.#", "....#"),
    "r": (".....", ".....", "#.##.", "##..#", "#....", "#....", "#...."),
    "s": (".....", ".....", ".####", "#....", ".###.", "....#", "####."),
    "t": ("..#..", "..#..", "#####", "..#..", "..#..", "..#.#", "...#."),
    "u": (".....", ".....", "#...#", "#...#", "#...#", "#..##", ".##.#"),
    "v": (".....", ".....", "#...#", "#...#", "#...#", ".#.#.", "..#.."),
    "w": (".....", ".....", "#...#", "#.#.#", "#.#.#", "#.#.#", ".#.#."),
    "x": (".....", ".....", "#...#", ".#.#.", "..#..", ".#.#.", "#...#"),
    "y": (".....", ".....", "#...#", "#...#", ".####", "....#", "#...#"),
    "z": (".....", ".....", "#####", "...#.", "..#..", ".#...", "#####"),
    "{": ("...#.", "..#..", "..#..", ".#...", "..#..", "..#..", "...#."),
    "|": ("..#..", "..#..", "..#..", ".....", "..#..", "..#..", "..#.."),
    "}": (".#...", "..#..", "..#..", "...#.", "..#..", "..#..", ".#..."),
    "~": (".#...", "#.#.#", "...#.", ".....", ".....", ".....", "....."),
}
assert len(FONT_ROWS) == 95 and len(set(FONT_ROWS)) == 95


def _glyph_columns(ch: str) -> tuple[int, ...]:
    """Five column bytes for ``ch`` (bit y set = pixel at row y)."""
    rows = FONT_ROWS.get(ch) or FONT_ROWS["?"]
    return tuple(sum((rows[y][x] == "#") << y for y in range(GLYPH_H)) for x in range(GLYPH_W))


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


def _clip(label: str, limit: int = LABEL_MAX) -> str:
    return label if len(label) <= limit else label[: limit - 3] + "..."


def text_width(text: str, scale: int = SCALE) -> int:
    return len(text) * CHAR_ADVANCE * scale


TextBox = tuple[int, int, int, int]


@dataclass
class Canvas:
    """In-memory RGB8 canvas; records every drawn text box for tests."""

    width: int
    height: int
    background: Color = WHITE
    text_boxes: list[TextBox] = field(default_factory=list[TextBox], init=False)

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
        self.text_boxes.append((x, y, x + text_width(text, scale), y + GLYPH_H * scale))
        cursor = x
        for ch in text:
            columns = _glyph_columns(ch)
            for col in range(GLYPH_W):
                bits = columns[col]
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


def _hatch(canvas: Canvas, x: int, y: int, w: int, h: int, color: Color) -> None:
    for offset in range(-h, w, 5):
        for step in range(h):
            px = x + offset + step
            if x <= px < x + w:
                canvas.pixel(px, y + h - 1 - step, color)


def _function_class(function: str) -> str:
    if function in ("gpio_out", "gpio_in", "pwm", "adc"):
        return function
    kind = FUNCTION_ROLE.get(function, ("other", ""))[0]
    return kind if kind in FUNCTION_COLORS else "other"


def _wrap(text: str, limit: int) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        if lines and len(lines[-1]) + 1 + len(word) <= limit:
            lines[-1] = f"{lines[-1]} {word}"
        else:
            lines.append(word[:limit])
    return lines or [""]


def render_glyph_sheet(columns: int = 16) -> bytes:
    """Every printable glyph at scale 3, one character per grid cell."""
    chars = sorted(FONT_ROWS)
    rows = math.ceil(len(chars) / columns)
    cell_w, cell_h = GLYPH_W * 3 + 12, GLYPH_H * 3 + 12
    canvas = Canvas(columns * cell_w, rows * cell_h, WHITE)
    for index, ch in enumerate(chars):
        cx = (index % columns) * cell_w
        cy = (index // columns) * cell_h
        canvas.rect(cx, cy, cell_w, cell_h, None, outline=GREY)
        canvas.text(cx + 6, cy + 6, ch, BLACK, scale=3)
    return canvas.to_png()


# ---------------------------------------------------------------------------
# Pin map — DIP-style: left and right pad columns, chip between, pin table below


def pinmap_canvas(contract: FirmwareContract, profile: McuProfile, contract_sha256: str) -> Canvas:
    """Build the pin-map canvas; text boxes are inspectable for tests."""
    by_pad: dict[str, Pin] = {}
    for pin in contract.pins:
        pad = profile.pad(pin.pad)
        if pad is not None:
            by_pad[pad.name] = pin
    pads = [pad.name for pad in profile.pads]
    half = (len(pads) + 1) // 2
    left_pads, right_pads = pads[:half], pads[half:]

    def label_of(name: str) -> str:
        pad = profile.pad(name)
        assert pad is not None
        pin = by_pad.get(name)
        if pad.reserved is not None:
            return _clip(f"{name} res:{pad.reserved}")
        if pin is None:
            return name
        return _clip(f"{name} {pin.signal}")

    def label_color(name: str) -> Color:
        pad = profile.pad(name)
        assert pad is not None
        pin = by_pad.get(name)
        if pin is not None:
            return FUNCTION_COLORS[_function_class(pin.function)]
        if pad.reserved is not None:
            return DARK_GREY
        return BLACK

    margin = 12
    row_h = GLYPH_H * SCALE + 6
    pin_w = 14  # pad square width on the chip edge
    caution_w = 14 + 24  # orange box + gap + 'ack'/'!'
    left_label_max = max((text_width(label_of(p)) for p in left_pads), default=0)
    right_label_max = max((text_width(label_of(p)) for p in right_pads), default=0)

    def _extra(names: list[str]) -> int:
        return (
            caution_w
            if any((pad := profile.pad(n)) is not None and pad.caution is not None for n in names)
            else 0
        )

    left_extra = _extra(left_pads)
    right_extra = _extra(right_pads)

    chip_lines = _wrap(f"{contract.mcu.ref} {profile.part} {profile.package}", 18)
    chip_w = max(96, max(text_width(line) for line in chip_lines) + 28)
    rows_n = max(len(left_pads), len(right_pads), 1)
    chip_h = rows_n * row_h + 10

    title = f"{contract.name} pin map  contract sha256 {contract_sha256[:12]}"
    table_rows: list[tuple[str, str | None, Color]] = []
    for pin in contract.pins:
        pad = profile.pad(pin.pad)
        base = (
            f"{pin.pad}  {pin.signal}  {pin.function}  {pin.net}  pull={pin.pull} act={pin.active}"
        )
        status: str | None = None
        color = BLACK
        if pad is not None and pad.caution is not None:
            acknowledged = pad.caution in pin.acknowledge
            status = f"caution:{pad.caution} {'ack' if acknowledged else '!'}"
            color = GREEN if acknowledged else RED
        table_rows.append((base, status, color))
    table_w = max(
        (text_width(base + ("  " + status if status else "")) for base, status, _ in table_rows),
        default=0,
    )
    header = "pins (used): pad  signal  function  net  pull/active  caution"
    legend = "grey = unused  hatched = reserved  orange box = caution (ack or !)"

    title_y = margin
    chip_y = margin + row_h + 4
    table_y = chip_y + chip_h + margin
    legend_y = table_y + row_h + len(table_rows) * row_h + margin
    height = legend_y + 3 * row_h + margin

    chip_x = margin + left_label_max + 6 + left_extra + pin_w
    right_edge = chip_x + chip_w + pin_w + right_extra + 6 + right_label_max
    width = max(
        right_edge + margin,
        margin * 2 + text_width(title),
        margin * 2 + text_width(header),
        margin * 2 + table_w,
        margin * 2 + text_width(legend),
    )

    canvas = Canvas(width, height, WHITE)
    canvas.text(margin, title_y, title, BLACK)
    canvas.rect(chip_x, chip_y, chip_w, chip_h, (245, 246, 248), outline=BLACK)
    label_y = chip_y + (chip_h - len(chip_lines) * (row_h - 2)) // 2
    for line in chip_lines:
        canvas.text(chip_x + (chip_w - text_width(line)) // 2, label_y, line, BLACK)
        label_y += row_h - 2

    def draw_pad(name: str, side: str, i: int, count: int) -> None:
        pad = profile.pad(name)
        assert pad is not None
        pin = by_pad.get(name)
        cy = chip_y + round((i + 0.5) * chip_h / count)
        fill = (
            FUNCTION_COLORS[_function_class(pin.function)]
            if pin is not None
            else (DARK_GREY if pad.reserved is not None else GREY)
        )
        label = label_of(name)
        caution = pad.caution is not None
        acknowledged = pin is not None and caution and pad.caution in pin.acknowledge
        if side == "left":
            sq_x = chip_x - pin_w
            label_x = chip_x - pin_w - 6 - (caution_w if caution else 0) - text_width(label)
            if caution:
                canvas.rect(sq_x - 12, cy - 5, 10, 10, None, outline=ORANGE)
                if acknowledged:
                    canvas.text(sq_x - 14 - 18, cy - 3, "ack", GREEN, scale=1)
                else:
                    canvas.text(sq_x - 10, cy - 3, "!", RED, scale=1)
        else:
            sq_x = chip_x + chip_w
            label_x = chip_x + chip_w + pin_w + 6 + (caution_w if caution else 0)
            if caution:
                canvas.rect(sq_x + pin_w + 2, cy - 5, 10, 10, None, outline=ORANGE)
                if acknowledged:
                    canvas.text(sq_x + pin_w + 16, cy - 3, "ack", GREEN, scale=1)
                else:
                    canvas.text(sq_x + pin_w + 4, cy - 3, "!", RED, scale=1)
        canvas.rect(sq_x, cy - 5, pin_w, 10, fill, outline=BLACK)
        if pad.reserved is not None:
            _hatch(canvas, sq_x, cy - 5, pin_w, 10, BLACK)
        canvas.text(label_x, cy - GLYPH_H * SCALE // 2, label, label_color(name))

    for i, name in enumerate(left_pads):
        draw_pad(name, "left", i, len(left_pads))
    for i, name in enumerate(right_pads):
        draw_pad(name, "right", i, len(right_pads))

    y = table_y
    canvas.text(margin, y, header, DARK_GREY)
    y += row_h
    for base, status, color in table_rows:
        canvas.text(margin, y, base, FUNCTION_COLORS[_function_class(base.split()[2])])
        if status:
            canvas.text(margin + text_width(base) + 12, y, status, color)
        y += row_h

    canvas.text(margin, legend_y, legend, DARK_GREY)
    lx = margin
    ly = legend_y + row_h
    for name, color in FUNCTION_COLORS.items():
        canvas.rect(lx, ly + 3, 10, 10, color, outline=BLACK)
        canvas.text(lx + 14, ly, name, BLACK)
        lx += 14 + text_width(name) + 18
        if lx > width - 140:
            lx = margin
            ly += row_h
    return canvas


def render_pinmap(contract: FirmwareContract, profile: McuProfile, contract_sha256: str) -> bytes:
    """DIP-style pin map: pads on both sides, used-pin table below."""
    return pinmap_canvas(contract, profile, contract_sha256).to_png()


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


def report_canvas(report: object, contract: FirmwareContract) -> Canvas:
    """Build the gate-report canvas; text boxes are inspectable for tests."""
    from .gates import GateReport  # local import: render must not load gates eagerly

    rep = report if isinstance(report, GateReport) else GateReport.model_validate(report)
    row_h = GLYPH_H * SCALE + 6
    margin = 12
    check_rows = [
        f"{c.id}  {c.status}  {_clip((c.detail or '; '.join(c.evidence))[:80])}" for c in rep.checks
    ]
    metrics = rep.metrics
    has_memory = "flash_bytes" in metrics
    power_modes = contract.power.modes
    budget_ua = contract.power.average_budget_ua

    memory_labels: list[str] = []
    if has_memory:
        for label, used_key, cap_key in (
            ("flash", "flash_bytes", "flash_capacity_bytes"),
            ("ram", "ram_bytes", "ram_capacity_bytes"),
        ):
            memory_labels.append(
                f"{label}: {int(metrics.get(used_key, 0.0))} B / {int(metrics.get(cap_key, 0.0))} B"
            )
    power_labels = [f"{m.id} {m.kind} {m.current_ua:.1f}uA duty={m.duty:.2f}" for m in power_modes]
    average = sum(m.current_ua * m.duty for m in power_modes)
    average_label = f"average {average:.1f}uA" + (
        f" budget {float(budget_ua):.1f}uA" if budget_ua is not None else ""
    )
    label_w = max(
        [text_width(text) for text in memory_labels + power_labels + [average_label]] or [0]
    )
    bar_w = 360
    bar_x = margin + label_w + 12

    title = f"{rep.design} gate report ({rep.scope}) verdict={rep.verdict}"
    tail_w = text_width("orange=budget", 1) + 10
    width = max(
        margin * 2 + max((text_width(r) for r in check_rows), default=0),
        margin * 2 + text_width(title),
        bar_x + bar_w + tail_w + margin,
    )

    y = margin + row_h + 4 + len(check_rows) * row_h + margin
    y += (3 * (row_h + 14) + margin) if has_memory else (row_h + margin)
    y += row_h + 4 + (len(power_modes) + 1) * (row_h + 6) + margin
    height = y
    canvas = Canvas(width, height, WHITE)
    canvas.text(margin, margin, title, BLACK)
    y = margin + row_h + 4
    for check, row in zip(rep.checks, check_rows, strict=True):
        canvas.rect(margin, y, 12, row_h - 6, STATUS_COLORS[check.status], outline=BLACK)
        canvas.text(margin + 18, y, row, BLACK)
        y += row_h
    y += margin

    if has_memory:
        flash_cap = metrics.get("flash_capacity_bytes", 0)
        ram_cap = metrics.get("ram_capacity_bytes", 0)
        for label_text, used_key, cap_key, budget_key in (
            ("flash", "flash_bytes", "flash_capacity_bytes", "flash_budget_bytes"),
            ("ram", "ram_bytes", "ram_capacity_bytes", "ram_budget_bytes"),
        ):
            used = metrics.get(used_key, 0.0)
            cap = metrics.get(cap_key, 0.0) or 1.0
            budget = metrics.get(budget_key)
            text = f"{label_text}: {int(used)} B / {int(cap)} B"
            canvas.text(margin, y, text, BLACK)
            markers = [] if budget is None else [(budget / cap, ORANGE)]
            _bar(canvas, bar_x, y, bar_w, 12, used / cap, BLUE, markers)
            canvas.text(bar_x + bar_w + 10, y + 2, "orange=budget", DARK_GREY, scale=1)
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
    if budget_ua is not None:
        currents.append(budget_ua)
    log_max = max(math.log10(max(c, 1.0)) for c in currents) or 1.0
    for mode, text in zip(power_modes, power_labels, strict=True):
        frac = math.log10(max(mode.current_ua, 1.0)) / log_max
        canvas.text(margin, y, text, BLACK)
        _bar(canvas, bar_x, y, bar_w, 12, frac, PURPLE, [])
        y += row_h + 6
    markers: list[tuple[float, Color]] = []
    if budget_ua is not None:
        markers.append((math.log10(max(budget_ua, 1.0)) / log_max, ORANGE))
    canvas.text(margin, y, average_label, BLACK)
    _bar(canvas, bar_x, y, bar_w, 12, math.log10(max(average, 1.0)) / log_max, GREEN, markers)
    return canvas


def render_report(report: object, contract: FirmwareContract) -> bytes:
    """Gate matrix + memory/power budget bars for a GateReport."""
    return report_canvas(report, contract).to_png()


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


def sim_timeline_canvas(
    sim: Simulation, transcript_lines: list[str], result: SimResult | None
) -> Canvas:
    """Build the sim-timeline canvas; text boxes are inspectable for tests."""
    lines = transcript_lines
    matched_at = _match_indices(lines, sim.expect)
    forbidden_at = {
        needle: [i for i, line in enumerate(lines) if needle in line] for needle in sim.forbid
    }
    margin = 12
    row_h = GLYPH_H * SCALE + 8
    label_w = max((text_width(_clip(e)) for e in [*sim.expect, *sim.forbid]), default=200)
    plot_w = 560
    right_texts = ["MISSING", f"line {len(lines)}", f"forbid x{len(lines)}"]
    right_w = max(text_width(t) for t in right_texts) + 12

    if result is not None:
        actual: str = str(result.exit_code) if result.exit_code is not None else "n/a"
        seconds = f"{result.seconds:.1f}s"
        verdict = "pass" if result.ok else "fail"
    else:
        actual = "n/a"
        seconds = "n/a"
        verdict = (
            "pass"
            if all(at is not None for at in matched_at) and not any(forbidden_at.values())
            else "fail"
        )
    footer = (
        f"runner={sim.runner} machine={sim.machine} fidelity={sim.fidelity} "
        f"exit_code expected={sim.exit_code if sim.exit_code is not None else 'n/a'} "
        f"actual={actual} seconds={seconds} verdict={verdict}"
    )
    title = f"sim {sim.id}: {sim.runner} {sim.machine} transcript"

    x0 = margin + label_w + 24
    rows = len(sim.expect) + len(sim.forbid)
    height = margin * 2 + row_h + rows * row_h + row_h + row_h + margin
    width = max(
        margin * 2 + text_width(title),
        margin * 2 + text_width(footer),
        x0 + plot_w + right_w + margin,
    )
    canvas = Canvas(width, height, WHITE)
    canvas.text(margin, margin, title, BLACK)

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

    canvas.text(margin, y + 6, footer, BLACK)
    return canvas


def render_sim_timeline(
    sim: Simulation, transcript_lines: list[str], result: SimResult | None
) -> bytes:
    """Serial/QEMU output plot: expect markers in order, forbid hits, footer."""
    return sim_timeline_canvas(sim, transcript_lines, result).to_png()
