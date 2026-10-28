"""Tests for the offline cryptographic proof bundle verifier CLI."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from tools.verify_bundle import verify_bundle


def _sample_bundle() -> dict[str, Any]:
    diff = """--- a/apps/buggyshop-backend/app/routes/checkout.py
+++ b/apps/buggyshop-backend/app/routes/checkout.py
@@ -43,2 +43,2 @@
-    discount = cast(int, discounts.get(coupon_code))
+    discount = cast(int, discounts.get(coupon_code, 0))
     total = subtotal - discount
"""
    diff_sha = hashlib.sha256(diff.encode("utf-8")).hexdigest()
    pre_digest = {
        "job_id": "test-job-123",
        "scenario_id": "scripted_checkout_repair",
        "diff_sha256": diff_sha,
        "baseline_verdict": "failed",
        "verification_verdict": "passed",
        "artifacts_count": 1,
    }
    bundle_digest = hashlib.sha256(
        json.dumps(pre_digest, sort_keys=True).encode("utf-8")
    ).hexdigest()

    return {
        "job_id": "test-job-123",
        "scenario_id": "scripted_checkout_repair",
        "timestamp": "2026-10-28T12:00:00Z",
        "status": "verified",
        "baseline_fingerprint": (
            "TypeError: unsupported operand type(s) for -: 'int' and 'NoneType'"
        ),
        "patch_diff": diff,
        "patch_diff_sha256": diff_sha,
        "ast_analysis": {"syntax_valid": True, "defect_guarded": True},
        "evidence_manifest": [
            {
                "role": "diff",
                "sha256": diff_sha,
                "size_bytes": len(diff),
                "content_type": "text/plain",
                "description": "Validated single-file patch diff",
            }
        ],
        "verification_verdict": "passed",
        "regressions_count": 0,
        "bundle_digest": bundle_digest,
    }


def test_verify_bundle_accepts_valid_bundle() -> None:
    bundle = _sample_bundle()
    valid, messages = verify_bundle(bundle)
    assert valid is True
    assert any("Patch diff SHA-256 matches" in m for m in messages)
    assert any("Proof bundle digest matches" in m for m in messages)


def test_verify_bundle_detects_tampered_diff() -> None:
    bundle = _sample_bundle()
    bundle["patch_diff"] += "\n# Malicious injected code"
    valid, errors = verify_bundle(bundle)
    assert valid is False
    assert any("Patch diff hash mismatch" in e for e in errors)


def test_verify_bundle_detects_tampered_digest() -> None:
    bundle = _sample_bundle()
    bundle["bundle_digest"] = "badhash12345"
    valid, errors = verify_bundle(bundle)
    assert valid is False
    assert any("Bundle digest mismatch" in e for e in errors)


def test_verify_bundle_detects_unverified_status() -> None:
    bundle = _sample_bundle()
    bundle["status"] = "unresolved"
    bundle["regressions_count"] = 2
    valid, errors = verify_bundle(bundle)
    assert valid is False
    assert any("Bundle status is 'unresolved'" in e for e in errors)
    assert any("Bundle has 2 regressions" in e for e in errors)


def test_cli_execution_success(tmp_path: Path) -> None:
    bundle = _sample_bundle()
    bundle_file = tmp_path / "proof_bundle.json"
    bundle_file.write_text(json.dumps(bundle))

    tool_path = Path(__file__).parents[3] / "tools/verify-bundle.py"
    res = subprocess.run(
        [sys.executable, str(tool_path), str(bundle_file)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert "PROOF BUNDLE VERIFIED AND CRYPTOGRAPHICALLY AUTHENTIC" in res.stdout
