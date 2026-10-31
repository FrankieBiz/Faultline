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
from app.cli_crawl import crawl_command, render_event, render_report, scan_command
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
            "element": "link",
        },
        {
            "step": 3,
            "action": "fill",
            "url": "http://127.0.0.1:3000/checkout",
            "selector": "#email",
            "label": "Email",
            "value": "test@example.com",
            "element": "field",
        },
        {
            "step": 4,
            "action": "click",
            "url": "http://127.0.0.1:3000/checkout",
            "selector": 'button:has-text("Place order")',
            "label": "Place order",
            "element": "button",
        },
    ],
    "elements_explored": 20,
    "actions_taken": 3,
    "pages_visited": ["http://127.0.0.1:3000/", "http://127.0.0.1:3000/checkout"],
    "screens_visited": [
        {
            "url": "http://127.0.0.1:3000/",
            "path": "/",
            "title": "Shop",
            "elements": 9,
            "forms": 0,
            "first_step": 1,
        },
        {
            "url": "http://127.0.0.1:3000/checkout",
            "path": "/checkout",
            "title": "Checkout",
            "elements": 11,
            "forms": 1,
            "first_step": 2,
        },
    ],
    "duration_ms": 2100,
    "reproduction_trail": [
        "1. Open http://127.0.0.1:3000/",
        '2. Click link "Trail Mug" on / [a:has-text("Trail Mug") >> nth=0]',
        '3. Fill "Email" with "test@example.com" on /checkout [#email]',
        '4. Click button "Place order" on /checkout [button:has-text("Place order")]'
        " -> HTTP 500 on POST /api/checkout",
    ],
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
    "reproduction_trail": ["1. Open http://127.0.0.1:3000/"],
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
    body = response.json()
    assert body == {**FAILURE_REPORT, **crawler_service.telemetry(FAILURE_REPORT)}
    assert body["elements_explored"] == 20
    assert [screen["path"] for screen in body["screens_visited"]] == ["/", "/checkout"]
    assert [(a["step"], a["action"], a["ok"]) for a in body["actions"]] == [
        (2, "click", True),
        (3, "fill", True),
        (4, "click", False),
    ]
    assert body["failure"]["endpoint"] == "/api/checkout"
    assert body["reproduction_trail"][-1].endswith("-> HTTP 500 on POST /api/checkout")
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
    {
        "type": "done",
        "steps": 4,
        "defect": True,
        "telemetry": crawler_service.telemetry(
            {
                **FAILURE_REPORT,
                "failure": {
                    **FAILURE_REPORT["failure"],
                    "response_body": '{"detail":"TypeError: x"}',
                },
            }
        ),
    },
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
        {
            "type": "done",
            "steps": 1,
            "defect": False,
            "telemetry": crawler_service.telemetry(CLEAN_REPORT),
        }
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


# --- telemetry ----------------------------------------------------------------


def test_telemetry_lists_actions_screens_and_the_failure() -> None:
    summary = crawler_service.telemetry(FAILURE_REPORT)
    assert summary["status"] == "failure"
    assert summary["elements_explored"] == 20
    assert summary["actions_taken"] == 3
    assert summary["actions"][0] == {
        "step": 2,
        "action": "click",
        "element": "link",
        "label": "Trail Mug",
        "selector": 'a:has-text("Trail Mug") >> nth=0',
        "value": None,
        "page": "/",
        "ok": True,
    }
    assert summary["actions"][-1]["ok"] is False
    assert summary["failure"] == FAILURE_REPORT["failure"]
    assert summary["reproduction_trail"] == FAILURE_REPORT["reproduction_trail"]
    assert "breadcrumbs" not in summary


def test_telemetry_of_clean_and_older_reports() -> None:
    clean = crawler_service.telemetry(CLEAN_REPORT)
    assert clean["failure"] is None
    assert clean["actions"] == []
    assert clean["stop_reason"] == "max_actions"
    # Reports without screens_visited fall back to pages_visited.
    assert clean["screens_visited"] == [{"url": "http://127.0.0.1:3000/", "path": "/"}]
    errored = crawler_service.telemetry({"status": "error", "error": "Could not load"})
    assert (errored["failure"], errored["error"], errored["reproduction_trail"]) == (
        None,
        "Could not load",
        [],
    )


# --- faultline scan / auto ----------------------------------------------------

SCAN_EVENTS: list[dict[str, Any]] = [
    {"type": "launch"},
    {"type": "navigate", "step": 1, "url": "http://127.0.0.1:3000/"},
    {**RUNNER_EVENTS[2], "title": "Shop", "total_elements": 9, "screens": 1},
    RUNNER_EVENTS[3],
    {
        "type": "discovered",
        "url": "http://127.0.0.1:3000/checkout",
        "title": "Checkout",
        "count": 11,
        "buttons": 4,
        "links": 6,
        "forms": 1,
        "total_elements": 20,
        "screens": 2,
    },
    RUNNER_EVENTS[4],
    RUNNER_EVENTS[5],
]


