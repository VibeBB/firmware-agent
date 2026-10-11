from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from firmware.contract import FirmwareContract, load_contract
from firmware.security import read_sdkconfig, security_problems

SECURE = """CONFIG_SECURE_BOOT=y
CONFIG_SECURE_BOOT_V2_ENABLED=y
CONFIG_SECURE_FLASH_ENC_ENABLED=y
CONFIG_SECURE_FLASH_ENCRYPTION_MODE_RELEASE=y
CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y
CONFIG_PARTITION_TABLE_CUSTOM=y
CONFIG_PARTITION_TABLE_CUSTOM_FILENAME="partitions.csv"
# CONFIG_SECURE_BOOT_ALLOW_JTAG is not set
"""
TABLE = """# Name, Type, SubType, Offset, Size
nvs, data, nvs, 0x9000, 0x4000
otadata, data, ota, 0xd000, 0x2000
ota_0, app, ota_0, 0x10000, 0x300000
ota_1, app, ota_1, 0x310000, 0x300000
"""
ALL = {"secure_boot": True, "flash_encryption": True, "ota_rollback": True, "jtag_disabled": True}


def _secure(lamp: Path, sdkconfig: str = SECURE, table: str | None = TABLE, **flags: bool) -> Path:
    fw = lamp.parent / "fw"
    (fw / "sdkconfig.defaults").write_text(sdkconfig, encoding="utf-8")
    if table is not None:
        (fw / "partitions.csv").write_text(table, encoding="utf-8")
    data = json.loads(lamp.read_text(encoding="utf-8"))
    data["security"] = {
        "sdkconfig": "fw/sdkconfig.defaults",
        **{**ALL, **flags},
        "rationale": "field-updated connected lamp",
    }
    lamp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return lamp


def _problems(lamp: Path) -> list[str]:
    return security_problems(load_contract(lamp), lamp)[0]


def test_secure_configuration_passes(lamp: Path) -> None:
    problems, evidence = security_problems(load_contract(_secure(lamp)), lamp)
    assert problems == []
    assert "OTA partitions from partitions.csv" in evidence


def test_built_in_two_ota_table_passes(lamp: Path) -> None:
    config = SECURE.replace("CONFIG_PARTITION_TABLE_CUSTOM=y", "CONFIG_PARTITION_TABLE_TWO_OTA=y")
    assert _problems(_secure(lamp, config, None)) == []


@pytest.mark.parametrize(
    ("drop", "needle"),
    [
        ("CONFIG_SECURE_BOOT_V2_ENABLED=y\n", "secure_boot requires CONFIG_SECURE_BOOT_V2_ENABLED"),
        ("CONFIG_SECURE_FLASH_ENC_ENABLED=y\n", "flash_encryption requires"),
        ("CONFIG_SECURE_FLASH_ENCRYPTION_MODE_RELEASE=y\n", "MODE_RELEASE"),
        ("CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y\n", "ota_rollback requires"),
        ("CONFIG_PARTITION_TABLE_CUSTOM=y\n", "no OTA partition table configured"),
    ],
)
def test_missing_setting_fails(lamp: Path, drop: str, needle: str) -> None:
    assert any(needle in p for p in _problems(_secure(lamp, SECURE.replace(drop, ""))))


@pytest.mark.parametrize(
    "insecure",
    [
        "CONFIG_SECURE_BOOT_INSECURE=y",
        "CONFIG_SECURE_FLASH_ENCRYPTION_MODE_DEVELOPMENT=y",
        "CONFIG_SECURE_BOOT_ALLOW_JTAG=y",
    ],
)
def test_insecure_option_fails(lamp: Path, insecure: str) -> None:
    problems = _problems(_secure(lamp, SECURE + insecure + "\n"))
    assert any(insecure.removesuffix("=y") in p for p in problems)


def test_partition_table_without_second_slot_fails(lamp: Path) -> None:
    table = TABLE.replace("ota_1, app, ota_1, 0x310000, 0x300000\n", "")
    assert any("partition subtypes ota_1" in p for p in _problems(_secure(lamp, table=table)))


def test_unreadable_files_fail(lamp: Path) -> None:
    assert any("partition table unreadable" in p for p in _problems(_secure(lamp, table=None)))
    (lamp.parent / "fw" / "sdkconfig.defaults").unlink()
    assert any("unreadable" in p for p in _problems(lamp))


def test_undeclared_properties_are_not_checked(lamp: Path) -> None:
    flags = dict.fromkeys(ALL, False)
    problems, evidence = security_problems(load_contract(_secure(lamp, "", None, **flags)), lamp)
    assert problems == [] and evidence[-1].startswith("required: none")


def test_read_sdkconfig_forms() -> None:
    values = read_sdkconfig('CONFIG_A=y\n# CONFIG_B is not set\nCONFIG_C="x.csv"\nnoise\n')
    assert values == {"CONFIG_A": "y", "CONFIG_B": "n", "CONFIG_C": "x.csv"}


def test_security_section_is_strict(lamp: Path) -> None:
    data = json.loads(_secure(lamp).read_text(encoding="utf-8"))
    for bad in ({"rationale": "short"}, {"secure_boot": None}, {"extra": 1}):
        broken = {**data, "security": {**data["security"], **bad}}
        with pytest.raises(ValidationError):
            FirmwareContract.model_validate(broken)
