"""Hero loop, rejection paths, cancellation, deadlines, and crash recovery."""

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from conftest import Harness, submission

from app.database import DatabaseError
from app.evidence import ArtifactError
from app.model_adapter import ModelError, ModelResponse, RepairContext
from app.policy import TARGET_FILE
from app.runtime import RuntimeArtifact
from app.worker import Budgets
from shared.contracts.models import (
    Artifact,
    CleanupStatus,
    JobEvent,
    JobMode,
    JobStage,
    JobState,
    TerminalOutcome,
)


async def test_full_simulated_hero_loop_exercises_actual_exported_api(harness: Harness) -> None:
    harness.runtime.real_api = True
    seed_bytes = (harness.snapshots.repository_root / TARGET_FILE).read_bytes()
    job = await harness.run()
    assert job.outcome == TerminalOutcome.VERIFIED, job.error_details
    assert job.state == JobState.SUCCEEDED and job.cleanup_status == CleanupStatus.SUCCEEDED
    assert harness.database.get_lease().owner_id is None
    reports = harness.database.list_executions(job.id)
    assert reports[0].report.verdict.value == "failed"
    assert reports[1].report.verdict.value == "passed"
    assert all(item.passed for item in reports[1].report.assertions)
    assert len(reports[1].report.assertions) == 36
    assert reports[0].candidate_snapshot_sha256 != reports[1].candidate_snapshot_sha256
    stages = [item.stage for item in harness.database.list_events(job.id)]
    assert stages == [
        JobStage.PREPARING,
        JobStage.PREPARING,
        JobStage.BASELINE,
        JobStage.DIAGNOSING,
        JobStage.PATCH_VALIDATION,
        JobStage.ACTIVATING,
        JobStage.VERIFICATION,
        JobStage.CLEANUP,
        JobStage.COMPLETED,
    ]
    assert (harness.snapshots.repository_root / TARGET_FILE).read_bytes() == seed_bytes
    assert not (harness.root / f"jobs/{job.id}/runtime").exists()
    assert harness.database.list_artifacts(job.id)
    harness.evidence.verify_job(job.id)


@pytest.mark.parametrize(
    "flag,outcome",
    [
        ("unexpected", TerminalOutcome.UNEXPECTED_FAILURE),
        ("baseline_passed", TerminalOutcome.NO_FAILURE),
        ("infrastructure_error", TerminalOutcome.INFRASTRUCTURE_ERROR),
        ("missing_evidence", TerminalOutcome.ARTIFACT_ERROR),
        ("wrong_generation", TerminalOutcome.INFRASTRUCTURE_ERROR),
        ("exit_disagreement", TerminalOutcome.INFRASTRUCTURE_ERROR),
        ("incomplete_suite", TerminalOutcome.INFRASTRUCTURE_ERROR),
        ("verification_failed", TerminalOutcome.UNRESOLVED),
        ("activation_failed", TerminalOutcome.UNRESOLVED),
    ],
)
async def test_classified_terminal_paths(
    harness: Harness, flag: str, outcome: TerminalOutcome
) -> None:
    setattr(harness.runtime, flag, True)
    job = await harness.run()
    assert job.outcome == outcome, job.error_details
    assert job.cleanup_status == CleanupStatus.SUCCEEDED
    assert harness.runtime.calls[-1] == "cleanup"
    if flag in {"verification_failed", "activation_failed"}:
        assert len(harness.database.list_attempts(job.id)) == 2
        seeds = [snapshot.source_sha256 for snapshot in harness.runtime.snapshots]
        assert seeds[1] == seeds[2]


