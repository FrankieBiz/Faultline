"""Contrarian fuzzing of the gate CLI and the evidence-bundle export/verification.

This file assumes nothing is safe. It throws hostile bytes at the two surfaces a
deployment decision flows through — ``faultline gate URL`` and the offline
``verify_bundle`` tool — and asserts four resilience properties:

1. Corrupted evidence-bundle checksums fail closed (never ``consistent``, never a
   traceback) for non-hex digests, deeply nested or non-serializable JSON,
   non-string patches, symlinked artifacts, and oversized artifacts.
2. ANSI escape sequences, OSC title/screen-control sequences, C1 controls, and
   carriage returns never reach a terminal, markdown, or CI log, so a hostile
   page cannot rewrite the terminal or forge GitHub workflow commands.
3. Oversized log streams (runaway reproduction trails, breadcrumbs, screens, and
   response bodies) are bounded before they are materialized into output.
4. Unhandled exceptions degrade gracefully: ``gate --json`` still emits exactly
   one JSON verdict, and the verifier still returns a ``(consistent, messages)``
   tuple instead of raising.

No sandbox, browser, or service is launched here; the runner seam is mocked.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from test_crawler import CLEAN_REPORT, FAILURE_REPORT
from test_gate import GATE_KEYS
from test_verify_bundle_tool import exported
from tools.verify_bundle import _artifact_file, _sha256_file, verify_bundle

from app import crawler_service
from app.cli import PLAIN, build_parser
from app.cli_crawl import (
    MAX_BREADCRUMBS,
    MAX_FIELD_CHARS,
    MAX_SCREENS,
    MAX_TRAIL_STEPS,
    _breadcrumb_lines,
    _evidence_lines,
    ci_text,
    describe_signal,
    gate_command,
    gate_error_result,
    gate_result,
    render_event,
    render_gate_agent,
    render_gate_ci,
    render_gate_human,
    render_gate_markdown,
    render_report,
    sanitize_report,
    sanitize_text,
)
from app.proof_bundle import bundle_digest

# --- hostile corpus -----------------------------------------------------------

ESC = "\x1b"
CSI_CLEAR = "\x1b[2J"
CSI_RED = "\x1b[31m"
OSC_TITLE = "\x1b]0;evil title\x07"
OSC_TITLE_ST = "\x1b]0;evil title\x9c"
BEL = "\x07"
CR = "\r"
C1_CSI = "\x9b"
C1_OSC = "\x9d"
GITHUB_INJECT = "\n::error title=owned::pwned\n::set-output name=secret::leak\n"

_TERMINAL_CONTROL = ("\x1b", "\x07", "\x9b", "\x9c", "\x9d", "\r", "\x00", "\x0b", "\x0c")


def _assert_no_terminal_control(text: str) -> None:
    for byte in _TERMINAL_CONTROL:
        assert byte not in text, f"raw control byte leaked into output: {byte!r}"


def _error_report(message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "target_url": "http://127.0.0.1:3000/",
        "breadcrumbs": [],
        "elements_explored": 0,
        "actions_taken": 0,
        "pages_visited": [],
        "error": message,
    }


def _hostile_failure_report() -> dict[str, Any]:
    report = copy.deepcopy(FAILURE_REPORT)
    report["failure"]["response_body"] = OSC_TITLE + '{"detail":"boom"}' + CSI_CLEAR
    report["failure"]["stack"] = "Traceback:\n  at evil.js " + C1_CSI + "31mboom"
    report["failure"]["console_errors"] = [BEL + "console " + CSI_RED + "error"]
    report["breadcrumbs"][1]["label"] = "Evil" + OSC_TITLE_ST + " Label"
    report["breadcrumbs"][1]["selector"] = "button" + CSI_CLEAR + "[x]"
    return report


# --- 1. corrupted evidence-bundle checksums -----------------------------------


def test_verify_bundle_rejects_non_hex_digest(tmp_path: Path) -> None:
    bundle, _ = exported(tmp_path)
    bundle["bundle_digest"] = "not-a-digest"
    consistent, messages = verify_bundle(bundle)
    assert not consistent
    assert any("digest" in message for message in messages)


def test_verify_bundle_fails_closed_on_deeply_nested_json(tmp_path: Path) -> None:
    """json.dumps recursion over a hostile nesting depth must fail closed, not raise."""
    bundle, _ = exported(tmp_path)
    deep: Any = "leaf"
    for _ in range(3000):
        deep = [deep]
    bundle["executions"] = [deep]
    bundle["bundle_digest"] = "0" * 64
    consistent, messages = verify_bundle(bundle)
    assert not consistent
    assert messages


def test_verify_bundle_fails_closed_on_non_serializable_field(tmp_path: Path) -> None:
    bundle, _ = exported(tmp_path)
    bundle["lifecycle"] = {"finalized": True, "state": object()}
    bundle["bundle_digest"] = "0" * 64
    consistent, messages = verify_bundle(bundle)
    assert not consistent
    assert messages


def test_verify_bundle_fails_closed_on_non_string_patch(tmp_path: Path) -> None:
    bundle, _ = exported(tmp_path)
    bundle["patch_diff"] = 12345
    consistent, messages = verify_bundle(bundle)
    assert not consistent
    assert messages


def test_verify_bundle_fails_closed_on_non_object_manifest_entry(tmp_path: Path) -> None:
    """A non-object manifest entry is reported, never an AttributeError traceback."""
    bundle, directory = exported(tmp_path)
    bundle["schema_version"] = "2.0"
    bundle["evidence_manifest"] = ["not-a-dict"]
    bundle["bundle_digest"] = bundle_digest(bundle)
    consistent, messages = verify_bundle(bundle, directory)
    assert not consistent
    assert any("not an object" in message or "Invalid" in message for message in messages)


def test_verify_bundle_does_not_follow_symlinked_artifacts(tmp_path: Path) -> None:
    bundle, directory = exported(tmp_path)
    target_id = bundle["evidence_manifest"][0]["id"]
    real = next(path for path in directory.iterdir() if path.stem == target_id)
    real.unlink()
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside bytes")
    (directory / f"{target_id}.bin").symlink_to(outside)
    consistent, messages = verify_bundle(bundle, directory)
    assert not consistent
    assert any("not found" in message for message in messages)


def test_artifact_file_ignores_symlinks(tmp_path: Path) -> None:
    outside = tmp_path / "target.bin"
    outside.write_bytes(b"data")
    link = tmp_path / "artifact-1.bin"
    link.symlink_to(outside)
    assert _artifact_file(tmp_path, "artifact-1") is None


def test_verify_bundle_caps_oversized_artifact_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An artifact over the cap is refused before it can be materialized in memory."""
    bundle, directory = exported(tmp_path)
    monkeypatch.setattr("tools.verify_bundle.MAX_ARTIFACT_BYTES", 8)
    consistent, messages = verify_bundle(bundle, directory)
    assert not consistent
    assert any("cap" in message for message in messages)


