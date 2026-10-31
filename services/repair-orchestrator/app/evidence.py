"""Durable content-addressed evidence with containment, byte caps, and redaction."""

import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from app.database import Database, utcnow
from app.runtime import RuntimeArtifact
from app.snapshots import contained_path
from shared.contracts.models import Artifact

_LIMITS = {
    "screenshot": 10 * 1024 * 1024,
    "trace": 25 * 1024 * 1024,
    "requests": 16 * 1024,
    "logs": 64 * 1024,
    "report": 64 * 1024,
    "proposal": 64 * 1024,
    "repro_spec": 64 * 1024,
    "diff": 16 * 1024,
    "proof_bundle": 128 * 1024,
    "proof_bundle_md": 128 * 1024,
}
_TYPES = frozenset(
    {"image/png", "application/zip", "application/json", "text/plain", "text/markdown"}
)


class ArtifactError(RuntimeError):
    """Required evidence could not be safely saved or verified."""


class EvidenceStore:
    """Register bytes only after an atomic file write and successful fsync."""

    def __init__(
        self, database: Database, data_root: Path, *, secrets: tuple[str, ...] = ()
    ) -> None:
        self.database = database
        self.data_root = data_root.resolve()
        self.secrets = tuple(secret for secret in secrets if secret)

    def redact(self, value: str) -> str:
        """Remove configured secret values before diagnostics leave memory."""
        for secret in self.secrets:
            value = value.replace(secret, "[redacted]")
        return re.sub(
            r"(?im)\b(authorization|cookie|set-cookie)\s*:\s*[^\r\n]*",
            r"\1: [redacted]",
            value,
        )

    def redact_value(self, value: Any) -> Any:
        """Redact nested diagnostic values without damaging JSON syntax."""
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, list):
            return [self.redact_value(item) for item in value]
        if isinstance(value, dict):
            return {
                key: "[redacted]"
                if key.lower() in {"authorization", "cookie", "set-cookie"}
                else self.redact_value(item)
                for key, item in value.items()
            }
        return value

    def save(
        self,
        job_id: str,
        evidence: RuntimeArtifact,
        *,
        execution_id: str | None = None,
        attempt_id: str | None = None,
    ) -> Artifact:
        """Persist allowlisted inert evidence under server-generated UUID paths."""
        try:
            if str(UUID(job_id)) != job_id:
                raise ArtifactError("Invalid job identity")
            limit = _LIMITS.get(evidence.role)
            if limit is None or evidence.content_type not in _TYPES:
                raise ArtifactError("Unsupported artifact role or media type")
            if not evidence.content or len(evidence.content) > limit:
                raise ArtifactError("Missing or oversized evidence")
            content = evidence.content
            if evidence.content_type == "application/json":
                content = json.dumps(
                    self.redact_value(json.loads(content)), ensure_ascii=False
                ).encode()
            elif evidence.content_type == "text/plain":
                content = self.redact(content.decode("utf-8")).encode()
            if len(content) > limit:
                raise ArtifactError("Redacted evidence exceeds its budget")
            artifact_id = str(uuid4())
            storage_key = f"jobs/{job_id}/artifacts/{artifact_id}"
            path = contained_path(self.data_root, storage_key)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            with temporary.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            artifact = Artifact(
                id=artifact_id,
                job_id=job_id,
                execution_id=execution_id,
                attempt_id=attempt_id,
                role=evidence.role,
                content_type=evidence.content_type,
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                storage_key=storage_key,
                created_at=utcnow(),
            )
            self.database.save_artifact(artifact)
            return artifact
        except (OSError, ValueError, sqlite3.Error) as exc:
            raise ArtifactError("Evidence persistence failed") from exc

    def read(self, artifact: Artifact) -> bytes:
        """Read only a registered contained file whose bytes still match its hash."""
        try:
            path = contained_path(self.data_root, artifact.storage_key)
            if not path.is_file() or path.stat().st_size != artifact.size_bytes:
                raise ArtifactError("Artifact size or existence check failed")
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != artifact.sha256:
                raise ArtifactError("Artifact checksum mismatch")
            return content
        except (OSError, ValueError) as exc:
            raise ArtifactError("Evidence containment or read failed") from exc

    def verify_job(self, job_id: str) -> None:
        """Confirm retained evidence before a verified outcome is finalized."""
        for artifact in self.database.list_artifacts(job_id):
            self.read(artifact)
