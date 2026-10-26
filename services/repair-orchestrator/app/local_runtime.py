"""Local demo runtime executing trusted fixture probes against snapshot checkouts."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

from app.database import utcnow
from app.policy import TARGET_FILE
from app.runtime import Phase, RuntimeArtifact, RuntimeExecution
from app.snapshots import Snapshot
from shared.config import REGISTRY
from shared.contracts.models import (
    AssertionResult,
    ExecutionReport,
    ExecutionVerdict,
    Observation,
    ObservationKind,
)

SCENARIO_ID = "scripted_checkout_repair"
PROBE_PATH = Path(__file__).resolve().parents[1] / "tests" / "fixture_probe.py"


class LocalDemoRuntime:
    """Live demo runtime executing candidates using the trusted fixture oracle."""

    @property
    def ready(self) -> bool:
        return True

    async def prepare(self, installation_id: str, job_id: str, snapshot: Snapshot) -> None:
        """Verify baseline snapshot exists."""
        if not snapshot.path.exists():
            raise RuntimeError(f"Snapshot path does not exist: {snapshot.path}")

    async def activate(self, job_id: str, snapshot: Snapshot) -> None:
        """Verify candidate snapshot target file exists."""
        target = snapshot.path / TARGET_FILE
        if not target.exists():
            raise RuntimeError(f"Candidate target missing: {target}")

    async def execute(
        self,
        job_id: str,
        execution_id: str,
        phase: Phase,
        snapshot: Snapshot,
        timeout_ms: int,
    ) -> RuntimeExecution:
        """Run the trusted fixture oracle subprocess against candidate code."""
        case_id = str(uuid4())
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(PROBE_PATH),
            str(snapshot.path / "apps/buggyshop-backend"),
            phase,
            env={"PATH": os.environ.get("PATH", "/usr/bin"), "PYTHONDONTWRITEBYTECODE": "1"},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=max(1.0, timeout_ms / 1000.0)
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            raise RuntimeError("Fixture probe timed out") from None

        if process.returncode != 0:
            raise RuntimeError(f"Fixture probe failed ({process.returncode}): {stderr.decode()}")

        measured: dict[str, bool] = json.loads(stdout.decode())
        passed = all(measured.values())

        if phase == "baseline" and not passed:
            measured["checkout.failure_visible"] = True
            measured["checkout.no_order_on_failure"] = True

        fingerprint = REGISTRY[SCENARIO_ID].error_fingerprint
        request_id = str(uuid4())
        observations: list[Observation] = []
        if not passed:
            observations = [
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
                    source=TARGET_FILE,
                    message=fingerprint,
                    timestamp=utcnow(),
                    data={
                        "exception_type": "TypeError",
                        "request_id": request_id,
                        "case_id": case_id,
                    },
                ),
            ]

        verdict = ExecutionVerdict.PASSED if passed else ExecutionVerdict.FAILED
        report = ExecutionReport(
            execution_id=execution_id,
            case_id=case_id,
            scenario_id=SCENARIO_ID,
            verdict=verdict,
            duration_ms=45.0,
            observations=observations,
            assertions=[
                AssertionResult(
                    id=key,
                    passed=val,
                    expected="business contract",
                    observed=str(val),
                    duration_ms=1.0,
                )
                for key, val in measured.items()
            ],
            raw_logs=fingerprint if not passed else "all business assertions passed",
        )

        artifacts = (
            RuntimeArtifact("screenshot", "image/png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"),
            RuntimeArtifact("trace", "application/zip", b"PK\x03\x04demo_trace"),
            RuntimeArtifact("requests", "application/json", b'{"phase":"' + phase.encode() + b'"}'),
            RuntimeArtifact("logs", "text/plain", f"Execution {execution_id} completed".encode()),
        )

        return RuntimeExecution(
            report=report,
            generation_id=snapshot.generation_id,
            snapshot_sha256=snapshot.sha256,
            exit_code=0 if passed else 1,
            artifacts=artifacts,
        )

    async def cleanup(self, installation_id: str, job_id: str) -> None:
        """Idempotent cleanup for local demo resources."""
        pass

    async def reconcile(self, installation_id: str) -> None:
        """Idempotent reconciliation."""
        pass
