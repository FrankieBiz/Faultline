"""Serial, cancellation-aware seven-stage repair orchestration.

Work and cleanup use separate monotonic deadlines. Every candidate starts from
the pinned seed, every observed report remains immutable, and completed GREEN
is possible only after evidence and cleanup have both been confirmed.
"""

import asyncio
import json
import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import timedelta
from functools import partial
from typing import Any
from uuid import uuid4

from app.database import Database, utcnow
from app.evidence import ArtifactError, EvidenceStore
from app.model_adapter import (
    CORRECTABLE_PROPOSAL_ERRORS,
    AttemptFeedback,
    FailedCheck,
    MetaRepairAdapter,
    ModelError,
    ProbeResult,
    RepairContext,
)
from app.policy import PatchPolicy, PatchPolicyError
from app.project import ProjectPatchPolicy, ProjectRun
from app.proof_bundle import ProofBundleCompiler
from app.runtime import (
    REGRESSION_ASSERTIONS,
    REQUIRED_EVIDENCE,
    CandidateRejected,
    Phase,
    Runtime,
    RuntimeArtifact,
    RuntimeUnavailable,
)
from app.snapshots import Snapshot, SnapshotManager, contained_path
from shared.config import REGISTRY, Scenario
from shared.contracts.models import (
    Artifact,
    CleanupStatus,
    ExecutionRecord,
    ExecutionReport,
    ExecutionVerdict,
    JobMode,
    JobStage,
    Observation,
    ObservationKind,
    OrchestratorJob,
    PatchProposal,
    RepairAttempt,
    TerminalOutcome,
)

logger = logging.getLogger("faultline.worker")
HEARTBEAT_SECONDS = 5.0
RETRY_BACKOFF_SECONDS = 1.0


@dataclass(frozen=True)
class Budgets:
    """SpecV1 stage allocations; tests may inject shorter deadlines."""

    baseline: float = 20
    attempt: float = 75
    generation: float = 45
    verification: float = 20
    work: float = 170
    cleanup: float = 10
    preflight: float = 45
    overall: float = 180
    poll: float = 0.025


class JobAbort(Exception):
    """A classified workflow exit retaining the stage that failed."""

    def __init__(self, outcome: TerminalOutcome, code: str) -> None:
        super().__init__(code)
        self.outcome = outcome
        self.code = code


def matches_fingerprint(report: ExecutionReport, scenario: Scenario) -> bool:
    """Require correlated checkout 500 and TypeError from the allowlisted file."""
    for http in report.observations:
        if (
            http.kind != ObservationKind.HTTP_ERROR
            or http.source != scenario.route
            or http.data.get("status") != 500
            or not http.data.get("request_id")
            or http.data.get("case_id") != report.case_id
        ):
            continue
        for server in report.observations:
            if (
                server.kind == ObservationKind.SERVER_EXCEPTION
                and server.source == scenario.target_file
                and scenario.error_fingerprint in server.message
                and server.data.get("exception_type") == "TypeError"
                and server.data.get("request_id") == http.data["request_id"]
                and server.data.get("case_id") == report.case_id
            ):
                assertions = {item.id: item.passed for item in report.assertions}
                return (
                    assertions.get("checkout.failure_visible") is True
                    and assertions.get("checkout.no_order_on_failure") is True
                )
    return False


