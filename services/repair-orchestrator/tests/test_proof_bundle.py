"""Tests for the proof-carrying pull request and evidence bundle compiler."""

from datetime import UTC, datetime
from uuid import uuid4

from app.proof_bundle import ProofBundle, ProofBundleCompiler
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


def test_proof_bundle_compiler_generates_valid_bundle_and_markdown() -> None:
    job = _make_sample_job()
    baseline = _make_report(ExecutionVerdict.FAILED, 1200.0)
    verification = _make_report(ExecutionVerdict.PASSED, 950.0)
    diff = """--- a/apps/buggyshop-backend/app/routes/checkout.py
+++ b/apps/buggyshop-backend/app/routes/checkout.py
@@ -43,2 +43,2 @@
-    discount = cast(int, discounts.get(coupon_code))
+    discount = cast(int, discounts.get(coupon_code, 0))
     total = subtotal - discount
"""
    ast_result = {
        "syntax_valid": True,
        "ast_safe": True,
        "defect_guarded": True,
        "target_function": "checkout",
        "affected_symbols": ["discount", "discounts", "total"],
        "guards_detected": ["dict_get_default_zero"],
        "complexity_delta": 1,
    }
    min_payload = {
        "minimal_payload": {"items": [{"product_id": "trail-mug", "quantity": 2}]},
        "removed_keys": ["analytics", "user_agent"],
        "reduction_ratio": 0.65,
    }
    now = datetime.now(UTC)
    artifacts = [
        ArtifactSummary(
            id=str(uuid4()),
            job_id=job.id,
            role="screenshot",
            content_type="image/png",
            size_bytes=10240,
            sha256="abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
            created_at=now,
        ),
        ArtifactSummary(
            id=str(uuid4()),
            job_id=job.id,
            role="diff",
            content_type="text/plain",
            size_bytes=256,
            sha256="123456abcdef7890123456abcdef7890123456abcdef7890123456abcdef7890",
            created_at=now,
        ),
    ]

    compiler = ProofBundleCompiler()
    bundle, md = compiler.compile(
        job=job,
        baseline_report=baseline,
        verification_report=verification,
        diff=diff,
        ast_result=ast_result,
        minimal_payload=min_payload,
        artifacts=artifacts,
    )

    assert isinstance(bundle, ProofBundle)
    assert bundle.job_id == job.id
    assert bundle.status == "verified"
    assert bundle.verification_verdict == "passed"
    assert bundle.regressions_count == 0
    assert len(bundle.evidence_manifest) == 2
    assert bundle.bundle_digest is not None

    # Check Markdown PR contents
    assert f"# [FaultLine Proof-Carrying Fix] {job.scenario_id}" in md
    assert "## Automated Repair Summary" in md
    assert "## Baseline Defect Diagnosis" in md
    assert "## Semantic AST Safety Clearance" in md
    assert "## Verified Patch Diff" in md
    assert "## Cryptographic Evidence Manifest" in md
    assert "`65.0%` noise eliminated" in md
    assert "dict_get_default_zero" in md
