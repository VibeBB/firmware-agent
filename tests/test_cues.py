from __future__ import annotations

import hashlib
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from firmware import service
from firmware.gates import GateReport, run_gates
from firmware.interchange import load_cue_manifest

from .conftest import read_json, write_json

type Mutation = Callable[[dict[str, Any]], None]


def _check(contract: Path) -> tuple[str, str]:
    report: GateReport = run_gates(contract, contract.parent / "fw-reports", full=False)
    check = next(c for c in report.checks if c.id == "fw.bard_cues")
    return check.status, check.detail


def _manifest(contract: Path) -> Path:
    return contract.parent / "bard" / "cues.json"


def _repin(contract: Path) -> None:
    data = read_json(contract)
    data["cues"]["sha256"] = hashlib.sha256(_manifest(contract).read_bytes()).hexdigest()
    write_json(contract, data)


def _edit_manifest(contract: Path, mutate: Mutation) -> None:
    data = read_json(_manifest(contract))
    mutate(data)
    write_json(_manifest(contract), data)
    _repin(contract)


def test_example_cues_pass(kettle: Path) -> None:
    assert _check(kettle) == ("pass", "")


def test_contract_without_cues_has_no_cue_gate(lamp: Path) -> None:
    report = run_gates(lamp, lamp.parent / "fw-reports", full=False)
    assert "fw.bard_cues" not in {c.id for c in report.checks}


def test_changed_manifest_without_repin_fails(kettle: Path) -> None:
    data = read_json(_manifest(kettle))
    data["product"] = "kettle-two"
    write_json(_manifest(kettle), data)
    status, detail = _check(kettle)
    assert status == "fail"
    assert "differs from pinned" in detail
    payload = service.cues_payload(kettle)
    assert payload["verdict"] == "fail"


def test_missing_manifest_fails_closed(kettle: Path) -> None:
    _manifest(kettle).unlink()
    status, detail = _check(kettle)
    assert status == "fail"
    assert "unreadable bard cue manifest" in detail


def test_foreign_artifact_kind_fails_closed(kettle: Path) -> None:
    _edit_manifest(kettle, lambda d: d.update(artifact_kind="bard_cue_set"))
    assert _check(kettle)[0] == "fail"


def _set_band(lo: float, hi: float) -> Mutation:
    def mutate(d: dict[str, Any]) -> None:
        d["cues"]["min_hz"] = lo
        d["cues"]["max_hz"] = hi

    return mutate


def _highest(contract: Path) -> float:
    manifest = load_cue_manifest(_manifest(contract))
    return max(t.freq_hz for c in manifest.cues for t in c.tones)


@pytest.mark.parametrize(("delta", "status"), [(-0.01, "fail"), (0.0, "pass"), (0.01, "pass")])
def test_band_upper_edge(kettle: Path, delta: float, status: str) -> None:
    top = _highest(kettle)
    data = read_json(kettle)
    _set_band(100.0, round(top + delta, 2))(data)
    write_json(kettle, data)
    service.cues_payload(kettle)
    assert _check(kettle)[0] == status


@pytest.mark.parametrize(("delta", "status"), [(-0.01, "pass"), (0.0, "pass"), (0.01, "fail")])
def test_band_lower_edge(kettle: Path, delta: float, status: str) -> None:
    manifest = load_cue_manifest(_manifest(kettle))
    low = min(t.freq_hz for c in manifest.cues for t in c.tones if t.freq_hz > 0)
    data = read_json(kettle)
    _set_band(round(low + delta, 2), 20000.0)(data)
    write_json(kettle, data)
    service.cues_payload(kettle)
    assert _check(kettle)[0] == status


def test_inverted_band_is_rejected(kettle: Path) -> None:
    data = read_json(kettle)
    _set_band(5000.0, 500.0)(data)
    write_json(kettle, data)
    report = run_gates(kettle, kettle.parent / "fw-reports", full=False)
    assert report.verdict == "fail"
    assert "min_hz must be below max_hz" in report.checks[0].detail


