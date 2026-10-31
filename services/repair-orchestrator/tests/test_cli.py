"""Unit tests for the FaultLine Developer Platform CLI."""

from __future__ import annotations

import argparse
import http.client
import queue
import signal
import urllib.error
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.cli import (
    OUTCOME_EXIT_CODES,
    HudState,
    _pump_events,
    apply_patch_for_job,
    build_parser,
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
