"""Workflow asset-path drift tests."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))

PLUGIN_PATH = re.compile(r"plugins/firmware(?:/[\w\-/*{}.,]+)?")

GENERATED = {"plugins/firmware/tools-image.json"}


def test_workflows_exist() -> None:
    assert WORKFLOWS, "no workflow files found"


def test_plugin_paths_referenced_exist() -> None:
    missing: list[str] = []
    for workflow in WORKFLOWS:
        text = workflow.read_text(encoding="utf-8")
        # `\.` regex escapes inside workflow grep patterns are not separate
        # paths; unescape so e.g. tools-image\.json still resolves to the
        # generated tools-image.json.
        for literal in PLUGIN_PATH.findall(text.replace("\\.", ".")):
            path = literal.rstrip(".,'\"")
            if path in GENERATED:
                continue
            if "*" in path:
                if not list(REPO_ROOT.glob(path)):
                    missing.append(f"{workflow.name}: {path}")
            elif not (REPO_ROOT / path).exists():
                missing.append(f"{workflow.name}: {path}")
    assert not missing, f"workflow references missing paths: {missing}"


def test_locked_image_workflows_run_firmware_launcher() -> None:
    publish = (REPO_ROOT / ".github" / "workflows" / "publish-firmware-images.yml").read_text(
        encoding="utf-8"
    )
    locked = (REPO_ROOT / ".github" / "workflows" / "locked-image-check.yml").read_text(
        encoding="utf-8"
    )
    for text in (publish, locked):
        assert "plugins/firmware/scripts/firmware_launcher.py" in text
        assert "FIRMWARE_SRC" in text
        assert "lamp_selftest" in text
    assert "FIRMWARE_TOOLS_IMAGE" in publish
    assert "FIRMWARE_TOOLS_IMAGE" not in locked


def test_e2e_prints_gate_report_before_enforcing_exit_status() -> None:
    text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    step = text.split("      - name: Full gates in the image (no network)\n", 1)[1].split(
        "      - name: Upload reports", 1
    )[0]
    capture = step.index('if python3 "$launcher" gates "$contract" > report.json; then')
    status = step.index("gate_status=$?", capture)
    print_table = step.index('for check in report["checks"]:', status)
    enforce = step.index(
        'sys.exit(0 if gate_status == 0 and report["verdict"] == "pass" else 1)',
        print_table,
    )
    assert capture < status < print_table < enforce


def test_publisher_retriggers_for_workflow_changes_and_attests_images() -> None:
    text = (REPO_ROOT / ".github" / "workflows" / "publish-firmware-images.yml").read_text(
        encoding="utf-8"
    )
    assert '".github/workflows/publish-firmware-images.yml"' in text
    assert '"scripts/update_image_digest_lock.py"' in text
    assert "actions/attest-build-provenance@4d101475d8b20a2381f78447822ac1eab6504dd8" in text
    assert '--attestation "$ATTESTATION_URL"' in text


def test_publish_dry_run_skips_only_irreversible_steps() -> None:
    text = (REPO_ROOT / ".github" / "workflows" / "publish-firmware-images.yml").read_text(
        encoding="utf-8"
    )
    assert "      dry_run:\n        description:" in text
    for name in (
        "Promote :latest",
        "Attest tools image provenance",
        "Attest tools SBOM",
        "Update digest lock and merge PR",
    ):
        step = text.split(f"      - name: {name}\n", 1)[1].split("      - name:", 1)[0]
        assert "if: inputs.dry_run != true" in step, name
    assert "push: ${{ inputs.dry_run != true }}" in text
    assert "load: ${{ inputs.dry_run }}" in text
    sarif = text.split("      - name: Upload Trivy SARIF\n", 1)[1].split("      - name:", 1)[0]
    assert "inputs.dry_run != true" in sarif
    # The gate chain still runs: Trivy scans, SBOM generation, measurement,
    # and the launcher smoke carry no dry_run skip.
    for name in (
        "Scan tools image (Trivy SARIF)",
        "Scan tools image (Trivy JSON)",
        "Generate tools SPDX SBOM",
        "Measure published tools",
        "Verify published tools smoke",
    ):
        step = text.split(f"      - name: {name}\n", 1)[1].split("      - name:", 1)[0]
        assert "inputs.dry_run != true" not in step, name


def test_locked_image_check_validates_provenance_and_uploads_smoke_artifacts() -> None:
    text = (REPO_ROOT / ".github" / "workflows" / "locked-image-check.yml").read_text(
        encoding="utf-8"
    )
    assert 're.fullmatch(r"sha256:[0-9a-f]{64}", digest)' in text
    assert "gh attestation verify" in text
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in text