@pytest.mark.parametrize(
    ("pin", "detail"),
    [("nonexistent", "is not declared"), ("heater_en", "must be a pwm pin")],
)
def test_cue_pin_must_be_declared_pwm(kettle: Path, pin: str, detail: str) -> None:
    data = read_json(kettle)
    data["cues"]["pin"] = pin
    write_json(kettle, data)
    service.cues_payload(kettle)
    status, text = _check(kettle)
    assert status == "fail"
    assert detail in text


def _gap(d: dict[str, Any]) -> None:
    d["cues"][0]["tones"][1]["start_ms"] += 1


def _short(d: dict[str, Any]) -> None:
    d["cues"][0]["duration_ms"] += 1


def _rest_with_pitch(d: dict[str, Any]) -> None:
    d["cues"][0]["tones"][0]["midi"] = None


def _confirm_loops(d: dict[str, Any]) -> None:
    next(c for c in d["cues"] if c["purpose"] == "confirm")["loop"] = True


@pytest.mark.parametrize(
    ("mutate", "detail"),
    [
        (_gap, "gap or overlap"),
        (_short, "tones last"),
        (_rest_with_pitch, "mixes rest and pitch"),
        (_confirm_loops, "only warning/error cues may loop"),
    ],
)
def test_corrupted_manifest_fails(kettle: Path, mutate: Mutation, detail: str) -> None:
    _edit_manifest(kettle, mutate)
    service.cues_payload(kettle)
    status, text = _check(kettle)
    assert status == "fail"
    assert detail in text


def test_missing_and_stale_header(kettle: Path) -> None:
    header = kettle.parent / "fw" / "include" / "fw_cues.h"
    header.write_text(header.read_text(encoding="utf-8") + "/* edit */\n", encoding="utf-8")
    assert "stale" in _check(kettle)[1]
    header.unlink()
    assert "missing" in _check(kettle)[1]
    assert service.cues_payload(kettle)["verdict"] == "pass"
    assert _check(kettle) == ("pass", "")


def test_regenerated_header_is_byte_identical(kettle: Path) -> None:
    header = kettle.parent / "fw" / "include" / "fw_cues.h"
    before = header.read_bytes()
    service.cues_payload(kettle)
    assert header.read_bytes() == before


def _expected_centihz(contract: Path, cue_index: int, elapsed_ms: int) -> int:
    cue = load_cue_manifest(_manifest(contract)).cues[cue_index]
    if elapsed_ms >= cue.duration_ms:
        if not cue.loop:
            return 0
        elapsed_ms %= cue.duration_ms
    for tone in cue.tones:
        if elapsed_ms < tone.duration_ms:
            return round(tone.freq_hz * 100)
        elapsed_ms -= tone.duration_ms
    return 0


@pytest.mark.skipif(shutil.which("cc") is None, reason="needs a host C compiler")
def test_header_player_matches_manifest(kettle: Path, tmp_path: Path) -> None:
    """Compile the generated header and sample every cue across each tone edge."""
    manifest = load_cue_manifest(_manifest(kettle))
    samples: list[tuple[int, int]] = []
    for index, cue in enumerate(manifest.cues):
        edges = {0, cue.duration_ms - 1, cue.duration_ms, 2 * cue.duration_ms + 7}
        for tone in cue.tones:
            end = tone.start_ms + tone.duration_ms
            edges |= {tone.start_ms, max(0, end - 1), end}
        samples += [(index, t) for t in sorted(edges)]
    samples.append((len(manifest.cues), 0))
    program = tmp_path / "player.c"
    calls = "\n".join(
        f'    printf("%lu\\n", (unsigned long)fw_cue_centihz_at({c}u, {t}u));' for c, t in samples
    )
    program.write_text(
        '#include <stdio.h>\n#define FW_PIN_BUZZER 16\n#include "fw_cues.h"\n'
        f"int main(void)\n{{\n{calls}\n    return FW_CUES_PIN == 16 ? 0 : 1;\n}}\n",
        encoding="utf-8",
    )
    binary = tmp_path / "player"
    include = kettle.parent / "fw" / "include"
    subprocess.run(
        [
            "cc",
            "-std=c99",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(include),
            str(program),
            "-o",
            str(binary),
        ],
        check=True,
    )
    result = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
    got = [int(line) for line in result.stdout.split()]
    expected = [
        _expected_centihz(kettle, c, t) if c < len(manifest.cues) else 0 for c, t in samples
    ]
    assert got == expected
