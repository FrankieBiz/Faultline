"""Local command composition using the durable worker, policy, and proof store."""

import fcntl
from dataclasses import fields, replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.database import Database
from app.evidence import EvidenceStore
from app.model_adapter import MetaRepairAdapter, ModelSettings
from app.project import ProjectRun, ProjectSnapshots
from app.project_runtime import ProjectRuntime
from app.worker import Budgets, RepairWorker
from shared.contracts.models import CleanupStatus, JobMode, JobRequest, TerminalOutcome


def project_budgets(run: ProjectRun) -> Budgets:
    allowed = {f.name for f in fields(Budgets)} - {"poll"}
    if set(run.budgets) - allowed or any(not 0 < v <= 3600 for v in run.budgets.values()):
        raise ValueError("unknown or invalid stage budget (expected 0 < seconds <= 3600)")
    return Budgets(**run.budgets)


async def _run_project(
    root: Path, run: ProjectRun, data_dir: Path, *, detect: bool = False
) -> dict[str, Any]:
    budgets = project_budgets(run)
    settings = replace(ModelSettings.from_environment(), model=run.model)
    if not detect and (not settings.api_key or settings.provider != "meta"):
        raise ValueError("repair requires META_API_KEY and a Meta-operated endpoint; use --detect")
    database = Database(data_dir / "faultline.db", scenario_ids={run.scenario.id})
    adapter = MetaRepairAdapter(settings)
    evidence = EvidenceStore(
        database, data_dir, secrets=(settings.api_key,) if settings.api_key else ()
    )
    runtime = ProjectRuntime(root, run)
    worker = RepairWorker(
        database,
        adapter,
        runtime,
        ProjectSnapshots(data_dir, root, run),
        evidence,
        budgets=budgets,
        project=run,
    )
    try:
        # No model probe before F1. Every actual proposal still uses the bounded
        # adapter with provider identity derived from the endpoint that answered.
        await worker.reconcile()
        job = database.create_job(
            JobRequest(
                scenario_id=run.scenario.id,
                idempotency_key=str(uuid4()),
                mode=JobMode.DETECT if detect else JobMode.REPAIR,
            )
        )
        result = await worker.run_job(job.id)
        proofs = [a for a in database.list_artifacts(job.id) if a.role == "proof_bundle"]
        proof = None
        if (
            result.outcome == TerminalOutcome.VERIFIED
            and result.cleanup_status == CleanupStatus.SUCCEEDED
        ):
            if not proofs:
                raise RuntimeError("verified job has no proof bundle")
            evidence.verify_job(job.id)
            proof = str(data_dir / proofs[-1].storage_key)
        return {
            "job_id": job.id,
            "scenario": run.scenario.id,
            "outcome": result.outcome.value if result.outcome else "infrastructure_error",
            "cleanup": result.cleanup_status.value,
            "proof_bundle": proof,
            "data_dir": str(data_dir),
            "error_details": result.error_details,
        }
    finally:
        await adapter.close()
        database.close()


async def run_project(
    root: Path, run: ProjectRun, data_dir: Path, *, detect: bool = False
) -> dict[str, Any]:
    """Reserve this installation before reconciliation can touch any resources."""
    data_dir.mkdir(parents=True, exist_ok=True)
    with (data_dir / ".run.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another run owns this data directory") from exc
        return await _run_project(root, run, data_dir, detect=detect)
