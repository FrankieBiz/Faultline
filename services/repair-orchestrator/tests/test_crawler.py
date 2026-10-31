"""Autonomous crawler: runner subprocess contract, POST /api/crawl, and the crawl HUD."""

from __future__ import annotations

import json
import shutil
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from conftest import Harness
from fastapi.testclient import TestClient

from app import crawler_service
from app.api import InspectorTranslator
from app.cli import COLOR, PLAIN, build_parser
from app.cli_crawl import crawl_command, render_event, render_report
from app.crawler_service import CrawlError, run_crawl, validate_url
from app.main import Settings, create_app

TOKEN = "test-controller-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

FAILURE_REPORT: dict[str, Any] = {
    "status": "failure",
    "target_url": "http://127.0.0.1:3000/",
    "breadcrumbs": [
        {"step": 1, "action": "navigate", "url": "http://127.0.0.1:3000/"},
        {
            "step": 2,
            "action": "click",
            "url": "http://127.0.0.1:3000/",
            "selector": 'a:has-text("Trail Mug") >> nth=0',
            "label": "Trail Mug",
        },
        {
            "step": 3,
            "action": "fill",
            "url": "http://127.0.0.1:3000/checkout",
            "selector": "#email",
            "label": "Email",
            "value": "test@example.com",
        },
        {
            "step": 4,
            "action": "click",
            "url": "http://127.0.0.1:3000/checkout",
            "selector": 'button:has-text("Place order")',
            "label": "Place order",
        },
    ],
    "elements_explored": 20,
    "actions_taken": 3,
    "pages_visited": ["http://127.0.0.1:3000/", "http://127.0.0.1:3000/checkout"],
    "duration_ms": 2100,
    "failure": {
        "kind": "http_error",
        "message": "500 Internal Server Error",
        "method": "POST",
        "url": "http://127.0.0.1:3000/api/checkout",
        "endpoint": "/api/checkout",
        "status": 500,
        "response_body": '{"detail":"TypeError"}',
        "step": 4,
        "console_errors": ["Failed to load resource: 500"],
        "related": [],
    },
}
CLEAN_REPORT: dict[str, Any] = {
    "status": "clean",
    "target_url": "http://127.0.0.1:3000/",
    "breadcrumbs": [{"step": 1, "action": "navigate", "url": "http://127.0.0.1:3000/"}],
    "elements_explored": 12,
    "actions_taken": 15,
    "pages_visited": ["http://127.0.0.1:3000/"],
    "duration_ms": 9000,
    "stop_reason": "max_actions",
}

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")


def fake_runner(tmp_path: Path, script: str) -> Path:
    """A stand-in for dist/cli.js; its parent's parent is the runner's cwd."""
    runner = tmp_path / "runner" / "dist" / "cli.js"
    runner.parent.mkdir(parents=True)
    runner.write_text(script, encoding="utf-8")
    return runner


# --- crawler_service -------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    ["", "127.0.0.1:3000", "file:///etc/passwd", "javascript:alert(1)", "http://", "x" * 3000],
)
def test_validate_url_rejects_non_http_targets(url: str) -> None:
    with pytest.raises(CrawlError) as error:
        validate_url(url)
    assert error.value.code == "invalid_url"


def test_validate_url_accepts_http_and_https() -> None:
    assert validate_url(" http://127.0.0.1:3000 ") == "http://127.0.0.1:3000"
    assert validate_url("https://shop.example.com/a?b=1") == "https://shop.example.com/a?b=1"


@pytest.mark.parametrize(
    "max_actions,timeout_ms", [(0, 60_000), (101, 60_000), (15, 999), (15, 10**6)]
)
def test_run_crawl_rejects_out_of_range_limits(max_actions: int, timeout_ms: int) -> None:
    with pytest.raises(CrawlError) as error:
        run_crawl("http://127.0.0.1:3000", max_actions=max_actions, timeout_ms=timeout_ms)
    assert error.value.code == "invalid_request"


def test_run_crawl_reports_a_missing_runner(tmp_path: Path) -> None:
    with pytest.raises(CrawlError) as error:
        run_crawl("http://127.0.0.1:3000", runner=tmp_path / "missing.js")
    assert error.value.code == "runner_unavailable"
    assert "npm --prefix tools/browser-runner run build" in str(error.value)


