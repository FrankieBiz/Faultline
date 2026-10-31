"""Transactional SQLite persistence for the single-owner repair workflow.

Connections may be shared with FastAPI's thread pool. A reentrant lock protects
each connection, while BEGIN IMMEDIATE arbitrates admission between connections
and processes. No transaction spans an await or an external side effect.
"""

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import UUID, uuid4

from shared.config import REGISTRY
from shared.contracts.models import (
    Artifact,
    CleanupStatus,
    ExecutionRecord,
    JobEvent,
    JobMode,
    JobRequest,
    JobStage,
    JobState,
    OrchestratorJob,
    RepairAttempt,
    RuntimeLease,
    TerminalOutcome,
)

MAX_EVENT_SEQUENCE = 2**63 - 1

TERMINAL_STATES = frozenset(
    {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED, JobState.INTERRUPTED}
)


def utcnow() -> datetime:
    """Return a timezone-aware UTC timestamp for durable records."""
    return datetime.now(UTC)


class DatabaseError(Exception):
    """A safe, structured conflict or lookup failure for the controller."""

    def __init__(self, code: str, status_code: int, job_id: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.job_id = job_id


class Database:
    """Store canonical typed records and a singleton quarantinable lease."""

    def __init__(
        self, path: str | Path = "data/faultline.db", *, scenario_ids: set[str] | None = None
    ) -> None:
        self.scenario_ids = set(REGISTRY) if scenario_ids is None else set(scenario_ids)
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._connection = sqlite3.connect(
            self.path, isolation_level=None, check_same_thread=False, timeout=5
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self.initialize()

    def initialize(self) -> None:
        """Apply the initial versioned schema; repeated initialization is safe."""
        with self._lock:
            version = self._connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise RuntimeError("Unsupported database schema version")
            self._connection.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    fingerprint TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS executions (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(id),
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS repair_attempts (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(id),
                    attempt_number INTEGER NOT NULL CHECK(attempt_number BETWEEN 1 AND 2),
                    payload TEXT NOT NULL,
                    UNIQUE(job_id, attempt_number)
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(id),
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS job_events (
                    job_id TEXT NOT NULL REFERENCES jobs(id),
                    sequence INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY(job_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS runtime_leases (
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                    job_id TEXT REFERENCES jobs(id),
                    owner_id TEXT,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS jobs_created_at ON jobs(created_at DESC);
                PRAGMA user_version = 1;
                COMMIT;
                """
            )
            with self._transaction():
                lease = RuntimeLease(
                    installation_id=str(uuid4()),
                    job_id=None,
                    owner_id=None,
                    generation_id=str(uuid4()),
                    quarantined=False,
                    updated_at=utcnow(),
                )
                self._connection.execute(
                    "INSERT OR IGNORE INTO runtime_leases VALUES (1, NULL, NULL, ?)",
                    (lease.model_dump_json(),),
                )

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    def close(self) -> None:
        """Close the owned connection after worker and streams have stopped."""
        with self._lock:
            self._connection.close()

    def _job(self, job_id: str) -> OrchestratorJob:
        row = self._connection.execute(
            "SELECT payload FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if row is None:
            raise DatabaseError("not_found", 404, job_id)
        return OrchestratorJob.model_validate_json(row[0])

    def _save_job(self, job: OrchestratorJob) -> None:
        self._connection.execute(
            "UPDATE jobs SET state = ?, payload = ? WHERE id = ?",
            (job.state.value, job.model_dump_json(), job.id),
        )

    def get_job(self, job_id: str) -> OrchestratorJob:
        """Read a fresh validated snapshot or raise a safe not-found error."""
        with self._lock:
            return self._job(job_id)

    def list_jobs(self, limit: int = 20) -> list[OrchestratorJob]:
        """Return newest submissions first, bounded to at most one hundred."""
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        with self._lock:
            return [
                OrchestratorJob.model_validate_json(row[0])
                for row in self._connection.execute(
                    "SELECT payload FROM jobs ORDER BY created_at DESC, rowid DESC LIMIT ?",
                    (limit,),
                )
            ]

    def unfinished_jobs(self) -> list[OrchestratorJob]:
        """Find all crash-recovery candidates without truncating job history."""
        with self._lock:
            return [
                OrchestratorJob.model_validate_json(row[0])
                for row in self._connection.execute(
                    "SELECT payload FROM jobs WHERE state IN ('queued', 'running')"
                )
            ]

    def _lease(self) -> RuntimeLease:
        row = self._connection.execute(
            "SELECT payload FROM runtime_leases WHERE singleton = 1"
        ).fetchone()
        return RuntimeLease.model_validate_json(row[0])

    def get_lease(self) -> RuntimeLease:
        """Read the durable lease, including installation identity."""
        with self._lock:
            return self._lease()

    def _save_lease(self, lease: RuntimeLease) -> None:
        self._connection.execute(
            "UPDATE runtime_leases SET job_id = ?, owner_id = ?, payload = ? WHERE singleton = 1",
            (lease.job_id, lease.owner_id, lease.model_dump_json()),
        )

    def _acquire(self, job_id: str | None, owner_id: str) -> RuntimeLease:
        lease = self._lease()
        if lease.quarantined:
            raise DatabaseError("cleanup_required", 503, lease.job_id)
        if lease.owner_id is not None:
            raise DatabaseError("busy", 409, lease.job_id)
        lease = lease.model_copy(
            update={
                "job_id": job_id,
                "owner_id": owner_id,
                "generation_id": str(uuid4()),
                "updated_at": utcnow(),
            }
        )
        self._save_lease(lease)
        return lease

    def acquire_lease(self, job_id: str, owner_id: str | None = None) -> RuntimeLease:
        """Atomically acquire the only runtime; never steal an existing lease."""
        with self._transaction():
            self._job(job_id)
            return self._acquire(job_id, owner_id or job_id)

    def release_lease(self, owner_id: str) -> bool:
        """Release only the matching, clean owner; quarantine cannot be bypassed."""
        with self._transaction():
            lease = self._lease()
            if lease.owner_id != owner_id or lease.quarantined:
                return False
            self._save_lease(
                lease.model_copy(update={"job_id": None, "owner_id": None, "updated_at": utcnow()})
            )
            return True

    def begin_reset(self) -> RuntimeLease:
        """Reserve idle maintenance, allowing an explicit quarantine recovery."""
        with self._transaction():
            lease = self._lease()
            active = self._connection.execute(
                "SELECT id FROM jobs WHERE state IN ('queued', 'running') LIMIT 1"
            ).fetchone()
            reset_active = lease.owner_id is not None and lease.owner_id.startswith("reset:")
            if (
                active is not None
                or reset_active
                or (lease.owner_id is not None and not lease.quarantined)
            ):
                raise DatabaseError("busy", 409, active[0] if active else lease.job_id)
            lease = lease.model_copy(
                update={"owner_id": f"reset:{uuid4()}", "updated_at": utcnow()}
            )
            self._save_lease(lease)
            return lease

    def finish_reset(self, owner_id: str, *, clean: bool) -> None:
        """Clear quarantine only after the reset owner confirms resource cleanup."""
        with self._transaction():
            lease = self._lease()
            if lease.owner_id != owner_id:
                raise DatabaseError("lease_mismatch", 409)
            self._save_lease(
                lease.model_copy(
                    update={
                        # A finished reset releases maintenance ownership even if
                        # cleanup failed; quarantine still prevents job admission.
                        "owner_id": None,
                        "job_id": None if clean else lease.job_id,
                        "quarantined": not clean,
                        "updated_at": utcnow(),
                    }
                )
            )

    @staticmethod
    def fingerprint(request: JobRequest) -> str:
        """Fingerprint semantic input independently of the retry key."""
        value = json.dumps([request.scenario_id, request.mode.value], separators=(",", ":"))
        return hashlib.sha256(value.encode()).hexdigest()

    def find_idempotent(self, request: JobRequest) -> OrchestratorJob | None:
        """Resolve retries before readiness/busy admission checks."""
        with self._lock:
            row = self._connection.execute(
                "SELECT payload FROM jobs WHERE idempotency_key = ?", (request.idempotency_key,)
            ).fetchone()
            if row is None:
                return None
            job = OrchestratorJob.model_validate_json(row[0])
            if job.request_fingerprint != self.fingerprint(request):
                raise DatabaseError("idempotency_conflict", 409, job.id)
            return job

    def create_job(
        self,
        request: JobRequest,
        *,
        effective_mode: JobMode | None = None,
        repair_block_reason: str | None = None,
    ) -> OrchestratorJob:
        """Atomically persist admission, reserve the lease, and emit event one."""
        if request.scenario_id not in self.scenario_ids:
            raise DatabaseError("unknown_scenario", 422)
        try:
            UUID(request.idempotency_key)
        except ValueError as exc:
            raise DatabaseError("invalid_idempotency_key", 422) from exc
        with self._transaction():
            existing = self.find_idempotent(request)
            if existing is not None:
                return existing
            job_id = str(uuid4())
            timestamp = utcnow()
            job = OrchestratorJob(
                id=job_id,
                scenario_id=request.scenario_id,
                state=JobState.QUEUED,
                stage=JobStage.PREPARING,
                cleanup_status=CleanupStatus.NOT_STARTED,
                created_at=timestamp,
                updated_at=timestamp,
                idempotency_key=request.idempotency_key,
                request_fingerprint=self.fingerprint(request),
                requested_mode=request.mode,
                effective_mode=effective_mode or request.mode,
                repair_block_reason=repair_block_reason,
            )
            self._connection.execute(
                "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?)",
                (
                    job.id,
                    job.idempotency_key,
                    job.request_fingerprint,
                    job.state.value,
                    timestamp.isoformat(),
                    job.model_dump_json(),
                ),
            )
            self._acquire(job.id, job.id)
            self._event(job, "queued", "Job accepted.")
            return job

    def claim_job(self, job_id: str) -> bool:
        """Transition a reserved queued job once; duplicate workers cannot run it."""
        with self._transaction():
            job = self._job(job_id)
            lease = self._lease()
            if job.state != JobState.QUEUED or lease.job_id != job_id or lease.quarantined:
                return False
            self._save_job(
                job.model_copy(update={"state": JobState.RUNNING, "updated_at": utcnow()})
            )
            return True

    def update_job(self, job_id: str, **changes: Any) -> OrchestratorJob:
        """Update controller-owned metadata without permitting identity changes."""
        allowed = {
            "deadline_at",
            "seed_commit",
            "seed_source_hash",
            "fixture_version",
            "scenario_version",
            "baseline_execution_id",
            "cleanup_status",
            "error_details",
        }
        if not changes.keys() <= allowed:
            raise ValueError("Only controller metadata can be updated")
        with self._transaction():
            job = self._job(job_id)
            if job.state in TERMINAL_STATES:
                raise DatabaseError("job_completed", 409, job_id)
            job = OrchestratorJob.model_validate(
                {**job.model_dump(), **changes, "updated_at": utcnow()}
            )
            self._save_job(job)
            return job

    def _event(self, job: OrchestratorJob, code: str, message: str) -> JobEvent:
        row = self._connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM job_events WHERE job_id = ?", (job.id,)
        ).fetchone()
        event = JobEvent(
            job_id=job.id,
            sequence=row[0],
            timestamp=utcnow(),
            stage=job.stage,
            message_code=code,
            message=message,
        )
        self._connection.execute(
            "INSERT INTO job_events VALUES (?, ?, ?)",
            (job.id, event.sequence, event.model_dump_json()),
        )
        return event

    def transition(self, job_id: str, stage: JobStage, code: str | None = None) -> JobEvent:
        """Commit a stage and its observable event in the same transaction."""
        with self._transaction():
            job = self._job(job_id)
            if job.state in TERMINAL_STATES:
                raise DatabaseError("job_completed", 409, job_id)
            job = job.model_copy(update={"stage": stage, "updated_at": utcnow()})
            self._save_job(job)
            return self._event(job, code or stage.value, f"Entered {stage.value}.")

    def list_events(self, job_id: str, after: int = 0, limit: int = 100) -> list[JobEvent]:
        """Replay an ordered, bounded SSE batch after a committed sequence."""
        if not 0 <= after <= MAX_EVENT_SEQUENCE or not 1 <= limit <= 1000:
            raise ValueError("Invalid event cursor or limit")
        with self._lock:
            self._job(job_id)
            return [
                JobEvent.model_validate_json(row[0])
                for row in self._connection.execute(
                    "SELECT payload FROM job_events WHERE job_id = ? AND sequence > ? "
                    "ORDER BY sequence LIMIT ?",
                    (job_id, after, limit),
                )
            ]

    def request_cancel(self, job_id: str) -> OrchestratorJob:
        """Persist cancellation intent; completed history is immutable."""
        with self._transaction():
            job = self._job(job_id)
            if job.state not in TERMINAL_STATES and not job.cancel_requested:
                job = job.model_copy(update={"cancel_requested": True, "updated_at": utcnow()})
                self._save_job(job)
                self._event(job, "cancel_requested", "Cancellation requested.")
            return job

    def finish_job(
        self,
        job_id: str,
        outcome: TerminalOutcome,
        *,
        clean: bool,
        error_details: dict[str, Any] | None = None,
    ) -> OrchestratorJob:
        """Finalize and release atomically; failed cleanup quarantines the lease."""
        with self._transaction():
            job = self._job(job_id)
            if job.state in TERMINAL_STATES:
                return job
            lease = self._lease()
            if lease.job_id != job_id:
                raise DatabaseError("lease_mismatch", 409, job_id)
            if not clean:
                error_details = {**(error_details or {}), "last_work_outcome": outcome.value}
                outcome = TerminalOutcome.CLEANUP_FAILED
            state = JobState.FAILED
            if outcome in {
                TerminalOutcome.VERIFIED,
                TerminalOutcome.DETECTED,
                TerminalOutcome.NO_FAILURE,
            }:
                state = JobState.SUCCEEDED
            elif outcome == TerminalOutcome.CANCELLED:
                state = JobState.CANCELLED
            elif outcome == TerminalOutcome.INTERRUPTED:
                state = JobState.INTERRUPTED
            job = job.model_copy(
                update={
                    "state": state,
                    "stage": JobStage.COMPLETED,
                    "outcome": outcome,
                    "cleanup_status": CleanupStatus.SUCCEEDED if clean else CleanupStatus.FAILED,
                    "updated_at": utcnow(),
                    "error_details": error_details,
                }
            )
            self._save_job(job)
            self._event(job, outcome.value, f"Job completed: {outcome.value}.")
            self._save_lease(
                lease.model_copy(
                    update={
                        "job_id": None if clean else job_id,
                        "owner_id": None if clean else lease.owner_id,
                        "quarantined": not clean,
                        "updated_at": utcnow(),
                    }
                )
            )
            return job

    def save_execution(self, execution: ExecutionRecord) -> None:
        """Insert immutable runner evidence; duplicate IDs never overwrite reports."""
        with self._transaction():
            self._job(execution.job_id)
            self._connection.execute(
                "INSERT INTO executions VALUES (?, ?, ?)",
                (execution.report.execution_id, execution.job_id, execution.model_dump_json()),
            )

    def list_executions(self, job_id: str) -> list[ExecutionRecord]:
        """Read every completed execution in insertion order."""
        with self._lock:
            self._job(job_id)
            return [
                ExecutionRecord.model_validate_json(row[0])
                for row in self._connection.execute(
                    "SELECT payload FROM executions WHERE job_id = ? ORDER BY rowid", (job_id,)
                )
            ]

    def save_attempt(self, attempt: RepairAttempt) -> None:
        """Insert or update one attempt, preserving its identity and job binding."""
        with self._transaction():
            row = self._connection.execute(
                "SELECT job_id, attempt_number FROM repair_attempts WHERE id = ?", (attempt.id,)
            ).fetchone()
            if row is not None and (row[0], row[1]) != (attempt.job_id, attempt.attempt_number):
                raise ValueError("Attempt identity is immutable")
            self._connection.execute(
                "INSERT INTO repair_attempts VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload",
                (attempt.id, attempt.job_id, attempt.attempt_number, attempt.model_dump_json()),
            )

    def list_attempts(self, job_id: str) -> list[RepairAttempt]:
        """Read the bounded attempt history in generation order."""
        with self._lock:
            self._job(job_id)
            return [
                RepairAttempt.model_validate_json(row[0])
                for row in self._connection.execute(
                    "SELECT payload FROM repair_attempts WHERE job_id = ? ORDER BY attempt_number",
                    (job_id,),
                )
            ]

    def save_artifact(self, artifact: Artifact) -> None:
        """Register already durable evidence without overwriting an existing ID."""
        with self._transaction():
            self._connection.execute(
                "INSERT INTO artifacts VALUES (?, ?, ?)",
                (artifact.id, artifact.job_id, artifact.model_dump_json()),
            )

    def get_artifact(self, artifact_id: str) -> Artifact:
        """Resolve a server-owned artifact ID to private storage metadata."""
        with self._lock:
            row = self._connection.execute(
                "SELECT payload FROM artifacts WHERE id = ?", (artifact_id,)
            ).fetchone()
            if row is None:
                raise DatabaseError("not_found", 404)
            return Artifact.model_validate_json(row[0])

    def list_artifacts(self, job_id: str) -> list[Artifact]:
        """Return registration metadata, never arbitrary directory listings."""
        with self._lock:
            self._job(job_id)
            return [
                Artifact.model_validate_json(row[0])
                for row in self._connection.execute(
                    "SELECT payload FROM artifacts WHERE job_id = ? ORDER BY rowid", (job_id,)
                )
            ]
