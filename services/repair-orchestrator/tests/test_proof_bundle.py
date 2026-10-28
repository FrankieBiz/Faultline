"""The evidence bundle restates recorded values and checksums all of them."""

from datetime import UTC, datetime
from uuid import uuid4

from app.proof_bundle import ProofBundleCompiler, bundle_digest
from shared.contracts.models import (
    ArtifactSummary,
    AssertionResult,
    CleanupStatus,
    ExecutionReport,
    ExecutionVerdict,
    JobMode,
    JobStage,
    JobState,
    Observation,
    ObservationKind,
    OrchestratorJob,
)


def _make_sample_job() -> OrchestratorJob:
    now = datetime.now(UTC)
    return OrchestratorJob(
        id=str(uuid4()),
        scenario_id="scripted_checkout_repair",
        state=JobState.SUCCEEDED,
        stage=JobStage.COMPLETED,
        cleanup_status=CleanupStatus.SUCCEEDED,
        created_at=now,
        updated_at=now,
        idempotency_key="idem-key-123",
        request_fingerprint="fp-123",
        requested_mode=JobMode.REPAIR,
        effective_mode=JobMode.REPAIR,
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


def test_bundle_restates_recorded_values_under_one_digest() -> None:
    job = _make_sample_job()
    items = [artifact(job.id, "screenshot", b"png"), artifact(job.id, "trace", b"zip")]
    bundle, summary = ProofBundleCompiler().compile(
        job=job,
        baseline_report=_make_report(ExecutionVerdict.FAILED, 1200.0),
        verification_report=_make_report(ExecutionVerdict.PASSED, 1500.0),
        diff=DIFF,
        artifacts=items,
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
    bundle, summary = ProofBundleCompiler().compile(
        job=job,
        baseline_report=_make_report(ExecutionVerdict.FAILED, 1200.0),
        verification_report=_make_report(ExecutionVerdict.FAILED, 1500.0),
        diff=DIFF,
    )
    assert bundle.status == "not_verified" and bundle.regressions_count == 2
    assert "## Failed assertions" in summary and "0 of 2" in summary
