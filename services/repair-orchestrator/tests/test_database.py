"""Durability, atomic admission/locking, and immutable evidence records."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from conftest import Harness, submission

from app.database import Database, DatabaseError
from shared.contracts.models import JobMode, JobStage, JobState, TerminalOutcome


def test_job_crud_idempotency_and_terminal_immutability(harness: Harness) -> None:
    db = harness.database
    request = submission()
    job = db.create_job(request)
    assert job.state == JobState.QUEUED
    assert db.get_job(job.id) == job
    assert db.create_job(request) == job
    assert db.list_jobs() == [job]
    assert db.get_lease().job_id == job.id
    assert db.claim_job(job.id)
    assert not db.claim_job(job.id)
    db.transition(job.id, JobStage.BASELINE)
    assert db.get_job(job.id).stage == JobStage.BASELINE
    db.request_cancel(job.id)
    assert db.get_job(job.id).cancel_requested
    done = db.finish_job(job.id, TerminalOutcome.CANCELLED, clean=True)
    assert done.state == JobState.CANCELLED
    assert db.request_cancel(job.id) == done
    assert db.finish_job(job.id, TerminalOutcome.VERIFIED, clean=True) == done
    assert db.get_lease().owner_id is None
    with pytest.raises(DatabaseError, match="job_completed"):
        db.transition(job.id, JobStage.BASELINE)
    with pytest.raises(DatabaseError, match="not_found"):
        db.get_job(str(uuid4()))


def test_idempotency_conflict_precedes_busy(harness: Harness) -> None:
    request = submission()
    harness.database.create_job(request)
    with pytest.raises(DatabaseError, match="idempotency_conflict"):
        harness.database.create_job(request.model_copy(update={"mode": JobMode.DETECT}))
    with pytest.raises(DatabaseError, match="busy"):
        harness.database.create_job(submission())


def test_release_requires_owner_and_quarantine_requires_reset(harness: Harness) -> None:
    db = harness.database
    job = db.create_job(submission())
    assert not db.release_lease("someone-else")
    assert db.get_lease().job_id == job.id
    db.finish_job(job.id, TerminalOutcome.VERIFIED, clean=False)
    assert db.get_job(job.id).outcome == TerminalOutcome.CLEANUP_FAILED
    assert db.get_job(job.id).error_details == {"last_work_outcome": "verified"}
    assert not db.release_lease(job.id)
    with pytest.raises(DatabaseError, match="cleanup_required"):
        db.create_job(submission())
    reservation = db.begin_reset()
    assert reservation.owner_id
    db.finish_reset(reservation.owner_id, clean=False)
    assert db.get_lease().quarantined
    reservation = db.begin_reset()
    assert reservation.owner_id
    db.finish_reset(reservation.owner_id, clean=True)
    assert not db.get_lease().quarantined
    assert db.create_job(submission()).id != job.id


def test_new_reset_and_job_are_mutually_exclusive(harness: Harness) -> None:
    db = harness.database
    reset = db.begin_reset()
    assert reset.owner_id
    with pytest.raises(DatabaseError, match="busy"):
        db.create_job(submission())
    db.finish_reset(reset.owner_id, clean=True)
    job = db.create_job(submission())
    with pytest.raises(DatabaseError, match="busy"):
        db.begin_reset()
    assert db.release_lease(job.id)
    assert db.acquire_lease(job.id).job_id == job.id
    with pytest.raises(DatabaseError, match="busy"):
        db.acquire_lease(job.id)


def test_cross_connection_atomic_admission_and_rollback(tmp_path: Path) -> None:
    path = tmp_path / "faultline.db"
    connections = [Database(path) for _ in range(8)]
    try:

        def submit(db: Database) -> str:
            try:
                return db.create_job(submission()).id
            except DatabaseError as exc:
                return exc.code

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(submit, connections))
        assert results.count("busy") == 7
        assert len(connections[0].list_jobs()) == 1
        installation = connections[0].get_lease().installation_id
        connections[0].initialize()
        assert connections[0].get_lease().installation_id == installation
    finally:
        for db in connections:
            db.close()
    reopened = Database(path)
    assert len(reopened.unfinished_jobs()) == 1
    assert reopened.get_lease().installation_id == installation
    reopened.close()


def test_concurrent_same_key_creates_exactly_one_job(tmp_path: Path) -> None:
    connections = [Database(tmp_path / "faultline.db") for _ in range(4)]
    request = submission()
    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            ids = list(executor.map(lambda db: db.create_job(request).id, connections))
        assert len(set(ids)) == 1
        assert len(connections[0].list_events(ids[0])) == 1
    finally:
        for db in connections:
            db.close()


def test_events_are_atomic_and_monotonic(harness: Harness) -> None:
    db = harness.database
    job = db.create_job(submission())
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda _: db.transition(job.id, JobStage.BASELINE), range(25)))
    events = db.list_events(job.id, limit=100)
    assert [item.sequence for item in events] == list(range(1, 27))
    assert db.list_events(job.id, after=25) == events[-1:]
    assert db.get_job(job.id).stage == events[-1].stage


@pytest.mark.parametrize("limit", [0, 101, -1])
def test_list_bounds(harness: Harness, limit: int) -> None:
    with pytest.raises(ValueError):
        harness.database.list_jobs(limit)


@pytest.mark.parametrize(
    "field,value", [("scenario_id", "unknown"), ("idempotency_key", "not-a-uuid")]
)
def test_admission_rejects_invalid_inputs(harness: Harness, field: str, value: str) -> None:
    with pytest.raises(DatabaseError):
        harness.database.create_job(submission().model_copy(update={field: value}))
    assert harness.database.list_jobs() == []


async def test_reports_attempts_and_artifacts_remain_durable(harness: Harness) -> None:
    job = await harness.run()
    assert job.outcome == TerminalOutcome.VERIFIED
    executions = harness.database.list_executions(job.id)
    assert len(executions) == 2
    with pytest.raises(sqlite3.IntegrityError):
        harness.database.save_execution(executions[0])
    assert harness.database.list_executions(job.id) == executions
    assert len(harness.database.list_attempts(job.id)) == 1
    artifact = harness.database.list_artifacts(job.id)[0]
    assert harness.database.get_artifact(artifact.id) == artifact
    with pytest.raises(sqlite3.IntegrityError):
        harness.database.save_artifact(artifact)