def test_sha256_file_streams_and_matches(tmp_path: Path) -> None:
    content = b"x" * 100_000
    path = tmp_path / "big.bin"
    path.write_bytes(content)
    within_cap, digest = _sha256_file(path)
    assert within_cap
    assert digest == hashlib.sha256(content).hexdigest()


# --- 2. ANSI escape sequences and terminal injection ---------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (OSC_TITLE + "boom" + CSI_CLEAR, "boom"),
        (OSC_TITLE_ST + "boom", "boom"),
        ("a" + BEL + "b", "ab"),
        ("a" + CR + "b", "a b"),
        ("a" + C1_CSI + "b", "ab"),
        ("a" + C1_OSC + "b", "ab"),
        ("\x00a\x0bb\x0cc", "abc"),
        ("🚀 Place order", "🚀 Place order"),
        ("line1\nline2\ttab", "line1\nline2\ttab"),
    ],
)
def test_sanitize_text_strips_control_keeps_text(value: str, expected: str) -> None:
    assert sanitize_text(value) == expected


def test_ci_text_collapses_newlines_and_tabs() -> None:
    assert ci_text("a\nb\tc") == "a b c"
    assert ci_text("a\rb") == "a b"
    _assert_no_terminal_control(ci_text(OSC_TITLE + "x" + GITHUB_INJECT))


