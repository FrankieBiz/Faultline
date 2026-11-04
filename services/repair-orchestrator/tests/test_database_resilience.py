"""WAL contention, lease fencing, process death, and durable cleanup recovery."""

import asyncio
import json
import shutil
import signal
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier, Event
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from conftest import Harness, submission

from app.database import LEASE_TIMEOUT, Database, DatabaseError
from app.isolated_runtime import IsolatedRuntime
from app.runtime import RuntimeUnavailable
from app.worker import HEARTBEAT_SECONDS, RepairWorker
from shared.contracts.models import JobStage, JobState, TerminalOutcome


def test_open_observer_during_write_transaction(tmp_path: Path) -> None:
    writer = Database(tmp_path / "wal.db")
    job = writer.create_job(submission())
    try:
        with writer._transaction():
            writer.claim_job(job.id)
            observer = Database(writer.path)
            try:
                assert observer.get_job(job.id).state == JobState.QUEUED
            finally:
                observer.close()
    finally:
        writer.close()


async def test_recovery_scope_failure_preserves_quarantine(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = harness.database.create_job(submission())
    harness.database.claim_job(job.id)
    monkeypatch.setattr(harness.runtime, "reconcile", AsyncMock(side_effect=RuntimeError("scope")))
    with pytest.raises(RuntimeError, match="scope"):
        await harness.worker.reconcile()
    assert harness.database.get_lease().quarantined
    with pytest.raises(DatabaseError, match="cleanup_required"):
        harness.database.create_job(submission())


async def test_recovery_attempts_snapshot_cleanup_after_runtime_failure(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = harness.database.create_job(submission())
    monkeypatch.setattr(harness.runtime, "cleanup", AsyncMock(side_effect=RuntimeError("runtime")))
    snapshots = AsyncMock()
    monkeypatch.setattr(harness.snapshots, "cleanup", snapshots)
    await harness.worker.reconcile()
    snapshots.assert_awaited_once_with(job.id)
    assert harness.database.get_lease().quarantined


async def test_cancelled_recovery_preserves_quarantine(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness.database.create_job(submission())
    entered = asyncio.Event()

    async def blocked(_: str) -> None:
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(harness.runtime, "reconcile", blocked)
    task = asyncio.create_task(harness.worker.reconcile())
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert harness.database.get_lease().quarantined


def test_pinned_wal_reader_does_not_block_commit(tmp_path: Path) -> None:
    writer = Database(tmp_path / "wal.db")
    reader = sqlite3.connect(writer.path, isolation_level=None)
    job = writer.create_job(submission())
    try:
        assert reader.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        reader.execute("BEGIN")
        assert reader.execute("SELECT state FROM jobs").fetchone()[0] == "queued"
        assert writer.claim_job(job.id)
        assert reader.execute("SELECT state FROM jobs").fetchone()[0] == "queued"
        reader.commit()
        assert reader.execute("SELECT state FROM jobs").fetchone()[0] == "running"
    finally:
        reader.close()
        writer.close()


def test_wal_readers_and_writers_preserve_event_order(tmp_path: Path) -> None:
    connections = [Database(tmp_path / "wal.db") for _ in range(8)]
    job = connections[0].create_job(submission())
    barrier = Barrier(len(connections))

    def work(index: int) -> None:
        database = connections[index]
        barrier.wait(timeout=5)
        for _ in range(30):
            if index < 4:
                database.transition(job.id, JobStage.BASELINE)
            else:
                assert database.list_jobs()[0].id == job.id
                events = database.list_events(job.id, limit=1000)
                assert [event.sequence for event in events] == list(range(1, len(events) + 1))
                assert database.get_lease().job_id == job.id

    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(work, range(8)))
        assert len(connections[0].list_events(job.id, limit=1000)) == 121
    finally:
        for database in connections:
            database.close()


def test_writer_waits_for_contending_transaction(tmp_path: Path) -> None:
    first = Database(tmp_path / "wal.db")
    second = Database(first.path)
    job = first.create_job(submission())
    started = Event()

    def write() -> None:
        started.set()
        second.transition(job.id, JobStage.BASELINE)

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            with first._transaction():
                first.claim_job(job.id)
                pending = executor.submit(write)
                assert started.wait(2)
                assert not pending.done()
            pending.result(timeout=5)
        assert second.get_job(job.id).state == JobState.RUNNING
        assert len(second.list_events(job.id)) == 2
    finally:
        second.close()
        first.close()


def test_nested_rollback_does_not_poison_connection(tmp_path: Path) -> None:
    database = Database(tmp_path / "wal.db")
    job = database.create_job(submission())
    try:
        with database._transaction():
            database.claim_job(job.id)
            with pytest.raises(KeyboardInterrupt):
                with database._transaction():
                    database.transition(job.id, JobStage.BASELINE)
                    raise KeyboardInterrupt
        assert database.get_job(job.id).state == JobState.RUNNING
        assert len(database.list_events(job.id)) == 1
        database.transition(job.id, JobStage.DIAGNOSING)
        assert len(database.list_events(job.id)) == 2
        assert not database._connection.in_transaction
    finally:
        database.close()


def test_heartbeat_fences_owner_and_generation(harness: Harness) -> None:
    database = harness.database
    first = database.create_job(submission())
    lease = database.get_lease()
    assert lease.owner_id is not None
    assert not database.heartbeat_lease("wrong-owner", lease.generation_id)
    assert not database.heartbeat_lease(lease.owner_id, "wrong-generation")
    assert database.get_lease() == lease
    assert database.heartbeat_lease(lease.owner_id, lease.generation_id)
    assert database.get_lease().updated_at >= lease.updated_at
    database.finish_job(first.id, TerminalOutcome.INTERRUPTED, clean=True)
    database.acquire_lease(first.id, lease.owner_id)
    assert database.get_lease().generation_id != lease.generation_id
    assert not database.heartbeat_lease(lease.owner_id, lease.generation_id)


@pytest.mark.parametrize("heartbeat", [False, True])
def test_expired_lease_quarantines_without_stealing(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, heartbeat: bool
) -> None:
    database = harness.database
    database.create_job(submission())
    lease = database.get_lease()
    assert lease.owner_id is not None
    assert not database.expire_lease()
    monkeypatch.setattr("app.database.utcnow", lambda: lease.updated_at + LEASE_TIMEOUT)
    if heartbeat:
        assert not database.heartbeat_lease(lease.owner_id, lease.generation_id)
    else:
        assert database.expire_lease()
    expired = database.get_lease()
    assert expired.quarantined
    assert (expired.owner_id, expired.job_id, expired.generation_id) == (
        lease.owner_id,
        lease.job_id,
        lease.generation_id,
    )
    assert not database.expire_lease()
    assert not database.heartbeat_lease(lease.owner_id, lease.generation_id)
    assert not database.release_lease(lease.owner_id)
    with pytest.raises(DatabaseError, match="cleanup_required"):
        database.create_job(submission())


def test_idle_lease_does_not_expire(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    lease = harness.database.get_lease()
    monkeypatch.setattr("app.database.utcnow", lambda: lease.updated_at + timedelta(days=1))
    assert not harness.database.expire_lease()
    assert harness.database.get_lease() == lease


def test_worker_lock_excludes_controllers_but_allows_queries(tmp_path: Path) -> None:
    first = Database(tmp_path / "wal.db")
    second = Database(first.path)
    try:
        first.reserve_worker("first")
        first.reserve_worker("first")
        assert second.list_jobs() == []
        with pytest.raises(DatabaseError, match="worker_busy"):
            second.reserve_worker("second")
        first.release_worker("wrong-owner")
        with pytest.raises(DatabaseError, match="worker_busy"):
            first.reserve_worker("other")
        first.release_worker("first")
        second.reserve_worker("second")
        second.close()
        first.reserve_worker("first")
    finally:
        first.close()
        second.close()


async def test_second_worker_cannot_reconcile_live_resources(
    harness: Harness, tmp_path: Path
) -> None:
    first = Database(tmp_path / "wal.db")
    second = Database(first.path)
    original = harness.worker.database
    harness.worker.database = first
    other = RepairWorker(
        second, harness.adapter, harness.runtime, harness.snapshots, harness.evidence
    )
    try:
        await harness.worker.reconcile()
        job = first.create_job(submission())
        harness.runtime.calls.clear()
        with pytest.raises(DatabaseError, match="worker_busy"):
            await other.reconcile()
        assert harness.runtime.calls == []
        assert first.get_job(job.id).state == JobState.QUEUED
        assert not first.get_lease().quarantined
        await harness.worker.stop()
        await other.reconcile()
        assert first.get_job(job.id).state == JobState.INTERRUPTED
    finally:
        await other.stop()
        harness.worker.database = original
        first.close()
        second.close()


async def test_worker_heartbeats_during_blocked_work_and_cleanup(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert HEARTBEAT_SECONDS < 30
    monkeypatch.setattr("app.worker.HEARTBEAT_SECONDS", 0.01)
    harness.runtime.block_phase = "prepare"
    job = harness.database.create_job(submission())
    initial = harness.database.get_lease().updated_at
    task = asyncio.create_task(harness.worker.run_job(job.id))
    cleanup_entered = asyncio.Event()
    cleanup_release = asyncio.Event()

    async def cleanup(_: str, __: str) -> None:
        cleanup_entered.set()
        await cleanup_release.wait()

    monkeypatch.setattr(harness.runtime, "cleanup", cleanup)
    try:
        await asyncio.wait_for(harness.runtime.entered.wait(), 5)
        async with asyncio.timeout(2):
            while harness.database.get_lease().updated_at <= initial:
                await asyncio.sleep(0.005)
        harness.database.request_cancel(job.id)
        await asyncio.wait_for(cleanup_entered.wait(), 2)
        initial = harness.database.get_lease().updated_at
        async with asyncio.timeout(2):
            while harness.database.get_lease().updated_at <= initial:
                await asyncio.sleep(0.005)
        cleanup_release.set()
        await asyncio.wait_for(task, 5)
        assert harness.database.get_lease().owner_id is None
    finally:
        cleanup_release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("failure", ["rejected", "database"])
async def test_heartbeat_failure_stops_work_and_quarantines(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    monkeypatch.setattr("app.worker.HEARTBEAT_SECONDS", 0.01)

    def heartbeat_result(*_: object) -> bool:
        # Let manifest verification and snapshot setup finish first. Otherwise,
        # a slow CI runner can reject the first heartbeat while `git worktree
        # add` is still creating its .git file, making this test exercise an
        # interrupted worktree setup instead of a failed lease during prepare.
        if not harness.runtime.entered.is_set():
            return True
        if failure == "database":
            raise sqlite3.OperationalError("disk unavailable")
        return False

    heartbeat = Mock(side_effect=heartbeat_result)
    monkeypatch.setattr(harness.database, "heartbeat_lease", heartbeat)
    harness.runtime.block_phase = "prepare"
    job = harness.database.create_job(submission())
    with pytest.raises(RuntimeUnavailable, match="lease_heartbeat_failed"):
        await asyncio.wait_for(harness.worker.run_job(job.id), 5)
    assert harness.runtime.entered.is_set()
    assert "cleanup" in harness.runtime.calls
    assert harness.database.get_lease().quarantined
    assert harness.worker._supervision_failed
    assert harness.database.get_job(job.id).state == JobState.CANCELLED


CRASHING_WORKER = r"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[2])
from conftest import SimulatedRuntime, submission
from app.database import Database
from app.evidence import EvidenceStore
from app.model_adapter import MetaRepairAdapter, ModelSettings
from app.snapshots import SnapshotManager
from app.worker import RepairWorker
from shared.contracts.models import JobStage, TerminalOutcome

async def main():
    root = Path(sys.argv[1])
    database = Database(root / "wal.db")
    adapter = MetaRepairAdapter(ModelSettings())
    runtime = SimulatedRuntime()
    worker = RepairWorker(database, adapter, runtime,
                          SnapshotManager(root), EvidenceStore(database, root))
    job = database.create_job(submission())
    async def crash_point(job_id):
        # Deliberately hold an uncommitted write at the instant of SIGKILL.
        with database._transaction():
            database.transition(job_id, JobStage.DIAGNOSING)
            print(json.dumps({"job_id": job_id}), flush=True)
            await asyncio.Event().wait()
    async def workflow(job_id, started):
        owned = root / "jobs" / job_id / "runtime"
        owned.mkdir(parents=True)
        (owned / "crash-marker").write_text("disposable snapshot")
        database.transition(job_id, JobStage.BASELINE)
        if sys.argv[3] == "cleanup":
            return TerminalOutcome.DETECTED
        await crash_point(job_id)
    async def cleanup(installation, job_id):
        await crash_point(job_id)
    if sys.argv[3] == "cleanup":
        runtime.cleanup = cleanup
    worker._workflow = workflow
    await worker.run_job(job.id)

asyncio.run(main())
"""


@pytest.mark.skipif(sys.platform != "linux", reason="requires SIGKILL")
@pytest.mark.parametrize("sweep_fails", [False, True])
@pytest.mark.parametrize("crash_phase", ["work", "cleanup"])
async def test_sigkill_worker_rolls_back_and_recovers(
    harness: Harness,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sweep_fails: bool,
    crash_phase: str,
) -> None:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        CRASHING_WORKER,
        str(tmp_path),
        str(Path(__file__).parent),
        crash_phase,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        assert process.stdout is not None
        line = await asyncio.wait_for(process.stdout.readline(), 15)
        assert line, "worker exited before entering the job"
        job_id = json.loads(line)["job_id"]
        process.kill()
        _, stderr = await asyncio.wait_for(process.communicate(), 5)
        assert process.returncode == -signal.SIGKILL, stderr.decode()
        database = Database(tmp_path / "wal.db")
        original = harness.worker.database
        harness.worker.database = database
        try:
            # The interrupted transaction never published its stage or event.
            assert database.get_job(job_id).state == JobState.RUNNING
            expected_stage = JobStage.CLEANUP if crash_phase == "cleanup" else JobStage.BASELINE
            assert database.get_job(job_id).stage == expected_stage
            committed_events = len(database.list_events(job_id))
            assert committed_events == (3 if crash_phase == "cleanup" else 2)
            lease = database.get_lease()
            assert lease.job_id == job_id
            owned = tmp_path / "jobs" / job_id / "runtime"
            assert (owned / "crash-marker").is_file()
            assert database._connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

            async def sweep(installation: str) -> None:
                assert installation == lease.installation_id
                assert database.get_lease().quarantined
                assert database.get_job(job_id).state == JobState.RUNNING
                if sweep_fails:
                    raise RuntimeError("orphaned scope remains")

            monkeypatch.setattr(harness.runtime, "reconcile", sweep)
            if sweep_fails:
                with pytest.raises(RuntimeError, match="orphaned scope"):
                    await harness.worker.reconcile()
                assert database.get_lease().quarantined
                with pytest.raises(DatabaseError, match="cleanup_required"):
                    database.create_job(submission())
                monkeypatch.setattr(harness.runtime, "reconcile", AsyncMock())
                await harness.worker.reset()
                assert not database.get_lease().quarantined
            else:
                await harness.worker.reconcile()
                assert database.get_job(job_id).outcome == TerminalOutcome.INTERRUPTED
                assert database.get_lease().owner_id is None
                assert not database.get_lease().quarantined
                # Repeating recovery cannot add another terminal event.
                monkeypatch.setattr(harness.runtime, "reconcile", AsyncMock())
                await harness.worker.reconcile()
                assert len(database.list_events(job_id)) == committed_events + 1
            assert database.get_lease().installation_id == lease.installation_id
            assert not owned.exists()
            assert database.create_job(submission()).id != job_id
        finally:
            await harness.worker.stop()
            harness.worker.database = original
            database.close()
    finally:
        if process.returncode is None:
            process.kill()
            await process.communicate()


async def test_scope_sweep_attempts_every_owned_unit_after_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = IsolatedRuntime(tmp_path)
    runtime._installation = str(uuid4())
    prefix = runtime._unit_prefix()
    owned = [f"{prefix}{uuid4()}.scope" for _ in range(2)]
    unrelated = f"faultline-{'a' * 32}-{uuid4()}.scope"
    output = "\n".join(f"{unit} loaded active running" for unit in [*owned, unrelated])
    monkeypatch.setattr(runtime, "_systemctl", AsyncMock(return_value=output))
    release = AsyncMock(
        side_effect=[RuntimeUnavailable("aggregate_scope_cleanup_unconfirmed"), None]
    )
    monkeypatch.setattr(runtime, "release_scope", release)
    with pytest.raises(RuntimeUnavailable, match="aggregate_scope_cleanup_unconfirmed"):
        await runtime._release_leftover_scopes()
    assert [call.args[0] for call in release.await_args_list] == owned


@pytest.mark.parametrize("state", ["active", "failed"])
async def test_orphan_scope_teardown_confirms_manager_absence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    runtime = IsolatedRuntime(tmp_path)
    runtime._installation = str(uuid4())
    unit = f"{runtime._unit_prefix()}{uuid4()}.scope"
    states = AsyncMock(
        side_effect=[
            {"LoadState": "loaded", "ActiveState": state},
            {"LoadState": "not-found", "ActiveState": "inactive"},
        ]
    )
    commands = AsyncMock(return_value="")
    monkeypatch.setattr(runtime, "_scope_state", states)
    monkeypatch.setattr(runtime, "_systemctl", commands)
    await runtime.release_scope(unit, grace=0)
    if state == "failed":
        commands.assert_awaited_once_with("reset-failed", unit)
    else:
        assert [call.args for call in commands.await_args_list] == [
            ("kill", "--signal=SIGKILL", unit),
            ("stop", "--no-block", unit),
        ]
    assert states.await_count == 2


def test_concurrent_first_open_initializes_one_installation(tmp_path: Path) -> None:
    barrier = Barrier(8)

    def initialize(_: int) -> str:
        barrier.wait(timeout=5)
        database = Database(tmp_path / "new.db")
        try:
            return database.get_lease().installation_id
        finally:
            database.close()

    with ThreadPoolExecutor(max_workers=8) as executor:
        installations = list(executor.map(initialize, range(8)))
    assert len(set(installations)) == 1


def test_legacy_schema_gets_additive_tables(tmp_path: Path) -> None:
    database = Database(tmp_path / "legacy.db")
    installation = database.get_lease().installation_id
    try:
        database._connection.execute("DROP TABLE probes")
        database._connection.execute("DROP TABLE invariant_checks")
    finally:
        database.close()
    database = Database(tmp_path / "legacy.db")
    try:
        assert database.get_lease().installation_id == installation
        database.save_probe("probe", "now", "{}", limit=1)
        assert database.list_probes() == ["{}"]
    finally:
        database.close()


async def test_interrupted_reset_releases_reservation_but_requires_cleanup(
    harness: Harness,
) -> None:
    reservation = harness.database.begin_reset()
    await harness.worker.reconcile()
    lease = harness.database.get_lease()
    assert lease.owner_id is None
    assert lease.quarantined
    assert lease.installation_id == reservation.installation_id
    await harness.worker.reset()
    assert not harness.database.get_lease().quarantined


@pytest.mark.skipif(sys.platform != "linux", reason="requires systemd user scopes")
async def test_real_orphan_scope_is_removed_after_launcher_sigkill(tmp_path: Path) -> None:
    systemd_run = shutil.which("systemd-run")
    if systemd_run is None:
        pytest.skip("systemd-run is unavailable")
    runtime = IsolatedRuntime(tmp_path)
    runtime._installation = str(uuid4())
    unit = f"{runtime._unit_prefix()}{uuid4()}.scope"
    try:
        await runtime._systemctl("show", "--property=Version")
    except RuntimeUnavailable:
        pytest.skip("systemd user manager is unavailable")
    launcher = await asyncio.create_subprocess_exec(
        systemd_run,
        "--user",
        "--scope",
        "--quiet",
        f"--unit={unit}",
        sys.executable,
        "-c",
        "import time; time.sleep(60)",
        env=runtime.manager_environment,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        async with asyncio.timeout(5):
            while True:
                state = await runtime._scope_state(unit)
                if state["ActiveState"] == "active":
                    break
                if launcher.returncode is not None:
                    pytest.fail("systemd scope launcher failed with a reachable manager")
                await asyncio.sleep(0.01)
        launcher.kill()
        await asyncio.wait_for(launcher.wait(), 5)
        # A fresh controller has only its durable installation identity.
        recovered = IsolatedRuntime(tmp_path)
        recovered._installation = runtime._installation
        await recovered._release_leftover_scopes()
        assert (await recovered._scope_state(unit))["LoadState"] == "not-found"
    finally:
        if launcher.returncode is None:
            launcher.kill()
            await launcher.wait()
        await runtime.release_scope(unit, grace=0)


async def test_expired_queued_lease_cannot_be_revived_by_claim(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = harness.database.create_job(submission())
    lease = harness.database.get_lease()
    monkeypatch.setattr("app.database.utcnow", lambda: lease.updated_at + LEASE_TIMEOUT)
    assert (await harness.worker.run_job(job.id)).state == JobState.QUEUED
    assert harness.runtime.calls == []
    assert harness.database.get_lease().quarantined
    await harness.worker.reset()
    assert harness.database.get_job(job.id).state == JobState.INTERRUPTED
    assert not harness.database.get_lease().quarantined


def test_successful_heartbeat_extends_expiration(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness.database.create_job(submission())
    lease = harness.database.get_lease()
    assert lease.owner_id is not None
    renewal_time = lease.updated_at + LEASE_TIMEOUT - timedelta(seconds=1)
    monkeypatch.setattr("app.database.utcnow", lambda: renewal_time)
    assert harness.database.heartbeat_lease(lease.owner_id, lease.generation_id)
    monkeypatch.setattr("app.database.utcnow", lambda: lease.updated_at + LEASE_TIMEOUT)
    assert not harness.database.expire_lease()
    monkeypatch.setattr("app.database.utcnow", lambda: renewal_time + LEASE_TIMEOUT)
    assert harness.database.expire_lease()