async def test_second_attempt_receives_failed_verification_checks(harness: Harness) -> None:
    harness.runtime.verification_failed = True
    original = harness.adapter.propose_patch
    contexts: list[RepairContext] = []

    async def observe(context: RepairContext, *, fallback: bool = False) -> ModelResponse:
        contexts.append(context)
        return await original(context)

    harness.adapter.propose_patch = observe  # type: ignore[method-assign]
    job = await harness.run()
    assert job.outcome == TerminalOutcome.UNRESOLVED
    assert [context.feedback is None for context in contexts] == [True, False]
    feedback = contexts[1].feedback
    assert feedback is not None and feedback.gate == "verification_failed"
    assert feedback.failed_count == len(feedback.failed_checks) > 0
    assert feedback.rejected_diff and "get(coupon_code, 0)" in feedback.rejected_diff
    assert "regression.missing_coupon" in {check.id for check in feedback.failed_checks}
    first, second = harness.database.list_attempts(job.id)
    assert first.validation_result and "prior_feedback" not in first.validation_result
    assert second.validation_result is not None
    prior = second.validation_result["prior_feedback"]
    assert prior["gate"] == "verification_failed" and prior["included_rejected_diff"] is True
    assert prior["failed_check_count"] == feedback.failed_count
    for attempt in (first, second):
        result = attempt.validation_result or {}
        assert result["provider"] == "deterministic"
        assert isinstance(result["generation_ms"], int) and result["generation_ms"] >= 0


async def test_policy_rejection_feeds_the_policy_error_forward(harness: Harness) -> None:
    original = harness.adapter.propose_patch
    contexts: list[RepairContext] = []

    async def malformed_then_valid(
        context: RepairContext, *, fallback: bool = False
    ) -> ModelResponse:
        contexts.append(context)
        result = await original(context)
        if len(contexts) == 1:
            broken = result.proposal.unified_diff.replace("@@ -40,7", "@@ -40,9")
            return replace(
                result, proposal=result.proposal.model_copy(update={"unified_diff": broken})
            )
        return result

    harness.adapter.propose_patch = malformed_then_valid  # type: ignore[method-assign]
    job = await harness.run()
    assert job.outcome == TerminalOutcome.VERIFIED, job.error_details
    feedback = contexts[1].feedback
    assert feedback is not None and feedback.gate == "patch_policy_rejected"
    assert feedback.policy_error and "line counts" in feedback.policy_error
    attempts = harness.database.list_attempts(job.id)
    assert [item.outcome for item in attempts] == ["patch_policy_rejected", "verified"]


async def test_transport_failure_retries_without_fabricated_feedback(harness: Harness) -> None:
    original = harness.adapter.propose_patch
    contexts: list[RepairContext] = []

    async def flaky(context: RepairContext, *, fallback: bool = False) -> ModelResponse:
        contexts.append(context)
        if len(contexts) == 1:
            raise ModelError("provider_transport", retryable=True)
        return await original(context)

    harness.adapter.propose_patch = flaky  # type: ignore[method-assign]
    job = await harness.run()
    assert job.outcome == TerminalOutcome.VERIFIED, job.error_details
    assert contexts[1].previous_gate == "provider_transport"
    assert contexts[1].feedback is None


async def test_explicit_detection_and_unavailable_repair(harness: Harness) -> None:
    job = await harness.run(mode=JobMode.DETECT)
    assert job.outcome == TerminalOutcome.DETECTED
    assert not harness.database.list_attempts(job.id)
    job = harness.database.create_job(
        submission(), effective_mode=JobMode.DETECT, repair_block_reason="model_unavailable"
    )
    done = await harness.worker.run_job(job.id)
    assert done.outcome == TerminalOutcome.REPAIR_UNAVAILABLE
    assert not harness.database.list_attempts(job.id)


async def test_invalid_proposals_are_bounded_and_never_activated(harness: Harness) -> None:
    original = harness.adapter.propose_patch

    async def invalid(context: RepairContext, *, fallback: bool = False) -> ModelResponse:
        result = await original(context)
        return replace(
            result, proposal=result.proposal.model_copy(update={"unified_diff": "invalid"})
        )

    harness.adapter.propose_patch = invalid  # type: ignore[method-assign]
    job = await harness.run()
    assert job.outcome == TerminalOutcome.INVALID_PATCH
    assert len(harness.database.list_attempts(job.id)) == 2
    assert "activate" not in harness.runtime.calls


