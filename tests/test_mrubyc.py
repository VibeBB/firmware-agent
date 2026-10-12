"""mruby/c capability: contract validation, generation, and the static gate."""

from __future__ import annotations

import hashlib
import json
import os
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


_STUB_MRBC = """#!/bin/sh
# Fake mrbc: `-c` fails on a SYNTAX_ERROR marker; `-B` emits a
# deterministic C array derived from the source bytes.
if [ "$1" = "-c" ]; then
  grep -q 'SYNTAX_ERROR' "$2" && { echo "mrbc: syntax error" >&2; exit 1; }
  exit 0
fi
sym="$2"
for last; do :; done
grep -q 'SYNTAX_ERROR' "$last" && { echo "mrbc: compile error" >&2; exit 1; }
printf 'const unsigned char %s[] = {' "$sym"
od -An -v -tu1 "$last" | tr -s ' ' | sed 's/^ *//; s/ /,/g' | tr '\\n' ','
printf '0};\\n'
"""


def _stub_mrbc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bindir = tmp_path / "stubbin"
    bindir.mkdir(exist_ok=True)
    stub = bindir / "mrbc"
    stub.write_text(_STUB_MRBC, encoding="utf-8")
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ.get('PATH', '')}")


def _pin_ref(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ref: str) -> None:
    ref_file = tmp_path / "REF"
    ref_file.write_text(ref + "\n", encoding="utf-8")
    monkeypatch.setenv("FIRMWARE_MRUBYC_REF", str(ref_file))


def _fresh_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **over: object
) -> tuple[FirmwareContract, Path]:
    """Copy the example, stub mrbc, pin the ref, and generate artifacts."""
    _stub_mrbc(tmp_path, monkeypatch)
    contract, cpath = _tmp_contract(tmp_path, **over)
    assert contract.mrubyc is not None
    _pin_ref(tmp_path, monkeypatch, contract.mrubyc.ref)
    _written, problems = generate(contract, cpath)
    assert problems == []
    return contract, cpath


