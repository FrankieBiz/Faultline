"""Unit tests for the FaultLine Developer Platform CLI."""

from __future__ import annotations

import argparse
import difflib
import http.client
import json
import os
import queue
import shlex
import signal
import socket
import subprocess
import sys
import threading
import tomllib
import urllib.error
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.cli import (
    OUTCOME_EXIT_CODES,
    HudState,
    _describe_check,
    _pump_events,
    apply_patch_for_job,
    build_parser,
    cmd_apply,
    cmd_check,
    cmd_dashboard,
    cmd_diff,
    cmd_doctor,
    cmd_init,
    cmd_jobs,
    cmd_listen,
    cmd_status,
    cmd_verify,
    cmd_version,
    detect_project_stack,
    generate_faultline_toml,
    parse_sse,
    render_frame,
    render_summary,
    revert_to_seeded,
    stream_job_events,
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
        "listen",
        "dashboard",
    ]:
        assert expected in commands

    listen = parser.parse_args(["listen", "job-1", "--port", "9100", "--plain", "--ascii"])
    assert (listen.job_id, listen.port, listen.plain, listen.ascii) == ("job-1", 9100, True, True)
    dashboard = parser.parse_args(["dashboard", "--port", "4100", "--no-open"])
    assert (dashboard.port, dashboard.no_open) == (4100, True)


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