@pytest.mark.parametrize("retryable,disabled,requests", [(True, False, 2), (False, True, 1)])
async def test_provider_failure_limits_and_disables_repair(
    harness: Harness,
    retryable: bool,
    disabled: bool,
    requests: int,
) -> None:
    mock = AsyncMock(
        side_effect=ModelError(
            "provider_http_401" if disabled else "provider_transport",
            retryable=retryable,
            disables_repair=disabled,
        )
    )
    harness.adapter.propose_patch = mock  # type: ignore[method-assign]
    job = await harness.run()
    assert job.outcome == TerminalOutcome.MODEL_ERROR
    assert mock.await_count == requests
    assert len(harness.database.list_attempts(job.id)) == requests
    if disabled:
        assert harness.worker.probe and not harness.worker.probe.available


async def test_valid_no_patch_stops_without_another_request(harness: Harness) -> None:
    original = harness.adapter.propose_patch

    async def no_patch(context: RepairContext, *, fallback: bool = False) -> ModelResponse:
        result = await original(context)
        return replace(
            result,
            proposal=result.proposal.model_copy(
                update={
                    "decision": "no_patch",
                    "target_file": "",
                    "base_sha256": "",
                    "unified_diff": "",
                }
            ),
        )

    harness.adapter.propose_patch = no_patch  # type: ignore[method-assign]
    job = await harness.run()
    assert job.outcome == TerminalOutcome.UNRESOLVED
    attempts = harness.database.list_attempts(job.id)
    assert len(attempts) == 1
    # Provider identity is recorded even when no patch reaches the policy gate.
    assert attempts[0].validation_result and attempts[0].validation_result["provider"]


async def test_cleanup_failure_blocks_green_and_reset_preserves_history(harness: Harness) -> None:
    harness.runtime.cleanup_failed = True
    job = await harness.run()
    assert job.outcome == TerminalOutcome.CLEANUP_FAILED
    assert job.error_details and job.error_details["last_work_outcome"] == "verified"
    assert harness.database.get_lease().quarantined
    artifacts = harness.database.list_artifacts(job.id)
    with pytest.raises(DatabaseError, match="cleanup_required"):
        harness.database.create_job(submission())
    harness.runtime.cleanup_failed = False
    await harness.worker.reset()
    assert not harness.database.get_lease().quarantined
    assert harness.database.list_artifacts(job.id) == artifacts
    assert harness.database.get_job(job.id) == job


async def test_artifact_corruption_prevents_verified(harness: Harness) -> None:
    def fail(job_id: str) -> None:
        raise ArtifactError("test checksum mismatch")

    harness.evidence.verify_job = fail  # type: ignore[method-assign]
    job = await harness.run()
    assert job.outcome == TerminalOutcome.ARTIFACT_ERROR
    assert harness.database.list_executions(job.id)[-1].report.verdict.value == "passed"


@pytest.mark.parametrize("phase", ["prepare", "baseline", "activate", "verification"])
async def test_cancellation_interrupts_blocking_operations(harness: Harness, phase: str) -> None:
    harness.runtime.block_phase = phase
    job = harness.database.create_job(submission())
    task = asyncio.create_task(harness.worker.run_job(job.id))
    await asyncio.wait_for(harness.runtime.entered.wait(), 5)
    harness.database.request_cancel(job.id)
    done = await asyncio.wait_for(task, 5)
    assert done.outcome == TerminalOutcome.CANCELLED
    assert done.cleanup_status == CleanupStatus.SUCCEEDED
    assert not harness.database.get_lease().quarantined


async def test_cancel_queued_job_has_no_runtime_side_effects(harness: Harness) -> None:
    job = harness.database.create_job(submission())
    harness.database.request_cancel(job.id)
    done = await harness.worker.run_job(job.id)
    assert done.outcome == TerminalOutcome.CANCELLED
    assert harness.runtime.calls == ["cleanup"]


async def test_global_work_timeout_and_local_baseline_timeout(harness: Harness) -> None:
    harness.runtime.block_phase = "prepare"
    harness.worker.budgets = replace(Budgets(), work=0.1)
    first = await harness.run()
    assert first.outcome == TerminalOutcome.TIMEOUT
    harness.worker.budgets = replace(Budgets(), baseline=0.1)
    second = await harness.run()
    assert second.outcome == TerminalOutcome.INFRASTRUCTURE_ERROR
    assert second.error_details and second.error_details["code"] == "baseline_timeout"


