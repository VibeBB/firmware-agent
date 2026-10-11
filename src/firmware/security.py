"""``fw.security``: secure boot, flash encryption, OTA rollback and JTAG lock.

The required properties are declared in the contract ``security`` section
and verified against the ESP-IDF ``sdkconfig.defaults`` the build applies
and the partition table it names. A setting that is absent is not assumed:
a required property without its configuration fails.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from .contract import FirmwareContract, Security, resolve

SECURE_BOOT = ("CONFIG_SECURE_BOOT", "CONFIG_SECURE_BOOT_V2_ENABLED")
FLASH_ENCRYPTION = (
    "CONFIG_SECURE_FLASH_ENC_ENABLED",
    "CONFIG_SECURE_FLASH_ENCRYPTION_MODE_RELEASE",
)
ROLLBACK = ("CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE",)
# otadata is the data partition of subtype "ota"; the two app slots are ota_0/ota_1.
OTA_SUBTYPES = frozenset({"ota", "ota_0", "ota_1"})
INSECURE = {
    "secure_boot": ("CONFIG_SECURE_BOOT_INSECURE",),
    "flash_encryption": ("CONFIG_SECURE_FLASH_ENCRYPTION_MODE_DEVELOPMENT",),
    "jtag_disabled": ("CONFIG_SECURE_BOOT_ALLOW_JTAG", "CONFIG_SECURE_FLASH_ENC_ALLOW_JTAG"),
}


def read_sdkconfig(text: str) -> dict[str, str]:
    """``KEY=value`` lines; ``# KEY is not set`` lines map to ``n``."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("# CONFIG_") and line.endswith(" is not set"):
            values[line[2:].removesuffix(" is not set")] = "n"
        elif line.startswith("CONFIG_") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value.strip().strip('"')
    return values


def ota_partitions(sdkconfig: dict[str, str], base: Path) -> tuple[set[str], str]:
    """Partition subtypes of the configured table and a label of its source."""
    if sdkconfig.get("CONFIG_PARTITION_TABLE_TWO_OTA") == "y":
        return set(OTA_SUBTYPES), "built-in two-OTA table"
    name = sdkconfig.get("CONFIG_PARTITION_TABLE_CUSTOM_FILENAME")
    if sdkconfig.get("CONFIG_PARTITION_TABLE_CUSTOM") != "y" or not name:
        return set(), "no OTA partition table configured"
    path = base / name
    text = path.read_text(encoding="utf-8")
    rows = csv.reader(io.StringIO(text))
    subtypes = {
        row[2].strip()
        for row in rows
        if row[2:3] and row[0].strip() and not row[0].lstrip().startswith("#")
    }
    return subtypes, name


def _required(keys: tuple[str, ...], values: dict[str, str], label: str) -> list[str]:
    return [f"{label} requires {key}=y" for key in keys if values.get(key) != "y"]


def security_problems(
    contract: FirmwareContract, contract_path: Path
) -> tuple[list[str], list[str]]:
    security: Security | None = contract.security
    if security is None:
        return [], []
    path = resolve(contract_path, security.sdkconfig)
    try:
        values = read_sdkconfig(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return [f"{security.sdkconfig} unreadable: {exc}"], []
    problems: list[str] = []
    evidence = [f"sdkconfig {security.sdkconfig}"]
    if security.secure_boot:
        problems += _required(SECURE_BOOT, values, "secure_boot")
    if security.flash_encryption:
        problems += _required(FLASH_ENCRYPTION, values, "flash_encryption")
    for prop, keys in INSECURE.items():
        if getattr(security, prop):
            problems += [f"{prop} forbids {key}=y" for key in keys if values.get(key) == "y"]
    if security.ota_rollback:
        problems += _required(ROLLBACK, values, "ota_rollback")
        try:
            subtypes, source = ota_partitions(values, path.parent)
        except OSError as exc:
            problems.append(f"partition table unreadable: {exc}")
        else:
            missing = sorted(OTA_SUBTYPES - subtypes)
            if missing:
                problems.append(
                    f"ota_rollback needs partition subtypes {', '.join(missing)} ({source})"
                )
            else:
                evidence.append(f"OTA partitions from {source}")
    declared = [
        name
        for name in ("secure_boot", "flash_encryption", "ota_rollback", "jtag_disabled")
        if getattr(security, name)
    ]
    evidence.append(f"required: {', '.join(declared) or 'none'} ({security.rationale})")
    return problems, evidence
