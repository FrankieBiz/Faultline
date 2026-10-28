"""The offline verifier agrees with the compiler and fails closed on any mismatch."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from test_proof_bundle import DIFF, _make_report, _make_sample_job, artifact

from app.proof_bundle import ProofBundleCompiler
from shared.contracts.models import ExecutionVerdict
from tools.verify_bundle import verify_bundle

TOOL = Path(__file__).parents[3] / "tools/verify-bundle.py"


def exported(tmp_path: Path) -> tuple[dict[str, Any], Path]:
    """Compile a bundle and write its artifacts the way the replay export does."""
    job = _make_sample_job()
    contents = {"screenshot": b"png bytes", "trace": b"zip bytes"}
    items = [artifact(job.id, role, content) for role, content in contents.items()]
    bundle, _ = ProofBundleCompiler().compile(
        job=job,
        baseline_report=_make_report(ExecutionVerdict.FAILED, 1.0),
        verification_report=_make_report(ExecutionVerdict.PASSED, 1.0),
        diff=DIFF,
        artifacts=items,
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
    assert any("All 2 listed artifact files match" in message for message in messages)


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
    job = _make_sample_job()
    failed, _ = ProofBundleCompiler().compile(
        job=job,
        baseline_report=_make_report(ExecutionVerdict.FAILED, 1.0),
        verification_report=_make_report(ExecutionVerdict.FAILED, 1.0),
        diff=DIFF,
    )
    consistent, errors = verify_bundle(json.loads(failed.model_dump_json()))
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
