"""The offline verifier agrees with the compiler and fails closed on any mismatch."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from test_proof_bundle import _make_report, _make_sample_job, artifact, compile_sample

from app.proof_bundle import bundle_digest
from shared.contracts.models import ExecutionVerdict
from tools.verify_bundle import verify_bundle

TOOL = Path(__file__).parents[3] / "tools/verify-bundle.py"


def exported(tmp_path: Path) -> tuple[dict[str, Any], Path]:
    """Compile a bundle and write its artifacts the way the replay export does."""
    job = _make_sample_job()
    contents = {"screenshot": b"png bytes", "trace": b"zip bytes", "report": b"report bytes"}
    items = [artifact(job.id, role, content) for role, content in contents.items()]
    bundle, _ = compile_sample(
        job,
        _make_report(ExecutionVerdict.FAILED, 1.0),
        _make_report(ExecutionVerdict.PASSED, 1.0),
        items,
    )
    directory = tmp_path / "artifacts"
    directory.mkdir()
    for item, content in zip(items, contents.values(), strict=True):
        (directory / f"{item.id}.bin").write_bytes(content)
    return json.loads(bundle.model_dump_json()), directory


def test_compiled_bundle_and_artifacts_are_consistent(tmp_path: Path) -> None:
    bundle, directory = exported(tmp_path)
    consistent, messages = verify_bundle(bundle, directory)
    assert consistent, messages
    assert any("All 3 listed artifact files match" in message for message in messages)
    assert any("Final lifecycle recorded" in message for message in messages)
    assert any("Containment not established" in message for message in messages)


def test_edits_and_corruption_are_detected(tmp_path: Path) -> None:
    bundle, directory = exported(tmp_path)
    edited = {**bundle, "verification_verdict": "failed"}
    assert not verify_bundle(edited)[0]
    corrupted = next(directory.iterdir())
    corrupted.write_bytes(b"changed")
    consistent, errors = verify_bundle(bundle, directory)
    assert not consistent and any("does not match its recorded hash" in e for e in errors)


def test_missing_or_ambiguous_artifacts_fail_closed(tmp_path: Path) -> None:
    bundle, directory = exported(tmp_path)
    first = sorted(directory.iterdir())[0]
    first.unlink()
    consistent, errors = verify_bundle(bundle, directory)
    assert not consistent and any("not found" in error for error in errors)
    assert not verify_bundle(bundle, tmp_path / "absent")[0]


def test_unverified_or_incomplete_bundles_are_rejected(tmp_path: Path) -> None:
    bundle, _ = exported(tmp_path)
    assert not verify_bundle({key: value for key, value in bundle.items() if key != "status"})[0]
    consistent, errors = verify_bundle({**bundle, "verification_verdict": "failed"})
    assert not consistent and any("does not record a verified candidate" in e for e in errors)


def test_cli_reports_a_checksum_not_a_signature(tmp_path: Path) -> None:
    bundle, directory = exported(tmp_path)
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(bundle))
    ok = subprocess.run(
        [sys.executable, str(TOOL), str(path), "--artifacts-dir", str(directory)],
        capture_output=True,
        text=True,
    )
    assert ok.returncode == 0, ok.stderr
    assert "not a signature" in ok.stdout and "AUTHENTIC" not in ok.stdout
    path.write_text(json.dumps({**bundle, "regressions_count": 1}))
    bad = subprocess.run([sys.executable, str(TOOL), str(path)], capture_output=True, text=True)
    assert bad.returncode == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("cleanup_status", "failed"),
        ("outcome", "artifact_error"),
        ("state", "running"),
        ("finalized", False),
        ("finalized", 1),
    ],
)
def test_rehashed_invalid_final_lifecycle_is_rejected(
    tmp_path: Path, field: str, value: object
) -> None:
    bundle, _ = exported(tmp_path)
    bundle["lifecycle"][field] = value
    bundle["bundle_digest"] = bundle_digest(bundle)
    assert not verify_bundle(bundle)[0]


@pytest.mark.parametrize(
    "field", ["lifecycle", "source", "generation", "executions", "containment"]
)
def test_rehashed_missing_final_metadata_is_rejected(tmp_path: Path, field: str) -> None:
    bundle, _ = exported(tmp_path)
    del bundle[field]
    bundle["bundle_digest"] = bundle_digest(bundle)
    assert not verify_bundle(bundle)[0]


@pytest.mark.parametrize(
    "field,value",
    [
        ("app_generation_id", "wrong-generation"),
        ("candidate_sha256", "a" * 64),
        ("base_sha256", "a" * 64),
        ("verification_execution_id", "wrong-execution"),
    ],
)
def test_rehashed_generation_disagreement_is_rejected(
    tmp_path: Path, field: str, value: str
) -> None:
    bundle, _ = exported(tmp_path)
    bundle["generation"][field] = value
    bundle["bundle_digest"] = bundle_digest(bundle)
    assert not verify_bundle(bundle)[0]


def test_simulation_cannot_claim_containment_by_rehashing(tmp_path: Path) -> None:
    bundle, _ = exported(tmp_path)
    bundle["containment"] = "recorded-isolated"
    bundle["bundle_digest"] = bundle_digest(bundle)
    assert not verify_bundle(bundle)[0]


@pytest.mark.parametrize(
    "limits",
    [
        {},
        {"mode": "disabled", "verified": True},
        {"mode": "cgroup-v2-scope", "verified": True, "memory_max_bytes": 1},
    ],
)
def test_rehashed_invalid_resource_limits_are_rejected(tmp_path: Path, limits: object) -> None:
    bundle, _ = exported(tmp_path)
    bundle["executions"][0]["resource_limits"] = limits
    bundle["bundle_digest"] = bundle_digest(bundle)
    assert not verify_bundle(bundle)[0]


def test_missing_resource_limits_must_be_explicitly_unknown(tmp_path: Path) -> None:
    bundle, _ = exported(tmp_path)
    del bundle["executions"][0]["resource_limits"]
    bundle["bundle_digest"] = bundle_digest(bundle)
    assert not verify_bundle(bundle)[0]


def test_disabled_limits_remain_consistent_without_containment(tmp_path: Path) -> None:
    bundle, _ = exported(tmp_path)
    for execution in bundle["executions"]:
        execution["runtime_kind"] = "isolated-browser"
        execution["resource_limits"] = {
            "mode": "disabled",
            "verified": False,
            "memory_max_bytes": None,
            "memory_swap_max_bytes": None,
            "tasks_max": None,
            "cpu_quota_percent": None,
        }
    bundle["bundle_digest"] = bundle_digest(bundle)
    consistent, messages = verify_bundle(bundle)
    assert consistent, messages
    assert any("Containment not established" in message for message in messages)


def test_retained_schema_two_is_explicitly_consistency_only() -> None:
    replay = Path(__file__).parents[3] / "docs/replay/3573b32b-09bd-4f14-897d-cf6dccf9b118"
    job = json.loads((replay / "job.json").read_text())
    proof = next(item for item in job["artifacts"] if item["role"] == "proof_bundle")
    bundle = json.loads((replay / f"artifacts/{proof['id']}.json").read_text())
    assert bundle["schema_version"] == "2.0"
    consistent, messages = verify_bundle(bundle)
    assert consistent, messages
    assert any("Legacy schema 2.0: consistency-only" in message for message in messages)
    assert any("final lifecycle and containment are not established" in m for m in messages)
