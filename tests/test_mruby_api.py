"""Device API: ``*.mruby-api.json`` schema, codegen and the fw.mrubyc gate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from firmware.contract import FirmwareContract, MrubycConfig, MrubyDeviceApi
from firmware.mruby_api import (
    MrubyApiDoc,
    api_problems,
    consumed_symbols,
    generate_api,
    render_api,
)

EXAMPLE = Path("examples/mruby-ux")
SPEC_REL = "api/mruby-ux.mruby-api.json"


def _contract() -> FirmwareContract:
    return FirmwareContract.model_validate(
        json.loads((EXAMPLE / "mruby-ux.fw.json").read_text(encoding="utf-8"))
    )


def _spec() -> MrubyApiDoc:
    return MrubyApiDoc.model_validate(json.loads((EXAMPLE / SPEC_REL).read_text(encoding="utf-8")))


def _mrubyc() -> MrubycConfig:
    mr = _contract().mrubyc
    assert mr is not None
    return mr


def _link() -> MrubyDeviceApi:
    link = _mrubyc().device_api
    assert link is not None
    return link


def _tmp_project(tmp_path: Path) -> Path:
    import shutil

    dst = tmp_path / "proj"
    shutil.copytree(EXAMPLE, dst)
    return dst / "mruby-ux.fw.json"


class TestSchema:
    def test_example_spec_validates(self) -> None:
        spec = _spec()
        assert [c.name for c in spec.classes] == ["LED", "Sample"]
        assert spec.symbols[0].const == "kFwHwLed1"

    def test_symbol_param_needs_enum(self) -> None:
        bad = json.loads((EXAMPLE / SPEC_REL).read_text())
        bad["classes"][0]["methods"][1]["params"][0]["enum"] = []
        with pytest.raises(ValueError, match="enum"):
            MrubyApiDoc.model_validate(bad)

    def test_enum_values_must_be_declared_symbols(self) -> None:
        bad = json.loads((EXAMPLE / SPEC_REL).read_text())
        bad["classes"][0]["methods"][1]["params"][0]["enum"] = ["led9"]
        with pytest.raises(ValueError, match="enum"):
            MrubyApiDoc.model_validate(bad)

    def test_system_task_requires_block(self) -> None:
        bad = json.loads((EXAMPLE / SPEC_REL).read_text())
        del bad["system_task"]
        with pytest.raises(ValueError, match="system_task"):
            MrubyApiDoc.model_validate(bad)

    def test_expert_requires_define(self) -> None:
        bad = json.loads((EXAMPLE / SPEC_REL).read_text())
        del bad["expert_define"]
        with pytest.raises(ValueError, match="expert_define"):
            MrubyApiDoc.model_validate(bad)

    def test_array_return_needs_cap_bounds(self) -> None:
        bad = json.loads((EXAMPLE / SPEC_REL).read_text())
        bad["classes"][1]["methods"][0]["returns"]["cap"] = 0
        with pytest.raises(ValueError, match="cap"):
            MrubyApiDoc.model_validate(bad)

    def test_reserved_arg_names(self) -> None:
        bad = json.loads((EXAMPLE / SPEC_REL).read_text())
        bad["classes"][0]["methods"][0]["kwargs"].append({"name": "blk", "type": "int"})
        with pytest.raises(ValueError, match="reserved"):
            MrubyApiDoc.model_validate(bad)

    def test_module_rejects_instance(self) -> None:
        bad = json.loads((EXAMPLE / SPEC_REL).read_text())
        bad["classes"][1]["kind"] = "module"
        with pytest.raises(ValueError, match="module"):
            MrubyApiDoc.model_validate(bad)


class TestCodegen:
    def test_expected_file_set(self) -> None:
        files = render_api(_spec(), "mruby-ux", SPEC_REL)
        assert set(files) == {
            "fw_api.h",
            "fw_api.c",
            "fw_api_symbols.h",
            "fw_api_symbols.c",
            "fw_api_led.h",
            "fw_api_led.c",
            "fw_api_sample.h",
            "fw_api_sample.c",
        }

    def test_kw_decode_uses_openblink_guard_block(self) -> None:
        led = render_api(_spec(), "mruby-ux", SPEC_REL)["fw_api_led.c"]
        assert "MRBC_KW_ARG(part, state);" in led
        assert "} while (0);" in led
        assert "MRBC_KW_DELETE(part, state);" in led
        assert "mrbc_israised(vm)" in led

    def test_symbol_dispatch_uses_symid_field(self) -> None:
        led = render_api(_spec(), "mruby-ux", SPEC_REL)["fw_api_led.c"]
        assert "fw_api_symbol_const(part.sym_id)" in led
        assert "fw_api_symbol_const(v[1].sym_id)" in led

    def test_system_task_gate(self) -> None:
        led = render_api(_spec(), "mruby-ux", SPEC_REL)["fw_api_led.c"]
        assert "fw_api_is_system_task(vm->vm_id)" in led
        agg = render_api(_spec(), "mruby-ux", SPEC_REL)["fw_api.c"]
        assert "return vm_id == 1u;" in agg

    def test_expert_define_guard(self) -> None:
        led = render_api(_spec(), "mruby-ux", SPEC_REL)["fw_api_led.c"]
        assert "#if defined(FW_DEBUG_API)" in led
        assert '"raw", c_led_raw);' in led.split("#if defined(FW_DEBUG_API)")[1]

    def test_block_and_rest_kwargs(self) -> None:
        led = render_api(_spec(), "mruby-ux", SPEC_REL)["fw_api_led.c"]
        assert "MRBC_TT_PROC == v[argc + 1].tt" in led
        assert "MRBC_KW_DICT(rest);" in led
        assert "fw_hw_led_on_change(&rest, blk)" in led

    def test_raise_mode_emits_extern(self) -> None:
        led = render_api(_spec(), "mruby-ux", SPEC_REL)["fw_api_led.c"]
        assert "extern struct RBuiltinNoMethodClass mrbc_class_ArgumentError;" in led
        assert 'mrbc_raise(vm, MRBC_CLASS(ArgumentError), "LED.toggle' in led

    def test_constants_registered(self) -> None:
        led = render_api(_spec(), "mruby-ux", SPEC_REL)["fw_api_led.c"]
        assert 'mrbc_set_class_const(fw_api_led_class, mrbc_str_to_symid("OFF"), &k);' in led

    def test_instance_ctor_dtor(self) -> None:
        sample = render_api(_spec(), "mruby-ux", SPEC_REL)["fw_api_sample.c"]
        assert "mrbc_instance_new(vm, v[0].cls, 16u)" in sample
        assert "mrbc_define_destructor(fw_api_sample_class, c_sample_dtor);" in sample
        assert "fw_hw_sample_close((void *)v->instance->data);" in sample
        assert "fw_hw_sample_read(data, a_ch," in sample

    def test_array_bounded_copy(self) -> None:
        led = render_api(_spec(), "mruby-ux", SPEC_REL)["fw_api_led.c"]
        assert "v[1].array->n_stored > 4u" in led
        assert "fw_hw_led_all(a_states, a_states_n)" in led

    def test_deterministic(self) -> None:
        spec = _spec()
        assert render_api(spec, "mruby-ux", SPEC_REL) == render_api(spec, "mruby-ux", SPEC_REL)


class TestConsumedSymbols:
    def test_count(self) -> None:
        # 3 declared + LED/Sample classes + methods + kwarg/const names
        assert consumed_symbols(_spec()) == 17


class TestGate:
    def test_committed_generated_files_pass(self, tmp_path: Path) -> None:
        import os

        os.environ["FIRMWARE_MRUBYC_REF"] = "/dev/null"
        contract_path = _tmp_project(tmp_path)
        probs, ev = api_problems(_contract(), _link(), contract_path)
        assert probs == []
        assert any(s.startswith("symbols=") for s in ev)

    def test_sha_drift_fails(self, tmp_path: Path) -> None:
        contract_path = _tmp_project(tmp_path)
        spec_path = contract_path.parent / SPEC_REL
        spec_path.write_text(spec_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        probs, _ = api_problems(_contract(), _link(), contract_path)
        assert any("sha256" in p for p in probs)

    def test_stale_generated_fails(self, tmp_path: Path) -> None:
        contract_path = _tmp_project(tmp_path)
        gen = contract_path.parent / "fw/generated/fw_api_led.c"
        gen.write_text("/* tampered */\n" + gen.read_text(), encoding="utf-8")
        probs, _ = api_problems(_contract(), _link(), contract_path)
        assert any("fw_api_led.c stale" in p for p in probs)

    def test_missing_handler_fails(self, tmp_path: Path) -> None:
        contract_path = _tmp_project(tmp_path)
        header = contract_path.parent / "fw/include/fw_api_handlers.h"
        header.write_text(
            header.read_text(encoding="utf-8").replace("fw_hw_led_toggle", "fw_hw_led_missing"),
            encoding="utf-8",
        )
        probs, _ = api_problems(_contract(), _link(), contract_path)
        assert any("fw_hw_led_toggle" in p for p in probs)

    def test_float_flag_conflict(self, tmp_path: Path) -> None:
        contract_path = _tmp_project(tmp_path)
        contract = FirmwareContract.model_validate(
            {
                **_contract().model_dump(mode="json"),
                "mrubyc": {**_mrubyc().model_dump(mode="json"), "use_float": 0},
            }
        )
        probs, _ = api_problems(contract, _link(), contract_path)
        assert any("float" in p for p in probs)

    def test_vm_id_over_max_fails(self, tmp_path: Path) -> None:
        contract_path = _tmp_project(tmp_path)
        spec_path = contract_path.parent / SPEC_REL
        spec_json = json.loads(spec_path.read_text(encoding="utf-8"))
        spec_json["system_task"]["vm_id"] = 9
        raw = json.dumps(spec_json, indent=2)
        spec_path.write_text(raw, encoding="utf-8")
        sha = hashlib.sha256(raw.encode()).hexdigest()
        contract = FirmwareContract.model_validate(
            {
                **_contract().model_dump(mode="json"),
                "mrubyc": {
                    **_mrubyc().model_dump(mode="json"),
                    "max_vm_count": 4,
                    "device_api": {
                        **_link().model_dump(mode="json"),
                        "sha256": sha,
                    },
                },
            }
        )
        assert contract.mrubyc is not None
        link = contract.mrubyc.device_api
        assert link is not None
        probs, _ = api_problems(contract, link, contract_path)
        assert any("vm_id" in p for p in probs)

    def test_regenerate_repairs_staleness(self, tmp_path: Path) -> None:
        contract_path = _tmp_project(tmp_path)
        out = contract_path.parent / "fw/generated"
        (out / "fw_api_led.c").unlink()
        spec = _spec()
        written = generate_api(spec, "mruby-ux", SPEC_REL, out)
        assert len(written) == 8
        probs, _ = api_problems(_contract(), _link(), contract_path)
        assert probs == []