class TestGenerate:
    def test_writes_header_bytecode_manifest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_mrbc(tmp_path, monkeypatch)
        contract, cpath = _tmp_contract(tmp_path)
        written, problems = generate(contract, cpath)
        assert problems == []
        names = {p.name for p in written}
        assert {"fw_mruby.h", "ux_app_bytecode.c", "fw_ruby_manifest.json"} <= names
        manifest = json.loads(
            (cpath.parent / "fw/generated/fw_ruby_manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["artifact_kind"] == "fw_ruby_manifest"
        assert manifest["files"][0]["symbol"] == "ux_app"
        assert len(manifest["files"][0]["sha256"]) == 64
        bytecode = (cpath.parent / "fw/generated/ux_app_bytecode.c").read_text(encoding="utf-8")
        assert "ux_app" in bytecode

    def test_missing_source_reported(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_mrbc(tmp_path, monkeypatch)
        contract, cpath = _tmp_contract(
            tmp_path,
            mrubyc={
                **MRUBYC,
                "sources": [{"file": "ux/nope.rb", "bytecode": "g/x.c", "symbol": "x"}],
            },
        )
        written, problems = generate(contract, cpath)
        assert any("ux/nope.rb" in p and "missing" in p for p in problems)
        # manifest + header are still written so the gate can diff them
        assert any(p.name == "fw_ruby_manifest.json" for p in written)

    def test_mrbc_absent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PATH", str(tmp_path / "empty"))
        contract, cpath = _tmp_contract(tmp_path)
        written, problems = generate(contract, cpath)
        assert written == []
        assert problems == ["mrbc not on PATH (mruby toolchain missing)"]

    def test_mrbc_failure_reported(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_mrbc(tmp_path, monkeypatch)
        contract, cpath = _tmp_contract(tmp_path)
        (cpath.parent / "ux/app.rb").write_text("SYNTAX_ERROR\n", encoding="utf-8")
        _written, problems = generate(contract, cpath)
        assert any("app.rb" in p and "mrbc" in p for p in problems)


class TestGateStubbed:
    def test_fresh_artifacts_pass(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        contract, cpath = _fresh_project(tmp_path, monkeypatch)
        problems, evidence = mrubyc_problems(contract, load_profile("nrf52840"), cpath)
        assert problems == []
        assert any("hal=zephyr" in e for e in evidence)
        assert any(e.startswith("toolchain=") for e in evidence)

    def test_stale_bytecode_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        contract, cpath = _fresh_project(tmp_path, monkeypatch)
        (cpath.parent / "fw/generated/ux_app_bytecode.c").write_bytes(b"corrupted")
        problems, _ = mrubyc_problems(contract, load_profile("nrf52840"), cpath)
        assert any("stale" in p for p in problems)

    def test_missing_bytecode_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        contract, cpath = _fresh_project(tmp_path, monkeypatch)
        (cpath.parent / "fw/generated/ux_app_bytecode.c").unlink()
        problems, _ = mrubyc_problems(contract, load_profile("nrf52840"), cpath)
        assert any("bytecode" in p and "missing" in p for p in problems)

    def test_stale_header_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        contract, cpath = _fresh_project(tmp_path, monkeypatch)
        (cpath.parent / "fw/include/fw_mruby.h").write_text("/* edited */\n", encoding="utf-8")
        problems, _ = mrubyc_problems(contract, load_profile("nrf52840"), cpath)
        assert any("config header" in p and "stale" in p for p in problems)

    def test_missing_manifest_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        contract, cpath = _fresh_project(tmp_path, monkeypatch)
        (cpath.parent / "fw/generated/fw_ruby_manifest.json").unlink()
        problems, _ = mrubyc_problems(contract, load_profile("nrf52840"), cpath)
        assert any("fw_ruby_manifest.json missing" in p for p in problems)

    def test_stale_manifest_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        contract, cpath = _fresh_project(tmp_path, monkeypatch)
        (cpath.parent / "ux/app.rb").write_text("# different source\n", encoding="utf-8")
        problems, _ = mrubyc_problems(contract, load_profile("nrf52840"), cpath)
        assert any("stale" in p for p in problems)

    def test_syntax_error_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        contract, cpath = _fresh_project(tmp_path, monkeypatch)
        (cpath.parent / "ux/app.rb").write_text("SYNTAX_ERROR\n", encoding="utf-8")
        problems, _ = mrubyc_problems(contract, load_profile("nrf52840"), cpath)
        assert any("mrbc -c" in p for p in problems)

    def test_missing_source_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        contract, cpath = _fresh_project(tmp_path, monkeypatch)
        (cpath.parent / "ux/app.rb").unlink()
        problems, _ = mrubyc_problems(contract, load_profile("nrf52840"), cpath)
        assert any("mruby source" in p and "missing" in p for p in problems)

    def test_memory_size_limit(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        contract, cpath = _fresh_project(
            tmp_path, monkeypatch, mrubyc={**MRUBYC, "memory_size": 300000}
        )
        problems, _ = mrubyc_problems(contract, load_profile("nrf52840"), cpath)
        assert any("memory_size" in p and "80%" in p for p in problems)

    def test_hal_needs_allowed_leg(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        contract, cpath = _fresh_project(tmp_path, monkeypatch)
        dumped = contract.model_dump(mode="json")
        dumped["build"] = {
            "backend": "make",
            "dir": "fw",
            "elf": "fw/fw.elf",
            "pins_header": "fw/include/fw_pins.h",
            "budget": {"flash_pct": 60, "ram_pct": 60},
        }
        dumped["simulations"] = []
        contract2 = FirmwareContract.model_validate(dumped)
        problems, _ = mrubyc_problems(contract2, load_profile("nrf52840"), cpath)
        assert any("needs a west build leg" in p for p in problems)

    def test_emscripten_needs_node_runner(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        contract, cpath = _fresh_project(tmp_path, monkeypatch)
        dumped = contract.model_dump(mode="json")
        dumped["mrubyc"]["hal"] = "emscripten"
        dumped["build"] = {
            "backend": "make",
            "dir": "wasm",
            "elf": "wasm/build/ux.mjs",
            "pins_header": "fw/include/fw_pins.h",
            "budget": {"flash_pct": 60, "ram_pct": 60},
        }
        dumped["simulations"] = []
        contract2 = FirmwareContract.model_validate(dumped)
        problems, _ = mrubyc_problems(contract2, load_profile("nrf52840"), cpath)
        assert any("node-runner" in p for p in problems)


class TestUxManifest:
    def _ux_doc(self, cpath: Path, **requires: object) -> dict[str, object]:
        doc: dict[str, object] = {
            "artifact_kind": "mruby_manifest",
            "product": "mruby-ux",
            "files": [
                {
                    "file": "ux/app.rb",
                    "sha256": hashlib.sha256((cpath.parent / "ux/app.rb").read_bytes()).hexdigest(),
                }
            ],
            "requires": {
                "float": 2,
                "math": False,
                "string": True,
                "utf8": False,
                "tick": True,
            }
            | requires,
        }
        return doc

    def _contract_with_ux(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        _contract_over: dict[str, object] | None = None,
        **requires: object,
    ) -> tuple[FirmwareContract, Path]:
        contract, cpath = _fresh_project(tmp_path, monkeypatch, **(_contract_over or {}))
        doc = self._ux_doc(cpath, **requires)
        ux_path = cpath.parent / "ux/mruby-ux.mruby-manifest.json"
        ux_path.write_text(json.dumps(doc), encoding="utf-8")
        dumped = contract.model_dump(mode="json")
        dumped["mrubyc"]["ux_manifest"] = {
            "manifest": "ux/mruby-ux.mruby-manifest.json",
            "sha256": hashlib.sha256(ux_path.read_bytes()).hexdigest(),
        }
        return FirmwareContract.model_validate(dumped), cpath

    def test_matching_manifest_passes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        contract, cpath = self._contract_with_ux(tmp_path, monkeypatch)
        problems, evidence = mrubyc_problems(contract, load_profile("nrf52840"), cpath)
        assert problems == []
        assert any(e.startswith("ux=mruby-ux") for e in evidence)

    def test_sha_mismatch_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        contract, cpath = self._contract_with_ux(tmp_path, monkeypatch)
        (cpath.parent / "ux/mruby-ux.mruby-manifest.json").write_text("{}", encoding="utf-8")
        problems, _ = mrubyc_problems(contract, load_profile("nrf52840"), cpath)
        assert any("differs from pinned" in p for p in problems)

    def test_missing_manifest_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        contract, cpath = _fresh_project(tmp_path, monkeypatch)
        dumped = contract.model_dump(mode="json")
        dumped["mrubyc"]["ux_manifest"] = {
            "manifest": "ux/nope.mruby-manifest.json",
            "sha256": "0" * 64,
        }
        contract2 = FirmwareContract.model_validate(dumped)
        problems, _ = mrubyc_problems(contract2, load_profile("nrf52840"), cpath)
        assert any("ux manifest" in p and "missing" in p for p in problems)

    def test_requires_math_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        contract, cpath = self._contract_with_ux(tmp_path, monkeypatch, math=True)
        problems, _ = mrubyc_problems(contract, load_profile("nrf52840"), cpath)
        assert any("needs Math" in p for p in problems)

    def test_requires_float_level_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        contract, cpath = self._contract_with_ux(
            tmp_path, monkeypatch, {"mrubyc": {**MRUBYC, "use_float": 1}}
        )
        problems, _ = mrubyc_problems(contract, load_profile("nrf52840"), cpath)
        assert any("needs float" in p for p in problems)

    def test_ux_file_not_in_sources(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        contract, cpath = _fresh_project(tmp_path, monkeypatch)
        doc = self._ux_doc(cpath)
        doc["files"] = [{"file": "ux/other.rb", "sha256": "0" * 64}]  # type: ignore[index]
        ux_path = cpath.parent / "ux/mruby-ux.mruby-manifest.json"
        ux_path.write_text(json.dumps(doc), encoding="utf-8")
        dumped = contract.model_dump(mode="json")
        dumped["mrubyc"]["ux_manifest"] = {
            "manifest": "ux/mruby-ux.mruby-manifest.json",
            "sha256": hashlib.sha256(ux_path.read_bytes()).hexdigest(),
        }
        contract2 = FirmwareContract.model_validate(dumped)
        problems, _ = mrubyc_problems(contract2, load_profile("nrf52840"), cpath)
        assert any("ux/other.rb" in p and "not in mrubyc.sources" in p for p in problems)


class TestHalProfileFit:
    @pytest.mark.parametrize(
        ("hal", "profile_id", "ok"),
        [
            ("avr", "atmega328p", True),
            ("avr", "nrf52840", False),
            ("esp32", "esp32s3", True),
            ("esp32", "rp2040", False),
            ("rp2040", "rp2350", True),
            ("rp2040", "atmega328p", False),
            ("stm32", "stm32f411re", True),
            ("stm32", "esp32", False),
            ("pic24", "pic24fj256gb110", True),
            ("pic24", "avr128db48", False),
            ("zephyr", "esp32c3", True),
            ("emscripten", "teensy4", True),
            ("posix", "mps2_an385", True),
        ],
    )
    def test_hal_profile_fit(self, hal: str, profile_id: str, ok: bool) -> None:
        from firmware.mrubyc import _hal_profile_ok  # pyright: ignore[reportPrivateUsage]

        assert _hal_profile_ok(hal, load_profile(profile_id)) is ok
