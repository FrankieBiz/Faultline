#!/usr/bin/env python3
"""Offline consistency check for a FaultLine evidence bundle (standard library only).

Recomputes the bundle digest over every recorded field, the patch hash, and,
with ``--artifacts-dir``, the size and SHA-256 of every listed artifact. Files
are found by artifact ID, matching the replay export layout
(``artifacts/<artifact-id>.<ext>``). A missing artifact is a failure.

The digest is a checksum, not a signature: it detects corruption and
inconsistent edits, not a forger who rewrites the bundle and recomputes it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REQUIRED = {
    "schema_version",
    "job_id",
    "scenario_id",
    "timestamp",
    "status",
    "baseline_verdict",
    "baseline_fingerprint",
    "patch_diff",
    "patch_diff_sha256",
    "verification_verdict",
    "assertions_total",
    "regressions_count",
    "evidence_manifest",
    "bundle_digest",
}


def bundle_digest(fields: dict[str, Any]) -> str:
    """Must match ``app.proof_bundle.bundle_digest`` exactly."""
    content = {key: value for key, value in fields.items() if key != "bundle_digest"}
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _artifact_file(directory: Path, artifact_id: str) -> Path | None:
    """Return the single file named for this artifact ID, or None if absent or ambiguous."""
    if not artifact_id or "/" in artifact_id or artifact_id.startswith("."):
        return None
    matches = [
        path
        for path in directory.iterdir()
        if path.is_file() and (path.name == artifact_id or path.stem == artifact_id)
    ]
    return matches[0] if len(matches) == 1 else None


def verify_bundle(
    bundle: dict[str, Any], artifacts_dir: Path | None = None
) -> tuple[bool, list[str]]:
    """Return (consistent, messages); messages list every failure when inconsistent."""
    missing = REQUIRED - set(bundle)
    if missing:
        return False, [f"Missing required bundle fields: {sorted(missing)}"]
    errors: list[str] = []
    notes: list[str] = []
    if bundle_digest(bundle) != bundle["bundle_digest"]:
        errors.append("Bundle digest does not match its recorded fields")
    else:
        notes.append(f"[OK] Bundle digest matches: {bundle['bundle_digest']}")
    if hashlib.sha256(bundle["patch_diff"].encode()).hexdigest() != bundle["patch_diff_sha256"]:
        errors.append("Patch diff does not match its recorded SHA-256")
    else:
        notes.append("[OK] Patch diff matches its recorded SHA-256")
    verified = (
        bundle["status"] == "verified"
        and bundle["baseline_verdict"] == "failed"
        and bundle["verification_verdict"] == "passed"
        and bundle["regressions_count"] == 0
        and bundle["assertions_total"] > 0
    )
    if not verified:
        errors.append(
            "Bundle does not record a verified candidate: "
            f"status={bundle['status']}, baseline={bundle['baseline_verdict']}, "
            f"verification={bundle['verification_verdict']}, "
            f"failed assertions={bundle['regressions_count']} of {bundle['assertions_total']}"
        )
    else:
        notes.append(
            f"[OK] Recorded: failing baseline, then {bundle['assertions_total']} of "
            f"{bundle['assertions_total']} assertions passed"
        )
    if artifacts_dir is not None:
        if not artifacts_dir.is_dir():
            errors.append(f"Artifacts directory not found: {artifacts_dir}")
        else:
            checked = 0
            for item in bundle["evidence_manifest"]:
                path = _artifact_file(artifacts_dir, str(item.get("id", "")))
                if path is None:
                    errors.append(f"Artifact {item.get('id')} ({item.get('role')}) not found")
                    continue
                content = path.read_bytes()
                if len(content) != item.get("size_bytes") or (
                    hashlib.sha256(content).hexdigest() != item.get("sha256")
                ):
                    errors.append(f"Artifact {path.name} does not match its recorded hash")
                    continue
                checked += 1
            if checked == len(bundle["evidence_manifest"]):
                notes.append(f"[OK] All {checked} listed artifact files match their hashes")
    else:
        notes.append("[--] Artifact files not checked (pass --artifacts-dir)")
    return (not errors), (notes if not errors else errors)


def main() -> None:
    """Exit 0 only when the bundle and any supplied artifacts are consistent."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle_path", type=Path, help="Path to the bundle JSON")
    parser.add_argument("--artifacts-dir", type=Path, help="Directory of exported artifacts")
    arguments = parser.parse_args()
    try:
        data = json.loads(arguments.bundle_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"Cannot read bundle: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    if not isinstance(data, dict):
        print("Bundle must be a JSON object", file=sys.stderr)
        raise SystemExit(1)
    consistent, messages = verify_bundle(data, arguments.artifacts_dir)
    stream = sys.stdout if consistent else sys.stderr
    for message in messages:
        print(message, file=stream)
    if consistent:
        print("RESULT: consistent. The digest is a checksum, not a signature.")
        raise SystemExit(0)
    print("RESULT: inconsistent or not a verified candidate.", file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
