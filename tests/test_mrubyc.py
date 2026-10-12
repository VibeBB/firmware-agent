"""mruby/c capability: contract validation, generation, and the static gate."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from firmware.contract import FirmwareContract
from firmware.mrubyc import (
    HAL_BACKENDS,
    MANIFEST_NAME,
    MrubyUxManifestDoc,
    compile_bytecode,
    config_header,
    feature_scan,
    generate,
    mrubyc_problems,
)
from firmware.profiles import load_profile

EXAMPLE = Path("examples/mruby-ux")
MRUBYC = {
    "ref": "2dec4802b09be1fc12f388d3c9267ffd9dc6c404",
    "hal": "zephyr",
    "memory_size": 40960,
    "sources": [
        {"file": "ux/app.rb", "bytecode": "fw/generated/ux_app_bytecode.c", "symbol": "ux_app"}
    ],
}


def _contract(**over: object) -> FirmwareContract:
    base = json.loads((EXAMPLE / "mruby-ux.fw.json").read_text(encoding="utf-8"))
    base.update(over)
    return FirmwareContract.model_validate(base)


def _tmp_contract(tmp_path: Path, **over: object) -> tuple[FirmwareContract, Path]:
    """Copy the example project into tmp_path so generation can write."""
    import shutil as _sh

    dst = tmp_path / "proj"
    _sh.copytree(EXAMPLE, dst)
    contract = _contract(**over)
    return contract, dst / "mruby-ux.fw.json"


class TestContract:
    def test_example_validates(self) -> None:
        c = _contract()
        assert c.mrubyc is not None and c.mrubyc.hal == "zephyr"
        assert c.build.backend == "west" and c.build.board == "nrf52840dk/nrf52840"

    def test_utf8_requires_string(self) -> None:
        with pytest.raises(ValueError, match="utf8"):
            FirmwareContract.model_validate(
                {
                    **_contract().model_dump(mode="json"),
                    "mrubyc": {**MRUBYC, "use_string": False, "use_utf8": True},
                }
            )

    def test_duplicate_symbols_rejected(self) -> None:
        dup = {
            **MRUBYC,
            "sources": [
                {"file": "ux/app.rb", "bytecode": "g/a.c", "symbol": "same"},
                {"file": "ux/app.rb", "bytecode": "g/b.c", "symbol": "same"},
            ],
        }
        with pytest.raises(ValueError, match="symbol"):
            FirmwareContract.model_validate({**_contract().model_dump(mode="json"), "mrubyc": dup})

    def test_west_requires_board(self) -> None:
        with pytest.raises(ValueError, match="board"):
            FirmwareContract.model_validate(
                {
                    **_contract().model_dump(mode="json"),
                    "build": {
                        "backend": "west",
                        "dir": "fw",
                        "sdk": "nrf-connect",
                        "elf": "fw/build/zephyr/zephyr.elf",
                        "pins_header": "fw/include/fw_pins.h",
                        "budget": {"flash_pct": 60, "ram_pct": 60},
                    },
                }
            )

    def test_node_runner_rules(self) -> None:
        sims = _contract().model_dump(mode="json")["simulations"]
        sims[0]["machine"] = "mps2-an385"
        with pytest.raises(ValueError, match="machine"):
            FirmwareContract.model_validate(
                {**_contract().model_dump(mode="json"), "simulations": sims}
            )

    def test_cross_prefix_requires_toolchain(self) -> None:
        c = _contract().model_dump(mode="json")
        c["build"]["cross_prefix"] = "riscv64-unknown-elf-"
        with pytest.raises(ValueError, match="cross"):
            FirmwareContract.model_validate(c)


class TestFeatureScan:
    def test_float_flag(self) -> None:
        c = _contract(mrubyc={**MRUBYC, "use_float": 0})
        assert feature_scan("x = 1.5\n", c.mrubyc)  # type: ignore[arg-type]

    def test_math_flag(self) -> None:
        c = _contract()
        assert feature_scan("Math.sqrt(4)\n", c.mrubyc)  # type: ignore[arg-type]
        c2 = _contract(mrubyc={**MRUBYC, "use_math": True})
        assert not feature_scan("Math.sqrt(4)\n", c2.mrubyc)  # type: ignore[arg-type]

    def test_timer_flag(self) -> None:
        c = _contract(mrubyc={**MRUBYC, "no_timer": True})
        assert feature_scan("VM.tick\n", c.mrubyc)  # type: ignore[arg-type]


class TestConfigHeader:
    def test_header_contents(self) -> None:
        c = _contract()
        text = config_header(c.mrubyc, c.name)  # type: ignore[arg-type]
        assert "#define FW_MRUBY_MEMORY_SIZE 40960u" in text
        assert "#define MRBC_USE_FLOAT 2" in text
        assert "#define MRBC_USE_STRING 1" in text
        assert "#define MRBC_TIMESLICE_TICK_COUNT 1" in text
        assert "#define MRBC_NO_TIMER" not in text


class TestGate:
    def test_missing_ref_file_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        contract, cpath = _tmp_contract(tmp_path)
        monkeypatch.setenv("FIRMWARE_MRUBYC_REF", str(tmp_path / "nope"))
        profile = load_profile("nrf52840", [cpath.parent])
        problems, _ = mrubyc_problems(contract, profile, cpath)
        assert any("ref file" in p for p in problems)

    def test_hal_profile_mismatch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        contract, cpath = _tmp_contract(tmp_path)
        ref = tmp_path / "REF"
        ref.write_text(contract.mrubyc.ref + "\n")  # type: ignore[union-attr]
        monkeypatch.setenv("FIRMWARE_MRUBYC_REF", str(ref))
        _problems, _ = mrubyc_problems(contract, load_profile("rp2040"), cpath)
        # zephyr hal accepts any profile, so emulate an avr contract instead
        contract2 = _contract(mrubyc={**MRUBYC, "hal": "avr"})
        problems2, _ = mrubyc_problems(contract2, load_profile("rp2040"), cpath)
        assert any("cannot target profile" in p for p in problems2)

    def test_fresh_artifacts_pass(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        if shutil.which("mrbc") is None:
            pytest.skip("mrbc not on PATH")
        contract, cpath = _tmp_contract(tmp_path)
        ref = tmp_path / "REF"
        ref.write_text(contract.mrubyc.ref + "\n")  # type: ignore[union-attr]
        monkeypatch.setenv("FIRMWARE_MRUBYC_REF", str(ref))
        profile = load_profile("nrf52840", [cpath.parent])
        _written, gen_problems = generate(contract, cpath)
        assert not gen_problems
        problems, evidence = mrubyc_problems(contract, profile, cpath)
        assert problems == []
        assert any("hal=zephyr" in e for e in evidence)

    def test_stale_bytecode_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        if shutil.which("mrbc") is None:
            pytest.skip("mrbc not on PATH")
        contract, cpath = _tmp_contract(tmp_path)
        ref = tmp_path / "REF"
        ref.write_text(contract.mrubyc.ref + "\n")  # type: ignore[union-attr]
        monkeypatch.setenv("FIRMWARE_MRUBYC_REF", str(ref))
        generate(contract, cpath)
        stale = cpath.parent / "fw/generated/ux_app_bytecode.c"
        stale.write_bytes(b"corrupted")
        problems, _ = mrubyc_problems(contract, load_profile("nrf52840"), cpath)
        assert any("stale" in p for p in problems)


@pytest.mark.tools
class TestMrbc:
    def test_compile_bytecode(self, tmp_path: Path) -> None:
        mrbc = shutil.which("mrbc")
        if mrbc is None:
            pytest.skip("mrbc not on PATH")
        src = tmp_path / "a.rb"
        src.write_text('puts "x"\n', encoding="utf-8")
        out = compile_bytecode(mrbc, "sym_a", src)
        assert b"sym_a" in out


class TestManifestDoc:
    def test_requires(self) -> None:
        doc = MrubyUxManifestDoc.model_validate(
            {
                "artifact_kind": "mruby_manifest",
                "product": "x",
                "files": [{"file": "ux/a.rb", "sha256": "0" * 64}],
                "requires": {"float": 1, "math": False, "string": True},
            }
        )
        assert doc.requires.float == 1


class TestHalBackends:
    def test_zephyr_needs_west(self) -> None:
        assert HAL_BACKENDS["zephyr"] == frozenset({"west"})
        assert "make" in HAL_BACKENDS["avr"]

    def test_manifest_filename(self) -> None:
        assert MANIFEST_NAME == "fw_ruby_manifest.json"
