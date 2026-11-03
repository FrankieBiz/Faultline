"""Cross-platform CLI entrypoint fuzzing: paths, URLs, scenario ids, and signals.

Property-based and edge-case tests for the four developer entrypoints
(``faultline run``, ``check``, ``init``, ``gate``) and the helpers they share.
Every hostile path spelling either fails closed or yields a contained
forward-slash path; every hostile URL is refused before a subprocess or HTTP
client launches; every hostile scenario identifier is refused before selection;
and an interrupt (SIGINT / Ctrl+C / SIGTERM) tears down child worker and
Playwright runner processes instead of orphaning them.

No sandbox, browser, or real service is launched here. Platform differences are
exercised by reassigning ``app.portable``'s host flags and by mocking the
subprocess seam, exactly as the production adapters select them.
"""

from __future__ import annotations

import argparse
import json
import random
import signal
import subprocess
from pathlib import Path
from typing import Any, Literal
from unittest.mock import patch

import pytest

import app.portable as portable
from app import crawler_service
from app.cli import PLAIN, build_parser, cmd_run
from app.cli_crawl import crawl_command, gate_command, scan_command
from app.crawler_service import CrawlError, validate_url
from app.probes import validate_target
from app.project import load_project, normalize_scenario_id, source_path
from app.snapshots import contained_path

HOSTILE_ATOMS = ("/", "\\", "..", ".", ":", "C", "x", "-", "_", " ", "\x00", "a", "Z", "9")


# --- path normalization: ``normalize_relpath`` ---------------------------------


def test_normalize_relpath_fuzz_never_emits_an_escape_sequence() -> None:
    """A deterministic fuzz: every spelling either fails or stays fully contained."""
    corpus = [
        "",
        ".",
        "..",
        "../escape",
        "a/../../etc/passwd",
        "..\\..\\etc\\passwd",
        "/etc/passwd",
        "//etc/passwd",
        "C:\\Windows\\System32",
        "C:relative",
        "C:/relative",
        "\\\\server\\share\\file",
        "a\x00b",
        "a//b",
        "a/./b",
        "./a",
        "a/",
        "/a",
        "a\\b\\..\\c",
        "apps\\buggyshop-backend\\app\\routes\\checkout.py",
        "apps/buggyshop-backend/app/routes/checkout.py",
        "x/..",
        "x/../..",
        "a..b",
        "..a",
        "a..",
    ]
    rng = random.Random(0xFA11)
    for _ in range(2000):
        corpus.append("".join(rng.choice(HOSTILE_ATOMS) for _ in range(rng.randint(0, 10))))

    for value in corpus:
        try:
            result = portable.normalize_relpath(value)
        except ValueError:
            continue
        assert isinstance(result, str) and result
        assert "\\" not in result
        assert not result.startswith("/") and not result.endswith("/")
        assert ".." not in result.split("/")
        assert "\x00" not in result


def test_normalize_relpath_is_idempotent_and_canonical() -> None:
    """Normalizing an already-normalized path returns it unchanged."""
    for value in ("a", "a/b", "a/b/c.py", "dir/sub/file.py", "x.y-z_9"):
        assert portable.normalize_relpath(value) == value
        assert portable.normalize_relpath(portable.normalize_relpath(value)) == value


# --- repair target paths: ``source_path`` --------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "../server.js",
        "a/../../server.js",
        "/tmp/server.js",
        "//server/share.js",
        "\\\\server\\share.js",
        "C:/server.js",
        "C:\\server.js",
        "C:server.js",
        ".env",
        "./.hidden",
        "meta-provided/a.js",
        "id_rsa",
        "id_ed25519",
        "secret.key",
        "secret.pem",
        "a\x00b.js",
    ],
)
def test_source_path_rejects_hostile_and_secret_targets(value: str) -> None:
    with pytest.raises(ValueError, match="ordinary"):
        source_path(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("server.js", "server.js"),
        ("app/routes/checkout.py", "app/routes/checkout.py"),
        (r"app\routes\checkout.py", "app/routes/checkout.py"),
        ("a/b/c.js", "a/b/c.js"),
    ],
)
def test_source_path_normalizes_windows_separators(value: str, expected: str) -> None:
    assert source_path(value) == expected