async def test_restart_marks_interrupted_and_releases_after_cleanup(harness: Harness) -> None:
    job = harness.database.create_job(submission())
    harness.database.claim_job(job.id)
    harness.database.transition(job.id, JobStage.DIAGNOSING)
    await harness.worker.reconcile()
    done = harness.database.get_job(job.id)
    assert done.state == JobState.INTERRUPTED
    assert done.outcome == TerminalOutcome.INTERRUPTED
    assert harness.database.get_lease().owner_id is None


async def test_restart_failed_cleanup_quarantines(harness: Harness) -> None:
    job = harness.database.create_job(submission())
    harness.runtime.ready = False
    await harness.worker.reconcile()
    assert harness.database.get_job(job.id).outcome == TerminalOutcome.CLEANUP_FAILED
    assert harness.database.get_lease().quarantined


async def test_serial_worker_and_shutdown_cleanup(harness: Harness) -> None:
    await harness.worker.start()
    try:
        harness.runtime.block_phase = "baseline"
        job = harness.database.create_job(submission())
        harness.worker.notify()
        await asyncio.wait_for(harness.runtime.entered.wait(), 5)
        with pytest.raises(DatabaseError, match="busy"):
            harness.database.create_job(submission())
    finally:
        await harness.worker.stop()
    assert harness.database.get_job(job.id).outcome == TerminalOutcome.INTERRUPTED
    assert harness.database.get_lease().owner_id is None


async def test_staged_index_export_excludes_fixtures_tests_and_git(harness: Harness) -> None:
    manifest = await harness.snapshots.manifest()
    job = harness.database.create_job(submission())
    source = (harness.snapshots.repository_root / TARGET_FILE).read_text()
    from hashlib import sha256

    from app.model_adapter import deterministic_diff

    candidate = await harness.snapshots.create(
        job.id,
        manifest,
        diff=deterministic_diff(source),
        base_sha256=sha256(source.encode()).hexdigest(),
    )
    exported = list(candidate.path.rglob("*"))
    assert exported and all(not path.is_symlink() for path in exported)
    assert all(
        ".git" not in path.parts and "fixtures" not in path.parts and "tests" not in path.parts
        for path in exported
    )
    assert "discounts.get(coupon_code, 0)" in (candidate.path / TARGET_FILE).read_text()
    assert "discounts.get(coupon_code))" in source
    await harness.snapshots.cleanup(job.id)
    harness.database.finish_job(job.id, TerminalOutcome.DETECTED, clean=True)


async def test_verification_timeout_is_recorded_and_never_green(harness: Harness) -> None:
    harness.runtime.block_phase = "verification"
    harness.worker.budgets = replace(Budgets(), verification=0.05)
    job = await harness.run()
    assert job.outcome == TerminalOutcome.UNRESOLVED
    reports = harness.database.list_executions(job.id)
    assert [item.report.verdict.value for item in reports] == ["failed", "timed_out", "timed_out"]
    assert all(
        item.outcome == "verification_timeout" for item in harness.database.list_attempts(job.id)
    )


async def test_diagnosis_cancellation_stops_model_and_cleans(harness: Harness) -> None:
    entered = asyncio.Event()

    async def blocked(context: RepairContext, *, fallback: bool = False) -> ModelResponse:
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("Unreachable")

    harness.adapter.propose_patch = blocked  # type: ignore[method-assign]
    job = harness.database.create_job(submission())
    task = asyncio.create_task(harness.worker.run_job(job.id))
    await asyncio.wait_for(entered.wait(), 5)
    harness.database.request_cancel(job.id)
    done = await asyncio.wait_for(task, 5)
    assert done.outcome == TerminalOutcome.CANCELLED
    assert "activate" not in harness.runtime.calls


