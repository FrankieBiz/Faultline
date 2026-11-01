"""Native setup smoke: real launchers, HTTP checks, and Chromium, without Linux repair."""

import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    launcher = ROOT / ("faultline.cmd" if os.name == "nt" else "faultline")
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["NO_COLOR"] = "1"
    return subprocess.run(
        [str(launcher), *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
    )


@pytest.fixture
def local_app() -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/fail":
                status, body = 500, b"deliberate native smoke failure"
            elif self.path == "/broken":
                status, body = (
                    200,
                    (
                        b"<!doctype html><title>Broken smoke app</title>"
                        b"<button onclick=\"fetch('/fail')\">Trigger failure</button>"
                    ),
                )
            else:
                status, body = 200, b"<!doctype html><title>Healthy smoke app</title><h1>Ready</h1>"
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_native_help_and_doctor(tmp_path: Path) -> None:
    result = cli(tmp_path, "--help")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "gate" in result.stdout
    result = cli(tmp_path, "doctor")
    # Native preflight must be ready; Linux may lack optional repair isolation.
    if os.name == "nt" or sys.platform == "darwin":
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode in (0, 1), result.stdout + result.stderr
    assert "FaultLine Doctor" in result.stdout
    assert "Traceback" not in result.stderr


def test_native_init_keeps_caller_directory(tmp_path: Path) -> None:
    caller = tmp_path / "caller project with spaces"
    caller.mkdir()
    (caller / "package.json").write_text('{"scripts":{"start":"node server.js"}}')
    (caller / "server.js").write_text("// Native smoke project\n")
    result = cli(caller, "init")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (caller / "faultline.toml").is_file()
    assert "[project]" in (caller / "faultline.toml").read_text()


def test_native_http_test_and_check(tmp_path: Path, local_app: str) -> None:
    result = cli(tmp_path, "test", local_app, "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["passed"] is True
    assert len(report["sessions"]) == 2
    (tmp_path / "faultline.toml").write_text(f'''schema = 1
[project]
name = "native-smoke"
dev_command = ["node", "server.js", "{{port}}"]
url = "{local_app}"
[[invariants.rule]]
id = "health"
target = "{local_app}"
expected_status = 200
''')
    result = cli(tmp_path, "check", "--config", "faultline.toml", "--json")
    report = json.loads(result.stdout)
    assert report["checks"][0]["passed"] is True
    assert len(report["checks"][0]["sessions"]) == 2
    if sys.platform == "linux" and report["sandbox"]["prerequisites_available"] is False:
        assert result.returncode == 1, result.stdout + result.stderr
        assert report["passed"] is False
        assert report["errors"] == ["Sandbox prerequisites missing; run faultline doctor."]
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert report["passed"] is True


@pytest.mark.parametrize(
    "route,expected_code,verdict",
    [
        ("/", 0, "SAFE_TO_DEPLOY"),
        ("/broken", 1, "DEPLOYMENT_BLOCKED"),
    ],
)
def test_native_chromium_gate(
    tmp_path: Path, local_app: str, route: str, expected_code: int, verdict: str
) -> None:
    result = cli(tmp_path, "gate", local_app + route, "--json", "--timeout", "20")
    assert result.returncode == expected_code, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["verdict"] == verdict
    if expected_code:
        assert report["failure"] is not None
    else:
        assert report["stop_reason"] == "exhausted"


def test_native_scan_healthy_app(tmp_path: Path, local_app: str) -> None:
    result = cli(tmp_path, "scan", local_app, "--no-repair", "--json", "--timeout", "20")
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "clean"
    assert report["failure"] is None


@pytest.mark.skipif(os.name != "nt", reason="Real Windows demo and process-tree cleanup")
@pytest.mark.parametrize("shell", ["pwsh", "powershell.exe"])
def test_native_windows_demo_stack_and_cleanup(tmp_path: Path, shell: str) -> None:
    executable = shutil.which(shell)
    assert executable, f"Native smoke requires {shell}"
    names = ("BUGGYSHOP_API_PORT", "FAULTLINE_PORT", "BUGGYSHOP_PORT", "INSPECTOR_PORT")
    env = {**os.environ, "PYTHONUTF8": "1"}
    env.pop("PSModulePath", None)
    with ExitStack() as sockets:
        for name in names:
            probe = sockets.enter_context(socket.socket())
            probe.bind(("127.0.0.1", 0))
            env[name] = str(probe.getsockname()[1])
    stop = tmp_path / "stop demo"
    output = tmp_path / "demo.log"
    with output.open("w") as log:
        process = subprocess.Popen(
            [
                executable,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ROOT / "scripts/start-demo.ps1"),
                "-StopFile",
                str(stop),
            ],
            cwd=tmp_path,
            env=env,
            stdout=log,
            stderr=log,
        )
        try:
            deadline = time.monotonic() + 240
            while "FaultLine Inspector:" not in output.read_text(errors="replace"):
                assert process.poll() is None, output.read_text(errors="replace")
                assert time.monotonic() < deadline, output.read_text(errors="replace")
                time.sleep(0.25)
            for index, name in enumerate(names):
                connection = http.client.HTTPConnection("127.0.0.1", int(env[name]), timeout=5)
                try:
                    connection.request("GET", "/healthz" if index < 2 else "/")
                    response = connection.getresponse()
                    assert response.status == 200
                    if index < 2:
                        body = json.loads(response.read())
                        assert body["app"] == ("buggyshop-api", "faultline-orchestrator")[index]
                        assert body["status"] == "ok"
                finally:
                    connection.close()
        finally:
            stop.touch()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"], check=False)
                process.wait(timeout=10)
    assert process.returncode == 130, output.read_text(errors="replace")
    for name in names:
        with socket.socket() as probe:
            probe.settimeout(1)
            assert probe.connect_ex(("127.0.0.1", int(env[name]))) != 0