def test_source_path_never_emits_a_separator_or_escape() -> None:
    rng = random.Random(0x5EED)
    corpus = [r"apps\buggyshop-backend\app\routes\checkout.py", "dir/subdir/file.py"]
    for _ in range(1500):
        corpus.append("".join(rng.choice(HOSTILE_ATOMS) for _ in range(rng.randint(1, 8))))
    for value in corpus:
        try:
            result = source_path(value)
        except ValueError:
            continue
        assert result == portable.normalize_relpath(value)
        assert "\\" not in result and "\x00" not in result
        assert ".." not in result.split("/")
        assert not result.startswith("/")


# --- containment: ``contained_path`` -------------------------------------------


@pytest.mark.parametrize(
    "relative",
    [
        "../escape",
        "..\\escape",
        "C:\\Windows\\System32",
        "C:/Windows",
        "\\\\server\\share",
        "/etc/passwd",
        "a/../../etc/passwd",
        "a\x00b",
        "",
    ],
)
def test_contained_path_never_escapes_its_root(tmp_path: Path, relative: str) -> None:
    with pytest.raises(ValueError):
        contained_path(tmp_path, relative)


def test_contained_path_rejects_symlink_components(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "link").symlink_to(outside)
    with pytest.raises(ValueError, match="Symlink"):
        contained_path(tmp_path, "link/file.py")


# --- scenario identifiers ------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "checkout_api",
        "addition",
        "home",
        "healthy",
        "broken",
        "project_x",
        "a.b-c_d9",
    ],
)
def test_normalize_scenario_id_accepts_plain_identifiers(value: str) -> None:
    assert normalize_scenario_id(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "..",
        "../evil",
        "a/b",
        "a\\b",
        "C:foo",
        "C:/foo",
        "C:\\foo",
        "\\\\server\\share",
        ".hidden",
        "-flag",
        "scenario.foo",
        "probe-foo",
        "a\x00b",
        "a b",
    ],
)
def test_normalize_scenario_id_rejects_path_like_and_reserved(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_scenario_id(value)


def test_load_project_rejects_a_path_like_scenario_name(tmp_path: Path) -> None:
    """The CLI scenario identifier is refused before the config is even read."""
    config = tmp_path / "faultline.toml"
    with pytest.raises(ValueError, match="scenario name"):
        load_project(config, "../evil")


def test_load_project_rejects_a_reserved_scenario_prefix(tmp_path: Path) -> None:
    config = tmp_path / "faultline.toml"
    with pytest.raises(ValueError, match="reserved prefix"):
        load_project(config, "probe-evil")


# --- URL arguments: gate / scan / crawl / test ---------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com",
        "C:\\Windows\\System32",
        "C:/Windows",
        "C:relative",
        "\\\\server\\share",
        "example.com",
        "http://",
        "http://user:pass@localhost",
        "http://localhost:99999",
        "http://localhost/#fragment",
        "",
    ],
)
def test_validate_url_rejects_non_http_and_path_like_urls(url: str) -> None:
    with pytest.raises(CrawlError) as excinfo:
        validate_url(url)
    assert excinfo.value.code == "invalid_url"


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com",
        "C:\\Windows\\System32",
        "\\\\server\\share",
        "example.com",
        "http://",
        "http://user:password@localhost",
        "http://localhost:99999",
        "http://localhost/#fragment",
        "http://localhost/{port}",
    ],
)
def test_validate_target_rejects_non_http_and_path_like_urls(url: str) -> None:
    with pytest.raises(ValueError):
        validate_target(url)


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1:3000", "http://127.0.0.1:3000/checkout", "https://example.com"],
)
def test_validate_url_accepts_absolute_http_urls(url: str) -> None:
    assert validate_url(url).startswith(("http://", "https://"))


