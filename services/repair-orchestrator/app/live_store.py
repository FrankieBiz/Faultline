"""Operator-triggered delivery of a verified candidate to the locally running store.

FaultLine never deploys or pushes (F8). Delivery writes only the showcase
fixture's working-tree file, which the launcher's hot-reloading store picks up,
and only from a job whose isolated candidate passed with confirmed cleanup.
State is read from file hashes on every request, so it cannot drift from disk.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app import cli
from app.database import Database, DatabaseError
from shared.config import REGISTRY
from shared.contracts.models import CleanupStatus, JobState, TerminalOutcome

MARKER = "live-store.json"


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _marker(data_dir: Path) -> dict[str, Any] | None:
    try:
        value = json.loads((data_dir / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def status(data_dir: Path, url: str) -> dict[str, Any]:
    """Classify the live checkout source as seeded, FaultLine-patched, or modified."""
    current = _sha256(cli.TARGET_FILE)
    marker = _marker(data_dir)
    if current is None:
        state = "missing"
    elif current == _sha256(cli.SEEDED_FILE):
        state = "seeded"
    elif marker is not None and marker.get("sha256") == current:
        state = "patched"
    else:
        state = "modified"
    patched = state == "patched" and marker is not None
    return {
        "state": state,
        "target_file": str(cli.TARGET_FILE.relative_to(cli.REPOSITORY_ROOT)),
        "sha256": current,
        "applied_job_id": marker.get("job_id") if patched and marker else None,
        "applied_at": marker.get("applied_at") if patched and marker else None,
        "url": url,
    }


def apply(job_id: str, database: Database, data_dir: Path, url: str) -> dict[str, Any]:
    """Apply a verified job's diff to the seeded store, recording which job it was."""
    job = database.get_job(job_id)
    scenario = REGISTRY.get(job.scenario_id)
    if scenario is None or scenario.executor != "checkout":
        # Project-runner jobs patch another repository; this delivers only the store.
        raise DatabaseError("delivery_unsupported", 409, job_id)
    if (
        job.state != JobState.SUCCEEDED
        or job.outcome != TerminalOutcome.VERIFIED
        or job.cleanup_status != CleanupStatus.SUCCEEDED
    ):
        raise DatabaseError("unverified_job", 409, job_id)
    if status(data_dir, url)["state"] != "seeded":
        # A diff verified against the seed applies only to the seed.
        raise DatabaseError("store_not_seeded", 409, job_id)
    result = cli.apply_patch_for_job(job_id, database=database)
    if not result.get("success"):
        raise DatabaseError(str(result.get("error_code", "apply_failed")), 409, job_id)
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / MARKER).write_text(
        json.dumps(
            {
                "job_id": job_id,
                "sha256": _sha256(cli.TARGET_FILE),
                "applied_at": datetime.now(UTC).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    return {"status": "applied", "store": status(data_dir, url)}


def revert(data_dir: Path, url: str) -> dict[str, Any]:
    """Restore the seeded defect so the next run reproduces it again."""
    result = cli.revert_to_seeded()
    if not result.get("success"):
        raise DatabaseError(str(result.get("error_code", "revert_failed")), 500)
    (data_dir / MARKER).unlink(missing_ok=True)
    return {"status": "reverted", "store": status(data_dir, url)}