@pytest.mark.parametrize(
    "stage", [JobStage.PATCH_VALIDATION, JobStage.ACTIVATING, JobStage.VERIFICATION]
)
async def test_cancel_at_stage_boundary_precedes_side_effects(
    harness: Harness,
    stage: JobStage,
) -> None:
    original = harness.database.transition
    cancel_stage = stage

    def cancel_on_transition(job_id: str, stage: JobStage, code: str | None = None) -> JobEvent:
        event = original(job_id, stage, code)
        if stage == cancel_stage:
            harness.database.request_cancel(job_id)
        return event

    harness.database.transition = cancel_on_transition  # type: ignore[method-assign]
    job = await harness.run()
    assert job.outcome == TerminalOutcome.CANCELLED
    assert "verification" not in harness.runtime.calls
    if stage in {JobStage.PATCH_VALIDATION, JobStage.ACTIVATING}:
        assert "activate" not in harness.runtime.calls


async def test_evidence_failure_preserves_observed_verification(harness: Harness) -> None:
    original = harness.evidence.save

    def fail_after_verification(
        job_id: str,
        evidence: RuntimeArtifact,
        *,
        execution_id: str | None = None,
        attempt_id: str | None = None,
    ) -> Artifact:
        if "verification" in harness.runtime.calls:
            raise ArtifactError("simulated durable write failure")
        return original(job_id, evidence, execution_id=execution_id, attempt_id=attempt_id)

    harness.evidence.save = fail_after_verification  # type: ignore[method-assign]
    job = await harness.run()
    assert job.outcome == TerminalOutcome.ARTIFACT_ERROR
    records = harness.database.list_executions(job.id)
    assert records[-1].report.verdict.value == "passed"
    assert not records[-1].artifact_ids


async def test_duplicate_worker_does_not_reexecute_terminal_job(harness: Harness) -> None:
    job = await harness.run()
    calls = list(harness.runtime.calls)
    assert await harness.worker.run_job(job.id) == job
    assert harness.runtime.calls == calls


@pytest.mark.parametrize("quarantined", [False, True])
async def test_restart_recovers_interrupted_reset_reservation(
    harness: Harness, quarantined: bool
) -> None:
    if quarantined:
        job = harness.database.create_job(submission())
        harness.database.finish_job(job.id, TerminalOutcome.INFRASTRUCTURE_ERROR, clean=False)
    interrupted = harness.database.begin_reset()
    assert interrupted.owner_id is not None
    assert not harness.database.unfinished_jobs()

    await harness.worker.reconcile()

    recovered = harness.database.get_lease()
    assert recovered.owner_id is None
    assert recovered.quarantined
    assert recovered.job_id == interrupted.job_id
    with pytest.raises(DatabaseError, match="cleanup_required"):
        harness.database.create_job(submission())
    await harness.worker.reset()
    assert not harness.database.get_lease().quarantined
    assert harness.database.create_job(submission()).state == JobState.QUEUED


async def test_verified_job_bundle_matches_its_stored_evidence(harness: Harness) -> None:
    import json

    from tools.verify_bundle import verify_bundle

    job = await harness.run()
    assert job.outcome == TerminalOutcome.VERIFIED
    artifacts = {item.role: item for item in harness.database.list_artifacts(job.id)}
    assert "minimal_incident_payload" not in artifacts
    bundle = json.loads(harness.evidence.read(artifacts["proof_bundle"]))
    directory = harness.root / "exported"
    directory.mkdir()
    for item in harness.database.list_artifacts(job.id):
        if item.id in {entry["id"] for entry in bundle["evidence_manifest"]}:
            (directory / f"{item.id}.bin").write_bytes(harness.evidence.read(item))
    consistent, messages = verify_bundle(bundle, directory)
    assert consistent, messages
    assert bundle["assertions_total"] == 36 and bundle["regressions_count"] == 0
    harness.evidence.verify_job(job.id)


async def test_bundle_compilation_fault_is_logged_not_silent(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    from app.proof_bundle import ProofBundleCompiler

    def broken(*args: object, **kwargs: object) -> None:
        raise ValueError("test compiler fault")

    original = ProofBundleCompiler.compile
    ProofBundleCompiler.compile = broken  # type: ignore[method-assign,assignment]
    try:
        job = await harness.run()
    finally:
        ProofBundleCompiler.compile = original  # type: ignore[method-assign]
    assert job.outcome == TerminalOutcome.VERIFIED
    assert "Evidence bundle compilation failed" in caplog.text
    assert "proof_bundle" not in {item.role for item in harness.database.list_artifacts(job.id)}
