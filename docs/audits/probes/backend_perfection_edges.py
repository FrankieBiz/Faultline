"""Audit characterization probe; exit zero does not mean the observed behavior is safe.

Run from the repository root using the locked orchestrator environment.
Uses synthetic inputs and temporary resources; does not call a model provider.
"""

# Repository imports require the test support path below.
# ruff: noqa: E402

import asyncio
import difflib
import json
import logging
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [
    str(ROOT / "services/repair-orchestrator"),
    str(ROOT / "services/repair-orchestrator/tests"),
]
from conftest import SimulatedRuntime, submission
from test_isolated_runtime import snapshot

from app.database import Database
from app.evidence import EvidenceStore
from app.isolated_runtime import BackendResources, IsolatedRuntime
from app.model_adapter import MetaRepairAdapter, ModelSettings
from app.policy import TARGET_FILE, PatchPolicy, validate_ast
from app.snapshots import SnapshotManager
from app.worker import RepairWorker
from shared.contracts.models import CleanupStatus, JobStage, TerminalOutcome

logging.disable(logging.CRITICAL)
results = {}


def policy_probes():
    base = (ROOT / TARGET_FILE).read_text()
    snippets = {
        "loop_shadow": (
            "for ValueError in [Exception]:\n    try:\n        1 / 0\n"
            "    except ValueError:\n        pass\n"
        ),
        "argument_shadow": (
            "def f(ValueError=Exception):\n    try:\n        1 / 0\n"
            "    except ValueError:\n        pass\nf()\n"
        ),
        "finally_return": (
            "def f():\n    try:\n        1 / 0\n    except Exception:\n"
            "        raise\n    finally:\n        return 1\n"
        ),
        "alias_recursion": "".join(f"A{i}=A{i + 1};" for i in range(1200))
        + "A1200=ValueError\ntry:\n    pass\nexcept A0:\n    pass\n",
    }
    for name, source in snippets.items():
        try:
            outcome = validate_ast(source)
        except Exception as exc:
            outcome = type(exc).__name__
        results["policy." + name] = {"bytes": len(source.encode()), "result": outcome}
    candidate = base + snippets["argument_shadow"]
    diff = "".join(
        difflib.unified_diff(
            base.splitlines(True),
            candidate.splitlines(True),
            fromfile="a/" + TARGET_FILE,
            tofile="b/" + TARGET_FILE,
        )
    )
    results["policy.full_patch_shadow"] = PatchPolicy().validate(diff, base).is_valid
    candidate = base + snippets["alias_recursion"]
    diff = "".join(
        difflib.unified_diff(
            base.splitlines(True),
            candidate.splitlines(True),
            fromfile="a/" + TARGET_FILE,
            tofile="b/" + TARGET_FILE,
        )
    )
    try:
        outcome = PatchPolicy().validate(diff, base).is_valid
    except Exception as exc:
        outcome = type(exc).__name__
    results["policy.full_patch_recursion"] = {"diff_bytes": len(diff.encode()), "result": outcome}
    # Existing seed need not be executed. This only checks mount identity validation.
    with tempfile.TemporaryDirectory(prefix="faultline-audit-snapshot-") as directory:
        snap = snapshot(Path(directory), False)
        (snap.path / "unhashed-extra.txt").write_text("innocuous audit marker")
        IsolatedRuntime._verify_snapshot(snap)
        results["snapshot.extra_file_admitted"] = True


