"""The evidence bundle restates recorded values and checksums all of them."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.proof_bundle import ProofBundle, ProofBundleCompiler, bundle_digest
from shared.contracts.models import (
    ArtifactSummary,
    AssertionResult,
    CleanupStatus,
    ExecutionRecord,
    ExecutionReport,
    ExecutionVerdict,
    JobMode,
    JobStage,
    JobState,
    Observation,
    ObservationKind,
    OrchestratorJob,
    RepairAttempt,
)


def _make_sample_job() -> OrchestratorJob:
    now = datetime.now(UTC)
    return OrchestratorJob(
        id=str(uuid4()),
        scenario_id="scripted_checkout_repair",
        state=JobState.RUNNING,
        stage=JobStage.CLEANUP,
        cleanup_status=CleanupStatus.SUCCEEDED,
        created_at=now,
        updated_at=now,
        idempotency_key="idem-key-123",
        request_fingerprint="fp-123",
        requested_mode=JobMode.REPAIR,
        effective_mode=JobMode.REPAIR,
        seed_commit="a" * 40,
        seed_source_hash="b" * 64,
    )


def _make_report(verdict: ExecutionVerdict, duration_ms: float) -> ExecutionReport:
    now = datetime.now(UTC)
    obs = [
        Observation(
            id=str(uuid4()),
            kind=ObservationKind.SERVER_EXCEPTION,
            source="apps/buggyshop-backend/app/routes/checkout.py",
            message="TypeError: unsupported operand type(s) for -: 'int' and 'NoneType'",
            data={},
            timestamp=now,
        )
    ]
    assertions = [
        AssertionResult(
            id="checkout.status_201",
            passed=verdict == ExecutionVerdict.PASSED,
            expected="HTTP 201",
            observed="HTTP 201" if verdict == ExecutionVerdict.PASSED else "HTTP 500",
            duration_ms=5.0,
        ),
        AssertionResult(
            id="checkout.total_matches_subtotal",
            passed=verdict == ExecutionVerdict.PASSED,
            expected="total == 3998",
            observed="total == 3998" if verdict == ExecutionVerdict.PASSED else "None",
            duration_ms=2.0,
        ),
    ]
    return ExecutionReport(
        execution_id=str(uuid4()),
        case_id=str(uuid4()),
        scenario_id="scripted_checkout_repair",
        verdict=verdict,
        duration_ms=duration_ms,
        observations=obs,
        assertions=assertions,
        raw_logs="sample server logs",
    )


DIFF = (
    "--- a/apps/buggyshop-backend/app/routes/checkout.py\n"
    "+++ b/apps/buggyshop-backend/app/routes/checkout.py\n"
    "@@ -43,1 +43,1 @@\n"
    "-    discount = cast(int, discounts.get(coupon_code))\n"
    "+    discount = cast(int, discounts.get(coupon_code, 0))\n"
)


def artifact(job_id: str, role: str, content: bytes) -> ArtifactSummary:
    from hashlib import sha256

    return ArtifactSummary(
        id=str(uuid4()),
        job_id=job_id,
        role=role,
        content_type="application/octet-stream",
        size_bytes=len(content),
        sha256=sha256(content).hexdigest(),
        created_at=datetime.now(UTC),
    )


def compile_sample(
    job: OrchestratorJob,
    baseline: ExecutionReport,
    verification: ExecutionReport,
    items: list[ArtifactSummary] | None = None,
) -> tuple[ProofBundle, str]:
    """Compile explicit simulation provenance, never claiming isolated execution."""
    attempt_id, generation = str(uuid4()), str(uuid4())
    items = items or []
    records = [
        ExecutionRecord(
            job_id=job.id,
            phase=phase,  # type: ignore[arg-type]
            attempt_id=attempt_id if phase == "verification" else None,
            app_generation_id=generation if phase == "verification" else "baseline-generation",
            candidate_snapshot_sha256=("c" if phase == "verification" else "d") * 64,
            artifact_ids=[item.id for item in items],
            started_at=job.created_at,
            finished_at=job.updated_at,
            report=report,
        )
        for phase, report in (("baseline", baseline), ("verification", verification))
    ]
    return ProofBundleCompiler().compile(
        job=job.model_copy(update={"baseline_execution_id": baseline.execution_id}),
        baseline_report=baseline,
        verification_report=verification,
        diff=DIFF,
        artifacts=items,
        executions=records,
        attempt=RepairAttempt(
            id=attempt_id,
            job_id=job.id,
            attempt_number=1,
            parsed_diff=DIFF,
            validation_result={
                "verification_execution_id": verification.execution_id,
                "base_sha256": job.seed_source_hash,
                "candidate_sha256": "c" * 64,
                "target_sha256": "e" * 64,
                "app_generation_id": generation,
                "provider": "test-double",
                "model": "test-double",
            },
        ),
    )


def test_bundle_restates_recorded_values_under_one_digest() -> None:
    job = _make_sample_job()
    items = [artifact(job.id, "screenshot", b"png"), artifact(job.id, "trace", b"zip")]
    bundle, summary = compile_sample(
        job,
        _make_report(ExecutionVerdict.FAILED, 1200.0),
        _make_report(ExecutionVerdict.PASSED, 1500.0),
        items,
    )
    assert bundle.status == "verified" and bundle.baseline_verdict == "failed"
    assert (bundle.assertions_total, bundle.regressions_count) == (2, 0)
    assert bundle.baseline_fingerprint.startswith("TypeError")
    assert [item.id for item in bundle.evidence_manifest] == [item.id for item in items]
    assert bundle.bundle_digest == bundle_digest(bundle.model_dump())
    # Every field is covered: changing any recorded value changes the digest.
    for field, value in (("verification_verdict", "failed"), ("patch_diff", DIFF + " ")):
        assert bundle_digest({**bundle.model_dump(), field: value}) != bundle.bundle_digest
    tampered = bundle.model_dump()
    tampered["evidence_manifest"][0]["sha256"] = "0" * 64
    assert bundle_digest(tampered) != bundle.bundle_digest
    assert "2 of 2" in summary and bundle.bundle_digest in summary
    assert "not a signature" in summary
    for claim in ("Cryptographically", "Signed", "Zero Regressions", "ddmin", "1-Minimal"):
        assert claim not in summary


def test_failed_verification_is_never_summarized_as_verified() -> None:
    job = _make_sample_job()
    with pytest.raises(ValueError, match="verified reports"):
        compile_sample(
            job,
            _make_report(ExecutionVerdict.FAILED, 1200.0),
            _make_report(ExecutionVerdict.FAILED, 1500.0),
        )


@pytest.mark.parametrize("cleanup", [CleanupStatus.IN_PROGRESS, CleanupStatus.FAILED])
def test_compiler_refuses_unconfirmed_cleanup(cleanup: CleanupStatus) -> None:
    job = _make_sample_job().model_copy(update={"cleanup_status": cleanup})
    with pytest.raises(ValueError, match="confirmed cleanup"):
        compile_sample(
            job, _make_report(ExecutionVerdict.FAILED, 1), _make_report(ExecutionVerdict.PASSED, 1)
        )
