"""The live-service configurator must change only the meta tag, and only after real checks."""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "configure-live-demo.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("faultline_configure_live_demo", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Dataclasses resolve string annotations through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tool = _load()

PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; connect-src {connect}">
  <meta name="faultline-live-api" content="">
  <title>FaultLine</title>
</head>
<body><p>content="unrelated"</p></body>
</html>
"""
STATUS: dict[str, Any] = {
    "available": True,
    "reason": None,
    "provider": "meta",
    "model": "muse-spark-1.3",
    "classification": "meta_model",
    "queue": {"running": False, "waiting": 0, "max_waiting": 3},
    "limits": {"per_client_per_hour": 4, "daily_cap": 150, "daily_remaining": 149},
    "defects": [],
    "runtime_limits": None,
}


def page_with(connect: str, value: str = "") -> str:
    page = PAGE.replace("{connect}", connect)
    return page.replace('content=""', f'content="{value}"', 1)


def test_rewrites_only_the_meta_content_value() -> None:
    page = page_with("https:")
    updated = tool.set_live_api(page, "https://1-2-3-4.sslip.io")
    assert tool.current_live_api(updated) == "https://1-2-3-4.sslip.io"
    assert updated.replace('content="https://1-2-3-4.sslip.io"', 'content=""', 1) == page
    assert tool.set_live_api(updated, "") == page


def test_handles_attribute_order_and_single_quotes() -> None:
    page = "<meta content='old' name='FaultLine-Live-API' >"
    updated = tool.set_live_api(page, "https://live.example.com")
    assert updated == "<meta content='https://live.example.com' name='FaultLine-Live-API' >"


@pytest.mark.parametrize(
    ("page", "message"),
    [
        ('<head><meta name="description" content="x"></head>', "has no <meta name"),
        ('<meta name="faultline-live-api" content="">' * 2, "Found 2"),
        ('<meta name="faultline-live-api">', "no content attribute"),
    ],
)
def test_missing_duplicate_or_malformed_tag_fails(page: str, message: str) -> None:
    with pytest.raises(tool.ConfigureError, match=message):
        tool.set_live_api(page, "https://live.example.com")


@pytest.mark.parametrize(
    ("raw", "allow_local", "expected"),
    [
        ("https://1-2-3-4.sslip.io", False, "https://1-2-3-4.sslip.io"),
        ("  HTTPS://Live.Example.COM/ ", False, "https://live.example.com"),
        ("https://live.example.com:443", False, "https://live.example.com"),
        ("https://live.example.com:8443", False, "https://live.example.com:8443"),
        ("http://127.0.0.1:9600", True, "http://127.0.0.1:9600"),
        ("http://localhost:9600/", True, "http://localhost:9600"),
        ("http://[::1]:9600", True, "http://[::1]:9600"),
    ],
)
def test_accepts_origins(raw: str, allow_local: bool, expected: str) -> None:
    assert tool.normalize_base_url(raw, allow_local=allow_local) == expected


@pytest.mark.parametrize(
    ("raw", "allow_local", "message"),
    [
        ("http://live.example.com", False, "must use https"),
        ("http://127.0.0.1:9600", False, "--allow-local"),
        ("https://live.example.com/api/live", False, "only the origin"),
        ("https://live.example.com/?x=1", False, "only the origin"),
        ("https://user:pass@live.example.com", False, "credentials"),
        ("ftp://live.example.com", False, "Expected https"),
        ("live.example.com", False, "Expected https"),
        ("https://live.example.com:99999", False, "Not a valid URL"),
        ("https://live_example.com", False, "Unsupported host"),
    ],
)
def test_rejects_unsafe_or_ambiguous_urls(raw: str, allow_local: bool, message: str) -> None:
    with pytest.raises(tool.ConfigureError, match=message):
        tool.normalize_base_url(raw, allow_local=allow_local)


@pytest.mark.parametrize(
    ("policy", "base", "allowed"),
    [
        ("default-src 'none'", "https://a.sslip.io", False),
        ("default-src 'none'; connect-src https:", "https://a.sslip.io", True),
        ("default-src 'none'; connect-src 'none'", "https://a.sslip.io", False),
        ("default-src 'none'; connect-src https://a.sslip.io", "https://a.sslip.io", True),
        ("default-src 'none'; connect-src https://a.sslip.io", "https://b.sslip.io", False),
        ("default-src 'none'; connect-src *.sslip.io", "https://a.sslip.io", True),
        ("default-src 'none'; connect-src *.sslip.io", "https://sslip.io", False),
        ("default-src 'none'; connect-src a.sslip.io:8443", "https://a.sslip.io:8443", True),
        ("default-src 'none'; connect-src a.sslip.io", "https://a.sslip.io:8443", False),
        ("default-src 'none'; connect-src 'self'", "https://a.sslip.io", False),
        ("default-src 'none'; connect-src http://127.0.0.1:*", "http://127.0.0.1:9600", True),
        ("default-src 'none'; connect-src 127.0.0.1:9600", "http://127.0.0.1:9600", False),
        ("img-src 'self'", "https://a.sslip.io", True),
    ],
)
def test_content_security_policy_check(policy: str, base: str, allowed: bool) -> None:
    page = f'<meta http-equiv="Content-Security-Policy" content="{policy}">'
    assert tool.csp_allows(page, base) is allowed


@dataclass
class FakeService:
    status_code: int = 200
    body: bytes = field(default_factory=lambda: json.dumps(STATUS).encode())
    allow_origin: str | None = "https://frankiebiz.github.io"
    origins: list[str | None] = field(default_factory=list)


@pytest.fixture
def service() -> Iterator[tuple[FakeService, str]]:
    fake = FakeService()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            fake.origins.append(self.headers.get("Origin"))
            ok = self.path == "/api/live/status"
            body = fake.body if ok else b"{}"
            self.send_response(fake.status_code if ok else 404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            if fake.allow_origin is not None:
                self.send_header("Access-Control-Allow-Origin", fake.allow_origin)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    try:
        yield fake, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def write_page(tmp_path: Path, connect: str = "http://127.0.0.1:*", value: str = "") -> Path:
    page = tmp_path / "index.html"
    page.write_text(page_with(connect, value), encoding="utf-8")
    return page


def test_sets_the_url_after_a_successful_probe(
    service: tuple[FakeService, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake, url = service
    page = write_page(tmp_path)
    assert tool.main([url, "--allow-local", "--page", str(page)]) == 0
    text = page.read_text(encoding="utf-8")
    assert tool.current_live_api(text) == url
    assert tool.set_live_api(text, "") == page_with("http://127.0.0.1:*")
    assert fake.origins == ["https://frankiebiz.github.io"]
    out = capsys.readouterr().out
    assert "classification: meta_model" in out
    assert "149 of 150 runs left today" in out


def test_dry_run_shows_the_change_and_writes_nothing(
    service: tuple[FakeService, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, url = service
    page = write_page(tmp_path)
    before = page.read_bytes()
    assert tool.main([url, "--allow-local", "--dry-run", "--page", str(page)]) == 0
    assert page.read_bytes() == before
    out = capsys.readouterr().out
    assert f'+  <meta name="faultline-live-api" content="{url}">' in out
    assert "Dry run: nothing written." in out


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"allow_origin": None}, "LIVE_DEMO_ALLOWED_ORIGINS"),
        ({"allow_origin": "https://evil.example"}, "LIVE_DEMO_ALLOWED_ORIGINS"),
        ({"status_code": 503}, "answered HTTP 503"),
        ({"body": b"<html>"}, "not JSON"),
        ({"body": b'{"available": "yes"}'}, "boolean 'available'"),
    ],
)
def test_refuses_to_write_when_the_service_check_fails(
    service: tuple[FakeService, str],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    change: dict[str, Any],
    message: str,
) -> None:
    fake, url = service
    for key, value in change.items():
        setattr(fake, key, value)
    page = write_page(tmp_path)
    before = page.read_bytes()
    assert tool.main([url, "--allow-local", "--page", str(page)]) == 1
    assert page.read_bytes() == before
    assert message in capsys.readouterr().err


def test_refuses_when_the_page_policy_blocks_the_service(
    service: tuple[FakeService, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, url = service
    page = write_page(tmp_path, connect="'none'")
    before = page.read_bytes()
    assert tool.main([url, "--allow-local", "--page", str(page)]) == 1
    assert page.read_bytes() == before
    assert "Content-Security-Policy" in capsys.readouterr().err
    assert tool.main([url, "--allow-local", "--force", "--page", str(page)]) == 0
    assert tool.current_live_api(page.read_text(encoding="utf-8")) == url


def test_unreachable_service_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    page = write_page(tmp_path)
    before = page.read_bytes()
    # Port 9 (discard) on loopback is closed on test hosts; the connection is refused.
    code = tool.main(["http://127.0.0.1:9", "--allow-local", "--timeout", "2", "--page", str(page)])
    assert code == 1
    assert page.read_bytes() == before
    assert "Could not reach" in capsys.readouterr().err


def test_clear_empties_the_value_without_a_network_check(tmp_path: Path) -> None:
    page = write_page(tmp_path, value="https://old.example.com")
    assert tool.main(["--clear", "--page", str(page)]) == 0
    assert page.read_text(encoding="utf-8") == page_with("http://127.0.0.1:*")
    assert tool.main(["--clear", "--page", str(page)]) == 0


def test_missing_meta_tag_fails_before_any_request(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    page = tmp_path / "index.html"
    page.write_text("<html><head><title>x</title></head></html>", encoding="utf-8")
    assert tool.main(["https://live.example.com", "--page", str(page)]) == 1
    captured = capsys.readouterr()
    assert "Checking" not in captured.out
    assert 'no <meta name="faultline-live-api"' in captured.err


@pytest.mark.parametrize("argv", [[], ["https://live.example.com", "--clear"]])
def test_requires_exactly_one_of_url_or_clear(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        tool.main(argv)
    assert raised.value.code == 2