def test_gate_rejects_a_drive_letter_url_as_bad_input(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A Windows-drive spelling is refused with exit 2 before any runner launches."""
    args = build_parser().parse_args(["gate", "C:\\Windows\\System32", "--json"])
    with patch("app.crawler_service.run_crawl") as run:
        run.side_effect = CrawlError("invalid_url", "not a URL")
        assert gate_command(args, PLAIN) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["exit_code"] == 2 and result["error"]["code"] == "invalid_url"


# --- signal handling: SIGINT / Ctrl+C teardown ---------------------------------


class _InterruptingLines:
    """An iterator that raises KeyboardInterrupt as soon as the runner reads stdout."""

    def __iter__(self) -> Any:
        raise KeyboardInterrupt


class _FakeRunner:
    """A subprocess stand-in whose teardown can be observed and scripted."""

    def __init__(self, *, hang: bool = False) -> None:
        self.stdout: Any = _InterruptingLines()
        self.stderr: Any = iter(())
        self.terminated = False
        self.killed = False
        self.wait_calls: list[float | None] = []
        self.hang = hang
        self._returncode: int | None = None

    def poll(self) -> int | None:
        return self._returncode

    def terminate(self) -> None:
        self.terminated = True
        self._returncode = -15

    def kill(self) -> None:
        self.killed = True
        self._returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls.append(timeout)
        if self.hang and timeout is not None:
            raise subprocess.TimeoutExpired("node", timeout)
        return self._returncode if self._returncode is not None else 0

    def __enter__(self) -> _FakeRunner:
        return self

    def __exit__(self, *exc: object) -> Literal[False]:
        return False


def _interrupt_crawl(monkeypatch: pytest.MonkeyPatch, fake: _FakeRunner) -> None:
    monkeypatch.setattr(crawler_service, "validate_url", lambda url: url)
    monkeypatch.setattr(crawler_service, "ensure_runner", lambda runner=None: "node")
    monkeypatch.setattr("app.crawler_service.subprocess.Popen", lambda *a, **k: fake)


def test_run_crawl_interrupt_terminates_and_reaps_the_playwright_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ctrl+C mid-crawl sends SIGTERM to the Node/Playwright runner and reaps it."""
    fake = _FakeRunner()
    _interrupt_crawl(monkeypatch, fake)
    with pytest.raises(KeyboardInterrupt):
        crawler_service.run_crawl("http://127.0.0.1:3000", max_actions=5, timeout_ms=1000)
    assert fake.terminated is True
    assert fake.killed is False
    assert fake.wait_calls, "the runner must be waited on after termination"


def test_run_crawl_escalates_to_kill_when_terminate_hangs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A runner that ignores SIGTERM is SIGKILLed instead of being orphaned."""
    fake = _FakeRunner(hang=True)
    _interrupt_crawl(monkeypatch, fake)
    with pytest.raises(KeyboardInterrupt):
        crawler_service.run_crawl("http://127.0.0.1:3000", max_actions=5, timeout_ms=1000)
    assert fake.terminated is True
    assert fake.killed is True


@pytest.mark.parametrize(
    ("argv", "command"),
    [
        (["crawl", "http://127.0.0.1:3000"], crawl_command),
        (["gate", "http://127.0.0.1:3000"], gate_command),
    ],
)
def test_crawl_commands_return_130_on_interrupt(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], command: Any
) -> None:
    args = build_parser().parse_args(argv)
    with patch("app.crawler_service.run_crawl", side_effect=KeyboardInterrupt):
        assert command(args, PLAIN) == 130


def test_scan_returns_130_on_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    args = build_parser().parse_args(["scan", "http://127.0.0.1:3000"])
    with patch("app.crawler_service.run_crawl", side_effect=KeyboardInterrupt):
        assert scan_command(args, PLAIN, port=9000) == 130


def test_run_returns_130_on_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Ctrl+C during ``faultline run`` selection returns the interrupt code."""
    args = argparse.Namespace(
        config="faultline.toml",
        scenario_name=None,
        repro=None,
        target=None,
        data_dir=None,
        detect=False,
    )
    with (
        patch("app.portable.detect_host", return_value="linux"),
        patch("app.project.load_project", side_effect=KeyboardInterrupt),
    ):
        assert cmd_run(args) == 130


def test_sigterm_handler_raises_a_keyboard_interrupt() -> None:
    """The CLI's own SIGTERM handler reuses the Ctrl+C path, so the cursor returns."""
    from app import cli

    with pytest.raises(KeyboardInterrupt):
        cli._raise_interrupt(signal.SIGTERM, None)