def _scan_args(*argv: str) -> Any:
    return build_parser().parse_args(["scan", *argv])


def _fake_crawl(monkeypatch: pytest.MonkeyPatch, report: dict[str, Any] = FAILURE_REPORT) -> None:
    def fake(url: str, **kwargs: Any) -> dict[str, Any]:
        for event in SCAN_EVENTS:
            kwargs["on_event"](event)
        return report

    monkeypatch.setattr(crawler_service, "run_crawl", fake)


class FakeEngine:
    """Stands in for the controller API that ``app.cli._api_request`` reaches."""

    def __init__(self, provider: str = "meta", status: str = "ready") -> None:
        self.provider = provider
        self.status = status
        self.requests: list[tuple[str, str, dict[str, Any] | None]] = []
        self.listened: list[Any] = []
        self.down = False

    def api(
        self,
        path: str,
        method: str = "GET",
        data: dict[str, Any] | None = None,
        port: int = 9000,
    ) -> dict[str, Any]:
        self.requests.append((method, path, data))
        if self.down:
            return {"error": "Connection refused", "status": 0}
        if path == "/api/faultline/scenarios":
            return {
                "scenarios": [
                    {"id": "scripted_checkout_repair", "route": "POST /api/checkout"},
                ]
            }
        if path == "/api/faultline/readiness":
            return {
                "status": self.status,
                "model": {
                    "provider": self.provider,
                    "model": "muse-spark",
                    "available": self.status == "ready",
                    "reason": None if self.status == "ready" else "missing_api_key",
                },
            }
        if path == "/api/faultline/jobs":
            mode = "repair" if self.status == "ready" else "detect"
            return {"job_id": "job-1", "state": "queued", "effective_mode": mode}
        raise AssertionError(path)

    def listen(self, args: Any) -> int:
        self.listened.append(args)
        return 0


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch) -> FakeEngine:
    from app import cli

    fake = FakeEngine()
    monkeypatch.setattr(cli, "_api_request", fake.api)
    monkeypatch.setattr(cli, "cmd_listen", fake.listen)
    return fake


def test_scan_and_auto_parse_with_one_command_defaults() -> None:
    parser = build_parser()
    scan = parser.parse_args(["scan", "http://127.0.0.1:3000"])
    auto = parser.parse_args(["auto", "127.0.0.1:3000", "--yes", "--port", "9100"])
    assert scan.func is auto.func
    assert (scan.max_actions, scan.timeout, scan.yes, scan.no_repair, scan.json) == (
        25,
        90,
        False,
        False,
        False,
    )
    assert (auto.yes, auto.port) == (True, 9100)
    with pytest.raises(SystemExit):
        parser.parse_args(["scan", "http://x", "--yes", "--no-repair"])


def test_scan_hud_shows_exploration_and_the_bug(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], engine: FakeEngine
) -> None:
    _fake_crawl(monkeypatch)
    assert scan_command(_scan_args("127.0.0.1:3000", "--no-repair"), PLAIN, port=9000) == 1
    out = capsys.readouterr().out.splitlines()
    assert out[:8] == [
        "[Playwright] Launching Chromium...",
        "[Playwright] Navigating to http://127.0.0.1:3000/...",
        "[Playwright] Discovered 9 interactive elements across 1 screen.",
        "[Playwright] Exercising buttons and forms...",
        "[Playwright] Step 2: Clicking Trail Mug -> OK",
        "[Playwright] Discovered 20 interactive elements across 2 screens.",
        '[Playwright] Step 3: Filling Email with "test@example.com" -> OK',
        "[Playwright] Step 4: Clicking Place order -> FAILED",
    ]
    assert out[8] == "[Playwright] 💥 BUG CAUGHT: HTTP 500 on POST /api/checkout"
    assert out[9] == "Explored 20 elements on 2 screens with 3 actions."
    text = "\n".join(out)
    assert 'response  {"detail":"TypeError"}' in text
    journey = text.split("Reproduction journey\n", 1)[1]
    assert journey.startswith("  1. Open http://127.0.0.1:3000/\n")
    assert '  4. Click button "Place order" on /checkout' in journey
    assert text.endswith("Repair skipped. Run ./faultline run to repair it later.")
    # --no-repair never contacts the engine.
    assert engine.requests == []


def test_scan_yes_dispatches_the_sandboxed_repair_and_streams_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], engine: FakeEngine
) -> None:
    _fake_crawl(monkeypatch)
    assert scan_command(_scan_args("http://127.0.0.1:3000", "-y"), PLAIN, port=9123) == 0
    out = capsys.readouterr().out
    assert (
        "Defect intercepted! Propose and verify patch with Meta in sandbox? [Y/n] y (--yes)" in out
    )
    assert "[FaultLine] Sandbox run job-1 started." in out
    method, path, data = engine.requests[-1]
    assert (method, path) == ("POST", "/api/faultline/jobs")
    assert data is not None and data["scenario_id"] == "scripted_checkout_repair"
    assert len(data["idempotency_key"]) == 32
    assert [(args.job_id, args.port) for args in engine.listened] == [("job-1", 9123)]


