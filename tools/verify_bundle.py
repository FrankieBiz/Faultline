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
import re
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


def verify_final_metadata(bundle: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Check schema 3 lifecycle/provenance consistency, never authenticate its author."""
    errors: list[str] = []
    lifecycle = bundle.get("lifecycle")
    if (
        not isinstance(lifecycle, dict)
        or any(
            lifecycle.get(key) != value
            for key, value in {
                "state": "succeeded",
                "outcome": "verified",
                "cleanup_status": "succeeded",
            }.items()
        )
        or lifecycle.get("finalized") is not True
    ):
        errors.append(
            "Invalid or missing final lifecycle: verified outcome requires cleanup succeeded"
        )

    def digest(value: Any) -> bool:
        return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None

    def text(value: Any) -> bool:
        return isinstance(value, str) and bool(value.strip())

    source = bundle.get("source")
    generation = bundle.get("generation")
    executions = bundle.get("executions")
    if (
        not isinstance(source, dict)
        or not text(source.get("seed_commit"))
        or not digest(source.get("seed_source_sha256"))
    ):
        errors.append("Invalid or missing source identity")
    if (
        not isinstance(generation, dict)
        or not all(
            text(generation.get(key))
            for key in (
                "attempt_id",
                "baseline_execution_id",
                "verification_execution_id",
                "app_generation_id",
            )
        )
        or not all(
            digest(generation.get(key))
            for key in ("base_sha256", "target_sha256", "candidate_sha256")
        )
        or any(
            key not in generation or (generation[key] is not None and not text(generation[key]))
            for key in ("provider", "model")
        )
    ):
        errors.append("Invalid or missing generation/provider identity")
    if errors:
        return errors, []
    if not isinstance(executions, list) or not executions:
        return ["Missing execution provenance"], []
    items = bundle["evidence_manifest"]
    if not isinstance(items, list) or any(
        not isinstance(item, dict)
        or not text(item.get("id"))
        or not text(item.get("role"))
        or not digest(item.get("sha256"))
        or type(item.get("size_bytes")) is not int
        or item["size_bytes"] < 0
        for item in items
    ):
        return ["Invalid final evidence manifest"], []
    if len({item["id"] for item in items}) != len(items):
        return ["Duplicate final evidence identity"], []
    manifest = {item["id"]: item for item in bundle["evidence_manifest"]}
    recorded: dict[str, dict[str, Any]] = {}
    isolated = True
    for execution in executions:
        if not isinstance(execution, dict):
            errors.append("Invalid execution provenance")
            continue
        identity = execution.get("execution_id")
        if not text(identity) or identity in recorded:
            errors.append("Missing or duplicate execution identity")
        recorded[identity] = execution
        if (
            execution.get("phase") not in {"baseline", "verification"}
            or not text(execution.get("app_generation_id"))
            or not digest(execution.get("candidate_snapshot_sha256"))
            or execution.get("runtime_kind") not in {"unverified", "isolated-browser"}
            or execution.get("verdict") not in {"failed", "passed", "error", "timed_out"}
            or type(execution.get("assertions_total")) is not int
            or type(execution.get("regressions_count")) is not int
            or not 0 <= execution["regressions_count"] <= execution["assertions_total"]
        ):
            errors.append("Invalid execution identity, runtime or verdict metadata")
        artifact_ids = execution.get("artifact_ids")
        if (
            not isinstance(artifact_ids, list)
            or not artifact_ids
            or len(set(artifact_ids)) != len(artifact_ids)
            or not set(artifact_ids) <= set(manifest)
            or not any(manifest.get(key, {}).get("role") == "report" for key in artifact_ids)
        ):
            errors.append("Execution artifacts are not bound to the evidence manifest")
        limits = execution.get("resource_limits")
        if "resource_limits" not in execution:
            errors.append("Missing per-execution resource_limits (use null for unknown)")
        if limits is not None:
            if (
                not isinstance(limits, dict)
                or type(limits.get("verified")) is not bool
                or not {
                    "mode",
                    "verified",
                    "memory_max_bytes",
                    "memory_swap_max_bytes",
                    "tasks_max",
                    "cpu_quota_percent",
                }
                <= set(limits)
            ):
                errors.append("Invalid recorded resource limits")
            else:
                values = [
                    limits.get(key)
                    for key in (
                        "memory_max_bytes",
                        "memory_swap_max_bytes",
                        "tasks_max",
                        "cpu_quota_percent",
                    )
                ]
                if limits.get("mode") == "disabled":
                    if limits["verified"] or any(v is not None for v in values):
                        errors.append("Disabled resource limits cannot claim enforcement")
                elif limits.get("mode") == "cgroup-v2-scope":
                    if any(type(v) is not int or v < 0 for v in values) or any(
                        type(v) is int and v < 1 for v in values[2:]
                    ):
                        errors.append("Incomplete cgroup resource-limit observations")
                elif limits.get("mode") in {"rlimits", "windows-job", "docker"}:
                    if limits.get("memory_max_bytes") is None or limits.get("tasks_max") is None:
                        errors.append("Incomplete resource-limit observations")
                else:
                    errors.append("Unknown resource-limit mode")
        isolated = isolated and (
            execution.get("runtime_kind") == "isolated-browser"
            and isinstance(limits, dict)
            and limits.get("verified") is True
            and limits.get("mode") in {"cgroup-v2-scope", "windows-job", "docker"}
        )
    baseline = recorded.get(generation["baseline_execution_id"], {})
    verification = recorded.get(generation["verification_execution_id"], {})
    if (
        baseline.get("phase") != "baseline"
        or baseline.get("verdict") != "failed"
        or verification.get("phase") != "verification"
        or verification.get("verdict") != "passed"
        or verification.get("attempt_id") != generation["attempt_id"]
        or verification.get("app_generation_id") != generation["app_generation_id"]
        or verification.get("candidate_snapshot_sha256") != generation["candidate_sha256"]
        or generation["base_sha256"] != source["seed_source_sha256"]
        or verification.get("assertions_total") != bundle["assertions_total"]
        or verification.get("regressions_count") != 0
    ):
        errors.append("Final source/generation/verdict identity is inconsistent with executions")
    expected_containment = "recorded-isolated" if isolated else "not-established"
    if bundle.get("containment") != expected_containment:
        errors.append("Invalid containment claim for the recorded runtime and resource limits")
    notes = ["[OK] Final lifecycle recorded: verified; cleanup succeeded"]
    notes.append(
        "[OK] Recorded isolated browser execution and verified aggregate limits (not authenticated)"
        if isolated
        else "[--] Containment not established: runtime or verified limits absent/disabled"
    )
    return errors, notes


def verify_bundle(
    bundle: dict[str, Any], artifacts_dir: Path | None = None
) -> tuple[bool, list[str]]:
    """Fail closed on malformed input as well as inconsistent recorded claims."""
    try:
        return _verify_bundle(bundle, artifacts_dir)
    except (AttributeError, KeyError, TypeError, ValueError, OSError) as exc:
        return False, [f"Invalid bundle metadata or unreadable artifacts: {type(exc).__name__}"]


def _verify_bundle(
    bundle: dict[str, Any], artifacts_dir: Path | None = None
) -> tuple[bool, list[str]]:
    """Return (consistent, messages); messages list every failure when inconsistent."""
    missing = REQUIRED - set(bundle)
    if missing:
        return False, [f"Missing required bundle fields: {sorted(missing)}"]
    errors: list[str] = []
    notes: list[str] = []
    if bundle["schema_version"] == "2.0":
        notes.append(
            "[--] Legacy schema 2.0: consistency-only verification; "
            "final lifecycle and containment are not established"
        )
    elif bundle["schema_version"] == "3.0":
        failures, final_notes = verify_final_metadata(bundle)
        errors.extend(failures)
        notes.extend(final_notes)
    else:
        errors.append("Unsupported bundle schema_version")
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
        and type(bundle["regressions_count"]) is int
        and bundle["regressions_count"] == 0
        and type(bundle["assertions_total"]) is int
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
