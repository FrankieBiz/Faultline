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
    ExecutionReport,
    OrchestratorJob,
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
    ) -> tuple[ProofBundle, str]:
        """Return the bundle and its summary, deriving every value from the reports."""
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
            "schema_version": "2.0",
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