async def worker_probe(fault_site):
    with tempfile.TemporaryDirectory(prefix="faultline-audit-worker-") as directory:
        db = Database(":memory:")
        runtime = SimulatedRuntime()
        snapshots = SnapshotManager(Path(directory))
        worker = RepairWorker(
            db,
            MetaRepairAdapter(ModelSettings()),
            runtime,
            snapshots,
            EvidenceStore(db, Path(directory)),
        )
        original_transition, original_update = db.transition, db.update_job

        def transition(job_id, stage, *args, **kwargs):
            if fault_site == "transition" and stage == JobStage.CLEANUP:
                raise sqlite3.OperationalError("audit persistence fault")
            return original_transition(job_id, stage, *args, **kwargs)

        def update(job_id, **kwargs):
            if fault_site == "update" and kwargs.get("cleanup_status") == CleanupStatus.IN_PROGRESS:
                raise sqlite3.OperationalError("audit persistence fault")
            return original_update(job_id, **kwargs)

        db.transition, db.update_job = transition, update
        job = db.create_job(submission())
        try:
            try:
                await worker.run_job(job.id)
            except Exception as exc:
                results["worker.persistence_" + fault_site] = {
                    "exception": type(exc).__name__,
                    "runtime_cleanup_called": "cleanup" in runtime.calls,
                    "runtime_prepared": "prepare" in runtime.calls,
                    "runtime_activated": "activate" in runtime.calls,
                    "snapshot_runtime_remains": snapshots._job_root(job.id).exists(),
                    "lease_quarantined_in_run_job": db.get_lease().quarantined,
                }
        finally:
            db.transition, db.update_job = original_transition, original_update
            await runtime.cleanup(db.get_lease().installation_id, job.id)
            await snapshots.cleanup(job.id)
            db.close()


async def cancellation_probe():
    db = Database(":memory:")
    with tempfile.TemporaryDirectory(prefix="faultline-audit-cancel-") as directory:
        runtime = SimulatedRuntime()
        worker = RepairWorker(
            db,
            MetaRepairAdapter(ModelSettings()),
            runtime,
            SnapshotManager(Path(directory)),
            EvidenceStore(db, Path(directory)),
        )
        entered = asyncio.Event()

        async def workflow(*args):
            return TerminalOutcome.DETECTED

        async def cleanup(*args):
            entered.set()
            await asyncio.Event().wait()

        worker._workflow = workflow
        runtime.cleanup = cleanup
        job = db.create_job(submission())
        task = asyncio.create_task(worker.run_job(job.id))
        await entered.wait()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        state = db.get_job(job.id)
        results["worker.cancel_during_cleanup"] = {
            "stage": state.stage.value,
            "cleanup_status": state.cleanup_status.value,
            "outcome": state.outcome,
            "lease_quarantined": db.get_lease().quarantined,
        }
    db.close()


async def deadline_probe():
    db = Database(":memory:")
    with tempfile.TemporaryDirectory(prefix="faultline-audit-budget-") as directory:
        worker = RepairWorker(
            db,
            MetaRepairAdapter(ModelSettings()),
            SimulatedRuntime(),
            SnapshotManager(Path(directory)),
            EvidenceStore(db, Path(directory)),
        )
        job = db.create_job(submission())
        cancelled, release = asyncio.Event(), asyncio.Event()

        async def operation():
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()

        task = asyncio.create_task(
            worker._bounded(job.id, operation, 0.01, asyncio.get_running_loop().time() + 5)
        )
        await cancelled.wait()
        await asyncio.sleep(0.05)
        results["worker.cooperative_deadline"] = {
            "local_budget_ms": 10,
            "still_pending_after_extra_ms": 50,
            "pending": not task.done(),
        }
        release.set()
        try:
            await task
        except TimeoutError:
            pass
    db.close()


async def stop_probe():
    runtime = IsolatedRuntime()
    runtime.release_scope = AsyncMock()
    process = AsyncMock()
    process.stop.side_effect = TimeoutError()
    try:
        await runtime._stop_backend(BackendResources(unit="synthetic", process=process))
    except TimeoutError:
        pass
    results["runtime.stop_timeout"] = {"scope_release_attempted": runtime.release_scope.called}


async def main():
    policy_probes()
    await worker_probe("transition")
    await worker_probe("update")
    await cancellation_probe()
    await deadline_probe()
    await stop_probe()
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
