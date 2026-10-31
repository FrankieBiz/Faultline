"""Run the browser runner's autonomous crawler and collect its CrawlReport.

The runner is invoked as ``node tools/browser-runner/dist/cli.js --crawl URL
--ndjson``. It prints one JSON event per line and ends with
``{"type": "report", "report": {...}}``. Progress events are forwarded to an
optional callback as they arrive, so a terminal HUD can render them live.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
import urllib.parse
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
RUNNER_CLI = REPOSITORY_ROOT / "tools" / "browser-runner" / "dist" / "cli.js"

DEFAULT_MAX_ACTIONS = 15
MAX_ACTIONS = 100
DEFAULT_TIMEOUT_MS = 60_000
MAX_TIMEOUT_MS = 300_000
# Time allowed beyond the crawl budget for Chromium launch and shutdown.
KILL_GRACE_SECONDS = 30
MAX_URL_LENGTH = 2048

Event = dict[str, Any]


class CrawlError(Exception):
    """The crawl could not run; ``code`` is a stable machine-readable reason."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def validate_url(url: str) -> str:
    """Return ``url`` if it is an absolute http(s) URL with a host."""
    candidate = url.strip()
    if len(candidate) > MAX_URL_LENGTH:
        raise CrawlError("invalid_url", f"URL is longer than {MAX_URL_LENGTH} characters.")
    parsed = urllib.parse.urlsplit(candidate)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise CrawlError("invalid_url", "URL must be an absolute http:// or https:// URL.")
    return candidate


def ensure_runner(runner: Path = RUNNER_CLI) -> str:
    """Return the Node.js executable, or raise ``runner_unavailable``."""
    node = shutil.which("node")
    if node is None:
        raise CrawlError("runner_unavailable", "Node.js is not on PATH.")
    if not runner.is_file():
        raise CrawlError(
            "runner_unavailable",
            "The browser runner is not built. Run: npm --prefix tools/browser-runner run build",
        )
    return node


def run_crawl(
    url: str,
    *,
    max_actions: int = DEFAULT_MAX_ACTIONS,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    on_event: Callable[[Event], None] | None = None,
    runner: Path = RUNNER_CLI,
    cancel: threading.Event | None = None,
) -> dict[str, Any]:
    """Crawl ``url`` in headless Chromium and return the runner's CrawlReport.

    Raises CrawlError when input is invalid, the runner is missing, or it
    exits without a report. Page defects are not errors: they come back as a
    report with ``status: "failure"``. Setting ``cancel`` stops the runner.
    """
    target = validate_url(url)
    if not 1 <= max_actions <= MAX_ACTIONS:
        raise CrawlError("invalid_request", f"max_actions must be from 1 to {MAX_ACTIONS}.")
    if not 1_000 <= timeout_ms <= MAX_TIMEOUT_MS:
        raise CrawlError("invalid_request", f"timeout_ms must be from 1000 to {MAX_TIMEOUT_MS}.")
    node = ensure_runner(runner)

    command = [
        node,
        str(runner),
        "--crawl",
        target,
        "--ndjson",
        "--max-actions",
        str(max_actions),
        "--timeout-ms",
        str(timeout_ms),
    ]
    stderr_tail: deque[str] = deque(maxlen=20)
    report: dict[str, Any] | None = None
    with subprocess.Popen(
        command,
        cwd=runner.parent.parent,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    ) as process:
        assert process.stdout is not None and process.stderr is not None
        stderr = process.stderr

        def drain_stderr() -> None:
            for line in stderr:
                stderr_tail.append(line.rstrip())

        drainer = threading.Thread(target=drain_stderr, daemon=True)
        drainer.start()
        finished = threading.Event()
        deadline = time.monotonic() + timeout_ms / 1000 + KILL_GRACE_SECONDS

        def watchdog() -> None:
            # Ends a runner that outlives its budget or whose caller gave up.
            while not finished.wait(0.2):
                if time.monotonic() >= deadline or (cancel is not None and cancel.is_set()):
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    return

        threading.Thread(target=watchdog, daemon=True).start()
        try:
            for line in process.stdout:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get("type") == "report" and isinstance(event.get("report"), dict):
                    report = event["report"]
                elif on_event is not None:
                    on_event(event)
        finally:
            finished.set()
            if process.poll() is None:
                # SIGTERM lets Playwright close Chromium before the runner exits.
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
            process.wait()
            drainer.join(timeout=5)

    if report is None:
        detail = next((line for line in reversed(stderr_tail) if line.strip()), "")
        raise CrawlError(
            "runner_failed",
            f"The browser runner exited with code {process.returncode} without a report"
            + (f": {detail}" if detail else "."),
        )
    return report
