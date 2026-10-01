from pathlib import Path

import pytest
from scripts.print_locked_image import locked_image
from scripts.update_image_digest_lock import update_lock


def _update(path: Path, sbom_attestation: str) -> str:
    digest = f"sha256:{'b' * 64}"
    update_lock(
        path,
        entry="firmware_tools",
        image="ghcr.io/vibebb/firmware-tools",
        tag=f"{'a' * 40}-tools",
        digest=digest,
        published_at="2026-10-01T00:00:00Z",
        workflow_run="https://github.com/VibeBB/firmware-agent/actions/runs/1",
        dockerfile="docker/firmware-tools.Dockerfile",
        tools={"python": "3.12"},
        sbom_attestation=sbom_attestation,
    )
    return digest


def test_sbom_attestation_is_written_and_readers_accept_it(tmp_path: Path) -> None:
    path = tmp_path / "image-digests.json"
    url = "https://github.com/VibeBB/firmware-agent/attestations/sbom"
    digest = _update(path, url)

    assert locked_image(path, "firmware_tools") == f"ghcr.io/vibebb/firmware-tools@{digest}"


@pytest.mark.parametrize(
    "url",
    ["http://example.test/attestation", "https://"],
)
def test_sbom_attestation_requires_https(tmp_path: Path, url: str) -> None:
    with pytest.raises(ValueError, match="sbom_attestation"):
        _update(tmp_path / "image-digests.json", url)