@pytest.mark.parametrize("answer,dispatched", [("", True), ("Y", True), ("n", False)])
def test_scan_asks_on_a_terminal(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    engine: FakeEngine,
    answer: str,
    dispatched: bool,
) -> None:
    _fake_crawl(monkeypatch)
    prompts: list[str] = []

    def ask(prompt: str) -> str:
        prompts.append(prompt)
        return answer

    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", ask)
    code = scan_command(_scan_args("http://127.0.0.1:3000"), PLAIN, port=9000)
    assert prompts == ["Defect intercepted! Propose and verify patch with Meta in sandbox? [Y/n] "]
    assert code == (0 if dispatched else 1)
    assert len(engine.listened) == (1 if dispatched else 0)
    if not dispatched:
        assert "Repair skipped." in capsys.readouterr().out


def test_scan_without_a_terminal_does_not_dispatch(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], engine: FakeEngine
) -> None:
    _fake_crawl(monkeypatch)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("prompted"))
    assert scan_command(_scan_args("http://127.0.0.1:3000"), PLAIN, port=9000) == 1
    assert "Re-run with --yes to repair." in capsys.readouterr().out
    assert engine.listened == []


@pytest.mark.parametrize(
    "provider,status,expected",
    [
        (
            "deterministic",
            "ready",
            "Propose and verify patch with the deterministic fallback (not a Meta model)"
            " in sandbox? [Y/n]",
        ),
        (
            "meta",
            "detect_only",
            "No model can propose a patch (missing_api_key). "
            "Reproduce it in the sandbox anyway? [Y/n]",
        ),
    ],
)
def test_scan_names_the_engine_truthfully(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    engine: FakeEngine,
    provider: str,
    status: str,
    expected: str,
) -> None:
    engine.provider, engine.status = provider, status
    _fake_crawl(monkeypatch)
    assert scan_command(_scan_args("http://x", "--yes"), PLAIN, port=9000) == 0
    out = capsys.readouterr().out
    assert expected in out
    assert "with Meta" not in out


def test_scan_explains_when_no_repair_can_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], engine: FakeEngine
) -> None:
    engine.down = True
    _fake_crawl(monkeypatch)
    assert scan_command(_scan_args("http://x", "--yes"), PLAIN, port=9555) == 1
    out = capsys.readouterr().out
    assert "The FaultLine engine is not reachable on port 9555" in out
    assert "./faultline demo" in out

    engine.down = False
    uncovered = {
        **FAILURE_REPORT,
        "failure": {**FAILURE_REPORT["failure"], "url": "http://127.0.0.1:3000/api/cart"},
    }
    _fake_crawl(monkeypatch, uncovered)
    assert scan_command(_scan_args("http://x", "--yes"), PLAIN, port=9000) == 1
    assert "No repair scenario covers POST /api/cart yet." in capsys.readouterr().out

    page_error = {
        **FAILURE_REPORT,
        "failure": {"kind": "page_error", "message": "TypeError: x", "step": 4},
    }
    _fake_crawl(monkeypatch, page_error)
    engine.requests.clear()
    assert scan_command(_scan_args("http://x", "--yes"), PLAIN, port=9000) == 1
    assert "FaultLine repairs failing HTTP routes" in capsys.readouterr().out
    assert engine.requests == []
    assert engine.listened == []


def test_scan_clean_and_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], engine: FakeEngine
) -> None:
    _fake_crawl(monkeypatch, CLEAN_REPORT)
    assert scan_command(_scan_args("http://x"), PLAIN, port=9000) == 0
    assert "No defect found." in capsys.readouterr().out

    monkeypatch.setattr(crawler_service, "run_crawl", lambda url, **_: FAILURE_REPORT)
    assert scan_command(_scan_args("http://x", "--json"), PLAIN, port=9000) == 1
    body = json.loads(capsys.readouterr().out)
    assert body["actions"][-1]["ok"] is False
    assert body["reproduction_trail"] == FAILURE_REPORT["reproduction_trail"]
    assert engine.requests == []


def test_scan_rejects_bad_urls(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(url: str, **_: Any) -> dict[str, Any]:
        raise CrawlError("invalid_url", "URL must be an absolute http:// or https:// URL.")

    monkeypatch.setattr(crawler_service, "run_crawl", fail)
    assert scan_command(_scan_args("ftp://x"), PLAIN, port=9000) == 2
    assert capsys.readouterr().out.startswith("faultline scan: URL must be")
