"""Explicit runtime simulations; none are available to the production API."""

import asyncio
import json
import os
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app.database import Database, utcnow
from app.evidence import EvidenceStore
from app.model_adapter import MetaRepairAdapter, ModelSettings
from app.policy import TARGET_FILE
from app.runtime import (
    REGRESSION_ASSERTIONS,
    CandidateRejected,
    Phase,
    RuntimeArtifact,
    RuntimeExecution,
)
from app.snapshots import REPOSITORY_ROOT, Snapshot, SnapshotManager
from app.worker import RepairWorker
from shared.config import REGISTRY
from shared.contracts.models import (
    AssertionResult,
    ExecutionReport,
    ExecutionVerdict,
    JobRequest,
    Observation,
    ObservationKind,
    OrchestratorJob,
)

SCENARIO_ID = "scripted_checkout_repair"


def submission(**changes: Any) -> JobRequest:
    """Build a unique, strict controller submission."""
    return JobRequest(scenario_id=SCENARIO_ID, idempotency_key=str(uuid4()), **changes)


@pytest.fixture
def seeded_source() -> str:
    """Read the trusted seed without consulting the golden repaired source."""
    return (REPOSITORY_ROOT / TARGET_FILE).read_text(encoding="utf-8")


class SimulatedRuntime:
    """Test-only controlled observations, with optional real fixture subprocess QA.

    The optional API probe executes candidate code on the test host, explicitly
    outside production. Browser artifacts are labeled simulation bytes; these
    tests establish controller behavior and do not establish browser containment.
    """

    def __init__(self) -> None:
        self.ready = True
        self.calls: list[str] = []
        self.snapshots: list[Snapshot] = []
        self.real_api = False
        self.baseline_passed = False
        self.unexpected = False
        self.verification_failed = False
        self.cleanup_failed = False
        self.activation_failed = False
        self.wrong_generation = False
        self.missing_evidence = False
        self.incomplete_suite = False
        self.exit_disagreement = False
        self.infrastructure_error = False
        self.delay = 0.0
        self.report_secret = ""
        self.block_phase: str | None = None
        self.entered = asyncio.Event()
        self.unblock = asyncio.Event()

    async def _block(self, phase: str) -> None:
        self.calls.append(phase)
        if self.block_phase == phase:
            self.entered.set()
            await self.unblock.wait()
        if self.delay:
            await asyncio.sleep(self.delay)

    async def prepare(self, installation_id: str, job_id: str, snapshot: Snapshot) -> None:
        """Observe baseline ownership without starting production containers."""
        self.snapshots.append(snapshot)
        await self._block("prepare")

    async def activate(self, job_id: str, snapshot: Snapshot) -> None:
        """Record candidate identity and simulate a readiness failure when requested."""
        self.snapshots.append(snapshot)
        await self._block("activate")
        if self.activation_failed:
            raise CandidateRejected("test readiness failure")

    async def execute(
        self,
        job_id: str,
        execution_id: str,
        phase: Phase,
        snapshot: Snapshot,
        timeout_ms: int,
    ) -> RuntimeExecution:
        """Return controlled evidence or exercise the exported fixture's real API."""
        await self._block(phase)
        case_id = str(uuid4())
        passed = self.baseline_passed if phase == "baseline" else not self.verification_failed
        assertions = list(REGISTRY[SCENARIO_ID].expected_assertions)
        if phase == "verification":
            assertions.extend(sorted(REGRESSION_ASSERTIONS))
        measured: dict[str, bool] = {key: passed for key in assertions}
        if self.real_api:
            measured = await self._probe(snapshot, phase)
            passed = all(measured.values())
        if phase == "baseline" and not passed:
            measured["checkout.failure_visible"] = True
            measured["checkout.no_order_on_failure"] = True
        if self.incomplete_suite and phase == "verification":
            measured.pop("confirmation.checkout")
        fingerprint = REGISTRY[SCENARIO_ID].error_fingerprint
        request_id = str(uuid4())
        observations = (
            []
            if passed
            else [
                Observation(
                    id=str(uuid4()),
                    kind=ObservationKind.HTTP_ERROR,
                    source="POST /api/checkout",
                    message="Checkout failed",
                    timestamp=utcnow(),
                    data={"status": 500, "request_id": request_id, "case_id": case_id},
                ),
                Observation(
                    id=str(uuid4()),
                    kind=ObservationKind.SERVER_EXCEPTION,
                    source="unrelated.py" if self.unexpected else TARGET_FILE,
                    message=fingerprint,
                    timestamp=utcnow(),
                    data={
                        "exception_type": "TypeError",
                        "request_id": request_id,
                        "case_id": case_id,
                    },
                ),
            ]
        )
        verdict = ExecutionVerdict.PASSED if passed else ExecutionVerdict.FAILED
        if self.infrastructure_error:
            verdict = ExecutionVerdict.ERROR
        report = ExecutionReport(
            execution_id=execution_id,
            case_id=case_id,
            scenario_id=SCENARIO_ID,
            verdict=verdict,
            duration_ms=1.0,
            observations=observations,
            assertions=[
                AssertionResult(
                    id=key,
                    passed=value,
                    expected="business contract",
                    observed=str(value),
                    duration_ms=1.0,
                )
                for key, value in measured.items()
            ],
            raw_logs=fingerprint + self.report_secret,
        )
        evidence = (
            RuntimeArtifact("screenshot", "image/png", b"test simulation screenshot"),
            RuntimeArtifact("trace", "application/zip", b"test simulation trace"),
            RuntimeArtifact("requests", "application/json", b'{"simulation":true}'),
            RuntimeArtifact("logs", "text/plain", b"test simulation logs"),
        )
        return RuntimeExecution(
            report,
            "wrong" if self.wrong_generation else snapshot.generation_id,
            snapshot.sha256,
            99
            if self.exit_disagreement
            else (2 if verdict == ExecutionVerdict.ERROR else 0 if passed else 1),
            evidence[:1] if self.missing_evidence else evidence,
        )

    async def _probe(self, snapshot: Snapshot, phase: Phase) -> dict[str, bool]:
        path = Path(__file__).with_name("fixture_probe.py")
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(path),
            str(snapshot.path / "apps/buggyshop-backend"),
            phase,
            env={"PATH": os.environ.get("PATH", "/usr/bin"), "PYTHONDONTWRITEBYTECODE": "1"},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            output, stderr = await process.communicate()
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        if process.returncode != 0:
            raise AssertionError(stderr.decode())
        value: dict[str, bool] = json.loads(output)
        return value

    async def cleanup(self, installation_id: str, job_id: str) -> None:
        """Confirm simulated disposal or intentionally fail cleanup."""
        self.calls.append("cleanup")
        if self.cleanup_failed:
            raise RuntimeError("test cleanup failure")

    async def reconcile(self, installation_id: str) -> None:
        """Observe installation-scoped startup/reset reconciliation."""
        self.calls.append("reconcile")
        if self.cleanup_failed:
            raise RuntimeError("test reconciliation failure")


@dataclass
class Harness:
    """Owned test dependencies with the same boundaries as the application."""

    database: Database
    adapter: MetaRepairAdapter
    runtime: SimulatedRuntime
    snapshots: SnapshotManager
    evidence: EvidenceStore
    worker: RepairWorker
    root: Path

    async def run(self, **changes: Any) -> OrchestratorJob:
        """Admit and synchronously await one complete simulated lifecycle."""
        job = self.database.create_job(submission(**changes))
        return await self.worker.run_job(job.id)


@pytest.fixture
def harness(tmp_path: Path) -> Iterator[Harness]:
    """Use real SQLite, Git exports, policy, and evidence with a test runtime."""
    db = Database(":memory:")
    adapter = MetaRepairAdapter(ModelSettings())
    runtime = SimulatedRuntime()
    snapshots = SnapshotManager(tmp_path)
    evidence = EvidenceStore(db, tmp_path)
    worker = RepairWorker(db, adapter, runtime, snapshots, evidence)
    value = Harness(db, adapter, runtime, snapshots, evidence, worker, tmp_path)
    yield value
    # Worker paths clean themselves. Finalizers deliberately avoid global Git pruning.
    db.close()
