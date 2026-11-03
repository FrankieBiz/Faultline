"""Checksummed evidence bundle and pull-request summary for a verified candidate.

The bundle restates what the controller recorded: the failing baseline, the
patch, the verification verdict, and the content address of every registered
artifact. Its digest is SHA-256 over all of those fields, so any inconsistent
edit or corrupted artifact is detectable offline with ``tools/verify_bundle.py``.
It is not signed: someone able to rewrite the bundle can recompute the digest.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from shared.contracts.models import (
    ArtifactSummary,
    ContractModel,
    ExecutionRecord,
    ExecutionReport,
    OrchestratorJob,
    RepairAttempt,
)

DESCRIPTIONS = {
    "screenshot": "Browser screenshot",
    "trace": "Playwright trace archive",
    "requests": "Bounded browser request log",
    "logs": "Isolated backend log",
    "report": "Execution report",
    "diff": "Patch the gates checked",
    "proposal": "Provider output as returned",
}


class EvidenceDigest(ContractModel):
    """Content address of one registered artifact; ``id`` names its exported file."""

    id: str
    role: str
    sha256: str
    size_bytes: int
    content_type: str
    description: str


class ProofBundle(ContractModel):
    """Checksummed restatement of one verified job's recorded evidence."""

    schema_version: str
    job_id: str
    scenario_id: str
    timestamp: str
    status: str
    baseline_verdict: str
    baseline_fingerprint: str
    patch_diff: str
    patch_diff_sha256: str
    verification_verdict: str
    assertions_total: int
    regressions_count: int
    evidence_manifest: list[EvidenceDigest]
    lifecycle: dict[str, Any]
    source: dict[str, Any]
    generation: dict[str, Any]
    executions: list[dict[str, Any]]
    containment: str
    bundle_digest: str


