"""Software bill of materials: declared components, hashed, and vendored-code coverage.

``fw.sbom`` fails when a declared component path is missing or when a file
under a conventional vendored-code directory of the build tree is not
covered by a declared component. ``firmware sbom`` writes a deterministic
CycloneDX 1.5 JSON (no timestamp, no serial number) of the declared
components with SHA-256 tree hashes.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .contract import Component, FirmwareContract, resolve

VENDOR_DIRS = frozenset(
    {"lib", "libs", "third_party", "vendor", "external", "components", "Drivers", "Middlewares"}
)
SKIP_DIRS = frozenset({"build", "out"})


def _files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(p for p in path.rglob("*") if p.is_file())


def tree_sha256(path: Path) -> str:
    """Hash of a file, or of a directory's sorted ``relative-path NUL file-sha256`` lines."""
    if path.is_file():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    digest = hashlib.sha256()
    for file in _files(path):
        rel = file.relative_to(path).as_posix()
        digest.update(f"{rel}\0{hashlib.sha256(file.read_bytes()).hexdigest()}\n".encode())
    return digest.hexdigest()


def vendored_files(build_dir: Path) -> list[Path]:
    """Files under a conventional vendored-code directory of the build tree."""
    found: list[Path] = []
    if not build_dir.is_dir():
        return found
    for file in sorted(build_dir.rglob("*")):
        parts = file.relative_to(build_dir).parts
        if not file.is_file() or any(p.startswith(".") or p in SKIP_DIRS for p in parts):
            continue
        if any(p in VENDOR_DIRS for p in parts[:-1]):
            found.append(file)
    return found


def component_problems(
    contract: FirmwareContract, contract_path: Path
) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    evidence: list[str] = []
    covered: list[Path] = []
    for component in contract.components:
        for rel in component.paths:
            path = resolve(contract_path, rel)
            if not path.exists():
                problems.append(f"component {component.name}: {rel} missing")
                continue
            covered.append(path.resolve())
            evidence.append(f"{component.name} {component.version} {rel} {tree_sha256(path)}")
    build_dir = resolve(contract_path, contract.build.dir)
    for file in vendored_files(build_dir):
        real = file.resolve()
        if not any(real == c or c in real.parents for c in covered):
            rel = file.relative_to(contract_path.parent).as_posix()
            problems.append(f"vendored file {rel} is not covered by a declared component")
    if not contract.components and not problems:
        evidence.append("no third-party components declared or vendored")
    return problems, evidence


def _component_entry(component: Component, contract_path: Path) -> dict[str, Any]:
    hashes = [
        {"alg": "SHA-256", "content": tree_sha256(resolve(contract_path, rel))}
        for rel in component.paths
    ]
    return {
        "type": "library",
        "bom-ref": component.name,
        "name": component.name,
        "version": component.version,
        "supplier": {"name": component.supplier},
        "licenses": [{"expression": component.license}],
        "hashes": hashes,
        "externalReferences": [{"type": "vcs", "url": component.source}],
        "properties": [{"name": "vibebb:path", "value": rel} for rel in component.paths],
    }


def cyclonedx(contract: FirmwareContract, contract_path: Path) -> dict[str, Any]:
    """CycloneDX 1.5 BOM of the declared components; raises when the gate would fail."""
    problems, _ = component_problems(contract, contract_path)
    if problems:
        raise ValueError("; ".join(problems))
    contract_sha = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    components = sorted(contract.components, key=lambda c: c.name)
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "component": {
                "type": "firmware",
                "bom-ref": contract.name,
                "name": contract.name,
                "hashes": [{"alg": "SHA-256", "content": contract_sha}],
                "properties": [
                    {"name": "vibebb:mcu_profile", "value": contract.mcu.profile},
                ],
            }
        },
        "components": [_component_entry(c, contract_path) for c in components],
        "dependencies": [{"ref": contract.name, "dependsOn": [c.name for c in components]}],
    }
