"""Unit tests for the FaultLine Developer Platform CLI."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.cli import (
    apply_patch_for_job,
    build_parser,
    cmd_diff,
    cmd_doctor,
    cmd_init,
    cmd_jobs,
    cmd_status,
    cmd_verify,
    cmd_version,
    detect_project_stack,
    generate_faultline_toml,
    revert_to_seeded,
)


def test_cli_parser_registration() -> None:
    """Ensure all core developer commands are properly registered."""
    parser = build_parser()
    subparsers_actions = [
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    ]
    assert len(subparsers_actions) == 1
    commands = list(subparsers_actions[0].choices.keys())
    for expected in [
        "version",
        "init",
        "doctor",
        "status",
        "jobs",
        "diff",
        "apply",
        "revert",
        "verify",
    ]:
        assert expected in commands


def test_cli_version_output(capsys: pytest.CaptureFixture[str]) -> None:
    """Test that faultline version outputs the CLI banner and platform info."""
    args = argparse.Namespace()
    ret = cmd_version(args)
    assert ret == 0
    captured = capsys.readouterr().out
    assert "FaultLine Developer Platform CLI" in captured
    assert "Python:" in captured
    assert "Platform:" in captured


def test_cli_doctor_runs(capsys: pytest.CaptureFixture[str]) -> None:
    """Test that faultline doctor executes diagnostic checks."""
    args = argparse.Namespace()
    with patch("app.cli._api_request", return_value={"status": "ok"}):
        cmd_doctor(args)
    captured = capsys.readouterr().out
    assert "FaultLine Doctor" in captured
    assert "Linux Bubblewrap" in captured
    assert "cgroup v2" in captured


def test_cli_status_command(capsys: pytest.CaptureFixture[str]) -> None:
    """Test faultline status queries readiness."""
    args = argparse.Namespace()
    mock_status = {
        "status": "ready",
        "runtime_ready": True,
        "quarantined": False,
        "model": {"model": "muse-spark-1.3", "provider": "meta"},
        "resource_limits": {"memory_bytes": 536870912, "cpu_quota_us": 100000},
    }
    with patch("app.cli._api_request", return_value=mock_status):
        ret = cmd_status(args)
    assert ret == 0
    captured = capsys.readouterr().out
    assert "FaultLine Orchestrator Status" in captured
    assert "muse-spark-1.3" in captured


def test_cli_jobs_command(capsys: pytest.CaptureFixture[str]) -> None:
    """Test faultline jobs renders table of jobs."""
    args = argparse.Namespace()
    mock_jobs = {
        "jobs": [
            {
                "id": "11112222-3333-4444-5555-666677778888",
                "scenario_id": "scripted_checkout_repair",
                "state": "succeeded",
                "outcome": "verified",
                "created_at": "2026-10-30T12:00:00",
            }
        ]
    }
    with patch("app.cli._api_request", return_value=mock_jobs):
        ret = cmd_jobs(args)
    assert ret == 0
    captured = capsys.readouterr().out
    assert "JOB ID" in captured
    assert "11112222" in captured
    assert "succeeded" in captured


def test_cli_diff_command(capsys: pytest.CaptureFixture[str]) -> None:
    """Test faultline diff displays colorized unified diff."""
    args = argparse.Namespace(job_id="job-123")
    mock_job = {
        "attempts": [{"parsed_diff": "--- a/file.py\n+++ b/file.py\n@@ -1,2 +1,2 @@\n-old\n+new\n"}]
    }
    with patch("app.cli._api_request", return_value=mock_job):
        ret = cmd_diff(args)
    assert ret == 0
    captured = capsys.readouterr().out
    assert "Verified Candidate Diff" in captured
    assert "+new" in captured


def test_cli_verify_command(capsys: pytest.CaptureFixture[str]) -> None:
    """Test faultline verify reports store health correctly."""
    args = argparse.Namespace()
    with patch("app.cli._api_request", return_value={"id": "order-123", "total": 1999}):
        ret = cmd_verify(args)
    assert ret == 0
    captured = capsys.readouterr().out
    assert "HEALTHY (HTTP 201 Created)" in captured

    with patch(
        "app.cli._api_request",
        return_value={"status": 500, "error": "TypeError: - NoneType"},
    ):
        ret = cmd_verify(args)
    assert ret == 1
    captured = capsys.readouterr().out
    assert "DEFECT ACTIVE" in captured


def test_detect_project_stack(tmp_path: Path) -> None:
    """Test automatic stack detection for FastAPI and Node projects."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n")
    (tmp_path / "uv.lock").write_text("")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("from fastapi import FastAPI\napp=FastAPI()\n")

    info = detect_project_stack(tmp_path)
    assert info["stack"] == "python-fastapi"
    assert "uvicorn" in info["dev_command"]
    assert "pytest" in info["test_command"]
    assert "uv.lock" in info["lockfiles"]

    toml = generate_faultline_toml(info)
    assert 'stack = "python-fastapi"' in toml
    assert "[[invariants.rule]]" in toml


def test_cmd_init_creates_config(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Test faultline init generates faultline.toml in target directory."""
    with patch("pathlib.Path.cwd", return_value=tmp_path):
        args = argparse.Namespace(force=False)
        ret = cmd_init(args)
        assert ret == 0
        config_path = tmp_path / "faultline.toml"
        assert config_path.exists()
        content = config_path.read_text()
        assert "schema = 1" in content
        assert "[project]" in content
        assert "[sandbox]" in content


def test_apply_and_revert_helpers() -> None:
    """Test helper functions apply_patch_for_job and revert_to_seeded with mock db."""
    mock_db = MagicMock()
    mock_job = MagicMock(state="failed", outcome="invalid_patch")
    mock_db.get_job.return_value = mock_job

    res = apply_patch_for_job("job-123", database=mock_db)
    assert not res["success"]
    assert res["error_code"] == "unverified_job"

    # Revert to seeded
    revert_res = revert_to_seeded()
    assert revert_res["success"]