@pytest.mark.parametrize("platform", ["darwin", "win32", "linux"])
@pytest.mark.parametrize("optional_ready", [False, True])
def test_doctor_platform_prerequisites(
    platform: str,
    optional_ready: bool,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.delenv("META_API_KEY", raising=False)
    if optional_ready:
        monkeypatch.setenv("META_API_KEY", "test-only")
    with (
        patch("app.cli.shutil.which", side_effect=lambda name: f"/tools/{name}"),
        patch("app.cli.Path.is_file", return_value=True),
        patch("app.cli.subprocess.check_output", return_value="v24.1.0\n"),
        patch("app.cli.subprocess.run", return_value=subprocess.CompletedProcess([], 0)),
        patch("app.cli._api_request", return_value={"status": "ok"} if optional_ready else {}),
    ):
        assert cmd_doctor(argparse.Namespace(plain=True)) == 0
    output = capsys.readouterr().out
    assert f"Platform: {platform}" in output
    assert "Playwright Chromium" in output
    assert "Node.js" in output
    assert "check, test, scan, init, gate" in output
    assert "WSL2" in output and "unverified" in output
    assert "META_API_KEY" in output


@pytest.mark.parametrize("platform", ["darwin", "win32", "linux"])
@pytest.mark.parametrize("missing", ["uv", "node", "playwright", "old-node", "bad-node"])
def test_doctor_missing_local_prerequisite(
    platform: str,
    missing: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    version = {"old-node": "v18.0.0", "bad-node": "unrecognised"}.get(missing, "v24.1.0")
    with (
        patch(
            "app.cli.shutil.which",
            side_effect=lambda name: None if name == missing else f"/tools/{name}",
        ),
        patch("app.cli.Path.is_file", return_value=True),
        patch("app.cli.subprocess.check_output", return_value=version),
        patch(
            "app.cli.subprocess.run",
            return_value=subprocess.CompletedProcess([], int(missing == "playwright")),
        ),
        patch("app.cli._api_request", return_value={}),
    ):
        assert cmd_doctor(argparse.Namespace(plain=True)) == 1
    assert "Result:" in capsys.readouterr().out


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_sandbox_readiness_non_linux_never_probes(
    platform: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.cli_check import sandbox_readiness

    monkeypatch.setattr(sys, "platform", platform)
    with (
        patch("app.cli_check.shutil.which", side_effect=AssertionError("Linux tool probe")),
        patch("app.cli_check.Path.is_file", side_effect=AssertionError("Linux filesystem probe")),
    ):
        readiness = sandbox_readiness()
    assert readiness["prerequisites_available"] is False
    assert readiness["runtime_ready"] is None
    assert readiness["status"] == "unavailable"
    assert "Linux" in readiness["note"]


@pytest.mark.parametrize("missing", [None, "bwrap", "systemd-run"])
def test_sandbox_readiness_linux_contract(
    missing: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.cli_check import sandbox_readiness

    monkeypatch.setattr(sys, "platform", "linux")
    with (
        patch(
            "app.cli_check.shutil.which",
            side_effect=lambda name: None if name == missing else f"/tools/{name}",
        ),
        patch("app.cli_check.Path.is_file", return_value=True),
    ):
        readiness = sandbox_readiness()
    assert set(readiness["prerequisites"]) == {
        "bubblewrap",
        "cgroup_v2",
        "systemd_run",
        "node",
        "uv",
    }
    assert readiness["prerequisites_available"] is (missing is None)
    assert readiness["status"] == ("unverified" if missing is None else "unavailable")
    assert readiness["runtime_ready"] is None


@pytest.mark.parametrize("platform", ["darwin", "win32"])
@pytest.mark.parametrize("repair", [False, True])
def test_native_config_checks_do_not_require_sandbox_unless_repair_requested(
    platform: str,
    repair: bool,
    tmp_path: Path,
    live_http: tuple[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _config(tmp_path, live_http[0])
    monkeypatch.setattr(sys, "platform", platform)
    with patch("app.cli_check.run_project", new_callable=AsyncMock) as runner:
        assert _check(config, "--json", *(["--repair"] if repair else [])) == int(repair)
    runner.assert_not_called()
    result = json.loads(capsys.readouterr().out)
    assert result["checks"][0]["passed"] is True
    assert result["sandbox"]["prerequisites_available"] is False


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_standalone_preflight_imports_without_unix_modules(
    platform: str, tmp_path: Path, live_http: tuple[str, list[str]]
) -> None:
    """A fresh interpreter catches import blockers hidden by pytest's module cache."""
    from app.cli import REPOSITORY_ROOT

    project = tmp_path / "project"
    project.mkdir()
    (project / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    config = _config(tmp_path, live_http[0])
    script = """
import builtins
import os
import subprocess
import sys
from unittest.mock import patch
original_import = builtins.__import__
def portable_import(name, *args, **kwargs):
    if name in {"fcntl", "resource", "pwd"}:
        raise ModuleNotFoundError(name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = portable_import
from app import cli, cli_check, cli_crawl, cli_demo
assert "app.run" not in sys.modules
assert "app.isolated_runtime" not in sys.modules
assert "app.project_runtime" not in sys.modules
sys.platform = sys.argv[2]
os.chdir(sys.argv[1])
def command(*argv):
    args = cli.build_parser().parse_args(argv)
    return args.func(args)
assert command("init", "--plain") == 0
assert command("test", sys.argv[3], "--json") == 0
assert command("check", "--config", sys.argv[4], "--json") == 0
with patch("app.crawler_service.run_crawl", return_value={
    "status": "clean", "stop_reason": "exhausted", "target_url": sys.argv[3],
    "breadcrumbs": [], "elements_explored": 0, "actions_taken": 0, "pages_visited": [],
}):
    assert command("scan", sys.argv[3], "--no-repair", "--json") == 0
    assert command("gate", sys.argv[3], "--json") == 0
with (
    patch("app.cli.shutil.which", return_value="node"),
    patch("app.cli.subprocess.check_output", return_value="v24.1.0"),
    patch("app.cli.subprocess.run", return_value=subprocess.CompletedProcess([], 0)),
    patch("app.cli._api_request", return_value={}),
):
    assert command("doctor", "--plain") == 0
assert command("run") == 30
assert "app.run" not in sys.modules
assert "app.project_runtime" not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(project), platform, live_http[0], str(config)],
        cwd=REPOSITORY_ROOT / "services/repair-orchestrator",
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_cli_status_command(capsys: pytest.CaptureFixture[str]) -> None:
    """Test faultline status queries readiness."""
    from app.isolated_runtime import IsolatedRuntime

    args = argparse.Namespace()
    mock_status = {
        "status": "ready",
        "runtime_ready": True,
        "quarantined": False,
        "model": {"model": "muse-spark-1.3", "provider": "meta"},
        "resource_limits": IsolatedRuntime().resource_limits_status,
    }
    with patch("app.cli._api_request", return_value=mock_status):
        ret = cmd_status(args)
    assert ret == 0
    captured = capsys.readouterr().out
    assert "FaultLine Orchestrator Status" in captured
    assert "muse-spark-1.3" in captured
    assert "Memory=512 MiB, Tasks=64, CPU=100% (1 CPU)" in captured
    assert "Enforcement: not_run" in captured


@pytest.mark.parametrize("mode", ["disabled", "invalid"])
def test_cli_status_does_not_invent_unavailable_limits(
    mode: str, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import cli
    from app.isolated_runtime import IsolatedRuntime

    runtime = IsolatedRuntime()
    runtime.aggregate_mode = mode
    monkeypatch.setattr(
        cli,
        "_api_request",
        lambda *args, **kwargs: {
            "resource_limits": runtime.resource_limits_status,
        },
    )
    assert cli.cmd_status(argparse.Namespace()) == 0
    output = capsys.readouterr().out
    assert "Sandbox Limits:" in output
    assert "Memory=" not in output
    assert "Enforcement:" in output


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
    """faultline diff prints the candidate with the job's recorded outcome, never assuming it."""
    args = argparse.Namespace(job_id="job-123")
    attempts = [{"parsed_diff": "--- a/file.py\n+++ b/file.py\n@@ -1,2 +1,2 @@\n-old\n+new\n"}]
    with patch("app.cli._api_request", return_value={"attempts": attempts}):
        ret = cmd_diff(args)
    assert ret == 0
    captured = capsys.readouterr().out
    assert "Candidate diff for job job-123" in captured
    assert "in progress" in captured
    assert "erified" not in captured
    assert "+new" in captured

    unresolved = {"job": {"outcome": "unresolved"}, "attempts": attempts}
    with patch("app.cli._api_request", return_value=unresolved):
        cmd_diff(args)
    assert "unresolved" in capsys.readouterr().out


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
    assert info["test_command"] == ""  # No invented test dependency.
    assert "uv.lock" in info["lockfiles"]

    toml = generate_faultline_toml(info)
    assert 'stack = "python-fastapi"' in toml
    assert "[[invariants.rule]]" in toml


def test_cmd_init_creates_config(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Test faultline init generates faultline.toml in target directory."""
    (tmp_path / "package.json").write_text('{"scripts":{"start":"node server.js"}}')
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


@pytest.mark.parametrize("via_database", [True, False])
@pytest.mark.parametrize("unsafe", [True, False])
@pytest.mark.parametrize("conflict", ["none", "missing_hash", "changed_base", "during_validation"])
def test_apply_patch_rechecks_policy_before_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    via_database: bool,
    unsafe: bool,
    conflict: str,
) -> None:
    from app import cli

    source = cli.SEEDED_FILE.read_text()
    candidate = cli.HEALTHY_FILE.read_text()
    if unsafe:
        candidate += '\nopen("/tmp/should-never-be-written", "w")\n'
    target = tmp_path / "checkout.py"
    target.write_text(source)
    from hashlib import sha256

    from app import policy

    base_hash = sha256(source.encode()).hexdigest() if conflict != "missing_hash" else None
    edited = source.replace("unit_price_cents", "human_price_cents")
    if conflict == "changed_base":
        target.write_text(edited)
    if conflict == "during_validation":
        validate = policy.validate_patch

        def edit(*args: Any, **kwargs: Any) -> Any:
            result = validate(*args, **kwargs)
            target.write_text(edited)
            return result

        monkeypatch.setattr(policy, "validate_patch", edit)
    monkeypatch.setattr(cli, "TARGET_FILE", target)
    monkeypatch.setattr(cli, "DATA_DIR", tmp_path / "data")
    path = "apps/buggyshop-backend/app/routes/checkout.py"
    diff = "".join(
        difflib.unified_diff(
            source.splitlines(keepends=True),
            candidate.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )
    database = None
    if via_database:
        database = MagicMock()
        database.get_job.return_value = MagicMock(state="succeeded", outcome="verified")
        database.list_attempts.return_value = [
            MagicMock(
                outcome="verified", parsed_diff=diff, validation_result={"base_sha256": base_hash}
            )
        ]
    else:
        monkeypatch.setattr(
            cli,
            "_api_request",
            lambda *args, **kwargs: {
                "job": {"state": "succeeded", "outcome": "verified"},
                "attempts": [
                    {
                        "outcome": "verified",
                        "parsed_diff": diff,
                        "validation_result": {"base_sha256": base_hash},
                    }
                ],
            },
        )
    result = apply_patch_for_job("verified-job", database=database)
    assert result["success"] is (not unsafe and conflict == "none")
    if conflict in {"changed_base", "during_validation"}:
        assert target.read_text() == edited
    else:
        assert target.read_text() == (candidate if result["success"] else source)
    if conflict in {"missing_hash", "changed_base"} or (
        conflict == "during_validation" and not unsafe
    ):
        assert result["error_code"] == "base_hash_mismatch"
    elif unsafe:
        assert result["error_code"] == "patch_policy_rejected"


JOB_ID = "7f3c2a1e-0000-4000-8000-000000000000"
STARTED = datetime(2026, 10, 30, 12, 4, 30, tzinfo=UTC)


def _event(
    sequence: int, stage: str, code: str | None = None, second: float = 0.0
) -> dict[str, Any]:
    timestamp = (STARTED + timedelta(seconds=second)).isoformat().replace("+00:00", "Z")
    return {
        "schema_version": "1.0",
        "job_id": JOB_ID,
        "sequence": sequence,
        "timestamp": timestamp,
        "stage": stage,
        "message_code": code or stage,
        "message": f"Entered {stage}." if code is None else f"Job {code}.",
    }


def _assertion(assertion_id: str, passed: bool, observed: str, expected: str) -> dict[str, Any]:
    return {
        "id": assertion_id,
        "passed": passed,
        "expected": expected,
        "observed": observed,
        "duration_ms": 3,
    }


VERIFIED_RUN = [
    _event(1, "preparing", "queued", 0.0),
    _event(2, "preparing", second=0.2),
    _event(3, "baseline", second=1.0),
    _event(4, "diagnosing", second=5.1),
    _event(5, "patch_validation", second=17.5),
    _event(6, "activating", second=17.6),
    _event(7, "verification", second=19.3),
    _event(8, "cleanup", second=24.4),
    _event(9, "completed", "verified", 25.2),
]

DETAIL: dict[str, Any] = {
    "job": {
        "id": JOB_ID,
        "scenario_id": "scripted_checkout_repair",
        "state": "succeeded",
        "cleanup_status": "succeeded",
    },
    "attempts": [{"id": "attempt-1", "attempt_number": 1}],
    "executions": [
        {
            "phase": "baseline",
            "attempt_id": None,
            "report": {
                "verdict": "failed",
                "assertions": [
                    _assertion("checkout.no_coupon.status", False, "500", "201"),
                    _assertion("checkout.tenoff.total", True, "3599", "3599"),
                ],
            },
        },
        {
            "phase": "verification",
            "attempt_id": "attempt-1",
            "report": {
                "verdict": "passed",
                "assertions": [
                    _assertion("checkout.no_coupon.status", True, "201", "201"),
                    _assertion("checkout.tenoff.total", True, "3599", "3599"),
                    _assertion("checkout.confirmation_shown", True, "shown", "shown"),
                ],
            },
        },
    ],
}


def _fold(events: list[dict[str, Any]], detail: dict[str, Any] | None = None) -> HudState:
    state = HudState(JOB_ID)
    if detail is not None:
        state.absorb(detail)
    for event in events:
        state.apply(event)
    return state


def test_hud_folds_a_verified_run() -> None:
    """Every stage settles in order with measured elapsed time and exit code 0."""
    state = _fold(VERIFIED_RUN)
    assert state.outcome == "verified"
    assert set(state.status.values()) == {"done"}
    assert [record.stage for record in state.settled] == [
        "preparing",
        "baseline",
        "diagnosing",
        "patch_validation",
        "activating",
        "verification",
        "cleanup",
    ]
    assert state.elapsed["baseline"] == pytest.approx(4.1)
    assert state.total_seconds(STARTED + timedelta(hours=1)) == pytest.approx(25.0)
    assert OUTCOME_EXIT_CODES[state.outcome] == 0


def test_hud_marks_the_stage_that_rejected_an_attempt() -> None:
    """A second attempt records where the first failed; untried stages end skipped."""
    events = [
        *VERIFIED_RUN[:7],
        _event(8, "diagnosing", second=24.0),
        _event(9, "patch_validation", second=30.0),
        _event(10, "cleanup", second=30.1),
        _event(11, "completed", "invalid_patch", 31.0),
    ]
    state = HudState(JOB_ID)
    for event in events[:8]:
        state.apply(event)
    assert state.attempt == 2
    assert state.status["verification"] == "pending"
    assert "attempt 1 rejected at Verify" in state.stage_detail("diagnosing")
    for event in events[8:]:
        state.apply(event)

    outcomes = [(record.stage, record.status, record.attempt) for record in state.settled]
    assert ("verification", "failed", 1) in outcomes
    assert ("patch_validation", "failed", 2) in outcomes
    assert state.status["activating"] == state.status["verification"] == "skipped"
    assert state.status["cleanup"] == "done"
    assert OUTCOME_EXIT_CODES["invalid_patch"] == 20

    # Attempt 2 never reached verification, so the measured column is attempt 1's.
    state.absorb(DETAIL)
    header = render_summary(state, width=100)[1]
    assert "Attempt 1" in header and "Candidate" not in header


def test_hud_repair_unavailable_keeps_the_reproduction() -> None:
    """A reproduced failure with no repair available marks Reproduce done, repair skipped."""
    state = _fold(
        [
            _event(1, "preparing"),
            _event(2, "baseline", second=1.0),
            _event(3, "cleanup", second=4.0),
            _event(4, "completed", "repair_unavailable", 5.0),
        ]
    )
    assert state.status["baseline"] == "done"
    assert state.status["diagnosing"] == "skipped"
    assert ("baseline", "done", 0) in [(r.stage, r.status, r.attempt) for r in state.settled]


def test_hud_detect_only_and_cleanup_failure() -> None:
    """Detect-only skips the repair stages; a failed cleanup is never shown as passed."""
    detected = _fold(
        [
            _event(1, "preparing"),
            _event(2, "baseline", second=1.0),
            _event(3, "cleanup", second=4.0),
            _event(4, "completed", "detected", 5.0),
        ]
    )
    assert detected.status["baseline"] == "done"
    assert detected.status["diagnosing"] == "skipped"
    assert OUTCOME_EXIT_CODES["detected"] == 10

    # The status read before the run ended is stale; the outcome decides cleanup.
    quarantined = _fold(
        [
            _event(1, "preparing"),
            _event(2, "baseline", second=1.0),
            _event(3, "cleanup", second=4.0),
            _event(4, "completed", "cleanup_failed", 15.0),
        ],
        {"job": {"cleanup_status": "not_started"}},
    )
    assert quarantined.cleanup_status == "failed"
    assert quarantined.status["baseline"] == "attention"
    assert quarantined.status["cleanup"] == "failed"
    summary = "\n".join(render_summary(quarantined, width=100))
    assert "cleanup FAILED ✗ (engine quarantined)" in summary


def test_hud_ignores_events_replayed_after_reconnect() -> None:
    state = HudState(JOB_ID)
    state.apply(VERIFIED_RUN[1])
    assert state.apply(VERIFIED_RUN[1]) is False
    assert len(state.log) == 1


def test_render_frame_draws_the_live_screen() -> None:
    """Stage glyphs, labels, elapsed time, and a stage-count bar fit the terminal width."""
    state = _fold(VERIFIED_RUN[:4], DETAIL)
    lines = render_frame(state, now=STARTED + timedelta(seconds=17.3), width=100, spin=0)
    screen = "\n".join(lines)
    assert "FaultLine · run 7f3c2a1e · scripted_checkout_repair" in screen
    assert "2/7 stages · elapsed 17.1s" in screen
    assert "█" in screen and "░" in screen
    assert "✓ Prepare" in screen
    assert "1 of 2 assertions failed" in screen
    assert "● Propose patch" in screen and "12.2s" in screen and "attempt 1" in screen
    assert "○ Policy check" in screen
    assert "Ctrl+C stops listening" in screen
    assert "\033[" not in screen
    assert all(len(line) <= 99 for line in lines)

    wide = "\n".join(render_frame(state, now=STARTED + timedelta(seconds=17.3), width=120))
    assert "1 of 2 assertions failed · checkout.no_coupon.status 500, expected 201" in wide

    state.cancel_requested = True
    narrow = render_frame(state, now=STARTED + timedelta(seconds=17.3), width=60)
    assert all(len(line) <= 59 for line in narrow)
    assert any(line.endswith("…") for line in narrow)


def test_render_frame_ascii_and_color() -> None:
    """--ascii uses the spec's word glyphs; color wraps glyphs in ANSI codes."""
    state = _fold(VERIFIED_RUN[:4], DETAIL)
    now = STARTED + timedelta(seconds=17.3)
    plain = render_frame(state, now=now, width=100, ascii_only=True)
    assert all(character.isascii() for line in plain for character in line)
    assert any(line.startswith(" ok   Prepare") for line in plain)
    assert any(line.startswith(" ..   Propose patch") for line in plain)
    assert any(line.startswith(" --   Verify") for line in plain)

    colored = "\n".join(render_frame(state, now=now, width=100, color=True, spin=0))
    assert "\033[32m✓" in colored
    # Work in flight reads cyan, like the Inspector: the running glyph, its spinner, and the bar.
    assert "\033[1m\033[36m●" in colored
    assert "\033[36m⠋\033[0m" in colored
    assert "[\033[36m█" in colored


def test_render_summary_marks_assertions() -> None:
    """The verdict block shows baseline and candidate marks for changed assertions."""
    state = _fold(VERIFIED_RUN, DETAIL)
    wide = render_summary(state, width=120)
    text = "\n".join(wide)
    assert "VERIFIED CANDIDATE" in text
    assert "cleanup confirmed ✓" in text
    row = next(line for line in wide if "checkout.no_coupon.status" in line)
    assert "✗ 500" in row and "✓ 201" in row and row.rstrip().endswith("201")
    assert "… 1 more passing in both" in text
    assert "… 1 more passing on the candidate (not run on the baseline)" in text
    assert "Expected" in text

    assert "Expected" not in "\n".join(render_summary(state, width=80))


def test_parse_sse_handles_pings_and_multiline_data() -> None:
    lines = [
        ": ping - 2026-10-30 12:00:00\r\n",
        "\r\n",
        "id: 1\r\n",
        "event: job_event\r\n",
        'data: {"a":\r\n',
        "data: 1}\r\n",
        "\r\n",
        "event: job_event\r\n",
        "data: unterminated\r\n",
    ]
    assert list(parse_sse(lines)) == [("job_event", '{"a":\n1}')]


class _FakeStream:
    def __init__(self, lines: list[bytes]) -> None:
        self.lines = lines

    def __enter__(self) -> _FakeStream:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def __iter__(self) -> Iterator[bytes]:
        return iter(self.lines)


def test_stream_job_events_resumes_from_cursor() -> None:
    """The client authenticates, resumes after a sequence, and keeps only job events."""
    payload = b'{"sequence": 5, "stage": "baseline"}'
    lines = [
        b": ping\r\n",
        b"\r\n",
        b"event: job_event\r\n",
        b"data: " + payload + b"\r\n",
        b"\r\n",
    ]
    with (
        patch("app.cli._get_control_token", return_value="test-token"),
        patch("app.cli.urllib.request.urlopen", return_value=_FakeStream(lines)) as opener,
    ):
        events = list(stream_job_events("job/1", after=4, port=9100))
    assert events == [{"sequence": 5, "stage": "baseline"}]
    request = opener.call_args.args[0]
    assert request.full_url == "http://127.0.0.1:9100/api/faultline/jobs/job%2F1/events?after=4"
    assert request.get_header("Authorization") == "Bearer test-token"
    assert request.get_header("Accept") == "text/event-stream"


def _drain(sink: queue.Queue[tuple[str, Any]]) -> list[tuple[str, Any]]:
    items = []
    while not sink.empty():
        items.append(sink.get_nowait())
    return items


def test_pump_events_reconnects_after_a_drop() -> None:
    """A dropped stream resumes after the last delivered sequence."""
    cursors: list[int] = []

    def fake_stream(job_id: str, *, after: int = 0, port: int = 9000) -> Iterator[dict[str, Any]]:
        cursors.append(after)
        if len(cursors) == 1:
            yield from VERIFIED_RUN[:2]
            raise urllib.error.URLError("connection reset")
        yield from VERIFIED_RUN[2:]

    sink: queue.Queue[tuple[str, Any]] = queue.Queue()
    with patch("app.cli.stream_job_events", fake_stream), patch("app.cli.time.sleep"):
        _pump_events(JOB_ID, 9000, sink)
    assert cursors == [0, 2]
    items = _drain(sink)
    assert [kind for kind, _ in items] == ["event"] * len(VERIFIED_RUN) + ["end"]


def test_pump_events_stops_on_http_error() -> None:
    def rejected(job_id: str, *, after: int = 0, port: int = 9000) -> Iterator[dict[str, Any]]:
        raise urllib.error.HTTPError("http://x", 401, "Unauthorized", {}, None)  # type: ignore[arg-type]
        yield {}

    sink: queue.Queue[tuple[str, Any]] = queue.Queue()
    with patch("app.cli.stream_job_events", rejected):
        _pump_events(JOB_ID, 9000, sink)
    assert _drain(sink) == [
        ("error", "controller returned HTTP 401 (check FAULTLINE_CONTROL_TOKEN)")
    ]


def test_pump_events_retries_truncated_chunks_and_reports_other_errors() -> None:
    """IncompleteRead (a killed controller) reconnects; anything else becomes an error item."""
    cursors: list[int] = []

    def truncated(job_id: str, *, after: int = 0, port: int = 9000) -> Iterator[dict[str, Any]]:
        cursors.append(after)
        if len(cursors) == 1:
            yield VERIFIED_RUN[0]
            raise http.client.IncompleteRead(b"")
        yield from VERIFIED_RUN[1:]

    sink: queue.Queue[tuple[str, Any]] = queue.Queue()
    with patch("app.cli.stream_job_events", truncated), patch("app.cli.time.sleep"):
        _pump_events(JOB_ID, 9000, sink)
    assert cursors == [0, 1]
    assert _drain(sink)[-1] == ("end", None)

    def malformed(job_id: str, *, after: int = 0, port: int = 9000) -> Iterator[dict[str, Any]]:
        yield ["not", "an", "event"]  # type: ignore[misc]

    with patch("app.cli.stream_job_events", malformed):
        _pump_events(JOB_ID, 9000, sink)
    kind, message = sink.get_nowait()
    assert kind == "error" and message.startswith("AttributeError")


def _fake_api(path: str, method: str = "GET", data: Any = None, port: int = 9000) -> dict[str, Any]:
    if path.startswith("/api/faultline/jobs?"):
        return {"jobs": [{"id": JOB_ID}]}
    return DETAIL


def _replay(events: list[dict[str, Any]]) -> Any:
    def stream(job_id: str, *, after: int = 0, port: int = 9000) -> Iterator[dict[str, Any]]:
        assert job_id == JOB_ID
        yield from (event for event in events if event["sequence"] > after)

    return stream


def test_cmd_listen_plain_mode_streams_latest_job(capsys: pytest.CaptureFixture[str]) -> None:
    """Without a TTY, listen prints one line per stage and exits with the outcome code."""
    args = argparse.Namespace(job_id=None, port=9000, plain=False, ascii=False)
    with (
        patch("app.cli._api_request", side_effect=_fake_api),
        patch("app.cli.stream_job_events", _replay(VERIFIED_RUN)),
    ):
        ret = cmd_listen(args)
    assert ret == 0
    out = capsys.readouterr().out
    assert f"faultline listen · run {JOB_ID} · scripted_checkout_repair" in out
    assert "[  0.8s] prepare     ok" in out
    assert "reproduce   ok    1 of 2 assertions failed" in out
    assert "verify      ok    attempt 1 · 3/3 assertions passed" in out
    assert "VERIFIED CANDIDATE" in out
    assert f"outcome=verified run={JOB_ID} cleanup=succeeded" in out
    assert "\033[" not in out


def test_cmd_listen_live_mode_redraws_in_place(capsys: pytest.CaptureFixture[str]) -> None:
    """In a terminal, listen hides the cursor, rewinds to redraw, and restores the cursor."""
    events = [*VERIFIED_RUN[:7], _event(8, "cleanup", second=24.4)]
    events.append(_event(9, "completed", "unresolved", 25.0))
    args = argparse.Namespace(job_id=JOB_ID, port=9000, plain=False, ascii=False)
    with (
        patch("app.cli._api_request", side_effect=_fake_api),
        patch("app.cli.stream_job_events", _replay(events)),
        patch("app.cli._output_mode", return_value=(False, False, False)),
    ):
        ret = cmd_listen(args)
    assert ret == 20
    out = capsys.readouterr().out
    assert out.startswith("\033[?25l")
    assert "F\033[J" in out
    assert "\033[?25h" in out
    assert "NO VERIFIED CANDIDATE (unresolved)" in out
    assert "✗ Verify" in out


def test_cmd_listen_restores_cursor_and_sigterm_on_unexpected_errors(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A crash mid-stream still shows the cursor again and puts back the SIGTERM handler."""
    handler_before = signal.getsignal(signal.SIGTERM)
    # The stream still completes, so the pump thread ends instead of reconnecting.
    malformed = [{"sequence": 1, "stage": "preparing", "message_code": "preparing"}]
    malformed.append(_event(2, "completed", "verified", 1.0))
    args = argparse.Namespace(job_id=JOB_ID, port=9000, plain=False, ascii=False)
    with (
        patch("app.cli._api_request", side_effect=_fake_api),
        patch("app.cli.stream_job_events", _replay(malformed)),
        patch("app.cli._output_mode", return_value=(False, False, False)),
        pytest.raises(KeyError),
    ):
        cmd_listen(args)
    assert capsys.readouterr().out.endswith("\033[?25h")
    assert signal.getsignal(signal.SIGTERM) is handler_before


def test_cmd_listen_reports_unreachable_controller(capsys: pytest.CaptureFixture[str]) -> None:
    args = argparse.Namespace(job_id=JOB_ID, port=9000, plain=True, ascii=False)
    with patch("app.cli._api_request", return_value={"error": "Connection refused", "status": 0}):
        ret = cmd_listen(args)
    assert ret == 1
    assert "Connection refused" in capsys.readouterr().out


def test_cmd_listen_reports_stream_failure(capsys: pytest.CaptureFixture[str]) -> None:
    def broken(job_id: str, *, after: int = 0, port: int = 9000) -> Iterator[dict[str, Any]]:
        raise urllib.error.HTTPError("http://x", 404, "Not Found", {}, None)  # type: ignore[arg-type]
        yield {}

    args = argparse.Namespace(job_id=JOB_ID, port=9000, plain=True, ascii=False)
    with (
        patch("app.cli._api_request", side_effect=_fake_api),
        patch("app.cli.stream_job_events", broken),
    ):
        ret = cmd_listen(args)
    assert ret == 1
    assert "Event stream failed: controller returned HTTP 404" in capsys.readouterr().out


def test_cmd_dashboard_opens_running_inspector(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A running Inspector is opened in the browser; --no-open and headless only print it."""
    monkeypatch.setenv("DISPLAY", ":0")
    with (
        patch("app.cli._probe_inspector", return_value="inspector"),
        patch("app.cli.webbrowser.open", return_value=True) as browser,
    ):
        assert cmd_dashboard(argparse.Namespace(port=4000, no_open=False)) == 0
        browser.assert_called_once_with("http://127.0.0.1:4000")
        browser.reset_mock()

        assert cmd_dashboard(argparse.Namespace(port=4000, no_open=True)) == 0
        monkeypatch.delenv("DISPLAY")
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        assert cmd_dashboard(argparse.Namespace(port=4000, no_open=False)) == 0
        browser.assert_not_called()
    out = capsys.readouterr().out
    assert "http://127.0.0.1:4000" in out
    assert "No graphical display detected" in out


def test_cmd_dashboard_refuses_foreign_service(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("app.cli._probe_inspector", return_value="other"):
        assert cmd_dashboard(argparse.Namespace(port=4000, no_open=True)) == 1
    assert "something other than the FaultLine Inspector" in capsys.readouterr().out


def test_cmd_dashboard_requires_a_build(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """With nothing serving, an unbuilt Inspector is reported rather than built."""
    next_bin = tmp_path / "node_modules" / "next" / "dist" / "bin" / "next"
    next_bin.parent.mkdir(parents=True)
    next_bin.write_text("")
    with (
        patch("app.cli._probe_inspector", return_value="down"),
        patch("app.cli.INSPECTOR_DIR", tmp_path),
        patch("app.cli.subprocess.Popen") as popen,
    ):
        assert cmd_dashboard(argparse.Namespace(port=4000, no_open=True)) == 1
    popen.assert_not_called()
    assert "npm --prefix web/inspector-ui run build" in capsys.readouterr().out


def test_cmd_dashboard_launches_inspector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """With nothing serving, the built Inspector starts detached on loopback and is opened."""
    inspector = tmp_path / "inspector"
    next_bin = inspector / "node_modules" / "next" / "dist" / "bin" / "next"
    next_bin.parent.mkdir(parents=True)
    next_bin.write_text("")
    (inspector / ".next").mkdir()
    (inspector / ".next" / "BUILD_ID").write_text("build")
    monkeypatch.delenv("FAULTLINE_ORCHESTRATOR_URL", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    process = MagicMock(pid=4242)
    process.poll.return_value = None
    with (
        patch("app.cli._probe_inspector", side_effect=["down", "down", "inspector"]),
        patch("app.cli.INSPECTOR_DIR", inspector),
        patch("app.cli.DATA_DIR", tmp_path / "data"),
        patch("app.cli.shutil.which", return_value="/usr/bin/node"),
        patch("app.cli._get_control_token", return_value="test-token"),
        patch("app.cli.subprocess.Popen", return_value=process) as popen,
        patch("app.cli.time.sleep"),
    ):
        assert cmd_dashboard(argparse.Namespace(port=4100, no_open=False)) == 0
    command = popen.call_args.args[0]
    assert command == ["/usr/bin/node", str(next_bin), "start", "-p", "4100", "-H", "127.0.0.1"]
    options = popen.call_args.kwargs
    assert options["cwd"] == inspector
    assert options["start_new_session"] is True
    assert options["env"]["FAULTLINE_ORCHESTRATOR_URL"] == "http://127.0.0.1:9000"
    assert options["env"]["FAULTLINE_CONTROL_TOKEN"] == "test-token"
    out = capsys.readouterr().out
    assert "Started as pid 4242" in out
    assert "kill 4242" in out
    assert (tmp_path / "data" / "inspector.log").exists()


@pytest.fixture
def live_http() -> Iterator[tuple[str, list[str]]]:
    seen: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            seen.append(self.headers.get("X-Faultline-Case-Id", ""))
            status = 500 if self.path == "/fail" else 200
            if self.path == "/flaky":
                status = 500 if len(seen) % 2 else 200
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true,"sum":3}')

        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", seen
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def _config(tmp_path: Path, url: str, route: str = "/") -> Path:
    path = tmp_path / "faultline.toml"
    path.write_text(f'''schema = 1
[project]
name = "test"
dev_command = ["node", "server.js", "{{port}}"]
url = "{url}"
[[invariants.rule]]
id = "health"
target = "{url}{route}"
expected_status = 200
''')
    return path


def _check(path: Path, *flags: str) -> int:
    args = build_parser().parse_args(["check", "--config", str(path), *flags])
    return cmd_check(args)


@pytest.fixture
def ready_sandbox() -> Iterator[MagicMock]:
    with patch(
        "app.cli_check.sandbox_readiness",
        return_value={
            "prerequisites_available": True,
            "runtime_ready": None,
            "status": "unverified",
        },
    ) as ready:
        yield ready


@pytest.mark.parametrize(
    "route,code,outcome",
    [("/", 0, "no_failure"), ("/fail", 1, "detected"), ("/flaky", 1, "no_failure")],
)
def test_check_real_http_two_sessions(
    tmp_path: Path,
    live_http: tuple[str, list[str]],
    ready_sandbox: MagicMock,
    capsys: pytest.CaptureFixture[str],
    route: str,
    code: int,
    outcome: str,
) -> None:
    url, seen = live_http
    config = _config(tmp_path, url, route)
    with patch("app.cli_check.run_project", new_callable=AsyncMock) as runner:
        assert _check(config, "--json", "--plain") == code
    runner.assert_not_called()
    result = json.loads(capsys.readouterr().out)
    assert result["checks"][0]["outcome"] == outcome
    assert result["exit_code"] == code
    assert len(seen) == 2 and seen[0] != seen[1]
    assert result["source_applied"] is False
    assert result["sandbox"]["runtime_ready"] is None


def test_check_json_assertions_and_body(
    tmp_path: Path,
    live_http: tuple[str, list[str]],
    ready_sandbox: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    url, _ = live_http
    path = _config(tmp_path, url)
    path.write_text(f'''schema = 1
[project]
dev_command = "node server.js"
url = "{url}"
[[invariants.rule]]
id = "echo"
request = {{path = "/echo", method = "POST", json = {{value = 3}}}}
assert = [{{status = 200}}, {{path = "$.value", equals = 3}}]
''')
    assert _check(path, "--json") == 0
    result = json.loads(capsys.readouterr().out)
    assert all(len(s["assertions"]) == 2 for s in result["checks"][0]["sessions"])
    path.write_text(path.read_text().replace("equals = 3", "equals = 4"))
    assert _check(path, "--plain") == 1
    out = capsys.readouterr().out
    assert "FAIL echo: failed the same way in both sessions: " in out and "\x1b" not in out
    assert "_reproduced_twice" not in out


@pytest.mark.parametrize(
    "text",
    [
        "",
        "schema = ",
        "schema = 2",
        "schema = true",
        'schema = 1\n[project]\ndev_command="node app.js"',
        'schema = 1\n[project]\ndev_command=""',
        'schema = 1\n[project]\ndev_command="node app.js"\n[invariants]\nrule="bad"',
    ],
)
def test_check_malformed_empty_schema_fails_before_http(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    text: str,
) -> None:
    path = tmp_path / "faultline.toml"
    path.write_text(text)
    with patch("app.cli_check.run_check", new_callable=AsyncMock) as probe:
        assert _check(path, "--json") == 1
    probe.assert_not_called()
    result = json.loads(capsys.readouterr().out)
    assert result["errors"] and not result["checks"]


@pytest.mark.parametrize(
    "extra",
    [
        "\n[unknown]\nx=1",
        '\n[sandbox]\nengine="docker"',
        '\n[model]\nprovider="other"',
        "\n[budgets]\nbaseline=-1",
        "\n[sandbox.limits]\ntasks_max=100",
        "\n[repair]\neditable=[]",
    ],
)
def test_check_rejects_invalid_envelope(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    extra: str,
) -> None:
    path = _config(tmp_path, "http://127.0.0.1:1")
    path.write_text(path.read_text() + extra)
    assert _check(path, "--json") == 1
    assert json.loads(capsys.readouterr().out)["errors"]


@pytest.mark.parametrize(
    "change",
    [
        ("expected_status = 200", 'expected_status = "200"'),
        ("expected_status = 200", "expected_status = true"),
        ("expected_status = 200", "expected_statuz = 200"),
        (
            "expected_status = 200",
            'expected_status = 200\nrequest={path="/"}\nassert=[{status=200}]',
        ),
        ("[[invariants.rule]]", "[invariants.rule]"),
    ],
)
def test_check_rejects_rule_errors(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    change: tuple[str, str],
) -> None:
    path = _config(tmp_path, "http://127.0.0.1:1")
    path.write_text(path.read_text().replace(*change))
    assert _check(path, "--json") == 1
    assert json.loads(capsys.readouterr().out)["errors"]


def test_check_missing_file_and_unreachable_target(
    tmp_path: Path,
    ready_sandbox: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _check(tmp_path / "missing.toml", "--json") == 1
    assert json.loads(capsys.readouterr().out)["errors"]
    # Reserve then release a real local port, avoiding assumptions about port 8000.
    server = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = server.server_port
    server.server_close()
    path = _config(tmp_path, f"http://127.0.0.1:{port}")
    with patch("app.cli_check.run_project", new_callable=AsyncMock) as runner:
        assert _check(path, "--json", "--repair") == 1
    runner.assert_not_called()
    result = json.loads(capsys.readouterr().out)
    assert result["checks"][0]["outcome"] == "infrastructure_error"
    assert result["checks"][0]["repair"]["status"] == "not_reproduced"


def test_check_missing_sandbox_fails_even_when_http_passes(
    tmp_path: Path,
    live_http: tuple[str, list[str]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _config(tmp_path, live_http[0])
    with patch("app.cli_check.shutil.which", return_value=None):
        assert _check(path, "--json") == 1
    result = json.loads(capsys.readouterr().out)
    assert result["checks"][0]["passed"] is True
    assert result["sandbox"]["status"] == "unavailable"
    assert result["errors"]


def test_check_port_substitution_and_plain(
    tmp_path: Path,
    live_http: tuple[str, list[str]],
    ready_sandbox: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    port = live_http[0].rsplit(":", 1)[1]
    path = _config(tmp_path, "http://127.0.0.1:{port}")
    assert _check(path, "--plain") == 1
    assert "error: port_required: this config's URLs use {port}; pass --port N" in (
        capsys.readouterr().out
    )
    assert _check(path, "--port", port, "--plain") == 0
    output = capsys.readouterr().out
    assert "PASS health: every assertion passed in both sessions" in output
    assert "\x1b" not in output
    assert _check(path, "--port", "0", "--json") == 1
    assert json.loads(capsys.readouterr().out)["errors"]


@pytest.mark.parametrize(
    "outcome,cleanup,proof,status",
    [
        ("verified", "succeeded", "/proof", "verified_candidate"),
        ("verified", "failed", "/proof", "unresolved"),
        ("verified", "succeeded", None, "unresolved"),
        ("no_failure", "succeeded", None, "unresolved"),
        ("invalid_patch", "succeeded", None, "unresolved"),
    ],
)
def test_check_repair_preserves_failed_exit_and_never_applies(
    tmp_path: Path,
    live_http: tuple[str, list[str]],
    ready_sandbox: MagicMock,
    capsys: pytest.CaptureFixture[str],
    outcome: str,
    cleanup: str,
    proof: str | None,
    status: str,
) -> None:
    path = _config(tmp_path, "http://127.0.0.1:{port}", "/fail")
    path.write_text(
        path.read_text() + '\n[repair]\neditable=["server.js"]\ntarget_file="server.js"\n'
    )
    source = tmp_path / "server.js"
    source.write_text("original")
    port = live_http[0].rsplit(":", 1)[1]

    async def run(*args: Any, **kwargs: Any) -> dict[str, Any]:
        print("runner diagnostic")
        assert kwargs == {"detect": False}
        assert args[1].scenario.target_file == "server.js"
        return {"outcome": outcome, "cleanup": cleanup, "proof_bundle": proof}

    with patch("app.cli_check.run_project", side_effect=run) as runner:
        assert _check(path, "--port", port, "--repair", "--json") == 1
    runner.assert_called_once()
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert "runner diagnostic" in captured.err
    assert result["checks"][0]["repair"]["status"] == status
    assert result["source_applied"] is False
    assert source.read_text() == "original"


@pytest.mark.parametrize(
    "route,readiness,status",
    [
        ("/", True, "not_needed"),
        ("/fail", True, "unsupported"),
        ("/fail", False, "unavailable"),
        ("/flaky", True, "not_reproduced"),
    ],
)
def test_check_repair_is_selective(
    tmp_path: Path,
    live_http: tuple[str, list[str]],
    ready_sandbox: MagicMock,
    capsys: pytest.CaptureFixture[str],
    route: str,
    readiness: bool,
    status: str,
) -> None:
    path = _config(tmp_path, live_http[0], route)
    ready_sandbox.return_value["prerequisites_available"] = readiness
    with patch("app.cli_check.run_project", new_callable=AsyncMock) as runner:
        code = _check(path, "--json", "--repair")
    runner.assert_not_called()
    result = json.loads(capsys.readouterr().out)
    assert result["checks"][0]["repair"]["status"] == status
    assert code == (0 if route == "/" else 1)


@pytest.mark.parametrize("router", ["app", "pages", "src/app", "src/pages"])
@pytest.mark.parametrize(
    "manager,lock",
    [
        ("npm", "package-lock.json"),
        ("pnpm", "pnpm-lock.yaml"),
        ("yarn", "yarn.lock"),
        ("bun", "bun.lock"),
    ],
)
def test_init_next_templates_validate_runtime(
    tmp_path: Path,
    router: str,
    manager: str,
    lock: str,
) -> None:
    from app.cli_check import validate_config
    from app.project import load_project

    folder = tmp_path / router
    folder.mkdir(parents=True)
    (folder / "page.tsx").write_text("export default function Page() { return null; }")
    (tmp_path / lock).touch()
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "dependencies": {"next": "16"},
                "scripts": {"dev": "next dev"},
                "packageManager": f"{manager}@2.0.0",
            }
        )
    )
    info = detect_project_stack(tmp_path)
    assert info["stack"] == "node-next"
    assert info["router"] == ("app" if router.endswith("app") else "pages")
    assert f"{router}/**/*.tsx" in info["editable"]
    assert info["lockfiles"] == [lock]
    assert info["dev_command"].startswith(f"env PORT={{port}} {manager} run dev")
    config = tmp_path / "faultline.toml"
    config.write_text(generate_faultline_toml(info))
    validate_config(config)
    config.write_text(
        config.read_text()
        + f'''\n[scenarios.home]
target_file="{router}/page.tsx"
[scenarios.home.repro]
id="home"
steps=[{{action="request",id="r",path="/",method="GET"}},{{action="assert",id="a",source="r",check={{status=200}}}}]
'''
    )
    _, run = load_project(config)
    assert run.command(1234)[0:2] == ["env", "PORT=1234"]
    assert "schema-v1.json" not in config.read_text()


@pytest.mark.parametrize("framework", ["react", "vue", "svelte"])
@pytest.mark.parametrize("typescript", [False, True])
def test_init_vite_language_and_scripts(tmp_path: Path, framework: str, typescript: bool) -> None:
    from app.cli_check import validate_config

    deps = {"vite": "1", framework: "1"}
    if typescript:
        deps["typescript"] = "1"
    (tmp_path / "package.json").write_text(
        json.dumps({"devDependencies": deps, "scripts": {"dev": "vite", "test": "vitest run"}})
    )
    info = detect_project_stack(tmp_path)
    assert info["stack"] == f"node-vite-{framework}"
    assert info["language"] == ("typescript" if typescript else "javascript")
    assert "--strictPort" in info["dev_command"]
    assert info["test_command"] == "npm run test"
    path = tmp_path / "faultline.toml"
    path.write_text(generate_faultline_toml(info))
    validate_config(path)


@pytest.mark.parametrize(
    "framework,dep,source",
    [
        ("fastapi", "fastapi>=0.1", "from fastapi import FastAPI\napi=FastAPI()"),
        ("starlette", "starlette", "from starlette.applications import Starlette\napi=Starlette()"),
        ("flask", "Flask[async]", "from flask import Flask\napi=Flask(__name__)"),
    ],
)
@pytest.mark.parametrize("manifest", ["pyproject.toml", "requirements.txt"])
def test_init_python_entrypoints_and_dependencies(
    tmp_path: Path,
    framework: str,
    dep: str,
    source: str,
    manifest: str,
) -> None:
    from app.cli_check import validate_config

    content = (
        f'[project]\nname="test"\ndependencies=["{dep}"]' if manifest == "pyproject.toml" else dep
    )
    (tmp_path / manifest).write_text(content)
    if manifest == "pyproject.toml":
        (tmp_path / "uv.lock").touch()
    # Dependency-only detection clearly discloses its conventional fallback.
    info = detect_project_stack(tmp_path)
    assert info["stack"] == f"python-{framework}"
    assert any("dependencies only" in note for note in info["notes"])
    path = tmp_path / "faultline.toml"
    path.write_text(generate_faultline_toml(info))
    validate_config(path)
    (tmp_path / "app").mkdir()
    (tmp_path / "app/main.py").write_text(source)
    info = detect_project_stack(tmp_path)
    assert "app.main:api" in info["dev_command"]
    assert info["health"] == "/"
    assert info["dev_command"].startswith(
        "uv run" if manifest == "pyproject.toml" else ".venv/bin/python"
    )
    path.write_text(generate_faultline_toml(info))
    validate_config(path)


def test_init_django_express_and_generic_node(tmp_path: Path) -> None:
    (tmp_path / "manage.py").touch()
    info = detect_project_stack(tmp_path)
    assert info["stack"] == "python-django"
    assert "manage.py runserver 127.0.0.1:{port} --noreload" in info["dev_command"]
    (tmp_path / "package.json").write_text(
        '{"dependencies":{"express":"5"},"scripts":{"start":"node api.js"}}'
    )
    info = detect_project_stack(tmp_path)
    assert info["stack"] == "node-express"
    assert info["dev_command"] == "env PORT={port} npm run start"
    (tmp_path / "package.json").write_text('{"main":"index.js"}')
    (tmp_path / "index.js").touch()
    info = detect_project_stack(tmp_path)
    assert info["stack"] == "node-generic"
    assert info["dev_command"] == "env PORT={port} node index.js"


def test_init_quotes_toml_and_does_not_overwrite(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "package.json").write_text('{"scripts":{"dev":"node app.js"}}')
    info = detect_project_stack(tmp_path)
    info["name"] = 'quoted "name" \\ path\nnew line 🐈'
    info["dev_command"] = 'node "space in name.js"'
    content = generate_faultline_toml(info)
    assert tomllib.loads(content)["project"]["name"] == info["name"]
    dest = tmp_path / "faultline.toml"
    dest.write_text("keep me")
    with patch("pathlib.Path.cwd", return_value=tmp_path):
        assert cmd_init(argparse.Namespace(force=False)) == 0
        assert dest.read_text() == "keep me"
        assert cmd_init(argparse.Namespace(force=True)) == 0
    assert tomllib.loads(dest.read_text())["schema"] == 1


@pytest.mark.parametrize(
    "file,content",
    [
        ("package.json", "[]"),
        ("package.json", "{"),
        ("pyproject.toml", "broken = ["),
        ("main.py", "syntax error !!!"),
    ],
)
def test_init_bad_project_reports_error_without_partial_config(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    file: str,
    content: str,
) -> None:
    (tmp_path / file).write_text(content)
    with patch("pathlib.Path.cwd", return_value=tmp_path):
        assert cmd_init(argparse.Namespace(force=False)) == 1
    assert "faultline init:" in capsys.readouterr().err
    assert not (tmp_path / "faultline.toml").exists()


def test_init_empty_project_refuses_fake_service(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with patch("pathlib.Path.cwd", return_value=tmp_path):
        assert cmd_init(argparse.Namespace(force=False)) == 1
    assert "No runnable service entrypoint" in capsys.readouterr().err
    assert not (tmp_path / "faultline.toml").exists()


@pytest.mark.parametrize(
    "command",
    ["init", "check", "run", "dashboard", "listen", "doctor", "apply", "revert", "verify"],
)
def test_root_launcher_uses_install_location_and_forwards_args(
    tmp_path: Path, command: str
) -> None:
    from app.cli import REPOSITORY_ROOT

    shim = tmp_path / "uv"
    shim.write_text(
        "#!/usr/bin/env python3\nimport json,os,sys\n"
        'print(json.dumps({"argv":sys.argv[1:],"cwd":os.getcwd()}))\n'
    )
    shim.chmod(0o755)
    launcher = tmp_path / "faultline"
    launcher.symlink_to(REPOSITORY_ROOT / "faultline")
    args = [command, "--config", "with spaces.toml", "--plain"]
    result = subprocess.run(
        [str(launcher), *args],
        cwd=tmp_path,
        env={**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"]},
        capture_output=True,
        text=True,
        check=True,
    )
    output = json.loads(result.stdout)
    assert output["argv"] == [
        "run",
        "--project",
        str(REPOSITORY_ROOT / "services/repair-orchestrator"),
        "--python",
        "3.13",
        "--locked",
        "--no-env-file",
        "python",
        "-m",
        "app.cli",
        *args,
    ]
    assert output["cwd"] == str(tmp_path)


@pytest.mark.parametrize(
    "metadata,lock,command",
    [
        ({}, "# yarn lockfile v1\n", "yarn install --frozen-lockfile"),
        ({}, "__metadata:\n  version: 8\n", "yarn install --immutable"),
        ({"packageManager": "yarn@1.22.22"}, "", "yarn install --frozen-lockfile"),
        ({"packageManager": "yarn@4.0.0"}, "", "yarn install --immutable"),
    ],
)
def test_init_yarn_lock_versions(
    tmp_path: Path, metadata: dict[str, str], lock: str, command: str
) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({**metadata, "scripts": {"start": "node app.js"}})
    )
    (tmp_path / "yarn.lock").write_text(lock)
    assert detect_project_stack(tmp_path)["setup_command"] == command


@pytest.mark.parametrize(
    "content", ["project=1", "project=[]", '[project]\ndependencies="fastapi"']
)
def test_init_invalid_pyproject_table(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], content: str
) -> None:
    (tmp_path / "pyproject.toml").write_text(content)
    with patch("pathlib.Path.cwd", return_value=tmp_path):
        assert cmd_init(argparse.Namespace(force=False)) == 1
    assert "faultline init:" in capsys.readouterr().err
    assert not (tmp_path / "faultline.toml").exists()


def test_check_selects_failed_scenario_only(
    tmp_path: Path,
    live_http: tuple[str, list[str]],
    ready_sandbox: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "faultline.toml"
    path.write_text("""schema=1
[project]
dev_command=["node","server.js","{port}"]
url="http://127.0.0.1:{port}"
[repair]
editable=["server.js"]
[scenarios.healthy]
target_file="server.js"
[scenarios.healthy.repro]
steps=[{action="request",id="r",method="GET",path="/"},{action="assert",id="a",source="r",check={status=200}}]
[scenarios.broken]
target_file="server.js"
[scenarios.broken.repro]
steps=[{action="request",id="r",method="GET",path="/fail"},{action="assert",id="a",source="r",check={status=200}}]
""")
    port = live_http[0].rsplit(":", 1)[1]
    with patch("app.cli_check.run_project", new_callable=AsyncMock) as runner:
        runner.return_value = {
            "outcome": "invalid_patch",
            "cleanup": "succeeded",
            "proof_bundle": None,
        }
        assert _check(path, "--port", port, "--json", "--repair") == 1
    runner.assert_called_once()
    assert runner.call_args.args[1].scenario.id == "broken"
    checks = json.loads(capsys.readouterr().out)["checks"]
    assert [c["repair"]["status"] for c in checks] == ["not_needed", "unresolved"]


@pytest.mark.parametrize(
    "extra",
    [
        '\n[[invariants.rule]]\nid="health"\ntarget="http://127.0.0.1:1/"\nexpected_status=200',
        '\n[invariants]\ntest="pytest"',
        "\n[sandbox.limits]\nmemory_swap_max_bytes=false",
        "\n[scenarios.bad]\ntitle=1",
        "\n[scenarios.bad]\nrepro=1",
    ],
)
def test_check_rejects_duplicates_unsupported_and_invalid_scenarios(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    extra: str,
) -> None:
    path = _config(tmp_path, "http://127.0.0.1:1")
    path.write_text(path.read_text() + extra)
    with patch("app.cli_check.run_check", new_callable=AsyncMock) as probe:
        assert _check(path, "--json") == 1
    probe.assert_not_called()
    assert json.loads(capsys.readouterr().out)["errors"]


def test_check_repair_runner_error_is_structured(
    tmp_path: Path,
    live_http: tuple[str, list[str]],
    ready_sandbox: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _config(tmp_path, "http://127.0.0.1:{port}", "/fail")
    path.write_text(
        path.read_text() + '\n[repair]\neditable=["server.js"]\ntarget_file="server.js"'
    )
    with patch("app.cli_check.run_project", side_effect=RuntimeError("preflight unavailable")):
        assert _check(path, "--port", live_http[0].rsplit(":", 1)[1], "--repair", "--json") == 1
    result = json.loads(capsys.readouterr().out)
    assert result["checks"][0]["repair"] == {"status": "error", "reason": "preflight unavailable"}


def test_target_rule_body_is_preserved_in_sandbox_oracle(tmp_path: Path) -> None:
    from app.project import load_project
    from app.repro import RequestStep

    path = _config(tmp_path, "http://127.0.0.1:{port}", "/echo")
    path.write_text(
        path.read_text().replace(
            "expected_status = 200", 'expected_status = 200\nmethod="POST"\njson={value=3}'
        )
        + """
[repair]
editable=["server.js"]
[scenarios.echo]
target_file="server.js"
[scenarios.echo.repro]
steps=[{action="request",id="r",method="GET",path="/"},{action="assert",id="a",source="r",check={status=200}}]
"""
    )
    _, run = load_project(path)
    request = next(
        s for s in run.repro.steps if isinstance(s, RequestStep) and s.id.startswith("invariant.")
    )
    assert request.body == {"value": 3}


def test_check_plain_output_explains_missing_config_bad_toml_and_no_response(
    tmp_path: Path, ready_sandbox: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "faultline.toml"
    assert _check(missing, "--plain") == 1
    assert f"error: {missing} not found; run faultline init or pass --config PATH" in (
        capsys.readouterr().out
    )
    missing.write_text("schema = 1\n[project\n")
    assert _check(missing, "--json") == 1
    (error,) = json.loads(capsys.readouterr().out)["errors"]
    assert error.startswith("faultline.toml is not valid TOML: ")
    # A closed port: the gate fails and says what to check, not an engine reason code.
    path = _config(tmp_path, "http://127.0.0.1:{port}")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed = probe.getsockname()[1]
    assert _check(path, "--port", str(closed), "--plain") == 1
    out = capsys.readouterr().out
    assert "FAIL health: no complete response (ConnectError); is the service running" in out
    assert "execution_or_cleanup_failed" not in out


def test_describe_check_names_flaky_and_mismatched_failures() -> None:
    def session(*passed: bool) -> dict[str, Any]:
        assertions = [{"id": f"a{i}", "passed": ok} for i, ok in enumerate(passed)]
        return {"error": None, "assertions": assertions}

    flaky = {
        "passed": False,
        "outcome": "no_failure",
        "reason": "failure_not_reproduced_twice",
        "sessions": [session(True, False), session(True, True)],
    }
    assert _describe_check(flaky) == "failed inconsistently across the two sessions (flaky): a1"
    mismatch = {**flaky, "reason": "fingerprint_mismatch", "sessions": [session(False)] * 2}
    assert _describe_check(mismatch) == "failed, but not with the declared server error: a0"


# --- Color policy and port resolution ---------------------------------------------------------

_DIFF_JOB = {
    "job": {"outcome": "verified"},
    "attempts": [{"parsed_diff": "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-old\n+new\n"}],
}
_READY = {"status": "ready", "runtime_ready": True, "model": {"model": "m", "provider": "meta"}}


def _styled_output(argv: list[str], capsys: pytest.CaptureFixture[str], *, tty: bool) -> str:
    """Run one command through the real parser with the orchestrator mocked; return stdout.

    With tty=True the captured stdout claims to be a terminal, so only NO_COLOR or a flag can
    turn color off. It is patched here, not in a fixture: capture swaps sys.stdout after setup.
    """
    args = build_parser().parse_args(argv)
    replies = {"diff": _DIFF_JOB, "status": _READY}
    reply = replies.get(argv[0], {"status": "ok"})
    with (
        patch("app.cli._api_request", return_value=reply),
        patch.object(sys.stdout, "isatty", return_value=tty),
    ):
        args.func(args)
    return capsys.readouterr().out


@pytest.fixture
def color_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)


COLOR_COMMANDS = [["version"], ["doctor"], ["diff", "job-1"], ["status"]]


@pytest.mark.parametrize("argv", COLOR_COMMANDS, ids=lambda argv: argv[0])
def test_terminal_output_is_colored_by_default(
    argv: list[str], color_env: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """Control: on a terminal without NO_COLOR, the same commands do style their output."""
    assert "\x1b[" in _styled_output(argv, capsys, tty=True)


@pytest.mark.parametrize("argv", COLOR_COMMANDS, ids=lambda argv: argv[0])
def test_no_color_env_strips_ansi_on_a_terminal(
    argv: list[str],
    color_env: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    out = _styled_output(argv, capsys, tty=True)
    assert out.strip() and "\x1b" not in out


@pytest.mark.parametrize("flag", ["--no-color", "--plain"])
@pytest.mark.parametrize("argv", COLOR_COMMANDS, ids=lambda argv: argv[0])
def test_color_flags_strip_ansi_on_a_terminal(
    argv: list[str], flag: str, color_env: None, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _styled_output([*argv, flag], capsys, tty=True)
    assert out.strip() and "\x1b" not in out


@pytest.mark.parametrize("argv", COLOR_COMMANDS, ids=lambda argv: argv[0])
def test_non_tty_output_has_no_ansi(
    argv: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Piped output (captured stdout is not a terminal) is plain even without NO_COLOR."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    out = _styled_output(argv, capsys, tty=False)
    assert out.strip() and "\x1b" not in out


def test_empty_no_color_does_not_disable_color(
    color_env: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """no-color.org: only a NO_COLOR that is present and non-empty disables color."""
    monkeypatch.setenv("NO_COLOR", "")
    assert "\x1b[" in _styled_output(["version"], capsys, tty=True)


def test_every_command_accepts_no_color() -> None:
    parser = build_parser()
    subparsers = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    for name, command in subparsers.choices.items():
        options = {option for action in command._actions for option in action.option_strings}
        assert {"--no-color", "--plain"} <= options, name


def test_listen_no_color_keeps_live_view_but_drops_color(
    color_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.cli import _output_mode

    monkeypatch.delenv("CI", raising=False)
    parser = build_parser()

    def plain_and_color(*argv: str) -> tuple[bool, bool]:
        with patch.object(sys.stdout, "isatty", return_value=True):
            plain, color, _ = _output_mode(parser.parse_args(["listen", *argv]))
        return plain, color

    assert plain_and_color() == (False, True)
    assert plain_and_color("--no-color") == (False, False)
    assert plain_and_color("--plain") == (True, False)
    monkeypatch.setenv("NO_COLOR", "1")
    assert plain_and_color() == (False, False)


def _ports_used(argv: list[str], reply: dict[str, Any] | None = None) -> list[int]:
    """Run a command through the parser and return the port of every API request it made."""
    args = build_parser().parse_args(argv)
    with patch("app.cli._api_request", return_value=reply or {"status": "ok"}) as api:
        args.func(args)
    return [call.kwargs["port"] for call in api.call_args_list]


@pytest.fixture
def default_ports(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("FAULTLINE_PORT", "BUGGYSHOP_API_PORT", "BUGGYSHOP_PORT"):
        monkeypatch.delenv(name, raising=False)


def test_commands_default_to_the_standard_ports(default_ports: None) -> None:
    assert _ports_used(["doctor"]) == [9000, 8000]
    assert _ports_used(["status"]) == [9000]
    assert _ports_used(["jobs"]) == [9000]
    assert _ports_used(["diff", "job-1"], _DIFF_JOB) == [9000]
    assert _ports_used(["verify"]) == [8000]


def test_port_flags_override_defaults(default_ports: None) -> None:
    assert _ports_used(["doctor", "--port", "9401", "--api-port", "8401"]) == [9401, 8401]
    assert _ports_used(["status", "--port", "9402"]) == [9402]
    assert _ports_used(["jobs", "--port", "9403"]) == [9403]
    assert _ports_used(["diff", "job-1", "--port", "9404"], _DIFF_JOB) == [9404]
    assert _ports_used(["verify", "--api-port", "8405"]) == [8405]


def test_port_environment_variables_are_respected(
    default_ports: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAULTLINE_PORT", "9500")
    monkeypatch.setenv("BUGGYSHOP_API_PORT", "8500")
    assert _ports_used(["doctor"]) == [9500, 8500]
    assert _ports_used(["status"]) == [9500]
    assert _ports_used(["jobs"]) == [9500]
    assert _ports_used(["verify"]) == [8500]
    # An explicit flag still wins over the environment.
    assert _ports_used(["doctor", "--port", "9501", "--api-port", "8501"]) == [9501, 8501]


def test_doctor_names_the_resolved_ports(
    default_ports: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("FAULTLINE_PORT", "9600")
    _ports_used(["doctor", "--api-port", "8600"])
    out = capsys.readouterr().out
    assert "Repair Orchestrator Service (port 9600)" in out
    assert "Storefront Backend API (port 8600)" in out
    assert "port 9000" not in out and "port 8000" not in out


def test_apply_uses_both_ports_and_the_storefront_port(
    default_ports: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("BUGGYSHOP_PORT", "3700")
    args = build_parser().parse_args(["apply", "job-1", "--port", "9700", "--api-port", "8700"])
    applied = {"success": True, "target": "checkout.py", "backup": "checkout.py.bak"}
    with (
        patch("app.cli.apply_patch_for_job", return_value=applied) as apply_patch,
        patch("app.cli._api_request", return_value={"id": "order-1", "total": 1000}) as api,
    ):
        assert cmd_apply(args) == 0
    apply_patch.assert_called_once_with("job-1", port=9700)
    assert api.call_args.kwargs["port"] == 8700
    assert "http://127.0.0.1:3700" in capsys.readouterr().out


def test_apply_patch_for_job_fetches_from_the_given_port() -> None:
    with patch("app.cli._api_request", return_value={"error": "down", "status": 0}) as api:
        result = apply_patch_for_job("job-1", port=9800)
    assert result["error_code"] == "job_fetch_failed"
    assert api.call_args.kwargs["port"] == 9800


def test_listen_resolves_port_from_environment(
    default_ports: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAULTLINE_PORT", "9900")
    args = build_parser().parse_args(["listen", "job-1", "--plain"])
    with patch("app.cli._api_request", return_value={"error": "down", "status": 0}) as api:
        assert cmd_listen(args) == 1
    assert api.call_args.kwargs["port"] == 9900


def test_dashboard_points_the_inspector_at_faultline_port(
    tmp_path: Path, default_ports: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    inspector = tmp_path / "inspector"
    next_bin = inspector / "node_modules" / "next" / "dist" / "bin" / "next"
    next_bin.parent.mkdir(parents=True)
    next_bin.write_text("")
    (inspector / ".next").mkdir()
    (inspector / ".next" / "BUILD_ID").write_text("build")
    monkeypatch.delenv("FAULTLINE_ORCHESTRATOR_URL", raising=False)
    monkeypatch.setenv("FAULTLINE_PORT", "9450")
    process = MagicMock(pid=1)
    process.poll.return_value = None
    with (
        patch("app.cli._probe_inspector", side_effect=["down", "inspector"]),
        patch("app.cli.INSPECTOR_DIR", inspector),
        patch("app.cli.DATA_DIR", tmp_path / "data"),
        patch("app.cli.shutil.which", return_value="/usr/bin/node"),
        patch("app.cli._get_control_token", return_value="t"),
        patch("app.cli.subprocess.Popen", return_value=process) as popen,
    ):
        assert cmd_dashboard(argparse.Namespace(port=4450, no_open=True)) == 0
    assert popen.call_args.kwargs["env"]["FAULTLINE_ORCHESTRATOR_URL"] == "http://127.0.0.1:9450"


@pytest.mark.parametrize("value", ["abc", "0", "70000"])
def test_invalid_port_environment_is_rejected(
    value: str, default_ports: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAULTLINE_PORT", value)
    with pytest.raises(SystemExit, match="FAULTLINE_PORT must be a port number"):
        _ports_used(["status"])


def test_invalid_port_flag_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        build_parser().parse_args(["status", "--port", "70000"])
    assert exit_info.value.code == 2
    assert "not a port number" in capsys.readouterr().err


def test_status_reaches_a_real_orchestrator_on_a_custom_port(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """End to end over HTTP: FAULTLINE_PORT routes the request, not the 9000 default."""
    seen: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            seen.append(self.path)
            body = json.dumps(_READY).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("FAULTLINE_PORT", str(server.server_address[1]))
        monkeypatch.setenv("FAULTLINE_CONTROL_TOKEN", "test-token")
        assert cmd_status(build_parser().parse_args(["status"])) == 0
    finally:
        server.shutdown()
        server.server_close()
    assert seen == ["/api/faultline/readiness"]
    out = capsys.readouterr().out
    assert "Status:          ready" in out and "\x1b" not in out


def test_control_token_lookup_matches_the_port_in_a_process_command_line() -> None:
    from app.cli import _process_listens_on

    code = "import time; print('up', flush=True); time.sleep(30)"
    with subprocess.Popen(
        [sys.executable, "-c", code, "--port", "9412"], stdout=subprocess.PIPE, text=True
    ) as process:
        try:
            # Until the child execs, /proc/PID/cmdline still shows the parent's argv.
            assert process.stdout is not None and process.stdout.readline() == "up\n"
            assert _process_listens_on(str(process.pid), 9412)
            assert not _process_listens_on(str(process.pid), 9000)
        finally:
            process.kill()
    assert not _process_listens_on("999999999", 9412)


# --- One-command demo and config-free HTTP tests ---------------------------------------------


def _command(*argv: str) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


@pytest.mark.parametrize(
    "route,status,code,description",
    [
        ("/", 200, 0, "every assertion passed in both sessions"),
        ("/fail", 200, 1, "failed the same way in both sessions"),
        ("/flaky", 200, 1, "flaky"),
        ("/fail", 500, 0, "every assertion passed in both sessions"),
    ],
)
def test_url_check_real_sessions_without_config(
    live_http: tuple[str, list[str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    route: str,
    status: int,
    code: int,
    description: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    # Deliberately malformed: this command must never load the project's configuration.
    (tmp_path / "faultline.toml").write_text("not TOML")
    with patch("app.cli_check.sandbox_readiness", side_effect=AssertionError("not a repair")):
        assert _command("test", live_http[0] + route, "--status", str(status), "--plain") == code
    out = capsys.readouterr().out
    assert description in out and "\x1b" not in out
    assert len(live_http[1]) == 2 and len(set(live_http[1])) == 2


def test_url_check_non_get_and_json(
    live_http: tuple[str, list[str]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _command("test", live_http[0], "--method", "post", "--json") == 0
    result = json.loads(capsys.readouterr().out)
    assert result["method"] == "POST" and result["expected_status"] == 200
    assert result["passed"] and result["exit_code"] == 0
    assert len(result["sessions"]) == 2
    assert all(s["requests"][0]["method"] == "POST" for s in result["sessions"])
    assert all(s["excerpt"] == "[omitted]" for s in result["sessions"])


def test_url_check_no_response_is_truthful(capsys: pytest.CaptureFixture[str]) -> None:
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))  # bound but not listening; cannot be reused by another test
        url = f"http://127.0.0.1:{reserved.getsockname()[1]}"
        assert _command("test", url, "--json") == 1
    result = json.loads(capsys.readouterr().out)
    assert not result["passed"] and result["outcome"] == "infrastructure_error"
    assert len(result["sessions"]) == 1
    assert result["sessions"][0]["status"] is None
    assert result["sessions"][0]["error"] == "ConnectError"


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com",
        "example.com",
        "http://",
        "http://user:password@localhost",
        "http://localhost:99999",
        "http://localhost/#fragment",
        "http://localhost/{port}",
    ],
)
def test_url_check_rejects_invalid_targets(url: str, capsys: pytest.CaptureFixture[str]) -> None:
    with patch("app.probes.run_check", new_callable=AsyncMock) as run:
        assert _command("test", url, "--json") == 2
    run.assert_not_called()
    result = json.loads(capsys.readouterr().out)
    assert result["errors"] and result["sessions"] == []
    assert "password" not in json.dumps(result)


@pytest.mark.parametrize("status", ["99", "600", "-1"])
def test_url_check_rejects_invalid_status(status: str, capsys: pytest.CaptureFixture[str]) -> None:
    with patch("app.probes.run_check", new_callable=AsyncMock) as run:
        assert _command("test", "https://example.com", "--status", status, "--json") == 2
    run.assert_not_called()
    assert json.loads(capsys.readouterr().out)["errors"]


@pytest.mark.parametrize("flags", [("--method", "TRACE"), ("--status", "abc")])
def test_url_check_bad_options_are_usage_errors(flags: tuple[str, str]) -> None:
    with pytest.raises(SystemExit) as error:
        _command("test", "https://example.com", *flags)
    assert error.value.code == 2


@pytest.fixture
def demo_ports(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[int, ...]:
    from app import cli_demo

    monkeypatch.setattr("app.cli.REPOSITORY_ROOT", tmp_path)
    for name in cli_demo.PORT_NAMES:
        monkeypatch.delenv(name, raising=False)
    return cli_demo.DEFAULT_PORTS


@pytest.mark.parametrize("platform", ["darwin", "win32"])
@pytest.mark.parametrize("restart,occupied", [(False, False), (False, True), (True, False)])
def test_demo_native_foreground_without_linux_discovery(
    platform: str,
    restart: bool,
    occupied: bool,
    tmp_path: Path,
    demo_ports: tuple[int, ...],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    def start(root: Path, ports: tuple[int, ...], ready: Any) -> int:
        assert root == tmp_path and ports == demo_ports
        ready()
        return 0

    with (
        patch("app.cli_demo.processes", side_effect=AssertionError("Linux process discovery")),
        patch("app.cli_demo._occupied", return_value=occupied),
        patch("app.cli_demo.start_demo", side_effect=start) as launch,
        patch("app.cli_demo.stop_stack") as stop,
        patch("app.cli.webbrowser.open", return_value=True) as browser,
    ):
        assert _command("demo", *(["--restart"] if restart else [])) == int(restart or occupied)
    stop.assert_not_called()
    if restart or occupied:
        launch.assert_not_called()
        assert "original terminal" in capsys.readouterr().err
    else:
        launch.assert_called_once()
        browser.assert_called_once_with("http://127.0.0.1:4000")


def test_demo_macos_launcher_waits_for_health_without_proc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import cli_demo

    monkeypatch.setattr(sys, "platform", "darwin")
    process = MagicMock()
    process.__enter__.return_value = process
    process.poll.return_value = None
    process.wait.return_value = 0
    ready = MagicMock()
    with (
        patch("app.cli_demo.subprocess.Popen", return_value=process),
        patch("app.cli_demo.processes", side_effect=AssertionError("Linux process discovery")),
        patch("app.cli_demo._healthy", return_value=True) as health,
    ):
        assert cli_demo.start_demo(tmp_path, cli_demo.DEFAULT_PORTS, ready) == 0
    assert health.call_count == 4
    ready.assert_called_once()


@pytest.mark.parametrize("shell", ["pwsh", "powershell.exe", None])
def test_demo_windows_launcher_health_and_shell_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shell: str | None
) -> None:
    from app import cli_demo

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("PSModulePath", "caller-specific-PowerShell-modules")
    process = MagicMock()
    process.__enter__.return_value = process
    process.poll.return_value = None
    process.wait.return_value = 0
    ready = MagicMock()
    with (
        patch(
            "app.cli_demo.shutil.which", side_effect=lambda name: shell if name == shell else None
        ),
        patch("app.cli_demo.subprocess.Popen", return_value=process) as launch,
        patch("app.cli_demo.processes", side_effect=AssertionError("Linux process discovery")),
        patch("app.cli_demo._healthy", side_effect=[False, True, True, True, True]) as health,
        patch("app.cli_demo.time.sleep"),
    ):
        if shell is None:
            with pytest.raises(RuntimeError, match="PowerShell is required"):
                cli_demo.start_demo(tmp_path, cli_demo.DEFAULT_PORTS, ready)
            launch.assert_not_called()
            ready.assert_not_called()
            return
        assert cli_demo.start_demo(tmp_path, cli_demo.DEFAULT_PORTS, ready) == 0
    assert health.call_count == 5
    command = launch.call_args.args[0]
    assert command[:7] == [
        shell,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(tmp_path / "scripts/start-demo.ps1"),
        "-StopFile",
    ]
    assert launch.call_args.kwargs["creationflags"] == 0x200
    assert launch.call_args.kwargs["start_new_session"] is False
    assert launch.call_args.kwargs["env"]["INSPECTOR_PORT"] == "4000"
    assert "PSModulePath" not in launch.call_args.kwargs["env"]
    ready.assert_called_once()
    process.terminate.assert_not_called()
    assert not Path(command[-1]).exists()


@pytest.mark.parametrize("stuck", [False, True])
def test_demo_windows_interrupt_requests_cleanup_before_tree_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stuck: bool
) -> None:
    from app import cli_demo

    monkeypatch.setattr(sys, "platform", "win32")
    process = MagicMock()
    process.__enter__.return_value = process
    process.poll.return_value = None
    process.pid = 45678
    ready = MagicMock()
    stop_file = None

    def wait(timeout: float | None = None) -> int:
        if timeout is None and stop_file is None:
            raise KeyboardInterrupt
        assert stop_file is not None and stop_file.exists()
        if stuck and timeout is not None:
            raise subprocess.TimeoutExpired("pwsh", timeout)
        return 130

    def stopping(*args: Any, **kwargs: Any) -> int:
        nonlocal stop_file
        stop_file = next((tmp_path / "data").glob("demo-stop-*"))
        return wait(*args, **kwargs)

    process.wait.side_effect = lambda **kw: stopping(**kw) if kw else wait()
    with (
        patch("app.cli_demo.shutil.which", return_value="pwsh"),
        patch("app.cli_demo.subprocess.Popen", return_value=process),
        patch("app.cli_demo.subprocess.run") as kill,
        patch("app.cli_demo._healthy", return_value=True),
    ):
        with pytest.raises(KeyboardInterrupt):
            cli_demo.start_demo(tmp_path, cli_demo.DEFAULT_PORTS, ready)
    assert kill.call_count == int(stuck)
    if stuck:
        assert kill.call_args.args[0] == ["taskkill.exe", "/PID", "45678", "/T", "/F"]
    assert stop_file is not None and not stop_file.exists()
    process.terminate.assert_not_called()


def test_demo_windows_file_lock_is_nonblocking_and_released(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import types

    from app import cli_demo

    locking = MagicMock()
    windows_lock = types.SimpleNamespace(locking=locking, LK_NBLCK=1, LK_UNLCK=2)
    # Keep pathlib native on the Unix test host while exercising the Windows lock.
    monkeypatch.setattr(cli_demo, "os", types.SimpleNamespace(name="nt", SEEK_END=os.SEEK_END))
    with patch.dict(sys.modules, msvcrt=windows_lock):
        with cli_demo.launch_lock(tmp_path) as release:
            release()
        assert [c.args[1:] for c in locking.call_args_list] == [(1, 1), (2, 1)]
        assert (tmp_path / "data/demo.lock").read_bytes() == b"\0"
        locking.side_effect = OSError("already locked")
        with pytest.raises(RuntimeError, match="already in progress"):
            with cli_demo.launch_lock(tmp_path):
                pytest.fail("contended Windows lock was acquired")


def _demo_snapshot(root: Path, ports: tuple[int, ...], *, count: int = 4) -> dict[int, Any]:
    from app import cli_demo

    script = root / "scripts/start-demo.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.touch()
    launcher = cli_demo.Process(100, 1, "start", root, ("bash", str(script)), frozenset())
    snapshot = {100: launcher}
    for index, port in enumerate(ports[:count]):
        argv = (
            ("uvicorn", "app.main:app", "--port", str(port))
            if index < 2
            else ("next-server (v16.0.0)",)
        )
        pid = 101 + index
        snapshot[pid] = cli_demo.Process(
            pid, 100, "start", root / cli_demo.SERVICE_DIRS[index], argv, frozenset({port})
        )
    return snapshot


@pytest.mark.parametrize("no_open", [False, True])
def test_demo_connects_existing_stack(
    tmp_path: Path,
    demo_ports: tuple[int, ...],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    no_open: bool,
) -> None:
    snapshot = _demo_snapshot(tmp_path, demo_ports)
    monkeypatch.setenv("DISPLAY", ":test")
    with (
        patch("app.cli_demo.processes", return_value=snapshot),
        patch("app.cli_demo._occupied", return_value=True),
        patch("app.cli_demo._healthy", return_value=True),
        patch("app.cli_demo.start_demo") as start,
        patch("app.cli_demo.stop_stack") as stop,
        patch("app.cli.webbrowser.open", return_value=True) as browser,
    ):
        assert _command("demo", *(["--no-open"] if no_open else [])) == 0
    start.assert_not_called()
    stop.assert_not_called()
    assert browser.call_count == (0 if no_open else 1)
    if not no_open:
        browser.assert_called_once_with("http://127.0.0.1:4000")
    assert "FaultLine demo stack is already active\n" in capsys.readouterr().out


def test_demo_start_uses_env_ports_and_opens_when_ready(
    tmp_path: Path,
    demo_ports: tuple[int, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import cli_demo

    ports = (8400, 9400, 3400, 4400)
    for name, port in zip(cli_demo.PORT_NAMES, ports, strict=True):
        monkeypatch.setenv(name, str(port))
    monkeypatch.setenv("DISPLAY", ":test")

    def start(root: Path, selected: tuple[int, ...], ready: Any) -> int:
        assert root == tmp_path and selected == ports
        ready()
        return 0

    with (
        patch("app.cli.REPOSITORY_ROOT", tmp_path),
        patch("app.cli_demo.processes", return_value={}),
        patch("app.cli_demo._occupied", return_value=False),
        patch("app.cli_demo.start_demo", side_effect=start) as launch,
        patch("app.cli.webbrowser.open", return_value=True) as browser,
    ):
        assert _command("demo") == 0
    launch.assert_called_once()
    browser.assert_called_once_with("http://127.0.0.1:4400")


@pytest.mark.parametrize("restart", [False, True])
def test_demo_foreign_collision_never_stops_or_starts(
    tmp_path: Path,
    demo_ports: tuple[int, ...],
    capsys: pytest.CaptureFixture[str],
    restart: bool,
) -> None:
    # Real unrelated listener, bound to an ephemeral demo API port.
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        with (
            patch.dict(os.environ, {"BUGGYSHOP_API_PORT": str(server.getsockname()[1])}),
            patch("app.cli_demo.start_demo") as start,
            patch("app.cli_demo.stop_stack") as stop,
        ):
            assert _command("demo", "--no-open", *(["--restart"] if restart else [])) == 1
        assert server.fileno() >= 0
    start.assert_not_called()
    stop.assert_not_called()
    assert "Foreign or unidentifiable service" in capsys.readouterr().err


@pytest.mark.parametrize("healthy,count", [(True, 2), (False, 4)])
def test_demo_partial_or_unhealthy_is_not_active(
    tmp_path: Path,
    demo_ports: tuple[int, ...],
    capsys: pytest.CaptureFixture[str],
    healthy: bool,
    count: int,
) -> None:
    snapshot = _demo_snapshot(tmp_path, demo_ports, count=count)
    with (
        patch("app.cli_demo.processes", return_value=snapshot),
        patch("app.cli_demo._occupied", side_effect=lambda p: p in demo_ports[:count]),
        patch("app.cli_demo._healthy", return_value=healthy),
        patch("app.cli_demo.start_demo") as start,
    ):
        assert _command("demo", "--no-open") == 1
    start.assert_not_called()
    assert "Partial or unhealthy" in capsys.readouterr().err
    assert "already active" not in capsys.readouterr().out


def test_demo_restart_refuses_other_worktree(
    tmp_path: Path,
    demo_ports: tuple[int, ...],
    capsys: pytest.CaptureFixture[str],
) -> None:
    snapshot = _demo_snapshot(tmp_path / "other", demo_ports)
    with (
        patch("app.cli.REPOSITORY_ROOT", tmp_path),
        patch("app.cli_demo.processes", return_value=snapshot),
        patch("app.cli_demo._occupied", return_value=True),
        patch("app.cli_demo._healthy", return_value=True),
        patch("app.cli_demo.start_demo") as start,
        patch("app.cli_demo.signal.pidfd_send_signal") as kill,
    ):
        assert _command("demo", "--restart", "--no-open") == 1
    kill.assert_not_called()
    start.assert_not_called()
    assert "another worktree" in capsys.readouterr().err


def test_demo_restart_stops_then_launches(
    tmp_path: Path,
    demo_ports: tuple[int, ...],
) -> None:
    snapshot = _demo_snapshot(tmp_path, demo_ports)
    events: list[str] = []

    def launch(*args: object) -> int:
        events.append("start")
        return 0

    with (
        patch("app.cli.REPOSITORY_ROOT", tmp_path),
        patch("app.cli_demo.processes", side_effect=[snapshot, snapshot, {}]),
        patch("app.cli_demo._occupied", return_value=True),
        patch("app.cli_demo._healthy", return_value=True),
        patch("app.cli_demo.stop_stack", side_effect=lambda *a: events.append("stop")),
        patch("app.cli_demo.start_demo", side_effect=launch),
    ):
        assert _command("demo", "--restart", "--no-open") == 0
    assert events == ["stop", "start"]


def test_demo_rejects_duplicate_ports(
    demo_ports: tuple[int, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INSPECTOR_PORT", "3000")
    with patch("app.cli_demo.processes") as scan:
        assert _command("demo", "--no-open") == 2
    scan.assert_not_called()


def test_demo_other_port_stack_prevents_rebuilding_same_worktree(
    tmp_path: Path,
    demo_ports: tuple[int, ...],
    capsys: pytest.CaptureFixture[str],
) -> None:
    snapshot = _demo_snapshot(tmp_path, (8400, 9400, 3400, 4400))
    with (
        patch("app.cli.REPOSITORY_ROOT", tmp_path),
        patch("app.cli_demo.processes", return_value=snapshot),
        patch("app.cli_demo._occupied", return_value=False),
        patch("app.cli_demo.start_demo") as start,
    ):
        assert _command("demo", "--no-open") == 1
    start.assert_not_called()
    assert "no build was started" in capsys.readouterr().err


def test_demo_start_launcher_and_cleanup_on_interrupt(
    tmp_path: Path, demo_ports: tuple[int, ...]
) -> None:
    from app import cli_demo

    process = MagicMock()
    process.__enter__.return_value = process
    process.poll.return_value = None
    process.wait.side_effect = [KeyboardInterrupt, 143]
    ready = MagicMock()
    stack = cli_demo.Stack(frozenset(demo_ports), (), tmp_path, frozenset(), True)
    with (
        patch("app.cli_demo.subprocess.Popen", return_value=process) as launch,
        patch("app.cli_demo.processes", return_value={}),
        patch("app.cli_demo.inspect_stack", return_value=stack),
    ):
        with pytest.raises(KeyboardInterrupt):
            cli_demo.start_demo(tmp_path, demo_ports, ready)
    assert launch.call_args.args[0] == ["bash", str(tmp_path / "scripts/start-demo.sh")]
    assert launch.call_args.kwargs["start_new_session"] is True
    assert launch.call_args.kwargs["env"]["INSPECTOR_PORT"] == "4000"
    ready.assert_called_once()
    process.terminate.assert_called_once()


def test_demo_launcher_exit_and_timeout(tmp_path: Path, demo_ports: tuple[int, ...]) -> None:
    from app import cli_demo

    process = MagicMock()
    process.__enter__.return_value = process
    process.poll.return_value = 7
    ready = MagicMock()
    with patch("app.cli_demo.subprocess.Popen", return_value=process):
        with pytest.raises(RuntimeError, match="code 7"):
            cli_demo.start_demo(tmp_path, demo_ports, ready)
        process.poll.return_value = None
        with patch("app.cli_demo.START_TIMEOUT", 0):
            with pytest.raises(RuntimeError, match="timed out"):
                cli_demo.start_demo(tmp_path, demo_ports, ready)
    ready.assert_not_called()
    process.terminate.assert_called_once()


def test_demo_stop_real_owned_launcher_preserves_unrelated_process(tmp_path: Path) -> None:
    from app import cli_demo

    root = tmp_path / "demo"
    backend = root / cli_demo.SERVICE_DIRS[0]
    backend.mkdir(parents=True)
    script = root / "scripts/start-demo.sh"
    script.parent.mkdir()
    # No real service, build, credential or default port: the listener chooses an ephemeral port.
    # A uvicorn-style argv is needed to identify the listener. Once the port is known,
    # a second small exec retains the socket and includes its real port in argv.
    code = (
        "import os,socket,sys; s=socket.socket(); s.bind(('127.0.0.1',0)); s.listen(); "
        "s.set_inheritable(True); port=s.getsockname()[1]; "
        "os.execv(sys.executable,[sys.executable,'-c',"
        "'import time; print('+str(port)+',flush=True); time.sleep(60)',"
        "'uvicorn','app.main:app','--port',str(port)])"
    )
    script.write_text(
        "#!/bin/bash\n"
        "child=''\n"
        'cleanup() { trap - TERM EXIT; kill -TERM "$child" 2>/dev/null || true; '
        'wait "$child" 2>/dev/null || true; exit 0; }\n'
        "trap cleanup TERM EXIT\n"
        f"(cd {shlex.quote(str(backend))}; exec {shlex.quote(sys.executable)} "
        f"-c {shlex.quote(code)}) &\n"
        'child=$!\nwait "$child"\n'
    )
    with (
        subprocess.Popen(
            ["bash", str(script)],
            cwd=root,
            stdout=subprocess.PIPE,
            text=True,
            start_new_session=True,
        ) as launcher,
        subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            cwd=tmp_path,
            start_new_session=True,
        ) as unrelated,
    ):
        try:
            assert launcher.stdout is not None
            port = int(launcher.stdout.readline())
            # A single occupied service exercises partial-stack ownership and cleanup.
            ports = (port,)
            snapshot = cli_demo.processes()
            stack = cli_demo.inspect_stack(ports, snapshot)
            assert stack.root == root and stack.occupied == frozenset({port})
            assert not stack.foreign and not stack.active
            owners = stack.owners
            assert owners and all(p.parent == launcher.pid for p in owners)
            cli_demo.stop_stack(root, ports, stack, snapshot)
            assert launcher.wait(timeout=3) == 0
            assert unrelated.poll() is None
            assert not cli_demo._occupied(port)
            current = cli_demo.processes()
            assert all(p.pid not in current for p in owners)
        finally:
            # Only this test's own subprocess handles are ever signaled.
            if launcher.poll() is None:
                launcher.terminate()
                launcher.wait(timeout=5)
            unrelated.terminate()
            unrelated.wait(timeout=5)


@pytest.mark.parametrize("case", ["orphan", "extra-port", "other-launcher", "stale"])
def test_demo_restart_ownership_refusals_never_signal(
    tmp_path: Path,
    demo_ports: tuple[int, ...],
    case: str,
) -> None:
    from dataclasses import replace

    from app import cli_demo

    snapshot = _demo_snapshot(tmp_path, demo_ports)
    if case == "orphan":
        del snapshot[100]
    elif case == "extra-port":
        snapshot[101] = replace(snapshot[101], ports=frozenset({demo_ports[0], 12345}))
    elif case == "other-launcher":
        snapshot[200] = replace(snapshot[100], pid=200)
    with (
        patch("app.cli_demo._occupied", return_value=True),
        patch("app.cli_demo._healthy", return_value=True),
    ):
        stack = cli_demo.inspect_stack(demo_ports, snapshot)
    # A harmless real file descriptor stands in for the pidfd in the stale-identity case.
    with (
        patch("app.cli_demo.os.pidfd_open", side_effect=lambda _: os.open(os.devnull, os.O_RDONLY)),
        patch("app.cli_demo._read_process", return_value=None),
        patch("app.cli_demo.signal.pidfd_send_signal") as signal_process,
    ):
        with pytest.raises(RuntimeError):
            cli_demo.stop_stack(tmp_path, demo_ports, stack, snapshot)
    signal_process.assert_not_called()


def test_demo_connect_rejects_mixed_installations(
    tmp_path: Path, demo_ports: tuple[int, ...]
) -> None:
    from dataclasses import replace

    from app import cli_demo

    snapshot = _demo_snapshot(tmp_path / "one", demo_ports)
    other = _demo_snapshot(tmp_path / "two", demo_ports)
    snapshot[104] = replace(other[104], parent=1)
    with patch("app.cli_demo._occupied", return_value=True):
        stack = cli_demo.inspect_stack(demo_ports, snapshot)
    assert not stack.active and stack.foreign == frozenset(demo_ports)


def test_demo_health_requires_real_identity() -> None:
    from app import cli_demo

    connection = MagicMock()
    response = connection.getresponse.return_value
    response.status = 200
    response.read.return_value = b'{"status":"ok","app":"foreign"}'
    with patch("app.cli_demo.http.client.HTTPConnection", return_value=connection):
        assert not cli_demo._healthy(0, 12345)
        response.read.return_value = b'{"status":"ok","app":"buggyshop-api"}'
        assert cli_demo._healthy(0, 12345)
        response.status = 503
        assert not cli_demo._healthy(2, 12345)
    assert connection.close.call_count == 3


def test_demo_launch_lock_contention_prevents_second_build(
    tmp_path: Path,
    demo_ports: tuple[int, ...],
    capsys: pytest.CaptureFixture[str],
) -> None:
    lock = tmp_path / "data/demo.lock"
    lock.parent.mkdir()
    code = (
        "import fcntl,sys; "
        "lock=open(sys.argv[1],'a'); fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB); "
        "print('locked',flush=True); sys.stdin.read()"
    )
    with subprocess.Popen(
        [sys.executable, "-c", code, str(lock)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    ) as owner:
        try:
            assert owner.stdout is not None and owner.stdout.readline() == "locked\n"
            with (
                patch("app.cli.REPOSITORY_ROOT", tmp_path),
                patch("app.cli_demo.processes", return_value={}),
                patch("app.cli_demo._occupied", return_value=False),
                patch("app.cli_demo.start_demo", return_value=0) as launch,
            ):
                assert _command("demo", "--no-open") == 1
            launch.assert_not_called()
            assert "launch already in progress" in capsys.readouterr().err
        finally:
            owner.communicate(timeout=5)


def test_demo_active_connection_bypasses_launch_lock(
    tmp_path: Path,
    demo_ports: tuple[int, ...],
) -> None:
    import fcntl

    snapshot = _demo_snapshot(tmp_path, demo_ports)
    lock = tmp_path / "data/demo.lock"
    lock.parent.mkdir()
    with lock.open("a") as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with (
            patch("app.cli.REPOSITORY_ROOT", tmp_path),
            patch("app.cli_demo.processes", return_value=snapshot),
            patch("app.cli_demo._occupied", return_value=True),
            patch("app.cli_demo._healthy", return_value=True),
            patch("app.cli_demo.start_demo") as launch,
        ):
            assert _command("demo", "--no-open") == 0
        launch.assert_not_called()


def test_demo_rechecks_build_owners_after_acquiring_launch_lock(
    tmp_path: Path,
    demo_ports: tuple[int, ...],
    capsys: pytest.CaptureFixture[str],
) -> None:
    snapshot = _demo_snapshot(tmp_path, (8400, 9400, 3400, 4400))
    with (
        patch("app.cli.REPOSITORY_ROOT", tmp_path),
        patch("app.cli_demo.processes", side_effect=[{}, snapshot]),
        patch("app.cli_demo._occupied", return_value=False),
        patch("app.cli_demo.start_demo", return_value=0) as launch,
    ):
        assert _command("demo", "--no-open") == 1
    launch.assert_not_called()
    assert "no build was started" in capsys.readouterr().err


@pytest.mark.parametrize("failure", [False, True])
def test_demo_launch_lock_releases_on_startup_exit(
    tmp_path: Path,
    demo_ports: tuple[int, ...],
    failure: bool,
) -> None:
    from app import cli_demo

    def start(*args: object) -> int:
        # Startup owns the actual kernel lock before the launcher is entered.
        with pytest.raises(RuntimeError, match="launch already in progress"):
            with cli_demo.launch_lock(tmp_path):
                pytest.fail("two concurrent launches admitted")
        if failure:
            raise RuntimeError("startup failed")
        return 0

    with (
        patch("app.cli.REPOSITORY_ROOT", tmp_path),
        patch("app.cli_demo.processes", return_value={}),
        patch("app.cli_demo._occupied", return_value=False),
        patch("app.cli_demo.start_demo", side_effect=start),
    ):
        assert _command("demo", "--no-open") == (1 if failure else 0)
    # A persistent file is not a stale lock; closing on either exit releases it.
    assert (tmp_path / "data/demo.lock").is_file()
    with cli_demo.launch_lock(tmp_path):
        pass


def test_demo_ready_releases_lock_before_foreground_wait(
    tmp_path: Path,
    demo_ports: tuple[int, ...],
) -> None:
    from collections.abc import Callable

    from app import cli_demo

    snapshot = _demo_snapshot(tmp_path, demo_ports)
    starts = 0

    def start(root: Path, ports: tuple[int, ...], ready: Callable[[], None]) -> int:
        nonlocal starts
        starts += 1
        ready()  # Mirrors start_demo's readiness callback before its foreground wait.
        with cli_demo.launch_lock(root):
            pass
        if starts == 1:
            with (
                patch("app.cli_demo.processes", return_value=snapshot),
                patch("app.cli_demo._occupied", return_value=True),
                patch("app.cli_demo._healthy", return_value=True),
            ):
                assert _command("demo", "--no-open") == 0
                assert starts == 1  # Connecting neither launches nor requires the lock.
            with (
                patch("app.cli_demo.processes", side_effect=[snapshot, snapshot, {}]),
                patch("app.cli_demo._occupied", return_value=True),
                patch("app.cli_demo._healthy", return_value=True),
                patch("app.cli_demo.stop_stack") as stop,
            ):
                assert _command("demo", "--restart", "--no-open") == 0
                stop.assert_called_once()
        return 0

    with (
        patch("app.cli.REPOSITORY_ROOT", tmp_path),
        patch("app.cli_demo.processes", return_value={}),
        patch("app.cli_demo._occupied", return_value=False),
        patch("app.cli_demo.start_demo", side_effect=start),
    ):
        assert _command("demo", "--no-open") == 0
    assert starts == 2


def test_demo_socket_ports_tolerates_missing_procfs_files(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import cli_demo

    tcp_sample = (
        "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt"
        "   uid  timeout inode\n"
        "   0: 0100007F:1F40 00000000:0000 0A 00000000:00000000 00:00000000 00000000"
        "  1000        0 99999 2 0 100 0 0 10 0\n"
    )

    original_read_text = Path.read_text

    def fake_read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        if str(self) == "/proc/net/tcp6":
            raise FileNotFoundError(2, "No such file or directory", "/proc/net/tcp6")
        if str(self) == "/proc/net/tcp":
            return tcp_sample
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)
    ports = cli_demo._socket_ports()
    assert ports == {"socket:[99999]": 8000}
