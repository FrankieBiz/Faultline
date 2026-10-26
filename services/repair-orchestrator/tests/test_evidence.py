"""Evidence bytes, checksums, private containment, and secret redaction."""

from pathlib import Path

import pytest
from conftest import Harness, submission

from app.evidence import ArtifactError, EvidenceStore
from app.runtime import RuntimeArtifact


def test_artifact_bytes_are_durable_and_checked(harness: Harness) -> None:
    job = harness.database.create_job(submission())
    artifact = harness.evidence.save(job.id, RuntimeArtifact("logs", "text/plain", b"real log"))
    assert harness.evidence.read(artifact) == b"real log"
    path = harness.root / artifact.storage_key
    path.write_bytes(b"fake log")
    with pytest.raises(ArtifactError, match="checksum"):
        harness.evidence.read(artifact)


def test_secret_redaction_and_evidence_budgets(harness: Harness) -> None:
    store = EvidenceStore(harness.database, harness.root, secrets=("private-token",))
    job = harness.database.create_job(submission())
    artifact = store.save(job.id, RuntimeArtifact("logs", "text/plain", b"failure private-token"))
    assert store.read(artifact) == b"failure [redacted]"
    for evidence in [
        RuntimeArtifact("logs", "text/html", b"<script>"),
        RuntimeArtifact("unknown", "text/plain", b"test"),
        RuntimeArtifact("logs", "text/plain", b"x" * 65537),
        RuntimeArtifact("logs", "text/plain", b""),
    ]:
        with pytest.raises(ArtifactError):
            store.save(job.id, evidence)


def test_artifact_path_traversal_and_symlinks_are_rejected(
    harness: Harness, tmp_path: Path
) -> None:
    job = harness.database.create_job(submission())
    artifact = harness.evidence.save(job.id, RuntimeArtifact("logs", "text/plain", b"log"))
    with pytest.raises(ArtifactError):
        harness.evidence.read(artifact.model_copy(update={"storage_key": "../../secret"}))
    path = harness.root / artifact.storage_key
    path.unlink()
    target = tmp_path / "outside"
    target.write_bytes(b"log")
    path.symlink_to(target)
    with pytest.raises(ArtifactError):
        harness.evidence.read(artifact)
