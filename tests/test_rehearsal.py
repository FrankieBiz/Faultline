"""The presenter must never see a failed or unclean job reported as verified."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("state", "outcome", "cleanup", "passed", "success"),
    [
        ("succeeded", "verified", "succeeded", True, True),
        ("failed", "unresolved", "succeeded", False, False),
        ("cancelled", "cancelled", "succeeded", False, False),
        ("interrupted", "interrupted", "succeeded", False, False),
        ("succeeded", "verified", "failed", True, False),
        ("succeeded", "verified", "succeeded", False, False),
    ],
)
def test_rehearsal_requires_measured_success(
    tmp_path: Path, state: str, outcome: str, cleanup: str, passed: bool, success: bool
) -> None:
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    curl = fakebin / "curl"
    curl.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "url = next(a for a in sys.argv if a.startswith('http://fixture/'))\n"
        "if url.endswith('/readiness'):\n"
        "    value = json.loads(os.environ['CASE_READY'])\n"
        "elif url.endswith('/jobs'):\n"
        "    value = {'job_id': 'recorded-job'}\n"
        "else:\n"
        "    value = json.loads(os.environ['CASE_DETAIL'])\n"
        "print(json.dumps(value))\n"
    )
    curl.chmod(0o755)
    uv = fakebin / "uv"
    uv.write_text("#!/bin/sh\nprintf '%s\\n' '00000000-0000-4000-8000-000000000001'\n")
    uv.chmod(0o755)
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/rehearse-demo.sh")],
        cwd=ROOT,
        env={
            "PATH": f"{fakebin}:/usr/bin:/bin",
            "FAULTLINE_INSPECTOR_URL": "http://fixture",
            "CASE_READY": json.dumps(
                {
                    "runtime_ready": True,
                    "quarantined": False,
                    "model": {
                        "available": True,
                        "provider": "deterministic",
                        "model": "deterministic-checkout-v1",
                    },
                }
            ),
            "CASE_DETAIL": json.dumps(
                {
                    "job": {
                        "id": "recorded-job",
                        "state": state,
                        "stage": "completed",
                        "outcome": outcome,
                        "cleanup_status": cleanup,
                    },
                    "baseline": {"report": {"verdict": "failed"}},
                    "executions": [
                        {
                            "phase": "verification",
                            "report": {
                                "verdict": "passed",
                                "assertions": [{"passed": passed}],
                            },
                        }
                    ],
                    "attempts": [
                        {
                            "parsed_diff": "recorded diff",
                            "validation_result": {
                                "provider": "deterministic",
                                "model": "deterministic-checkout-v1",
                            },
                        }
                    ],
                }
            ),
        },
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert (result.returncode == 0) == success, result.stdout + result.stderr
    assert ("Candidate verified" in result.stdout) == success
    assert "not a live Meta trial" in result.stdout


def _rehearse(
    tmp_path: Path, ready: dict[str, object], *args: str
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Run the rehearsal against a fake Inspector that logs every URL it serves."""
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    calls = tmp_path / "calls.log"
    curl = fakebin / "curl"
    curl.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "url = next(a for a in sys.argv if a.startswith('http://fixture/'))\n"
        "with open(os.environ['CALLS'], 'a') as log:\n"
        "    log.write(url + '\\n')\n"
        "print(os.environ['CASE_READY'] if url.endswith('/readiness') else '{}')\n"
    )
    curl.chmod(0o755)
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/rehearse-demo.sh"), *args],
        cwd=ROOT,
        env={
            "PATH": f"{fakebin}:/usr/bin:/bin",
            "FAULTLINE_INSPECTOR_URL": "http://fixture",
            "CALLS": str(calls),
            "CASE_READY": json.dumps(ready),
        },
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=5,
    )
    served = calls.read_text().split() if calls.exists() else []
    return result, served


READY = {
    "runtime_ready": True,
    "quarantined": False,
    "model": {"available": True, "provider": "deterministic", "model": "deterministic-checkout-v1"},
}


def test_dry_run_checks_readiness_without_creating_a_job(tmp_path: Path) -> None:
    result, served = _rehearse(tmp_path, READY, "--dry-run")
    assert result.returncode == 0, result.stdout + result.stderr
    assert served == ["http://fixture/api/faultline/readiness"]
    assert "no job was created" in result.stdout
    assert "27 business checks" in result.stdout
    assert "not a live Meta trial" in result.stdout


def test_dry_run_fails_when_the_runtime_is_not_ready(tmp_path: Path) -> None:
    result, served = _rehearse(tmp_path, {**READY, "runtime_ready": False}, "--dry-run")
    assert result.returncode == 1
    assert served == ["http://fixture/api/faultline/readiness"]
    assert "Repair unavailable" in result.stderr


def test_interactive_without_a_terminal_does_not_wait(tmp_path: Path) -> None:
    result, _ = _rehearse(tmp_path, READY, "--interactive", "--dry-run")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "continuing without pauses" in result.stdout
    assert "Enter to continue" not in result.stdout


def test_unknown_option_is_rejected(tmp_path: Path) -> None:
    result, served = _rehearse(tmp_path, READY, "--bogus")
    assert result.returncode == 2
    assert served == []
