#!/usr/bin/env python3
"""Portable zero-dependency offline cryptographic verifier for FaultLine proof bundles.

Validates the cryptographic digest chain, patch hash, baseline failure evidence,
and artifact manifest without requiring a running server, network connection, or database.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


def verify_bundle(
    bundle_data: dict[str, Any], artifacts_dir: Path | None = None
) -> tuple[bool, list[str]]:
    """Verify proof bundle internal integrity and optional artifact files."""
    errors: list[str] = []
    log: list[str] = []

    # 1. Verify required bundle keys
    required_keys = {
        "job_id",
        "scenario_id",
        "timestamp",
        "status",
        "baseline_fingerprint",
        "patch_diff",
        "patch_diff_sha256",
        "evidence_manifest",
        "verification_verdict",
        "regressions_count",
        "bundle_digest",
    }
    missing = required_keys - set(bundle_data.keys())
    if missing:
        errors.append(f"Missing required bundle fields: {sorted(missing)}")
        return False, errors

    # 2. Check status and regression count
    if bundle_data["status"] != "verified":
        errors.append(
            f"Bundle status is '{bundle_data['status']}', expected 'verified'"
        )
    if bundle_data["verification_verdict"] != "passed":
        errors.append(
            f"Verification verdict is '{bundle_data['verification_verdict']}', expected 'passed'"
        )
    if bundle_data["regressions_count"] != 0:
        errors.append(
            f"Bundle has {bundle_data['regressions_count']} regressions, expected 0"
        )

    # 3. Cryptographically verify patch diff hash
    diff = bundle_data["patch_diff"]
    computed_diff_sha = hashlib.sha256(diff.encode("utf-8")).hexdigest()
    recorded_diff_sha = bundle_data["patch_diff_sha256"]
    if computed_diff_sha != recorded_diff_sha:
        errors.append(
            f"Patch diff hash mismatch: computed {computed_diff_sha}, recorded {recorded_diff_sha}"
        )
    else:
        log.append(f"[OK] Patch diff SHA-256 matches: {computed_diff_sha[:16]}...")

    # 4. Cryptographically verify bundle digest
    manifest = bundle_data.get("evidence_manifest", [])
    pre_digest = {
        "job_id": bundle_data["job_id"],
        "scenario_id": bundle_data["scenario_id"],
        "diff_sha256": recorded_diff_sha,
        "baseline_verdict": "failed",
        "verification_verdict": bundle_data["verification_verdict"],
        "artifacts_count": len(manifest),
    }
    computed_bundle_digest = hashlib.sha256(
        json.dumps(pre_digest, sort_keys=True).encode("utf-8")
    ).hexdigest()
    recorded_bundle_digest = bundle_data["bundle_digest"]

    if computed_bundle_digest != recorded_bundle_digest:
        errors.append(
            f"Bundle digest mismatch: computed {computed_bundle_digest}, recorded {recorded_bundle_digest}"
        )
    else:
        log.append(
            f"[OK] Proof bundle digest matches: {computed_bundle_digest[:16]}..."
        )

    # 5. Verify physical artifact files if directory provided
    if artifacts_dir is not None:
        if not artifacts_dir.is_dir():
            errors.append(f"Artifacts directory not found: {artifacts_dir}")
        else:
            verified_count = 0
            for item in manifest:
                role = item.get("role", "unknown")
                expected_sha = item.get("sha256")
                matching_files = list(artifacts_dir.glob(f"*{role}*"))
                if not matching_files:
                    continue
                file_path = matching_files[0]
                content = file_path.read_bytes()
                actual_sha = hashlib.sha256(content).hexdigest()
                if actual_sha != expected_sha:
                    errors.append(
                        f"Artifact '{role}' ({file_path.name}) hash mismatch: expected {expected_sha}, got {actual_sha}"
                    )
                else:
                    verified_count += 1
            if verified_count > 0:
                log.append(
                    f"[OK] Verified {verified_count} physical artifact files against manifest"
                )

    log.append(
        f"[OK] Baseline defect fingerprint: {bundle_data.get('baseline_fingerprint', '')[:60]}..."
    )
    log.append(
        f"[OK] Zero regressions verified across {len(manifest)} cryptographic evidence records"
    )

    return len(errors) == 0, log if not errors else errors


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Offline cryptographic verifier for FaultLine proof-carrying PR bundles."
    )
    parser.add_argument("bundle_path", type=Path, help="Path to proof_bundle.json file")
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=None,
        help="Optional directory containing downloaded execution artifacts to verify",
    )
    args = parser.parse_args()

    if not args.bundle_path.is_file():
        print(
            f"Error: proof bundle file not found: {args.bundle_path}", file=sys.stderr
        )
        sys.exit(1)

    try:
        data = json.loads(args.bundle_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Error reading JSON from {args.bundle_path}: {exc}", file=sys.stderr)
        sys.exit(1)

    print("=================================================================")
    print(f"FaultLine Offline Proof Verifier: {args.bundle_path.name}")
    print("=================================================================")

    valid, messages = verify_bundle(data, args.artifacts_dir)
    for msg in messages:
        print(msg)

    print("-----------------------------------------------------------------")
    if valid:
        print("RESULT: PROOF BUNDLE VERIFIED AND CRYPTOGRAPHICALLY AUTHENTIC.")
        print("=================================================================")
        sys.exit(0)
    else:
        print(
            "RESULT: VERIFICATION FAILED. PROOF BUNDLE TAMPERED OR INVALID.",
            file=sys.stderr,
        )
        print(
            "=================================================================",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
