"""``faultline gate URL``: the pre-deployment verdict for agents and CI."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from test_crawler import CLEAN_REPORT, FAILURE_REPORT, broken_shop, needs_node, two_action_shop

from app import crawler_service
from app.cli import COLOR, PLAIN, build_parser
from app.cli_crawl import gate_command, gate_result, remediation_prompt, render_gate_markdown
from app.crawler_service import CrawlError

__all__ = ["broken_shop", "two_action_shop"]  # re-exported pytest fixtures

# Ordinary crawl remains clean when its budget is reached; a gate needs completion.
COMPLETED_REPORT = {**CLEAN_REPORT, "stop_reason": "exhausted"}

SERVICE_ROOT = Path(__file__).resolve().parent.parent
GATE_KEYS = {
    "gate_status",
    "verdict",
    "exit_code",
    "target_url",
    "summary",
    "elements_explored",
    "stop_reason",
    "actions_taken",
    "screens_visited",
    "failure",
    "reproduction_trail",
    "agent_remediation_prompt",
    "error",
}
EVENTS: list[dict[str, Any]] = [
    {"type": "launch"},
    {"type": "navigate", "step": 1, "url": "http://127.0.0.1:3000/"},
]


def _args(*argv: str) -> Any:
    return build_parser().parse_args(["gate", *argv])


def _fake_crawl(
    monkeypatch: pytest.MonkeyPatch, report: dict[str, Any], seen: dict[str, Any] | None = None
) -> None:
    def fake(url: str, **kwargs: Any) -> dict[str, Any]:
        if seen is not None:
            seen.update(url=url, **kwargs)
        if kwargs["on_event"] is not None:
            for event in EVENTS:
                kwargs["on_event"](event)
        return report

    monkeypatch.setattr(crawler_service, "run_crawl", fake)


def _raise(monkeypatch: pytest.MonkeyPatch, code: str, message: str = "it broke") -> None:
    def fail(url: str, **_: Any) -> dict[str, Any]:
        raise CrawlError(code, message)

    monkeypatch.setattr(crawler_service, "run_crawl", fail)


# --- parser --------------------------------------------------------------------


def test_gate_parses_with_ci_friendly_defaults() -> None:
    args = _args("http://127.0.0.1:3000")
    assert (args.max_actions, args.timeout, args.json, args.markdown, args.format) == (
        25,
        90,
        False,
        False,
        None,
    )
    assert _args("x", "--format", "agent").format == "agent"
    assert _args("x", "--format", "ci", "--max-actions", "5").max_actions == 5


@pytest.mark.parametrize(
    "argv",
    [
        ["http://x", "--json", "--markdown"],
        ["http://x", "--json", "--format", "agent"],
        ["http://x", "--markdown", "--format", "ci"],
        ["http://x", "--format", "yaml"],
        ["http://x", "--max-actions", "0"],
        ["http://x", "--timeout", "301"],
        [],
    ],
)
def test_gate_rejects_invalid_arguments_with_exit_2(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        _args(*argv)
    assert exited.value.code == 2


# --- exit codes and the JSON contract -------------------------------------------


def test_clean_crawl_passes_with_exit_0(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, Any] = {}
    _fake_crawl(monkeypatch, COMPLETED_REPORT, seen)
    assert gate_command(_args("127.0.0.1:3000", "--json"), PLAIN) == 0
    body = json.loads(capsys.readouterr().out)
    assert set(body) == GATE_KEYS
    assert body["gate_status"] == "PASSED"
    assert body["verdict"] == "SAFE_TO_DEPLOY"
    assert body["exit_code"] == 0
    assert body["target_url"] == "http://127.0.0.1:3000/"
    assert body["summary"] == (
        "No defects found in explored flows: explored 12 elements across 1 screen with 15 actions. "
        "This does not establish business completeness."
    )
    assert body["elements_explored"] == 12
    assert body["stop_reason"] == "exhausted"
    assert body["actions_taken"] == 15
    assert body["screens_visited"] == [{"url": "http://127.0.0.1:3000/", "path": "/"}]
    assert body["failure"] is None
    assert body["agent_remediation_prompt"] is None
    assert body["error"] is None
    # The scheme is added, and --json keeps stdout to exactly one document.
    assert seen["url"] == "http://127.0.0.1:3000"
    assert seen["on_event"] is None
    assert (seen["max_actions"], seen["timeout_ms"]) == (25, 90_000)


def test_defect_blocks_deployment_with_exit_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_crawl(monkeypatch, FAILURE_REPORT)
    assert gate_command(_args("http://127.0.0.1:3000", "--json"), PLAIN) == 1
    body = json.loads(capsys.readouterr().out)
    assert set(body) == GATE_KEYS
    assert (body["gate_status"], body["verdict"], body["exit_code"]) == (
        "FAILED",
        "DEPLOYMENT_BLOCKED",
        1,
    )
    assert body["summary"] == (
        "Defect intercepted: HTTP 500 on POST /api/checkout after 3 actions across 2 screens."
    )
    assert body["elements_explored"] == 20
    assert [screen["path"] for screen in body["screens_visited"]] == ["/", "/checkout"]
    assert body["failure"] == FAILURE_REPORT["failure"]
    assert body["reproduction_trail"] == FAILURE_REPORT["reproduction_trail"]
    assert body["error"] is None
    prompt = body["agent_remediation_prompt"]
    assert prompt.startswith(
        "FaultLine caught an unhandled HTTP 500 error on POST /api/checkout. "
        'Triggered by clicking "Place order" (button:has-text("Place order")) on /checkout.'
    )
    assert 'Server response: {"detail":"TypeError"}' in prompt
    assert "  1. Open http://127.0.0.1:3000/" in prompt
    assert prompt.endswith(
        "Fix the server-side exception handling for POST /api/checkout so it no longer "
        "returns HTTP 500 before deploying, then re-run "
        "`faultline gate http://127.0.0.1:3000/ --json` and continue only when it exits 0."
    )


@pytest.mark.parametrize(
    "code,exit_code",
    [("invalid_url", 2), ("invalid_request", 2), ("runner_unavailable", 1), ("runner_failed", 1)],
)
def test_crawl_errors_block_with_exit_2_for_input_and_1_otherwise(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    code: str,
    exit_code: int,
) -> None:
    _raise(monkeypatch, code)
    assert gate_command(_args("http://x", "--json"), PLAIN) == exit_code
    body = json.loads(capsys.readouterr().out)
    assert set(body) == GATE_KEYS
    assert (body["gate_status"], body["verdict"], body["exit_code"]) == (
        "FAILED",
        "DEPLOYMENT_BLOCKED",
        exit_code,
    )
    assert body["error"] == {"code": code, "message": "it broke"}
    assert body["failure"] is None
    assert body["stop_reason"] is None
    assert body["actions_taken"] == 0
    assert body["summary"] == "Gate could not run: it broke"
    assert "it broke" in body["agent_remediation_prompt"]


def test_bad_url_exits_2_through_the_real_validator(capsys: pytest.CaptureFixture[str]) -> None:
    assert gate_command(_args("ftp://example.com", "--json"), PLAIN) == 2
    body = json.loads(capsys.readouterr().out)
    assert body["error"]["code"] == "invalid_url"
    assert body["target_url"] == "ftp://example.com"


@pytest.mark.parametrize("stop_reason", ["max_actions", "timeout", None, "unknown", 42])
def test_incomplete_clean_crawl_blocks_without_claiming_a_defect(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    stop_reason: Any,
) -> None:
    report = {**CLEAN_REPORT, "stop_reason": stop_reason}
    if stop_reason is None:
        del report["stop_reason"]
    _fake_crawl(monkeypatch, report)
    assert gate_command(_args("http://127.0.0.1:3000", "--json"), PLAIN) == 1
    body = json.loads(capsys.readouterr().out)
    assert set(body) == GATE_KEYS
    assert (body["gate_status"], body["verdict"]) == ("FAILED", "DEPLOYMENT_BLOCKED")
    assert body["error"]["code"] == "incomplete_crawl"
    assert body["failure"] is None
    assert "inconclusive" in body["summary"].lower()
    assert body["stop_reason"] == (stop_reason if isinstance(stop_reason, str) else None)
    assert body["actions_taken"] == 15
    assert "--max-actions" in body["agent_remediation_prompt"]
    assert "--timeout" in body["agent_remediation_prompt"]


def test_only_raw_clean_status_and_exhausted_can_pass() -> None:
    result = gate_result({**COMPLETED_REPORT, "status": "unknown"}, "http://x")
    assert result["exit_code"] == 1
    assert result["verdict"] == "DEPLOYMENT_BLOCKED"


def test_runner_error_report_blocks_with_exit_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    report = {
        "status": "error",
        "target_url": "http://127.0.0.1:3000/",
        "breadcrumbs": [],
        "elements_explored": 0,
        "actions_taken": 0,
        "pages_visited": [],
        "error": "Could not load http://127.0.0.1:3000/: net::ERR_CONNECTION_REFUSED",
    }
    _fake_crawl(monkeypatch, report)
    assert gate_command(_args("http://127.0.0.1:3000", "--json"), PLAIN) == 1
    body = json.loads(capsys.readouterr().out)
    assert body["verdict"] == "DEPLOYMENT_BLOCKED"
    assert body["error"] == {"code": "crawl_error", "message": report["error"]}
    assert "ERR_CONNECTION_REFUSED" in body["summary"]
    assert "Do not deploy until the gate exits 0." in body["agent_remediation_prompt"]


def test_main_exit_codes_end_to_end() -> None:
    """The real entry point exits 2 on bad input, never a traceback."""

    def run(*argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "app.cli", "gate", *argv],
            cwd=SERVICE_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )

    bad_url = run("file:///etc/passwd", "--json")
    assert bad_url.returncode == 2
    assert json.loads(bad_url.stdout)["verdict"] == "DEPLOYMENT_BLOCKED"
    bad_flags = run("http://x", "--json", "--markdown")
    assert bad_flags.returncode == 2
    assert "not allowed with argument" in bad_flags.stderr


# --- remediation prompts ---------------------------------------------------------


def _failure(**overrides: Any) -> dict[str, Any]:
    report = copy.deepcopy(FAILURE_REPORT)
    report["failure"] = {**report["failure"], **overrides}
    return report


def test_client_errors_ask_for_a_request_or_route_fix() -> None:
    report = _failure(status=422, message="422 Unprocessable Entity")
    prompt = remediation_prompt(report, report["failure"], "http://x")
    assert prompt.startswith("FaultLine caught an HTTP 422 error on POST /api/checkout.")
    assert "Fix the request the page sends to POST /api/checkout" in prompt


def test_prompt_keeps_non_ascii_control_labels_readable() -> None:
    report = _failure()
    step = report["failure"]["step"]
    for crumb in report["breadcrumbs"]:
        if crumb["step"] == step:
            crumb["label"] = "🚀 Place order"
    prompt = remediation_prompt(report, report["failure"], "http://x")
    assert 'Triggered by clicking "🚀 Place order"' in prompt
    assert "\\u" not in prompt


def test_page_errors_point_at_client_code_and_the_stack() -> None:
    report = _failure(
        kind="page_error",
        message="TypeError: cart.items is undefined",
        stack="TypeError: cart.items is undefined\n    at total (cart.js:4:9)",
        response_body=None,
    )
    prompt = remediation_prompt(report, report["failure"], "http://x")
    assert prompt.startswith(
        "FaultLine caught an uncaught JavaScript exception: TypeError: cart.items is undefined."
    )
    assert "Stack: TypeError: cart.items is undefined |     at total (cart.js:4:9)" in prompt
    assert "Fix the client-side code that throws this exception before deploying" in prompt


def test_failed_requests_ask_the_route_to_answer() -> None:
    report = _failure(kind="request_failed", message="net::ERR_EMPTY_RESPONSE")
    prompt = remediation_prompt(report, report["failure"], "http://x")
    assert "a failed network request: POST /api/checkout failed: net::ERR_EMPTY_RESPONSE" in prompt
    assert "Make POST /api/checkout answer instead of dropping the connection" in prompt


def test_older_reports_without_a_trail_fall_back_to_breadcrumbs() -> None:
    report = copy.deepcopy(FAILURE_REPORT)
    del report["reproduction_trail"]
    result = gate_result(report, "http://127.0.0.1:3000")
    assert result["reproduction_trail"][0] == "1. navigate http://127.0.0.1:3000/"
    assert result["reproduction_trail"][-1].endswith("<- fails here")
    assert "Reproduce:\n  1. navigate" in result["agent_remediation_prompt"]


# --- renderers -------------------------------------------------------------------


def test_markdown_reports_a_blocked_deploy_for_github(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_crawl(monkeypatch, FAILURE_REPORT)
    assert gate_command(_args("http://127.0.0.1:3000", "--markdown"), PLAIN) == 1
    captured = capsys.readouterr()
    out = captured.out
    assert out.startswith("## 🛑 FaultLine Pre-Flight Gate: FAILED\n")
    assert (
        "![FaultLine gate: DEPLOYMENT_BLOCKED]"
        "(https://img.shields.io/badge/FaultLine_gate-DEPLOYMENT__BLOCKED-red)"
    ) in out
    assert "| http://127.0.0.1:3000/ | **DEPLOYMENT_BLOCKED** | 20 | `/`, `/checkout` |" in out
    assert "### Defect\n\n```text\nHTTP 500 on POST /api/checkout\n" in out
    assert "### Reproduction trail\n\n```text\n1. Open http://127.0.0.1:3000/\n" in out
    assert "### Agent fix prompt" in out
    assert "<sub>Exit code 1 · `faultline gate`</sub>" in out
    # Progress goes to the job log so the step summary holds only markdown.
    assert "[Playwright]" not in out
    assert "[Playwright] Launching Chromium..." in captured.err


def test_markdown_reports_a_safe_deploy(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_crawl(monkeypatch, COMPLETED_REPORT)
    assert gate_command(_args("http://127.0.0.1:3000", "--markdown"), PLAIN) == 0
    out = capsys.readouterr().out
    assert out.startswith("## ✅ FaultLine Pre-Flight Gate: PASSED\n")
    assert "FaultLine_gate-SAFE__TO__DEPLOY-brightgreen" in out
    assert "### Defect" not in out
    assert "### Agent fix prompt" not in out


def test_markdown_fences_survive_backticks_and_pipes_in_evidence() -> None:
    report = _failure(response_body="```\nboom\n````")
    result = gate_result({**report, "target_url": "http://x/?a|b"}, "http://x")
    markdown = render_gate_markdown(result)
    assert "`````text\nHTTP 500 on POST /api/checkout\n" in markdown
    assert "| http://x/?a\\|b |" in markdown


def test_agent_format_is_plain_labelled_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_crawl(monkeypatch, FAILURE_REPORT)
    assert gate_command(_args("http://127.0.0.1:3000", "--format", "agent"), COLOR) == 1
    out = capsys.readouterr().out
    assert "\033[" not in out
    assert "[Playwright]" not in out
    lines = out.splitlines()
    assert lines[0] == "FAULTLINE PRE-FLIGHT GATE: FAILED (DEPLOYMENT_BLOCKED, exit 1)"
    assert lines[3] == "Explored: 20 elements across 2 screens (/, /checkout)"
    assert "Defect: HTTP 500 on POST /api/checkout" in lines
    assert "Required action:" in lines
    assert lines[lines.index("Required action:") + 1].startswith("FaultLine caught an unhandled")
    assert out.count("1. Open http://127.0.0.1:3000/") == 1


def test_agent_format_says_proceed_when_clean(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_crawl(monkeypatch, COMPLETED_REPORT)
    assert gate_command(_args("http://127.0.0.1:3000", "--format", "agent"), PLAIN) == 0
    out = capsys.readouterr().out
    assert out.startswith("FAULTLINE PRE-FLIGHT GATE: PASSED (SAFE_TO_DEPLOY, exit 0)\n")
    assert out.rstrip().endswith("Required action: none. The explored flows are clean; proceed.")


def test_ci_format_annotates_github_actions(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_crawl(monkeypatch, FAILURE_REPORT)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert gate_command(_args("http://127.0.0.1:3000", "--format", "ci"), PLAIN) == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines[:2] == [
        "[Playwright] Launching Chromium...",
        "[Playwright] Navigating to http://127.0.0.1:3000/...",
    ]
    assert "faultline gate: FAILED (DEPLOYMENT_BLOCKED)" in lines
    assert "defect:   HTTP 500 on POST /api/checkout" in lines
    assert lines[-1] == (
        "::error title=FaultLine gate FAILED::Defect intercepted: HTTP 500 on "
        "POST /api/checkout after 3 actions across 2 screens."
    )

    monkeypatch.delenv("GITHUB_ACTIONS")
    _fake_crawl(monkeypatch, COMPLETED_REPORT)
    assert gate_command(_args("http://127.0.0.1:3000", "--format", "ci"), PLAIN) == 0
    out = capsys.readouterr().out
    assert "faultline gate: PASSED (SAFE_TO_DEPLOY)" in out
    assert "::" not in out


def test_human_output_streams_progress_then_the_verdict(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_crawl(monkeypatch, FAILURE_REPORT)
    assert gate_command(_args("http://127.0.0.1:3000", "--plain"), PLAIN) == 1
    out = capsys.readouterr().out
    assert out.startswith("[Playwright] Launching Chromium...\n")
    assert "FaultLine Pre-Flight Gate  🛑 FAILED · DEPLOYMENT_BLOCKED" in out
    assert "Reproduction journey" in out
    assert "Agent fix prompt" in out


# --- real Chromium ---------------------------------------------------------------


@needs_node
@pytest.mark.skipif(
    not crawler_service.RUNNER_CLI.is_file(), reason="browser runner is not built (make runner)"
)
def test_real_gate_blocks_budget_before_the_failing_submit(
    two_action_shop: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        gate_command(
            _args(two_action_shop, "--json", "--max-actions", "1", "--timeout", "30"), PLAIN
        )
        == 1
    )
    incomplete = json.loads(capsys.readouterr().out)
    assert incomplete["verdict"] == "DEPLOYMENT_BLOCKED"
    assert incomplete["stop_reason"] == "max_actions"
    assert incomplete["actions_taken"] == 1
    assert incomplete["failure"] is None
    assert incomplete["error"]["code"] == "incomplete_crawl"

    assert (
        gate_command(
            _args(two_action_shop, "--json", "--max-actions", "5", "--timeout", "30"), PLAIN
        )
        == 1
    )
    failure = json.loads(capsys.readouterr().out)
    assert failure["failure"]["status"] == 500
    assert failure["failure"]["endpoint"] == "/api/orders"
    assert failure["error"] is None


@needs_node
@pytest.mark.skipif(
    not crawler_service.RUNNER_CLI.is_file(), reason="browser runner is not built (make runner)"
)
def test_real_gate_blocks_a_500_in_chromium(
    broken_shop: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert gate_command(_args(broken_shop, "--json", "--timeout", "30"), PLAIN) == 1
    body = json.loads(capsys.readouterr().out)
    assert body["verdict"] == "DEPLOYMENT_BLOCKED"
    assert body["failure"]["endpoint"] == "/api/orders"
    assert body["agent_remediation_prompt"].startswith(
        "FaultLine caught an unhandled HTTP 500 error on POST /api/orders. "
        'Triggered by clicking "Place order"'
    )