class RepairWorker:
    """Own one queued job at a time and emit durable events for every stage."""

    def __init__(
        self,
        database: Database,
        adapter: MetaRepairAdapter,
        runtime: Runtime,
        snapshots: SnapshotManager,
        evidence: EvidenceStore,
        *,
        budgets: Budgets | None = None,
        project: ProjectRun | None = None,
    ) -> None:
        self.project = project
        self.scenarios = {project.scenario.id: project.scenario} if project else dict(REGISTRY)
        self.database = database
        self.adapter = adapter
        self.runtime = runtime
        self.snapshots = snapshots
        self.evidence = evidence
        self.budgets = budgets if budgets is not None else Budgets()
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._job_lock = asyncio.Lock()
        self._stopping = False
        self._supervision_failed = False
        self._owner_id = str(uuid4())
        self.probe: ProbeResult | None = None
        self.probe_time: str | None = None

    async def start(self) -> None:
        """Reconcile crash leftovers and perform one separately counted probe."""
        await self.reconcile()
        if self.project is not None and (
            not self.adapter.settings.api_key or self.adapter.settings.provider != "meta"
        ):
            self.probe = ProbeResult(
                False,
                self.adapter.settings.provider,
                self.adapter.settings.model,
                "meta_credentials_required",
            )
        else:
            self.probe = await self.adapter.probe()
        self.probe_time = utcnow().isoformat()
        self._stopping = False
        self._supervision_failed = False
        self._task = asyncio.create_task(self._loop(), name="faultline-serial-worker")
        self._task.add_done_callback(self._task_done)

    def _task_done(self, task: asyncio.Task[None]) -> None:
        """Fail closed on dispatcher death, including unexpected cancellation/return."""
        if self._stopping or task is not self._task:
            return
        self._supervision_failed = True
        # Retrieve the exception now, so task failures are observed before shutdown.
        error = None if task.cancelled() else task.exception()
        logger.error(
            "Worker task terminated unexpectedly: %s",
            "cancelled" if task.cancelled() else type(error).__name__ if error else "returned",
        )
        try:
            self.database.quarantine_runtime()
        except Exception:
            logger.exception("Worker supervision could not persist quarantine")

    @property
    def healthy(self) -> bool:
        """Admission requires both a live dispatcher and confirmed persistent state."""
        return (
            self._task is not None
            and not self._task.done()
            and not self._stopping
            and not self._supervision_failed
        )

    async def stop(self) -> None:
        """Cancel active work and wait for bounded resource cleanup."""
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Worker shutdown encountered a trusted operation failure")
            self._task = None
        self.database.release_worker(self._owner_id)

    def notify(self) -> None:
        """Wake the sole worker after durable admission or cancellation."""
        self._wake.set()

    def _check_cancel(self, job_id: str) -> None:
        if self.database.get_job(job_id).cancel_requested:
            raise JobAbort(TerminalOutcome.CANCELLED, "cancel_requested")

    def _transition(self, job_id: str, stage: JobStage) -> None:
        self.database.transition(job_id, stage)
        self._check_cancel(job_id)

    async def _loop(self) -> None:
        while not self._stopping:
            self._wake.clear()
            if not self._supervision_failed:
                try:
                    queued = self.database.unfinished_jobs()
                    for job in queued:
                        if job.state.value == "queued":
                            await self.run_job(job.id)
                except Exception:
                    # Even a scan/claim failure may follow an ambiguous commit.
                    # Never retry candidate side effects. Keep this task alive,
                    # block admission, and require explicit reset or restart.
                    self._supervision_failed = True
                    logger.exception("Worker supervision quarantined an unexpected failure")
                    try:
                        self.database.quarantine_runtime()
                    except Exception:
                        # Disk failure must not defeat the in-memory interlock.
                        logger.exception("Worker supervision could not persist quarantine")
            if self._stopping:
                break
            # Polling also notices submissions admitted by another connection.
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=0.25)
            except TimeoutError:
                pass

    async def _cancellation(self, job_id: str) -> None:
        while not self.database.get_job(job_id).cancel_requested:
            await asyncio.sleep(self.budgets.poll)

    async def _bounded[T](
        self,
        job_id: str,
        operation: Callable[[], Coroutine[Any, Any, T]],
        local: float,
        work_deadline: float,
    ) -> T:
        """Check cancellation before dispatch and interrupt long external operations."""
        self._check_cancel(job_id)
        remaining = work_deadline - time.monotonic()
        if remaining <= 0:
            raise JobAbort(TerminalOutcome.TIMEOUT, "work_deadline")
        if local <= 0:
            raise TimeoutError
        task = asyncio.create_task(operation())
        cancellation = asyncio.create_task(self._cancellation(job_id))
        cancel_reason = "controller_cancelled"
        try:
            done, _ = await asyncio.wait(
                {task, cancellation},
                timeout=min(local, remaining),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancellation in done:
                raise JobAbort(TerminalOutcome.CANCELLED, "cancel_requested")
            if task in done:
                self._check_cancel(job_id)
                return task.result()
            cancel_reason = "controller_timeout"
            if time.monotonic() >= work_deadline:
                raise JobAbort(TerminalOutcome.TIMEOUT, "work_deadline")
            raise TimeoutError
        finally:
            for pending in (task, cancellation):
                if not pending.done():
                    pending.cancel(cancel_reason)
            await asyncio.gather(task, cancellation, return_exceptions=True)

    async def _execution(
        self,
        job: OrchestratorJob,
        phase: Phase,
        snapshot: Snapshot,
        timeout: float,
        attempt_id: str | None = None,
    ) -> ExecutionReport:
        execution_id = str(uuid4())
        started = utcnow()
        try:
            result = await self.runtime.execute(
                job.id,
                execution_id,
                phase,
                snapshot,
                max(1, min(20_000, int(timeout * 1000))),
            )
        except asyncio.CancelledError as exc:
            if exc.args == ("controller_timeout",):
                report = ExecutionReport(
                    execution_id=execution_id,
                    case_id=str(uuid4()),
                    scenario_id=job.scenario_id,
                    verdict=ExecutionVerdict.TIMED_OUT,
                    duration_ms=max(0.0, (utcnow() - started).total_seconds() * 1000),
                    observations=[
                        Observation(
                            id=str(uuid4()),
                            kind=ObservationKind.RUNNER_ERROR,
                            source="controller",
                            message="Controller enforced the execution deadline.",
                            data={"code": "execution_timeout"},
                            timestamp=utcnow(),
                        )
                    ],
                    assertions=[],
                    raw_logs="Controller enforced the execution deadline.",
                )
                self.database.save_execution(
                    ExecutionRecord(
                        job_id=job.id,
                        phase=phase,
                        attempt_id=attempt_id,
                        app_generation_id=snapshot.generation_id,
                        candidate_snapshot_sha256=snapshot.sha256,
                        runtime_kind=getattr(self.runtime, "kind", "unverified"),
                        artifact_ids=[],
                        started_at=started,
                        finished_at=utcnow(),
                        report=report,
                    )
                )
            raise
        report = result.report
        if (
            report.execution_id != execution_id
            or report.scenario_id != job.scenario_id
            or result.generation_id != snapshot.generation_id
            or result.snapshot_sha256 != snapshot.sha256
        ):
            raise JobAbort(TerminalOutcome.INFRASTRUCTURE_ERROR, "execution_identity_mismatch")
        expected_exit = {
            ExecutionVerdict.PASSED: 0,
            ExecutionVerdict.FAILED: 1,
            ExecutionVerdict.ERROR: 2,
            ExecutionVerdict.TIMED_OUT: 3,
        }[report.verdict]
        if result.exit_code != expected_exit:
            raise JobAbort(TerminalOutcome.INFRASTRUCTURE_ERROR, "runner_exit_disagreement")
        ids = [item.id for item in report.assertions]
        if len(set(ids)) != len(ids) or not report.case_id:
            raise JobAbort(TerminalOutcome.INFRASTRUCTURE_ERROR, "invalid_assertion_manifest")
        if report.verdict == ExecutionVerdict.PASSED:
            required = set(self.scenarios[job.scenario_id].expected_assertions)
            if phase == "verification":
                required.update(
                    REGRESSION_ASSERTIONS
                    if self.project is None
                    else self.scenarios[job.scenario_id].regression_assertions
                )
            if not required <= set(ids) or not all(item.passed for item in report.assertions):
                raise JobAbort(TerminalOutcome.INFRASTRUCTURE_ERROR, "incomplete_or_false_pass")
        # Redact individual string values, retaining valid strict JSON envelopes.
        sanitized = self.evidence.redact_value(report.model_dump(mode="json"))
        report = ExecutionReport.model_validate_json(json.dumps(sanitized))
        artifacts = []
        try:
            self._check_cancel(job.id)
            roles = [item.role for item in result.artifacts]
            if not REQUIRED_EVIDENCE <= set(roles) or len(set(roles)) != len(roles):
                raise ArtifactError("Required runner evidence is missing or duplicated")
            for item in (
                *result.artifacts,
                RuntimeArtifact(
                    "report",
                    "application/json",
                    report.model_dump_json().encode(),
                ),
            ):
                artifacts.append(
                    self.evidence.save(
                        job.id,
                        item,
                        execution_id=execution_id,
                        attempt_id=attempt_id,
                    )
                )
        finally:
            # Preserve the observed verdict even if required evidence cannot be saved.
            self.database.save_execution(
                ExecutionRecord(
                    job_id=job.id,
                    phase=phase,
                    attempt_id=attempt_id,
                    app_generation_id=snapshot.generation_id,
                    candidate_snapshot_sha256=snapshot.sha256,
                    runtime_kind=getattr(self.runtime, "kind", "unverified"),
                    resource_limits=result.resource_limits,
                    artifact_ids=[item.id for item in artifacts],
                    started_at=started,
                    finished_at=utcnow(),
                    report=report,
                )
            )
        if phase == "baseline":
            self.database.update_job(job.id, baseline_execution_id=execution_id)
        return report

    def _save_bundle(
        self,
        job: OrchestratorJob,
        baseline: ExecutionReport,
        verification: ExecutionReport,
        diff: str,
        attempt_id: str,
    ) -> list[Artifact]:
        """Persist final proof only after cleanup; any proof failure fails the job closed."""
        saved_proofs: list[Artifact] = []
        try:
            attempt = next(a for a in self.database.list_attempts(job.id) if a.id == attempt_id)
            bundle, summary = ProofBundleCompiler().compile(
                job=job,
                baseline_report=baseline,
                verification_report=verification,
                diff=diff,
                artifacts=self.database.list_artifacts(job.id),
                executions=self.database.list_executions(job.id),
                attempt=attempt,
            )
        except Exception:
            logger.exception("Evidence bundle compilation failed for job %s", job.id)
            raise ArtifactError("Proof compilation failed") from None
        try:
            # Write the machine-readable final envelope last. A failed summary
            # write must not leave an independently consumable verified bundle.
            for role, content_type, content in (
                ("proof_bundle_md", "text/markdown", summary.encode()),
                ("proof_bundle", "application/json", bundle.model_dump_json().encode()),
            ):
                saved = self.evidence.save(
                    job.id, RuntimeArtifact(role, content_type, content), attempt_id=attempt_id
                )
                saved_proofs.append(saved)
                retained = self.evidence.read(saved)
                if role == "proof_bundle" and json.loads(retained) != bundle.model_dump(
                    mode="json"
                ):
                    raise ArtifactError("Proof changed during persistence")
        except Exception as exc:
            # Revoke partial proof bytes before the enclosing transaction rolls
            # back their registrations; failed jobs cannot export final proof.
            self._discard_proof_files(self.database.list_artifacts(job.id))
            raise ArtifactError("Proof persistence failed") from exc
        return saved_proofs

    def _discard_proof_files(self, artifacts: list[Artifact]) -> None:
        """Best-effort removal; registration rollback remains the publication guard."""
        for item in artifacts:
            if item.role.startswith("proof_bundle"):
                try:
                    contained_path(self.evidence.data_root, item.storage_key).unlink(
                        missing_ok=True
                    )
                except (OSError, ValueError):
                    logger.exception("Could not remove unregistered proof file %s", item.id)

    async def _workflow(self, job_id: str, started: float) -> TerminalOutcome:
        deadline = started + self.budgets.work
        baseline_deadline = started + self.budgets.baseline
        job = self.database.get_job(job_id)
        self.database.update_job(
            job_id, deadline_at=utcnow() + timedelta(seconds=self.budgets.overall)
        )
        self._transition(job_id, JobStage.PREPARING)
        if self.project is not None:
            self.evidence.save(
                job_id,
                RuntimeArtifact(
                    "repro_spec", "application/json", self.project.model_dump_json().encode()
                ),
            )
        try:
            manifest = await self._bounded(
                job_id,
                self.snapshots.manifest,
                baseline_deadline - time.monotonic(),
                deadline,
            )
            baseline = await self._bounded(
                job_id,
                lambda: self.snapshots.create(job_id, manifest),
                baseline_deadline - time.monotonic(),
                deadline,
            )
            self.database.update_job(
                job_id,
                seed_commit=baseline.seed_commit,
                seed_source_hash=baseline.source_sha256,
                fixture_version=manifest["fixture_version"],
                scenario_version=manifest["scenario_version"],
            )
            await self._bounded(
                job_id,
                lambda: self.runtime.prepare(
                    self.database.get_lease().installation_id,
                    job_id,
                    baseline,
                ),
                baseline_deadline - time.monotonic(),
                deadline,
            )
            self._transition(job_id, JobStage.BASELINE)
            report = await self._bounded(
                job_id,
                lambda: self._execution(
                    job,
                    "baseline",
                    baseline,
                    baseline_deadline - time.monotonic(),
                ),
                baseline_deadline - time.monotonic(),
                deadline,
            )
        except TimeoutError as exc:
            raise JobAbort(TerminalOutcome.INFRASTRUCTURE_ERROR, "baseline_timeout") from exc
        if report.verdict in {ExecutionVerdict.ERROR, ExecutionVerdict.TIMED_OUT}:
            raise JobAbort(TerminalOutcome.INFRASTRUCTURE_ERROR, "runner_error")
        if report.verdict == ExecutionVerdict.PASSED:
            return TerminalOutcome.NO_FAILURE
        if self.project is not None:
            # execute() owns a new application + browser session each time. Its
            # successful return confirms cleanup before either report is accepted.
            second = await self._bounded(
                job_id,
                lambda: self._execution(
                    job, "baseline", baseline, baseline_deadline - time.monotonic()
                ),
                baseline_deadline - time.monotonic(),
                deadline,
            )
            if second.verdict in {ExecutionVerdict.ERROR, ExecutionVerdict.TIMED_OUT}:
                raise JobAbort(TerminalOutcome.INFRASTRUCTURE_ERROR, "runner_error")

            def signature(value: ExecutionReport) -> list[tuple[str, str, str]]:
                return [(a.id, a.expected, a.observed) for a in value.assertions if not a.passed]

            if (
                report.case_id == second.case_id
                or not signature(report)
                or signature(report) != signature(second)
            ):
                return TerminalOutcome.NO_FAILURE
            fingerprints = [
                [o.message for o in r.observations if o.kind == ObservationKind.SERVER_EXCEPTION]
                for r in (report, second)
            ]
            if fingerprints[0] != fingerprints[1]:
                return TerminalOutcome.NO_FAILURE
            expected = self.project.repro.fingerprint
            if expected is not None and fingerprints[0] != [expected]:
                return TerminalOutcome.UNEXPECTED_FAILURE
        elif not matches_fingerprint(report, self.scenarios[job.scenario_id]):
            return TerminalOutcome.UNEXPECTED_FAILURE
        if job.requested_mode == JobMode.DETECT:
            return TerminalOutcome.DETECTED
        if job.effective_mode == JobMode.DETECT or (self.probe and not self.probe.available):
            return TerminalOutcome.REPAIR_UNAVAILABLE
        previous_gate: str | None = None
        # Independent gate findings from a rejected attempt guide the next proposal.
        feedback: AttemptFeedback | None = None
        final = TerminalOutcome.INVALID_PATCH
        retry_delay = 0.0
        for number in range(1, (self.project.max_attempts if self.project else 2) + 1):
            if number > 1:
                remaining = deadline - time.monotonic()
                if retry_delay + self.budgets.attempt > remaining:
                    break
                if retry_delay:
                    await self._bounded(
                        job_id, partial(asyncio.sleep, retry_delay), remaining, deadline
                    )
                # Scheduling delays and cancellation also count against the job budget.
                self._check_cancel(job_id)
                if deadline - time.monotonic() < self.budgets.attempt:
                    break
            retry_delay = 0.0
            attempt_deadline = min(deadline, time.monotonic() + self.budgets.attempt)
            # Where the request was sent stays separate from who answered: only a
            # returned response sets provider/model, so errors never read as inference.
            attempt = RepairAttempt(
                id=str(uuid4()),
                job_id=job_id,
                attempt_number=number,
                validation_result={
                    **(
                        {
                            "dispatched_provider": self.probe.provider,
                            "dispatched_model": self.probe.model,
                        }
                        if self.probe
                        else {}
                    ),
                    **({"prior_feedback": feedback.summary()} if feedback else {}),
                }
                or None,
            )
            self.database.save_attempt(attempt)
            proposal: PatchProposal | None = None
            try:
                self._transition(job_id, JobStage.DIAGNOSING)
                context = RepairContext(
                    source=baseline.source,
                    failure_traceback=report.raw_logs,
                    previous_gate=previous_gate,
                    feedback=feedback,
                    target_file=self.scenarios[job.scenario_id].target_file,
                    contract=self.project.repro.model_dump_json() if self.project else None,
                )
                requested = time.monotonic()
                model = await self._bounded(
                    job_id,
                    partial(self.adapter.propose_patch, context),
                    min(self.budgets.generation, attempt_deadline - time.monotonic()),
                    deadline,
                )
                proposal = model.proposal
                attempt = attempt.model_copy(
                    update={
                        # The provider's own output; parsed_diff is what the gates checked.
                        "raw_patch": self.evidence.redact(model.model_output.model_dump_json()),
                        "parsed_diff": self.evidence.redact(proposal.unified_diff),
                        "prompt_tokens": model.prompt_tokens,
                        "completion_tokens": model.completion_tokens,
                        "validation_result": {
                            **(attempt.validation_result or {}),
                            "provider": model.provider,
                            "model": model.model,
                            "generation_ms": round((time.monotonic() - requested) * 1000),
                            "diff_recounted": model.original_diff is not None,
                        },
                    }
                )
                self.database.save_attempt(attempt)
                self.evidence.save(
                    job_id,
                    RuntimeArtifact(
                        "proposal",
                        "application/json",
                        model.model_output.model_dump_json().encode(),
                    ),
                    attempt_id=attempt.id,
                )
                if proposal.decision == "no_patch":
                    attempt = attempt.model_copy(update={"outcome": "no_patch"})
                    self.database.save_attempt(attempt)
                    return TerminalOutcome.UNRESOLVED
                self._transition(job_id, JobStage.PATCH_VALIDATION)
                policy = ProjectPatchPolicy(self.project) if self.project else PatchPolicy()
                validation = policy.validate(
                    proposal.unified_diff,
                    baseline.source,
                    base_sha256=proposal.base_sha256,
                )
                attempt = attempt.model_copy(
                    update={
                        "validation_result": {
                            **(attempt.validation_result or {}),
                            **validation.model_dump(),
                            "base_sha256": baseline.source_sha256,
                        }
                    }
                )
                self.database.save_attempt(attempt)
                self.evidence.save(
                    job_id,
                    RuntimeArtifact(
                        "diff",
                        "text/plain",
                        proposal.unified_diff.encode(),
                    ),
                    attempt_id=attempt.id,
                )
                if not validation.is_valid:
                    feedback = AttemptFeedback(
                        "patch_policy_rejected",
                        rejected_diff=proposal.unified_diff,
                        policy_error=validation.error_message,
                    )
                    raise JobAbort(TerminalOutcome.INVALID_PATCH, "patch_policy_rejected")
                self._transition(job_id, JobStage.ACTIVATING)
                candidate = await self._bounded(
                    job_id,
                    partial(
                        self.snapshots.create,
                        job_id,
                        manifest,
                        diff=proposal.unified_diff,
                        base_sha256=proposal.base_sha256,
                    ),
                    attempt_deadline - time.monotonic(),
                    deadline,
                )
                attempt = attempt.model_copy(
                    update={
                        "validation_result": {
                            **(attempt.validation_result or {}),
                            "candidate_sha256": candidate.sha256,
                            "target_sha256": candidate.source_sha256,
                            "app_generation_id": candidate.generation_id,
                        }
                    }
                )
                self.database.save_attempt(attempt)
                await self._bounded(
                    job_id,
                    partial(self.runtime.activate, job_id, candidate),
                    attempt_deadline - time.monotonic(),
                    deadline,
                )
                self._transition(job_id, JobStage.VERIFICATION)
                verification_budget = min(
                    self.budgets.verification,
                    attempt_deadline - time.monotonic(),
                )
                verification = await self._bounded(
                    job_id,
                    partial(
                        self._execution,
                        job,
                        "verification",
                        candidate,
                        verification_budget,
                        attempt.id,
                    ),
                    verification_budget,
                    deadline,
                )
                attempt = attempt.model_copy(
                    update={
                        "validation_result": {
                            **(attempt.validation_result or {}),
                            "verification_execution_id": verification.execution_id,
                        }
                    }
                )
                if verification.verdict == ExecutionVerdict.ERROR:
                    raise JobAbort(TerminalOutcome.INFRASTRUCTURE_ERROR, "runner_error")
                if verification.verdict == ExecutionVerdict.TIMED_OUT:
                    feedback = AttemptFeedback(
                        "verification_timeout", rejected_diff=proposal.unified_diff
                    )
                    raise JobAbort(TerminalOutcome.UNRESOLVED, "verification_timeout")
                if verification.verdict != ExecutionVerdict.PASSED:
                    failed = [item for item in verification.assertions if not item.passed]
                    feedback = AttemptFeedback(
                        "verification_failed",
                        rejected_diff=proposal.unified_diff,
                        failed_checks=tuple(
                            FailedCheck(item.id, item.expected, item.observed) for item in failed
                        ),
                        failed_count=len(failed),
                    )
                    raise JobAbort(TerminalOutcome.UNRESOLVED, "verification_failed")
                attempt = attempt.model_copy(update={"outcome": "verified"})
                self.database.save_attempt(attempt)
                self.evidence.verify_job(job_id)
                return TerminalOutcome.VERIFIED
            except ModelError as exc:
                previous_gate = exc.code
                # Provider transport failures returned no proposal to correct.
                feedback = (
                    AttemptFeedback(exc.code) if exc.code in CORRECTABLE_PROPOSAL_ERRORS else None
                )
                final = TerminalOutcome.MODEL_ERROR
                if exc.disables_repair:
                    settings = self.adapter.settings
                    self.probe = ProbeResult(False, settings.provider, settings.model, exc.code)
                    self.adapter.readiness = self.probe
                attempt = attempt.model_copy(update={"outcome": exc.code})
                self.database.save_attempt(attempt)
                if exc.disables_repair or not exc.retryable:
                    break
                if exc.code not in CORRECTABLE_PROPOSAL_ERRORS:
                    retry_delay = max(
                        RETRY_BACKOFF_SECONDS * 2 ** (number - 1), exc.retry_after or 0.0
                    )
            except (PatchPolicyError, CandidateRejected) as exc:
                final = (
                    TerminalOutcome.INVALID_PATCH
                    if isinstance(exc, PatchPolicyError)
                    else TerminalOutcome.UNRESOLVED
                )
                previous_gate = "candidate_rejected"
                feedback = AttemptFeedback(
                    previous_gate,
                    rejected_diff=proposal.unified_diff if proposal else None,
                    policy_error=str(exc),
                )
                self.database.save_attempt(attempt.model_copy(update={"outcome": previous_gate}))
            except TimeoutError:
                stage = self.database.get_job(job_id).stage
                final = (
                    TerminalOutcome.MODEL_ERROR
                    if stage == JobStage.DIAGNOSING
                    else TerminalOutcome.UNRESOLVED
                )
                previous_gate = (
                    "provider_timeout"
                    if stage == JobStage.DIAGNOSING
                    else "verification_timeout"
                    if stage == JobStage.VERIFICATION
                    else "attempt_timeout"
                )
                feedback = (
                    AttemptFeedback(previous_gate, rejected_diff=proposal.unified_diff)
                    if proposal is not None
                    else None
                )
                self.database.save_attempt(attempt.model_copy(update={"outcome": previous_gate}))
                if previous_gate == "provider_timeout":
                    retry_delay = RETRY_BACKOFF_SECONDS * 2 ** (number - 1)
            except JobAbort as exc:
                self.database.save_attempt(attempt.model_copy(update={"outcome": exc.code}))
                if exc.outcome not in {TerminalOutcome.INVALID_PATCH, TerminalOutcome.UNRESOLVED}:
                    raise
                final, previous_gate = exc.outcome, exc.code
        self.database.update_job(
            job_id,
            error_details={
                "failed_stage": self.database.get_job(job_id).stage.value,
                "code": previous_gate,
            },
        )
        return final

    async def _cleanup_job(self, installation: str, job_id: str, started: float) -> bool:
        """Attempt independent teardown actions within the reserved cleanup budget."""
        deadline = asyncio.get_running_loop().time() + max(
            0, min(self.budgets.cleanup, started + self.budgets.overall - time.monotonic())
        )
        clean = True
        try:
            async with asyncio.timeout_at(deadline):
                await self.runtime.cleanup(installation, job_id)
        except (Exception, asyncio.CancelledError):
            logger.exception("Runtime cleanup for job %s was not confirmed", job_id)
            clean = False
        finally:
            try:
                async with asyncio.timeout_at(deadline):
                    await self.snapshots.cleanup(job_id)
            except (Exception, asyncio.CancelledError):
                logger.exception("Snapshot cleanup for job %s was not confirmed", job_id)
                clean = False
        return clean

    async def run_job(self, job_id: str) -> OrchestratorJob:
        """Run the seven-stage machine, always attempting cleanup before terminal state."""
        async with self._job_lock:
            self.database.reserve_worker(self._owner_id)
            # Capture ownership before any workflow side effects or logging faults.
            installation = self.database.get_lease().installation_id
            if not self.database.claim_job(job_id):
                if self.database.get_lease().quarantined:
                    self._supervision_failed = True
                return self.database.get_job(job_id)
            lease = self.database.get_lease()
            parent = asyncio.current_task()
            assert parent is not None
            heartbeat_failed = False

            async def heartbeat() -> None:
                nonlocal heartbeat_failed
                try:
                    while True:
                        await asyncio.sleep(HEARTBEAT_SECONDS)
                        if lease.owner_id is None or not self.database.heartbeat_lease(
                            lease.owner_id, lease.generation_id
                        ):
                            raise RuntimeUnavailable("lease_heartbeat_rejected")
                except Exception:
                    heartbeat_failed = True
                    self._supervision_failed = True
                    logger.exception("Lease heartbeat failed for job %s", job_id)
                    # The parent owns cancellation-safe cleanup. Stop side effects
                    # immediately; do not let a detached task continue the job.
                    parent.cancel("lease_heartbeat_failed")

            renewal = asyncio.create_task(heartbeat(), name="faultline-lease-heartbeat")
            try:
                result = await self._run_claimed_job(job_id, installation)
                if heartbeat_failed:
                    raise RuntimeUnavailable("lease_heartbeat_failed")
                return result
            except (Exception, asyncio.CancelledError):
                self._supervision_failed = True
                try:
                    self.database.quarantine_runtime()
                except Exception:
                    logger.exception("Job finalization could not persist quarantine")
                raise
            finally:
                renewal.cancel()
                await asyncio.gather(renewal, return_exceptions=True)

    async def _run_claimed_job(self, job_id: str, installation: str) -> OrchestratorJob:
        """Keep resource disposal independent of workflow and persistence failures."""
        started = time.monotonic()
        outcome = TerminalOutcome.INFRASTRUCTURE_ERROR
        details: dict[str, Any] | None = None
        try:
            try:
                outcome = await self._workflow(job_id, started)
            except JobAbort as exc:
                outcome = exc.outcome
                details = {
                    "code": exc.code,
                    "failed_stage": self.database.get_job(job_id).stage.value,
                }
            except ArtifactError:
                outcome = TerminalOutcome.ARTIFACT_ERROR
                details = {
                    "code": "artifact_error",
                    "failed_stage": self.database.get_job(job_id).stage.value,
                }
            except asyncio.CancelledError:
                outcome = (
                    TerminalOutcome.INTERRUPTED if self._stopping else TerminalOutcome.CANCELLED
                )
                details = {
                    "code": outcome.value,
                    "failed_stage": self.database.get_job(job_id).stage.value,
                }
            except Exception as exc:
                logger.exception("Job %s failed in a trusted operation", job_id)
                details = {
                    "code": "trusted_operation_failed",
                    "exception_type": type(exc).__name__,
                    "failed_stage": self.database.get_job(job_id).stage.value,
                }
                if isinstance(exc, RuntimeUnavailable | CandidateRejected):
                    # Their messages are fixed reason codes, never untrusted content.
                    details["reason"] = str(exc)[:120]
            if time.monotonic() >= started + self.budgets.work:
                outcome = TerminalOutcome.TIMEOUT
            if (
                self.database.get_job(job_id).cancel_requested
                and outcome != TerminalOutcome.TIMEOUT
            ):
                outcome = TerminalOutcome.CANCELLED
            self.database.transition(job_id, JobStage.CLEANUP)
            self.database.update_job(job_id, cleanup_status=CleanupStatus.IN_PROGRESS)
        finally:
            # Teardown owns its deadline and task. Incoming (even repeated)
            # cancellation must not cancel resource disposal or skip bookkeeping.
            cleanup = asyncio.create_task(self._cleanup_job(installation, job_id, started))
            while True:
                try:
                    clean = await asyncio.shield(cleanup)
                    break
                except asyncio.CancelledError:
                    outcome = (
                        TerminalOutcome.INTERRUPTED if self._stopping else TerminalOutcome.CANCELLED
                    )
                    details = {**(details or {}), "code": outcome.value}
                    if cleanup.cancelled():
                        clean = False
                        break
            if not clean:
                details = {**(details or {}), "cleanup_error": "resource_cleanup_unconfirmed"}
        # Keep failed-attempt details unless a more specific outer failure exists.
        if self.database.get_job(job_id).cancel_requested and outcome != TerminalOutcome.TIMEOUT:
            outcome = TerminalOutcome.CANCELLED
        details = details or self.database.get_job(job_id).error_details
        if clean and outcome == TerminalOutcome.VERIFIED:
            saved_proofs: list[Artifact] = []
            try:
                # Re-read durable provenance after disposal, never a stale
                # pre-cleanup job or a fabricated completed job object.
                self.database.update_job(job_id, cleanup_status=CleanupStatus.SUCCEEDED)

                def publish(job: OrchestratorJob) -> None:
                    executions = self.database.list_executions(job_id)
                    attempt = self.database.list_attempts(job_id)[-1]
                    validation = attempt.validation_result or {}
                    baseline = next(
                        e.report
                        for e in executions
                        if e.report.execution_id == job.baseline_execution_id
                    )
                    verification = next(
                        e.report
                        for e in executions
                        if e.report.execution_id == validation.get("verification_execution_id")
                    )
                    self.evidence.verify_job(job_id)
                    saved_proofs.extend(
                        self._save_bundle(
                            job, baseline, verification, attempt.parsed_diff or "", attempt.id
                        )
                    )

                return self.database.finalize_verified(job_id, publish)
            except Exception:
                logger.exception("Final proof for job %s failed", job_id)
                self._discard_proof_files(saved_proofs)
                outcome = TerminalOutcome.ARTIFACT_ERROR
                details = {"code": "artifact_error", "failed_stage": JobStage.CLEANUP.value}
        return self.database.finish_job(job_id, outcome, clean=clean, error_details=details)

    async def reconcile(self) -> None:
        """Abandon interrupted jobs; never resume midway through a candidate mutation."""
        self.database.reserve_worker(self._owner_id)
        lease = self.database.get_lease()
        installation = lease.installation_id
        jobs = self.database.unfinished_jobs()
        # Persist before the first await: cancellation or another crash during
        # recovery must never expose an apparently idle, clean runtime.
        if jobs or lease.owner_id is not None:
            self.database.quarantine_runtime()
        reconciliation_error: Exception | None = None
        try:
            async with asyncio.timeout(self.budgets.preflight):
                # Fresh runtime objects have no in-memory generations. Only the
                # installation sweep can discover scopes orphaned by SIGKILL.
                await self.runtime.reconcile(installation)
        except Exception as exc:
            self.database.quarantine_runtime()
            reconciliation_error = exc
        for job in jobs:
            clean = await self._cleanup_job(installation, job.id, time.monotonic())
            clean = clean and self.runtime.ready and reconciliation_error is None
            self.database.finish_job(
                job.id,
                TerminalOutcome.INTERRUPTED,
                clean=clean,
                error_details={"code": "controller_restart", "failed_stage": job.stage.value},
            )
        if reconciliation_error is not None:
            raise reconciliation_error
        lease = self.database.get_lease()
        if lease.owner_id is not None and lease.owner_id.startswith("reset:"):
            # This controller is the sole startup owner. An interrupted reset
            # cannot remain an active maintenance reservation after restart.
            # Keep quarantine until an explicit reset confirms all cleanup.
            self.database.finish_reset(lease.owner_id, clean=False)

    async def reset(self) -> None:
        """Reserve idle maintenance and clear quarantine only after confirmed cleanup."""
        self.database.reserve_worker(self._owner_id)
        if self._supervision_failed:
            await self.reconcile()
        lease = self.database.begin_reset()
        if lease.owner_id is None:
            raise RuntimeError("Reset reservation has no owner")
        clean = False
        try:
            async with asyncio.timeout(self.budgets.preflight):
                if not self.runtime.ready:
                    raise RuntimeError("Runtime is not ready")
                await self.runtime.reconcile(lease.installation_id)
                if lease.job_id:
                    await self.runtime.cleanup(lease.installation_id, lease.job_id)
                    await self.snapshots.cleanup(lease.job_id)
                await self.snapshots.manifest()
                clean = True
        finally:
            self.database.finish_reset(lease.owner_id, clean=clean)
        self._supervision_failed = False
        self.notify()