@needs_node
def test_run_crawl_streams_events_and_returns_the_report(tmp_path: Path) -> None:
    report = json.dumps({"type": "report", "report": FAILURE_REPORT})
    runner = fake_runner(
        tmp_path,
        f"""
        const lines = [
          JSON.stringify({{type: "launch"}}),
          "not json",
          JSON.stringify([1, 2]),
          JSON.stringify({{type: "argv", argv: process.argv.slice(2), cwd: process.cwd()}}),
          {json.dumps(report)},
        ];
        process.stdout.write(lines.join("\\n") + "\\n");
        process.exitCode = 1;
        """,
    )
    events: list[dict[str, Any]] = []
    result = run_crawl(
        "http://127.0.0.1:3000",
        max_actions=7,
        timeout_ms=5000,
        runner=runner,
        on_event=events.append,
    )
    assert result == FAILURE_REPORT
    assert events[0] == {"type": "launch"}
    assert events[1]["argv"] == [
        "--crawl",
        "http://127.0.0.1:3000",
        "--ndjson",
        "--max-actions",
        "7",
        "--timeout-ms",
        "5000",
    ]
    assert Path(events[1]["cwd"]) == runner.parent.parent
    assert len(events) == 2


@needs_node
def test_run_crawl_raises_when_the_runner_exits_without_a_report(tmp_path: Path) -> None:
    runner = fake_runner(
        tmp_path, 'process.stderr.write("chromium exploded\\n"); process.exitCode = 2;'
    )
    with pytest.raises(CrawlError) as error:
        run_crawl("http://127.0.0.1:3000", runner=runner)
    assert error.value.code == "runner_failed"
    assert "code 2" in str(error.value)
    assert "chromium exploded" in str(error.value)


class _BrokenShop(BaseHTTPRequestHandler):
    """A page whose only button posts to an endpoint that fails with HTTP 500."""

    def log_message(self, *args: object) -> None:
        return

    def _send(self, status: int, content_type: str, body: str) -> None:
        payload = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path != "/":
            self._send(404, "text/plain", "not found")
            return
        self._send(
            200,
            "text/html",
            "<main><button onclick=\"fetch('/api/orders',{method:'POST'})\">Place order</button>"
            "</main>",
        )

    def do_POST(self) -> None:
        self._send(500, "application/json", '{"detail":"orders table is locked"}')


@pytest.fixture
def broken_shop() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _BrokenShop)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/"
    finally:
        server.shutdown()
        server.server_close()


@needs_node
@pytest.mark.skipif(
    not crawler_service.RUNNER_CLI.is_file(), reason="browser runner is not built (make runner)"
)
def test_real_runner_finds_the_500_in_chromium(broken_shop: str) -> None:
    events: list[dict[str, Any]] = []
    report = run_crawl(broken_shop, timeout_ms=30_000, on_event=events.append)
    assert report["status"] == "failure", report
    assert report["failure"]["kind"] == "http_error"
    assert report["failure"]["status"] == 500
    assert report["failure"]["method"] == "POST"
    assert report["failure"]["endpoint"] == "/api/orders"
    assert report["failure"]["response_body"] == '{"detail":"orders table is locked"}'
    assert [crumb["action"] for crumb in report["breadcrumbs"]] == ["navigate", "click"]
    assert report["breadcrumbs"][1]["selector"] == 'button:has-text("Place order")'
    assert [event["type"] for event in events][:3] == ["launch", "navigate", "discovered"]


# --- POST /api/crawl ---------------------------------------------------------


@pytest.fixture
def client(harness: Harness) -> Iterator[TestClient]:
    app = create_app(
        Settings(data_dir=harness.root, control_token=TOKEN),
        database=harness.database,
        adapter=harness.adapter,
        runtime=harness.runtime,
        snapshots=harness.snapshots,
    )
    with TestClient(app) as value:
        yield value