def bundle_digest(fields: dict[str, Any]) -> str:
    """SHA-256 over canonical JSON of every bundle field except the digest itself."""
    content = {key: value for key, value in fields.items() if key != "bundle_digest"}
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class ProofBundleCompiler:
    """Compile the recorded evidence into a bundle and a markdown summary."""

    def compile(
        self,
        job: OrchestratorJob,
        baseline_report: ExecutionReport,
        verification_report: ExecutionReport,
        diff: str,
        artifacts: Sequence[ArtifactSummary] | None = None,
        *,
        executions: Sequence[ExecutionRecord],
        attempt: RepairAttempt,
    ) -> tuple[ProofBundle, str]:
        """Bind final cleanup to recorded provenance, without inventing containment.

        The worker calls this synchronously after confirmed cleanup, immediately
        before terminal persistence. It must never pass a synthetic completed job.
        """
        if job.cleanup_status.value != "succeeded" or job.cancel_requested:
            raise ValueError("Final proof requires confirmed cleanup and no cancellation")
        if job.state.value != "running" or job.stage.value != "cleanup" or job.outcome is not None:
            raise ValueError("Final proof requires an active finalization transaction")
        if attempt.job_id != job.id or attempt.parsed_diff != diff:
            raise ValueError("Proof attempt identity or diff mismatch")
        if any(e.job_id != job.id or e.report.scenario_id != job.scenario_id for e in executions):
            raise ValueError("Proof execution identity mismatch")
        if any(a.job_id != job.id for a in artifacts or []):
            raise ValueError("Proof artifact identity mismatch")
        baseline = next((e for e in executions if e.report == baseline_report), None)
        verification = next((e for e in executions if e.report == verification_report), None)
        validation = attempt.validation_result or {}
        if (
            baseline is None
            or baseline.phase != "baseline"
            or baseline.report.execution_id != job.baseline_execution_id
            or baseline.report.verdict.value != "failed"
            or verification is None
            or verification.phase != "verification"
            or verification.attempt_id != attempt.id
            or verification.report.verdict.value != "passed"
            or not verification.report.assertions
            or any(not a.passed for a in verification.report.assertions)
            or validation.get("verification_execution_id") != verification.report.execution_id
            or validation.get("candidate_sha256") != verification.candidate_snapshot_sha256
            or validation.get("app_generation_id") != verification.app_generation_id
            or validation.get("base_sha256") != job.seed_source_hash
            or not validation.get("target_sha256")
            or not job.seed_source_hash
            or not job.seed_commit
        ):
            raise ValueError(
                "Final proof requires matching source, generation and verified reports"
            )
        manifest = [
            EvidenceDigest(
                id=item.id,
                role=item.role,
                sha256=item.sha256,
                size_bytes=item.size_bytes,
                content_type=item.content_type,
                description=DESCRIPTIONS.get(item.role, "Supporting artifact"),
            )
            for item in artifacts or []
        ]
        fingerprint = next(
            (
                item.message
                for item in baseline_report.observations
                if item.kind.value == "server_exception"
            ),
            "",
        )
        regressions = sum(1 for item in verification_report.assertions if not item.passed)
        fields: dict[str, Any] = {
            "schema_version": "3.0",
            "job_id": job.id,
            "scenario_id": job.scenario_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "status": "verified"
            if verification_report.verdict.value == "passed" and regressions == 0
            else "not_verified",
            "baseline_verdict": baseline_report.verdict.value,
            "baseline_fingerprint": fingerprint,
            "patch_diff": diff,
            "patch_diff_sha256": hashlib.sha256(diff.encode()).hexdigest(),
            "verification_verdict": verification_report.verdict.value,
            "assertions_total": len(verification_report.assertions),
            "regressions_count": regressions,
            "evidence_manifest": [item.model_dump() for item in manifest],
            "lifecycle": {
                "finalized": True,
                "state": "succeeded",
                "outcome": "verified",
                "cleanup_status": job.cleanup_status.value,
            },
            "source": {
                "seed_commit": job.seed_commit,
                "seed_source_sha256": job.seed_source_hash,
                "fixture_version": job.fixture_version,
                "scenario_version": job.scenario_version,
            },
            "generation": {
                "attempt_id": attempt.id,
                "baseline_execution_id": baseline_report.execution_id,
                "verification_execution_id": verification_report.execution_id,
                **{
                    key: (attempt.validation_result or {}).get(key)
                    for key in (
                        "provider",
                        "model",
                        "base_sha256",
                        "target_sha256",
                        "candidate_sha256",
                        "app_generation_id",
                    )
                },
            },
            "executions": [
                {
                    "execution_id": e.report.execution_id,
                    "phase": e.phase,
                    "attempt_id": e.attempt_id,
                    "app_generation_id": e.app_generation_id,
                    "candidate_snapshot_sha256": e.candidate_snapshot_sha256,
                    "runtime_kind": e.runtime_kind,
                    "resource_limits": e.resource_limits.model_dump()
                    if e.resource_limits
                    else None,
                    "artifact_ids": e.artifact_ids,
                    "verdict": e.report.verdict.value,
                    "assertions_total": len(e.report.assertions),
                    "regressions_count": sum(not a.passed for a in e.report.assertions),
                }
                for e in executions
            ],
            "containment": "recorded-isolated"
            if executions
            and all(
                e.runtime_kind == "isolated-browser"
                and e.resource_limits is not None
                and e.resource_limits.verified
                for e in executions
            )
            else "not-established",
        }
        bundle = ProofBundle.model_validate({**fields, "bundle_digest": bundle_digest(fields)})
        return bundle, self._markdown(bundle, verification_report)

    @staticmethod
    def _markdown(bundle: ProofBundle, verification: ExecutionReport) -> str:
        """Render a review summary that states only recorded values."""
        failed = [item for item in verification.assertions if not item.passed]
        lines = [
            f"# FaultLine candidate repair: {bundle.scenario_id}",
            "",
            "| Recorded value | Result |",
            "| --- | --- |",
            f"| Job | `{bundle.job_id}` |",
            f"| Baseline verdict | `{bundle.baseline_verdict}` |",
            f"| Baseline failure | `{bundle.baseline_fingerprint or 'not recorded'}` |",
            f"| Verification verdict | `{bundle.verification_verdict}` |",
            f"| Assertions passed | {bundle.assertions_total - bundle.regressions_count} "
            f"of {bundle.assertions_total} |",
            f"| Bundle status | `{bundle.status}` |",
            "| Final cleanup | `succeeded` |",
            f"| Recorded containment | `{bundle.containment}` |",
            f"| Bundle SHA-256 | `{bundle.bundle_digest}` |",
            "",
            "## Patch",
            "",
            "```diff",
            bundle.patch_diff.strip(),
            "```",
            "",
        ]
        if failed:
            lines += ["## Failed assertions", ""]
            lines += [
                f"- `{item.id}`: expected {item.expected}; observed {item.observed}"
                for item in failed
            ]
            lines.append("")
        lines += [
            "## Evidence",
            "",
            "| Artifact | Role | SHA-256 | Bytes |",
            "| --- | --- | --- | ---: |",
        ]
        lines += [
            f"| `{item.id}` | {item.role} | `{item.sha256}` | {item.size_bytes} |"
            for item in bundle.evidence_manifest
        ]
        lines += [
            "",
            "Check consistency offline with `python3 tools/verify_bundle.py bundle.json "
            "--artifacts-dir <exported artifacts>`. The digest detects corruption and "
            "inconsistent edits; it is not a signature. A verified candidate is not a "
            "production deployment.",
            "",
        ]
        return "\n".join(lines)
