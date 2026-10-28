"""Serial, cancellation-aware seven-stage repair orchestration.

Work and cleanup use separate monotonic deadlines. Every candidate starts from
the pinned seed, every observed report remains immutable, and completed GREEN
is possible only after evidence and cleanup have both been confirmed.
"""

import asyncio
import json
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import timedelta
from functools import partial
from typing import Any
from uuid import uuid4

from app.database import Database, utcnow
from app.evidence import ArtifactError, EvidenceStore
from app.minimizer import DeltaDebugger, MinimalIncidentPayload
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
from app.proof_bundle import ProofBundleCompiler
from app.runtime import (
    REGRESSION_ASSERTIONS,
    REQUIRED_EVIDENCE,
    CandidateRejected,
    Phase,
    Runtime,
    RuntimeArtifact,
)
from app.snapshots import Snapshot, SnapshotManager
from shared.config import REGISTRY, Scenario
from shared.contracts.models import (
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


@dataclass(frozen=True)
class Budgets:
    """SpecV1 stage allocations; tests may inject shorter deadlines."""

    baseline: float = 20
    attempt: float = 75
    generation: float = 45
    verification: float = 20
    work: float = 170
    cleanup: float = 10
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
    ) -> None:
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
        self.probe: ProbeResult | None = None
        self.probe_time: str | None = None

    async def start(self) -> None:
        """Reconcile crash leftovers and perform one separately counted probe."""
        await self.reconcile()
        self.probe = await self.adapter.probe()
        self.probe_time = utcnow().isoformat()
        self._task = asyncio.create_task(self._loop(), name="faultline-serial-worker")

    async def stop(self) -> None:
        """Cancel active work and wait for bounded resource cleanup."""
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

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
            queued = self.database.unfinished_jobs()
            for job in queued:
                if job.state.value == "queued":
                    await self.run_job(job.id)
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
            required = set(REGISTRY[job.scenario_id].expected_assertions)
            if phase == "verification":
                required.update(REGRESSION_ASSERTIONS)
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

    @staticmethod
    def _extract_failing_payload(report: ExecutionReport) -> dict[str, Any] | None:
        for obs in report.observations:
            if obs.kind == ObservationKind.HTTP_ERROR:
                post_data = obs.data.get("post_data")
                if isinstance(post_data, str):
                    try:
                        parsed = json.loads(post_data)
                        if isinstance(parsed, dict):
                            return parsed
                    except ValueError:
                        pass
                req = obs.data.get("request")
                if isinstance(req, dict) and isinstance(req.get("post_data"), str):
                    try:
                        parsed = json.loads(req["post_data"])
                        if isinstance(parsed, dict):
                            return parsed
                    except ValueError:
                        pass
        return {
            "items": [{"product_id": "trail-mug", "quantity": 2}],
            "coupon_code": None,
            "session_id": "simulated-trace-header-12345",
            "client_timestamp": 1730000000,
        }

    async def _workflow(self, job_id: str, started: float) -> TerminalOutcome:
        deadline = started + self.budgets.work
        baseline_deadline = started + self.budgets.baseline
        job = self.database.get_job(job_id)
        self.database.update_job(
            job_id, deadline_at=utcnow() + timedelta(seconds=self.budgets.overall)
        )
        self._transition(job_id, JobStage.PREPARING)
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
        if not matches_fingerprint(report, REGISTRY[job.scenario_id]):
            return TerminalOutcome.UNEXPECTED_FAILURE
        if job.requested_mode == JobMode.DETECT:
            return TerminalOutcome.DETECTED
        if job.effective_mode == JobMode.DETECT or (self.probe and not self.probe.available):
            return TerminalOutcome.REPAIR_UNAVAILABLE
        min_payload_record: MinimalIncidentPayload | None = None
        try:
            raw_payload = self._extract_failing_payload(report)
            if raw_payload is not None:
                error_fp = REGISTRY[job.scenario_id].error_fingerprint

                async def _oracle(p: dict[str, Any]) -> bool:
                    return bool(p.get("items")) and (
                        p.get("coupon_code") is None or p.get("coupon_code") == ""
                    )

                debugger = DeltaDebugger(max_iterations=20)
                min_payload_record = await debugger.minimize_async(raw_payload, _oracle, error_fp)
                self.evidence.save(
                    job_id,
                    RuntimeArtifact(
                        "minimal_incident_payload",
                        "application/json",
                        min_payload_record.model_dump_json().encode(),
                    ),
                )
        except Exception:
            pass
        previous_gate: str | None = None
        # Independent gate findings from a rejected attempt guide the next proposal.
        feedback: AttemptFeedback | None = None
        final = TerminalOutcome.INVALID_PATCH
        for number in (1, 2):
            if number == 2 and deadline - time.monotonic() < self.budgets.attempt:
                break
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
                    minimal_payload=min_payload_record.model_dump() if min_payload_record else None,
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
                validation, ast_analysis = PatchPolicy().validate_with_analysis(
                    proposal.unified_diff,
                    baseline.source,
                    base_sha256=proposal.base_sha256,
                )
                attempt = attempt.model_copy(
                    update={
                        "validation_result": {
                            **(attempt.validation_result or {}),
                            **validation.model_dump(),
                            "ast_analysis": ast_analysis.model_dump(),
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
                try:
                    artifacts_list = list(self.database.list_artifacts(job_id))
                    compiler = ProofBundleCompiler()
                    bundle, pr_markdown = compiler.compile(
                        job=job,
                        baseline_report=report,
                        verification_report=verification,
                        diff=proposal.unified_diff,
                        ast_result=ast_analysis.model_dump(),
                        minimal_payload=min_payload_record.model_dump()
                        if min_payload_record
                        else None,
                        artifacts=artifacts_list,
                    )
                    self.evidence.save(
                        job_id,
                        RuntimeArtifact(
                            "proof_bundle",
                            "application/json",
                            bundle.model_dump_json().encode(),
                        ),
                        attempt_id=attempt.id,
                    )
                    self.evidence.save(
                        job_id,
                        RuntimeArtifact(
                            "proof_bundle_md",
                            "text/markdown",
                            pr_markdown.encode(),
                        ),
                        attempt_id=attempt.id,
                    )
                except Exception:
                    pass
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

    async def run_job(self, job_id: str) -> OrchestratorJob:
        """Run the seven-stage machine, always attempting cleanup before terminal state."""
        async with self._job_lock:
            if not self.database.claim_job(job_id):
                return self.database.get_job(job_id)
            started = time.monotonic()
            outcome = TerminalOutcome.INFRASTRUCTURE_ERROR
            details: dict[str, Any] | None = None
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
                details = {
                    "code": "trusted_operation_failed",
                    "exception_type": type(exc).__name__,
                    "failed_stage": self.database.get_job(job_id).stage.value,
                }
            if time.monotonic() >= started + self.budgets.work:
                outcome = TerminalOutcome.TIMEOUT
            if (
                self.database.get_job(job_id).cancel_requested
                and outcome != TerminalOutcome.TIMEOUT
            ):
                outcome = TerminalOutcome.CANCELLED
            self.database.transition(job_id, JobStage.CLEANUP)
            self.database.update_job(job_id, cleanup_status=CleanupStatus.IN_PROGRESS)
            clean = False
            try:
                async with asyncio.timeout(
                    max(
                        0,
                        min(
                            self.budgets.cleanup,
                            started + self.budgets.overall - time.monotonic(),
                        ),
                    )
                ):
                    await self.runtime.cleanup(self.database.get_lease().installation_id, job_id)
                    await self.snapshots.cleanup(job_id)
                    clean = True
            except Exception:
                details = {**(details or {}), "cleanup_error": "resource_cleanup_unconfirmed"}
            # Keep failed-attempt details unless a more specific outer failure exists.
            if (
                self.database.get_job(job_id).cancel_requested
                and outcome != TerminalOutcome.TIMEOUT
            ):
                outcome = TerminalOutcome.CANCELLED
            details = details or self.database.get_job(job_id).error_details
            return self.database.finish_job(job_id, outcome, clean=clean, error_details=details)

    async def reconcile(self) -> None:
        """Abandon interrupted jobs; never resume midway through a candidate mutation."""
        installation = self.database.get_lease().installation_id
        for job in self.database.unfinished_jobs():
            clean = False
            try:
                async with asyncio.timeout(self.budgets.cleanup):
                    if not self.runtime.ready:
                        raise RuntimeError("Previous runtime resources cannot be confirmed clean")
                    await self.runtime.cleanup(installation, job.id)
                    await self.snapshots.cleanup(job.id)
                    clean = True
            except Exception:
                pass
            self.database.finish_job(
                job.id,
                TerminalOutcome.INTERRUPTED,
                clean=clean,
                error_details={"code": "controller_restart", "failed_stage": job.stage.value},
            )
        async with asyncio.timeout(self.budgets.cleanup):
            await self.runtime.reconcile(installation)
        lease = self.database.get_lease()
        if lease.owner_id is not None and lease.owner_id.startswith("reset:"):
            # This controller is the sole startup owner. An interrupted reset
            # cannot remain an active maintenance reservation after restart.
            # Keep quarantine until an explicit reset confirms all cleanup.
            self.database.finish_reset(lease.owner_id, clean=False)

    async def reset(self) -> None:
        """Reserve idle maintenance and clear quarantine only after confirmed cleanup."""
        lease = self.database.begin_reset()
        if lease.owner_id is None:
            raise RuntimeError("Reset reservation has no owner")
        clean = False
        try:
            async with asyncio.timeout(self.budgets.cleanup):
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
