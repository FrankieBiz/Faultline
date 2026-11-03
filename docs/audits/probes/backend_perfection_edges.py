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
import os
import shlex
import sqlite3
import subprocess
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
from app.runtime import CandidateRejected
from app.snapshots import SnapshotManager
from app.worker import RepairWorker
from shared.contracts.models import CleanupStatus, JobStage, TerminalOutcome

logging.disable(logging.CRITICAL)
results = {}


def build_coverage_probe():
    """Exercise Make's ordering and integration environment without running candidates."""
    prerequisites = next(
        line.partition(":")[2].split()
        for line in (ROOT / "Makefile").read_text().splitlines()
        if line.startswith("test:")
    )
    with tempfile.TemporaryDirectory(prefix="faultline-audit-make-") as directory:
        root = Path(directory)
        recorder = root / "record.py"
        recorder.write_text(
            "import json, os, sys, time\n"
            "from pathlib import Path\n"
            "root = Path(__file__).parent\n"
            "mode = sys.argv[1]\n"
            "if mode in ('frontend', 'runner', 'inspector'):\n"
            "    time.sleep(0.05)\n"
            "    (root / mode).touch()\n"
            "elif mode == 'test':\n"
            "    ready = all((root / name).exists() "
            "for name in ('frontend', 'runner', 'inspector'))\n"
            "    (root / 'ordering.json').write_text(json.dumps(ready))\n"
            "    sys.exit(0 if ready else 1)\n"
            "elif mode == 'integration':\n"
            "    (root / 'integration.json').write_text(json.dumps({\n"
            "        'required_flag': os.environ.get('FAULTLINE_REQUIRE_ISOLATED_TESTS'),\n"
            "        'arguments': sys.argv[2:],\n"
            "    }))\n"
        )
        command = f"{shlex.quote(sys.executable)} {shlex.quote(str(recorder))}"
        overrides = root / "overrides.mk"
        overrides.write_text(
            "".join(
                f"{target}:\n\t@{command} {target}\n"
                for target in ("frontend", "runner", "inspector", "test")
            )
        )
        make = [
            "make",
            "--no-print-directory",
            "-f",
            str(ROOT / "Makefile"),
            "-f",
            str(overrides),
            "-j8",
        ]
        ordering = subprocess.run(
            [*make, "test"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )
        # Deliberately conflict with the recipe: it must force required isolation.
        integration = subprocess.run(
            [*make, "integration", f"ORCHESTRATOR_UV={command} integration"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            env={**os.environ, "FAULTLINE_REQUIRE_ISOLATED_TESTS": "0"},
        )
        ordering_path, integration_path = (
            root / "ordering.json",
            root / "integration.json",
        )
        builds_ready = json.loads(ordering_path.read_text()) if ordering_path.exists() else False
        observed = json.loads(integration_path.read_text()) if integration_path.exists() else {}
        files = [
            f"services/repair-orchestrator/tests/{name}.py"
            for name in (
                "test_isolated_runtime",
                "test_resource_limits_cgroup",
                "test_repro_browser",
                "test_project_run",
            )
        ]
        all_files = all(name in observed.get("arguments", []) for name in files)
        required = observed.get("required_flag") == "1"
        dependency_edge = {"frontend", "runner", "inspector"} <= set(prerequisites)
        results["build.P08"] = {
            "method": "Parallel build markers and integration recipe interception",
            "test_prerequisites": prerequisites,
            "dependency_edge_present": dependency_edge,
            "parallel_test_exit_code": ordering.returncode,
            "parallel_builds_ready_before_tests": builds_ready,
            "integration_exit_code": integration.returncode,
            "integration_inherited_required_flag": "0",
            "integration_observed_required_flag": observed.get("required_flag"),
            "integration_arguments": observed.get("arguments", []),
            "all_four_integration_files_present": all_files,
            "resolved": dependency_edge
            and builds_ready
            and required
            and all_files
            and ordering.returncode == 0
            and integration.returncode == 0,
        }


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
    results["policy.full_patch_recursion"] = {
        "diff_bytes": len(diff.encode()),
        "result": outcome,
    }
    # Existing seed need not be executed. This only checks mount identity validation.
    with tempfile.TemporaryDirectory(prefix="faultline-audit-snapshot-") as directory:
        snap = snapshot(Path(directory), False)
        (snap.path / "unhashed-extra.txt").write_text("innocuous audit marker")
        try:
            IsolatedRuntime._verify_snapshot(snap)
            results["snapshot.extra_file_admitted"] = True
        except CandidateRejected as exc:
            results["snapshot.extra_file_admitted"] = False
            results["snapshot.rejection_reason"] = str(exc)


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
    build_coverage_probe()
    policy_probes()
    await worker_probe("transition")
    await worker_probe("update")
    await cancellation_probe()
    await deadline_probe()
    await stop_probe()
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