def test_sanitize_report_recurses_and_preserves_scalars() -> None:
    report = {
        "nested": [{"label": OSC_TITLE + "x"}, [C1_CSI + "y"]],
        "count": 7,
        "ok": True,
        "nothing": None,
    }
    cleaned = sanitize_report(report)
    assert cleaned == {
        "nested": [{"label": "x"}, ["y"]],
        "count": 7,
        "ok": True,
        "nothing": None,
    }


@pytest.mark.parametrize(
    "field",
    ["message", "endpoint", "method"],
)
def test_describe_signal_sanitizes_untrusted_fields(field: str) -> None:
    signal = {"kind": "http_error", "status": 500, "method": "POST", "endpoint": "/x"}
    signal[field] = OSC_TITLE + "evil" + CSI_CLEAR
    _assert_no_terminal_control(describe_signal(signal))


def test_render_event_sanitizes_url_and_label() -> None:
    event = {"type": "navigate", "url": "http://x/" + OSC_TITLE}
    _assert_no_terminal_control(render_event(event, PLAIN))
    event = {"type": "action", "step": 1, "action": "click", "label": C1_CSI + "Evil", "ok": True}
    _assert_no_terminal_control(render_event(event, PLAIN))


def test_evidence_and_breadcrumb_lines_sanitize() -> None:
    failure = {
        "kind": "http_error",
        "method": "POST",
        "url": OSC_TITLE + "http://x/",
        "response_body": CSI_CLEAR + "body",
        "stack": "trace\n  at x " + C1_OSC,
        "console_errors": [BEL + "err"],
    }
    for line in _evidence_lines(failure, PLAIN):
        _assert_no_terminal_control(line)
    report = {"breadcrumbs": [{"step": 1, "action": "navigate", "url": OSC_TITLE + "http://x/"}]}
    for line in _breadcrumb_lines(report, PLAIN):
        _assert_no_terminal_control(line)


def test_render_report_error_line_is_sanitized() -> None:
    report = _error_report(OSC_TITLE + "boom" + CSI_CLEAR)
    for line in render_report(report, PLAIN):
        _assert_no_terminal_control(line)


@pytest.mark.parametrize(
    "renderer",
    [
        lambda r: json.dumps(r, ensure_ascii=True),
        render_gate_markdown,
        render_gate_agent,
        lambda r: render_gate_ci(r, github=True),
        lambda r: "\n".join(render_gate_human(r, None, PLAIN)),
    ],
    ids=["json", "markdown", "agent", "ci", "human"],
)
def test_every_gate_renderer_is_control_free(renderer: Any) -> None:
    result = gate_result(_hostile_failure_report(), "http://127.0.0.1:3000")
    _assert_no_terminal_control(renderer(result))