def test_crawl_endpoint_requires_the_control_token(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[str] = []
    monkeypatch.setattr(crawler_service, "run_crawl", lambda url, **_: called.append(url))
    response = client.post("/api/crawl", json={"url": "http://127.0.0.1:3000"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert called == []


def test_crawl_endpoint_returns_the_report(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake(url: str, **kwargs: Any) -> dict[str, Any]:
        calls.append((url, kwargs))
        return FAILURE_REPORT

    monkeypatch.setattr(crawler_service, "run_crawl", fake)
    response = client.post("/api/crawl", json={"url": "http://127.0.0.1:3000"}, headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == FAILURE_REPORT
    assert calls == [("http://127.0.0.1:3000", {"max_actions": 15})]

    response = client.post(
        "/api/crawl", json={"url": "http://127.0.0.1:3000", "max_actions": 40}, headers=HEADERS
    )
    assert response.status_code == 200
    assert calls[-1] == ("http://127.0.0.1:3000", {"max_actions": 40})


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"url": "http://x", "max_actions": 0},
        {"url": "http://x", "max_actions": 101},
        {"url": "http://x", "unexpected": True},
    ],
)
def test_crawl_endpoint_validates_the_body(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, body: dict[str, Any]
) -> None:
    monkeypatch.setattr(crawler_service, "run_crawl", lambda url, **_: pytest.fail("ran"))
    response = client.post("/api/crawl", json=body, headers=HEADERS)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


@pytest.mark.parametrize(
    "code,status", [("invalid_url", 422), ("runner_unavailable", 503), ("runner_failed", 502)]
)
def test_crawl_endpoint_maps_crawl_errors(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, code: str, status: int
) -> None:
    def fail(url: str, **_: Any) -> dict[str, Any]:
        raise CrawlError(code, "detail that stays server-side")

    monkeypatch.setattr(crawler_service, "run_crawl", fail)
    response = client.post("/api/crawl", json={"url": "ftp://x"}, headers=HEADERS)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_crawl_endpoint_allows_one_crawl_at_a_time(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    started, release = threading.Event(), threading.Event()

    def slow(url: str, **_: Any) -> dict[str, Any]:
        started.set()
        assert release.wait(10)
        return CLEAN_REPORT

    monkeypatch.setattr(crawler_service, "run_crawl", slow)
    first: dict[str, Any] = {}
    thread = threading.Thread(
        target=lambda: first.update(
            response=client.post("/api/crawl", json={"url": "http://x"}, headers=HEADERS)
        )
    )
    thread.start()
    try:
        assert started.wait(10)
        busy = client.post("/api/crawl", json={"url": "http://x"}, headers=HEADERS)
        assert busy.status_code == 409
        assert busy.json()["error"]["code"] == "crawl_in_progress"
    finally:
        release.set()
        thread.join(10)
    assert first["response"].status_code == 200
    again = client.post("/api/crawl", json={"url": "http://x"}, headers=HEADERS)
    assert again.status_code == 200


# --- faultline crawl / break -------------------------------------------------


def test_break_is_an_alias_for_crawl_with_defaults() -> None:
    parser = build_parser()
    crawl = parser.parse_args(["crawl", "http://127.0.0.1:3000"])
    alias = parser.parse_args(["break", "http://127.0.0.1:3000", "--max-actions", "30"])
    assert crawl.func is alias.func
    assert (crawl.url, crawl.max_actions, crawl.timeout, crawl.json) == (
        "http://127.0.0.1:3000",
        15,
        60,
        False,
    )
    assert alias.max_actions == 30


@pytest.mark.parametrize(
    "flags", [["--max-actions", "0"], ["--max-actions", "x"], ["--timeout", "301"]]
)
def test_crawl_rejects_out_of_range_flags(flags: list[str]) -> None:
    with pytest.raises(SystemExit) as error:
        build_parser().parse_args(["crawl", "http://x", *flags])
    assert error.value.code == 2


def test_hud_lines_match_the_playwright_transcript() -> None:
    events: list[dict[str, Any]] = [
        {"type": "launch"},
        {"type": "navigate", "step": 1, "url": "http://127.0.0.1:3000/"},
        {"type": "discovered", "url": "http://127.0.0.1:3000/", "count": 8},
        {"type": "action", "step": 2, "action": "click", "label": "Trail Mug", "ok": True},
        {
            "type": "action",
            "step": 3,
            "action": "fill",
            "label": "Email",
            "value": "test@example.com",
            "ok": True,
        },
        {
            "type": "action",
            "step": 4,
            "action": "click",
            "label": "Place order",
            "ok": False,
            "failure": FAILURE_REPORT["failure"],
        },
        {"type": "report", "report": FAILURE_REPORT},
    ]
    assert [render_event(event, PLAIN) for event in events] == [
        "[Playwright] Launching Chromium...",
        "[Playwright] Navigating to http://127.0.0.1:3000/...",
        "[Playwright] Discovered 8 interactive elements.",
        "[Playwright] Step 2: Clicking Trail Mug -> OK",
        '[Playwright] Step 3: Filling Email with "test@example.com" -> OK',
        "[Playwright] Step 4: Clicking Place order -> 💥 HTTP 500 on POST /api/checkout",
        None,
    ]
    assert "\033[" in str(render_event(events[3], COLOR))


def test_failure_summary_has_evidence_and_reproduction() -> None:
    text = "\n".join(render_report(FAILURE_REPORT, PLAIN))
    assert "HTTP 500 on POST /api/checkout" in text
    assert "endpoint  POST http://127.0.0.1:3000/api/checkout" in text
    assert 'response  {"detail":"TypeError"}' in text
    assert "console   Failed to load resource: 500" in text
    assert '3. fill #email = "test@example.com"' in text
    assert '4. click button:has-text("Place order")  <- fails here' in text
    assert text.endswith("Defect intercepted! Run ./faultline run to repair it with Meta.")
    assert "\033[" not in text


def test_page_error_summary_shows_the_stack() -> None:
    report = {
        **FAILURE_REPORT,
        "failure": {
            "kind": "page_error",
            "message": "TypeError: cart is undefined",
            "stack": "TypeError: cart is undefined\n    at onClick (app.js:1:2)",
            "step": 4,
            "console_errors": [],
            "related": [],
        },
    }
    text = "\n".join(render_report(report, PLAIN))
    assert "Uncaught TypeError: cart is undefined" in text
    assert "stack     TypeError: cart is undefined" in text
    assert "at onClick (app.js:1:2)" in text


def _args(*argv: str) -> Any:
    return build_parser().parse_args(["crawl", *argv])


def test_crawl_command_streams_and_exits_1_on_a_defect(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, Any] = {}

    def fake(url: str, **kwargs: Any) -> dict[str, Any]:
        seen.update(url=url, **kwargs)
        kwargs["on_event"]({"type": "launch"})
        return FAILURE_REPORT

    monkeypatch.setattr(crawler_service, "run_crawl", fake)
    assert crawl_command(_args("127.0.0.1:3000", "--timeout", "90"), PLAIN) == 1
    out = capsys.readouterr().out
    assert out.startswith("[Playwright] Launching Chromium...\n")
    assert "Defect intercepted!" in out
    assert seen["url"] == "http://127.0.0.1:3000"
    assert (seen["max_actions"], seen["timeout_ms"]) == (15, 90_000)


def test_crawl_command_exits_0_when_clean(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(crawler_service, "run_crawl", lambda url, **_: CLEAN_REPORT)
    assert crawl_command(_args("http://127.0.0.1:3000"), PLAIN) == 0
    out = capsys.readouterr().out
    assert "No defect found. Explored 12 elements with 15 actions across 1 pages" in out
    assert "Defect intercepted" not in out


def test_crawl_command_json_prints_only_the_report(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake(url: str, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["on_event"] is None
        return FAILURE_REPORT

    monkeypatch.setattr(crawler_service, "run_crawl", fake)
    assert crawl_command(_args("http://127.0.0.1:3000", "--json"), PLAIN) == 1
    assert json.loads(capsys.readouterr().out) == FAILURE_REPORT


@pytest.mark.parametrize(
    "code,exit_code", [("invalid_url", 2), ("runner_unavailable", 1), ("runner_failed", 1)]
)
def test_crawl_command_reports_crawl_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    code: str,
    exit_code: int,
) -> None:
    def fail(url: str, **_: Any) -> dict[str, Any]:
        raise CrawlError(code, "it broke")

    monkeypatch.setattr(crawler_service, "run_crawl", fail)
    assert crawl_command(_args("http://x"), PLAIN) == exit_code
    assert capsys.readouterr().out == "faultline crawl: it broke\n"
    assert crawl_command(_args("http://x", "--json"), PLAIN) == exit_code
    assert json.loads(capsys.readouterr().out) == {
        "status": "error",
        "code": code,
        "error": "it broke",
    }


# --- POST /api/faultline/crawl (Inspector HUD stream) --------------------------

RUNNER_EVENTS: list[dict[str, Any]] = [
    {"type": "launch"},
    {"type": "navigate", "step": 1, "url": "http://127.0.0.1:3000/"},
    {
        "type": "discovered",
        "url": "http://127.0.0.1:3000/",
        "count": 9,
        "buttons": 3,
        "links": 6,
        "forms": 0,
    },
    {
        "type": "action",
        "step": 2,
        "action": "click",
        "url": "http://127.0.0.1:3000/",
        "element": "link",
        "submit": False,
        "label": "Trail Mug",
        "selector": 'a:has-text("Trail Mug") >> nth=0',
        "ok": True,
    },
    {
        "type": "action",
        "step": 3,
        "action": "fill",
        "url": "http://127.0.0.1:3000/checkout",
        "element": "field",
        "submit": False,
        "label": "Email",
        "selector": "#email",
        "value": "test@example.com",
        "ok": True,
    },
    {
        "type": "action",
        "step": 4,
        "action": "click",
        "url": "http://127.0.0.1:3000/checkout",
        "element": "button",
        "submit": True,
        "label": "Place order",
        "selector": 'button:has-text("Place order")',
        "ok": False,
        "failure": {**FAILURE_REPORT["failure"], "response_body": '{"detail":"TypeError: x"}'},
    },
]
HUD_EVENTS: list[dict[str, Any]] = [
    {
        "type": "step",
        "n": 1,
        "action": "visit",
        "target": "http://127.0.0.1:3000/",
        "page": "/",
        "ok": True,
    },
    {"type": "scan", "url": "http://127.0.0.1:3000/", "buttons": 3, "forms": 0, "links": 6},
    {"type": "step", "n": 2, "action": "click", "target": "Trail Mug", "page": "/", "ok": True},
    {"type": "step", "n": 3, "action": "fill", "target": "Email", "page": "/checkout", "ok": True},
    {
        "type": "step",
        "n": 4,
        "action": "submit",
        "target": "Place order",
        "page": "/checkout",
        "ok": False,
        "note": "HTTP 500",
    },
    {
        "type": "defect",
        "method": "POST",
        "path": "/api/checkout",
        "status": 500,
        "trigger": {"kind": "Button", "label": "Place order", "page": "/checkout"},
        "fingerprint": "TypeError: x",
    },
    {"type": "done", "steps": 4, "defect": True},
]


def _failure_report_for_hud() -> dict[str, Any]:
    return {
        **FAILURE_REPORT,
        "failure": {**FAILURE_REPORT["failure"], "response_body": '{"detail":"TypeError: x"}'},
    }


def test_translator_maps_runner_events_to_the_hud_contract() -> None:
    translator = InspectorTranslator()
    produced = [item for event in RUNNER_EVENTS for item in translator.feed(event)]
    produced += translator.feed({"type": "report", "report": _failure_report_for_hud()})
    assert produced == HUD_EVENTS


def test_translator_reports_clean_errors_and_page_errors() -> None:
    assert InspectorTranslator().feed({"type": "report", "report": CLEAN_REPORT}) == [
        {"type": "done", "steps": 1, "defect": False}
    ]
    assert InspectorTranslator().feed(
        {"type": "report", "report": {"status": "error", "error": "Could not load"}}
    ) == [{"type": "error", "message": "Could not load"}]
    translator = InspectorTranslator()
    translator.feed(RUNNER_EVENTS[3])
    report = {
        **FAILURE_REPORT,
        "failure": {
            "kind": "page_error",
            "message": "TypeError: cart is undefined",
            "step": 2,
            "console_errors": [],
            "related": [],
        },
    }
    defect = translator.feed({"type": "report", "report": report})[0]
    assert defect == {
        "type": "defect",
        "method": "JS",
        "path": "/",
        "status": None,
        "trigger": {"kind": "Link", "label": "Trail Mug", "page": "/"},
        "fingerprint": "TypeError: cart is undefined",
    }


def _ndjson(response: Any) -> list[dict[str, Any]]:
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def test_inspector_crawl_streams_hud_events(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def fake(url: str, **kwargs: Any) -> dict[str, Any]:
        seen.update(url=url, max_actions=kwargs["max_actions"])
        for event in RUNNER_EVENTS:
            kwargs["on_event"](event)
        return _failure_report_for_hud()

    monkeypatch.setattr(crawler_service, "ensure_runner", lambda: "node")
    monkeypatch.setattr(crawler_service, "run_crawl", fake)
    response = client.post(
        "/api/faultline/crawl",
        json={"url": "http://127.0.0.1:3000/", "max_steps": 25},
        headers=HEADERS,
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert _ndjson(response) == HUD_EVENTS
    assert seen == {"url": "http://127.0.0.1:3000/", "max_actions": 25}
    # The lock is free again once the stream ends.
    monkeypatch.setattr(crawler_service, "run_crawl", lambda url, **_: CLEAN_REPORT)
    assert client.post("/api/crawl", json={"url": "http://x"}, headers=HEADERS).status_code == 200


def test_inspector_crawl_streams_runner_failures_as_error_events(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(url: str, **_: Any) -> dict[str, Any]:
        raise CrawlError("runner_failed", "The browser runner exited with code 2")

    monkeypatch.setattr(crawler_service, "ensure_runner", lambda: "node")
    monkeypatch.setattr(crawler_service, "run_crawl", fail)
    response = client.post("/api/faultline/crawl", json={"url": "http://x/"}, headers=HEADERS)
    assert response.status_code == 200
    assert _ndjson(response) == [
        {"type": "error", "message": "The browser runner exited with code 2"}
    ]


def test_inspector_crawl_rejects_before_streaming(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(crawler_service, "run_crawl", lambda url, **_: pytest.fail("ran"))
    assert client.post("/api/faultline/crawl", json={"url": "http://x"}).status_code == 401
    bad_url = client.post("/api/faultline/crawl", json={"url": "ftp://x"}, headers=HEADERS)
    assert (bad_url.status_code, bad_url.json()["error"]["code"]) == (422, "invalid_url")
    bad_steps = client.post(
        "/api/faultline/crawl", json={"url": "http://x", "max_steps": 0}, headers=HEADERS
    )
    assert bad_steps.status_code == 422

    def missing() -> str:
        raise CrawlError("runner_unavailable", "not built")

    monkeypatch.setattr(crawler_service, "ensure_runner", missing)
    unavailable = client.post("/api/faultline/crawl", json={"url": "http://x"}, headers=HEADERS)
    # 503 tells the Inspector to retry, then stand in a direct HTTP check.
    assert (unavailable.status_code, unavailable.json()["error"]["code"]) == (
        503,
        "runner_unavailable",
    )


def test_inspector_crawl_shares_the_single_crawl_lock(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    started, release = threading.Event(), threading.Event()

    def slow(url: str, **_: Any) -> dict[str, Any]:
        started.set()
        assert release.wait(10)
        return CLEAN_REPORT

    monkeypatch.setattr(crawler_service, "ensure_runner", lambda: "node")
    monkeypatch.setattr(crawler_service, "run_crawl", slow)
    first: dict[str, Any] = {}
    thread = threading.Thread(
        target=lambda: first.update(
            response=client.post("/api/crawl", json={"url": "http://x"}, headers=HEADERS)
        )
    )
    thread.start()
    try:
        assert started.wait(10)
        busy = client.post("/api/faultline/crawl", json={"url": "http://x"}, headers=HEADERS)
        assert (busy.status_code, busy.json()["error"]["code"]) == (409, "crawl_in_progress")
    finally:
        release.set()
        thread.join(10)
    assert first["response"].status_code == 200


@needs_node
@pytest.mark.skipif(
    not crawler_service.RUNNER_CLI.is_file(), reason="browser runner is not built (make runner)"
)
def test_inspector_crawl_streams_a_real_chromium_defect(
    client: TestClient, broken_shop: str
) -> None:
    response = client.post(
        "/api/faultline/crawl", json={"url": broken_shop, "max_steps": 5}, headers=HEADERS
    )
    events = _ndjson(response)
    assert response.status_code == 200
    assert [event["type"] for event in events] == ["step", "scan", "step", "defect", "done"]
    assert events[2] == {
        "type": "step",
        "n": 2,
        "action": "click",
        "target": "Place order",
        "page": "/",
        "ok": False,
        "note": "HTTP 500",
    }
    assert events[3] == {
        "type": "defect",
        "method": "POST",
        "path": "/api/orders",
        "status": 500,
        "trigger": {"kind": "Button", "label": "Place order", "page": "/"},
        "fingerprint": "orders table is locked",
    }