def test_gate_json_stdout_is_control_free(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    report = _hostile_failure_report()
    monkeypatch.setattr(crawler_service, "run_crawl", lambda url, **kwargs: report)
    args = build_parser().parse_args(["gate", "http://127.0.0.1:3000", "--json"])
    assert gate_command(args, PLAIN) == 1
    out = capsys.readouterr().out
    _assert_no_terminal_control(out)
    body = json.loads(out)
    # The hostile bytes are gone from the recorded evidence, not merely escaped.
    assert body["failure"]["response_body"] == '{"detail":"boom"}'


def test_ci_annotation_cannot_be_forged_by_newline_injection() -> None:
    result = gate_result(_error_report(GITHUB_INJECT), "http://x")
    out = render_gate_ci(result, github=True)
    _assert_no_terminal_control(out)
    commands = [line for line in out.split("\n") if line.startswith("::")]
    assert len(commands) == 1
    assert commands[0].startswith("::error title=FaultLine gate FAILED::")
    assert not any(line.startswith("::error title=owned") for line in out.split("\n"))
    assert not any(line.startswith("::set-output") for line in out.split("\n"))


# --- 3. oversized log stream memory limits ------------------------------------


def test_gate_result_bounds_runaway_reproduction_trail() -> None:
    report = copy.deepcopy(FAILURE_REPORT)
    report["reproduction_trail"] = [
        f"step {index} " + "x" * (MAX_FIELD_CHARS + 100) for index in range(5000)
    ]
    result = gate_result(report, "http://x")
    assert len(result["reproduction_trail"]) <= MAX_TRAIL_STEPS
    assert all(len(step) <= MAX_FIELD_CHARS for step in result["reproduction_trail"])


def test_gate_result_bounds_runaway_screens() -> None:
    report = copy.deepcopy(CLEAN_REPORT)
    report["stop_reason"] = "exhausted"
    report["screens_visited"] = [
        {"url": f"http://x/{index}", "path": f"/{index}"} for index in range(5000)
    ]
    result = gate_result(report, "http://x")
    assert len(result["screens_visited"]) <= MAX_SCREENS


def test_breadcrumb_lines_bound_runaway_breadcrumbs() -> None:
    report = {
        "breadcrumbs": [
            {"step": index, "action": "navigate", "url": f"http://x/{index}"}
            for index in range(5000)
        ]
    }
    assert len(_breadcrumb_lines(report, PLAIN)) <= MAX_BREADCRUMBS


def test_gate_result_clips_runaway_error_message() -> None:
    report = _error_report("A" * (MAX_FIELD_CHARS * 10))
    result = gate_result(report, "http://x")
    assert len(result["summary"]) <= MAX_FIELD_CHARS + 60
    assert len(result["error"]["message"]) <= MAX_FIELD_CHARS


def test_gate_result_clips_huge_response_body_and_stack() -> None:
    report = copy.deepcopy(FAILURE_REPORT)
    huge_body = "R" * 1_000_000
    huge_stack = ("S" * 1_000 + "\n") * 10_000
    report["failure"]["response_body"] = huge_body
    report["failure"]["stack"] = huge_stack
    result = gate_result(report, "http://x")
    prompt = result["agent_remediation_prompt"]
    assert huge_body not in prompt
    assert "S" * 1_000_000 not in prompt
    assert len(prompt) < 100_000


# --- 4. unhandled exception JSON schema degradation ---------------------------


def test_gate_survives_unexpected_exception_with_valid_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(url: str, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("surprise")

    monkeypatch.setattr(crawler_service, "run_crawl", boom)
    args = build_parser().parse_args(["gate", "http://127.0.0.1:3000", "--json"])
    assert gate_command(args, PLAIN) == 1
    body = json.loads(capsys.readouterr().out)
    assert set(body) == GATE_KEYS
    assert body["gate_status"] == "FAILED"
    assert body["verdict"] == "DEPLOYMENT_BLOCKED"
    assert body["exit_code"] == 1
    assert body["error"] == {"code": "unexpected_error", "message": "surprise"}


def test_gate_survives_malformed_report_with_valid_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(crawler_service, "run_crawl", lambda url, **kwargs: "not-a-dict")
    args = build_parser().parse_args(["gate", "http://127.0.0.1:3000", "--json"])
    assert gate_command(args, PLAIN) == 1
    body = json.loads(capsys.readouterr().out)
    assert set(body) == GATE_KEYS
    assert body["error"]["code"] == "unexpected_error"
    assert body["failure"] is None


def test_unexpected_error_prompt_is_sanitized() -> None:
    result = gate_error_result("unexpected_error", OSC_TITLE + "boom" + CSI_CLEAR, "http://x")
    assert set(result) == GATE_KEYS
    assert result["error"]["message"] == "boom"
    _assert_no_terminal_control(result["summary"])
    _assert_no_terminal_control(result["agent_remediation_prompt"])
    _assert_no_terminal_control(result["target_url"])


def test_gate_human_format_survives_unexpected_exception(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(url: str, **kwargs: Any) -> dict[str, Any]:
        raise ValueError("x")

    monkeypatch.setattr(crawler_service, "run_crawl", boom)
    args = build_parser().parse_args(["gate", "http://127.0.0.1:3000", "--plain"])
    assert gate_command(args, PLAIN) == 1
    _assert_no_terminal_control(capsys.readouterr().out)
