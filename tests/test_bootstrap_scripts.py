"""Exercise the actual entry scripts with clean-machine tools and no downloads."""

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PWSH = os.environ.get("FAULTLINE_TEST_PWSH") or shutil.which("pwsh")
pytestmark = pytest.mark.skipif(os.name == "nt", reason="Unix clean-PATH shell harness")


def executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        path.unlink()
    path.write_text(body)
    path.chmod(0o755)


@pytest.fixture
def machine(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    repo = tmp_path / "repo with spaces"
    (repo / "scripts").mkdir(parents=True)
    for name in (
        "faultline",
        "scripts/setup.sh",
        "scripts/start-demo.sh",
        "scripts/start-demo.ps1",
        "setup.ps1",
        "faultline.ps1",
    ):
        shutil.copy2(ROOT / name, repo / name)
        if name.endswith(".sh") or name == "faultline":
            # Sandbox system fallback locations so a host Homebrew uv cannot
            # escape the clean-machine fixture or trigger real installations.
            script = repo / name
            script.write_text(
                script.read_text()
                .replace("/opt/homebrew/bin", f'"{tmp_path / "homebrew/bin"}"')
                .replace("/usr/local/bin", f'"{tmp_path / "local/bin"}"')
            )
    for project in (
        "apps/buggyshop-backend",
        "services/repair-orchestrator",
        "apps/buggyshop-frontend",
        "tools/browser-runner",
        "web/inspector-ui",
    ):
        (repo / project).mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # An intentionally restricted PATH: no uv, python3, node, npm, or setsid.
    for name in ("bash", "sh", "dirname", "readlink", "sleep"):
        (bin_dir / name).symlink_to(shutil.which(name))
    env = {
        "HOME": str(home),
        "PATH": str(bin_dir),
        "CALLS": str(tmp_path / "calls.jsonl"),
    }
    return repo, bin_dir, env


TOOL = (
    f"#!{sys.executable}\n"
    "import json, os, sys\n"
    "from pathlib import Path\n"
    "with open(os.environ['CALLS'], 'a') as log:\n"
    "    log.write(json.dumps({'tool': Path(sys.argv[0]).name, 'args': sys.argv[1:], "
    "'cwd': os.getcwd(), 'path': os.environ['PATH']}) + '\\n')\n"
    "if os.environ.get('FAIL_ARGS') == ' '.join(sys.argv[1:]): sys.exit(37)\n"
    "sys.exit(int(os.environ.get('FAIL_' + Path(sys.argv[0]).name.upper(), '0')))\n"
)


def calls(env: dict[str, str]) -> list[dict]:
    path = Path(env["CALLS"])
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def run(script: Path, env: dict[str, str], *args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(script), *args], env=env, cwd=cwd, capture_output=True, text=True, timeout=15
    )


def setup_tools(bin_dir: Path) -> None:
    for name in ("node", "npm", "npx"):
        executable(bin_dir / name, TOOL)


def test_launcher_finds_uv_outside_path_and_preserves_cwd_args_status(machine) -> None:
    repo, _, env = machine
    uv = Path(env["HOME"]) / ".local/bin/uv"
    executable(uv, TOOL)
    env["FAIL_UV"] = "7"
    caller = repo.parent
    result = run(repo / "faultline", env, "gate", "a b", "--json", cwd=caller)
    assert result.returncode == 7, result.stderr
    [call] = calls(env)
    assert call["cwd"] == str(caller)
    assert str(uv.parent) in call["path"].split(os.pathsep)
    assert call["args"] == [
        "run",
        "--project",
        str(repo / "services/repair-orchestrator"),
        "--python",
        "3.13",
        "--locked",
        "--no-env-file",
        "python",
        "-m",
        "app.cli",
        "gate",
        "a b",
        "--json",
    ]


def test_setup_installs_missing_uv_and_managed_python_before_locked_sync(machine) -> None:
    repo, bin_dir, env = machine
    setup_tools(bin_dir)
    executable(
        bin_dir / "curl",
        f"#!{sys.executable}\n"
        "import os\nfrom pathlib import Path\n"
        f"body = {TOOL!r}\n"
        "target = Path(os.environ['HOME']) / '.local/bin/uv'\n"
        "target.parent.mkdir(parents=True)\ntarget.write_text(body)\ntarget.chmod(0o755)\n"
        "print('exit 0')\n",
    )
    result = run(repo / "scripts/setup.sh", env, cwd=repo.parent)
    assert result.returncode == 0, result.stderr
    recorded = calls(env)
    assert next(c for c in recorded if c["tool"] == "uv")["args"] == ["python", "install", "3.13"]
    assert [c["args"] for c in recorded if c["tool"] == "uv"][1:] == [
        ["sync", "--project", "apps/buggyshop-backend", "--python", "3.13", "--locked"],
        ["sync", "--project", "services/repair-orchestrator", "--python", "3.13", "--locked"],
    ]
    assert [c["args"] for c in recorded if c["tool"] == "npm"] == [
        *(
            ["--prefix", project, "ci"]
            for project in ("apps/buggyshop-frontend", "tools/browser-runner", "web/inspector-ui")
        ),
        ["--prefix", "tools/browser-runner", "run", "build"],
    ]
    assert recorded[-1]["args"] == ["playwright", "install", "chromium"]


@pytest.mark.parametrize(
    "location", [".local/bin", ".cargo/bin", "../homebrew/bin", "../local/bin"]
)
def test_launcher_fallback_and_bsd_symlink_chain(machine, location: str) -> None:
    repo, bin_dir, env = machine
    executable(Path(env["HOME"]) / location / "uv", TOOL)
    # Reject the GNU-only flags even on a Linux test host.
    readlink = shutil.which("readlink")
    executable(
        bin_dir / "readlink",
        f'#!/bin/sh\ncase "$1" in -*) exit 91;; esac\nexec "{readlink}" "$@"\n',
    )
    links = repo.parent / "links with spaces"
    links.mkdir()
    (links / "relative link").symlink_to("../repo with spaces/faultline")
    (bin_dir / "faultline").symlink_to(links / "relative link")
    result = run(bin_dir / "faultline", env, "init", cwd=links)
    assert result.returncode == 0, result.stderr
    [call] = calls(env)
    assert call["cwd"] == str(links)
    assert call["args"][2] == str(repo / "services/repair-orchestrator")
    assert call["args"][-1] == "init"


def test_launcher_prefers_uv_on_path(machine) -> None:
    repo, bin_dir, env = machine
    executable(bin_dir / "uv", TOOL)
    executable(Path(env["HOME"]) / ".local/bin/uv", "#!/bin/sh\nexit 92\n")
    assert run(repo / "faultline", env, "--help", cwd=repo).returncode == 0


def test_launcher_without_uv_explains_setup(machine) -> None:
    repo, _, env = machine
    result = run(repo / "faultline", env, "--help", cwd=repo)
    assert result.returncode == 1
    assert "make setup" in result.stderr
    assert "command not found" not in result.stderr


@pytest.mark.parametrize(
    "arguments",
    [
        "python install 3.13",
        "sync --project apps/buggyshop-backend --python 3.13 --locked",
        "sync --project services/repair-orchestrator --python 3.13 --locked",
        "--prefix apps/buggyshop-frontend ci",
        "--prefix tools/browser-runner run build",
        "playwright install chromium",
    ],
)
def test_setup_stops_on_native_failure(machine, arguments: str) -> None:
    repo, bin_dir, env = machine
    setup_tools(bin_dir)
    executable(bin_dir / "uv", TOOL)
    env["FAIL_ARGS"] = arguments
    result = run(repo / "scripts/setup.sh", env, cwd=repo.parent)
    assert result.returncode == 37, result.stderr
    assert " ".join(calls(env)[-1]["args"]) == arguments


@pytest.mark.parametrize("failure", ["download", "installer", "discovery"])
def test_setup_does_not_continue_after_uv_install_failure(machine, failure: str) -> None:
    repo, bin_dir, env = machine
    setup_tools(bin_dir)
    if failure == "download":
        body = "#!/bin/sh\nexit 9\n"
    elif failure == "installer":
        body = "#!/bin/sh\nprintf 'exit 23\\n'\n"
    else:
        body = "#!/bin/sh\nprintf 'exit 0\\n'\n"
    executable(bin_dir / "curl", body)
    result = run(repo / "scripts/setup.sh", env, cwd=repo)
    assert result.returncode == {"download": 9, "installer": 23, "discovery": 1}[failure]
    assert not calls(env)
    if failure == "discovery":
        assert "Add it to PATH" in result.stderr


@pytest.mark.parametrize("missing", ["node", "npm", "npx"])
def test_setup_explains_missing_node_tools(machine, missing: str) -> None:
    repo, bin_dir, env = machine
    setup_tools(bin_dir)
    (bin_dir / missing).unlink()
    executable(bin_dir / "uv", TOOL)
    result = run(repo / "scripts/setup.sh", env, cwd=repo)
    assert result.returncode == 1
    assert f"Missing {missing}" in result.stderr
    assert "Install Node.js" in result.stderr


@pytest.mark.parametrize(
    "version,accepted",
    [
        ("18.20.0", False),
        ("20.8.0", False),
        ("20.19.0", True),
        ("22.12.0", False),
        ("22.13.0", True),
        ("24.0.0", True),
    ],
)
def test_setup_checks_actual_locked_node_floor(machine, version: str, accepted: bool) -> None:
    repo, bin_dir, env = machine
    setup_tools(bin_dir)
    executable(bin_dir / "uv", TOOL)
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed to evaluate the actual setup version expression")
    executable(
        bin_dir / "node",
        f"#!{sys.executable}\nimport os, sys\n"
        f"os.execv({node!r}, ['node', '-e', "
        f'\'Object.defineProperty(process.versions, "node", {{value: "{version}"}});\''
        " + sys.argv[2]])\n",
    )
    result = run(repo / "scripts/setup.sh", env, cwd=repo)
    assert (result.returncode == 0) == accepted, result.stderr
    if not accepted:
        assert "20.19+" in result.stderr
        assert not calls(env)


@pytest.mark.skipif(not PWSH, reason="PowerShell is optional on Unix")
def test_powershell_setup_checks_native_failures_and_restores_cwd(machine) -> None:
    repo, bin_dir, env = machine
    setup_tools(bin_dir)
    executable(bin_dir / "node", f"#!{sys.executable}\nprint('v24.0.0')\n")
    executable(bin_dir / "uv", TOOL)
    env["FAIL_ARGS"] = "--prefix tools/browser-runner run build"
    result = subprocess.run(
        [PWSH, "-NoProfile", "-File", str(repo / "setup.ps1")],
        env=env,
        cwd=repo.parent,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 37, result.stdout + result.stderr
    assert calls(env)[-1]["args"] == ["--prefix", "tools/browser-runner", "run", "build"]


@pytest.mark.skipif(not PWSH, reason="PowerShell is optional on Unix")
def test_powershell_launcher_fallback_cwd_args_status(machine) -> None:
    repo, _, env = machine
    executable(Path(env["HOME"]) / ".cargo/bin/uv.exe", TOOL)
    env["FAIL_UV.EXE"] = "7"
    result = subprocess.run(
        [PWSH, "-NoProfile", "-File", str(repo / "faultline.ps1"), "gate", "a b", "--json"],
        env=env,
        cwd=repo.parent,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 7, result.stdout + result.stderr
    [call] = calls(env)
    assert call["cwd"] == str(repo.parent)
    assert call["args"][-3:] == ["gate", "a b", "--json"]


@pytest.mark.parametrize("stop", ["service_exit", "signal"])
def test_demo_without_setsid_or_system_python_cleans_owned_sessions(machine, stop: str) -> None:
    import signal
    import time

    repo, bin_dir, env = machine
    for project in ("apps/buggyshop-frontend", "tools/browser-runner", "web/inspector-ui"):
        (repo / project / "node_modules").mkdir()
    (bin_dir / "env").symlink_to(shutil.which("env"))
    env["SESSIONS"] = str(repo.parent / "sessions")
    env["STOP_SERVICE"] = str(repo.parent / "stop")
    env["FAULTLINE_CONTROL_TOKEN"] = "test-session-only"
    service = (
        "import json, os, signal, subprocess, sys, time\n"
        "from pathlib import Path\n"
        "def stopped(*_): raise SystemExit(0)\n"
        "signal.signal(signal.SIGTERM, stopped)\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "with open(os.environ['SESSIONS'], 'a') as log:\n"
        "    log.write(json.dumps([os.getpid(), os.getpgrp(), os.getsid(0), child.pid]) + '\\n')\n"
        "try:\n"
        "    while True:\n"
        "        if Path.cwd().name == 'inspector-ui' "
        "and Path(os.environ['STOP_SERVICE']).exists():\n"
        "            child.terminate()\n"
        "            sys.exit(37)\n"
        "        time.sleep(0.05)\n"
        "finally: child.wait(timeout=5)\n"
    )
    executable(
        bin_dir / "uv",
        f"#!{sys.executable}\nimport sys\n"
        f"service = {service!r}\n"
        "if 'uvicorn' in sys.argv: exec(service)\n"
        "elif 'sys.executable' in sys.argv[-1]: print(sys.executable)\n",
    )
    executable(
        bin_dir / "node",
        f"#!{sys.executable}\nimport sys\n"
        f"service = {service!r}\n"
        "if '-e' not in sys.argv: exec(service)\n",
    )
    executable(bin_dir / "npm", "#!/bin/sh\nexit 0\n")
    executable(
        bin_dir / "curl",
        f"#!{sys.executable}\nimport os, sys\nfrom pathlib import Path\n"
        "p = Path(os.environ['SESSIONS'])\n"
        "sys.exit(0 if p.exists() and len(p.read_text().splitlines()) == 4 else 1)\n",
    )
    output = repo.parent / "demo.log"
    process = None
    try:
        with output.open("w") as log:
            process = subprocess.Popen(
                [str(repo / "scripts/start-demo.sh")], env=env, stdout=log, stderr=log
            )
            deadline = time.monotonic() + 10
            while "FaultLine is running" not in output.read_text():
                assert process.poll() is None, output.read_text()
                assert time.monotonic() < deadline, output.read_text()
                time.sleep(0.05)
            if stop == "service_exit":
                Path(env["STOP_SERVICE"]).touch()
            else:
                process.send_signal(signal.SIGTERM)
            assert process.wait(timeout=10) == (37 if stop == "service_exit" else 143)
        sessions = [json.loads(line) for line in Path(env["SESSIONS"]).read_text().splitlines()]
        assert len(sessions) == 4
        for pid, group, session, descendant in sessions:
            assert pid == group == session
            for owned in (pid, descendant):
                with pytest.raises(ProcessLookupError):
                    os.kill(owned, 0)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        if Path(env["SESSIONS"]).exists():
            for _pid, group, _session, _child in map(
                json.loads, Path(env["SESSIONS"]).read_text().splitlines()
            ):
                try:
                    os.killpg(group, signal.SIGKILL)
                except ProcessLookupError:
                    pass


@pytest.mark.skipif(not PWSH, reason="PowerShell is optional on Unix")
@pytest.mark.parametrize(
    "failure",
    [
        None,
        "module",
        "download",
        "script",
        "native",
        "discovery",
        "zip_download",
        "zip_invalid",
        "zip_missing",
    ],
)
def test_powershell_setup_installs_uv_from_official_script_or_zip(machine, failure) -> None:
    repo, bin_dir, env = machine
    setup_tools(bin_dir)
    executable(bin_dir / "node", f"#!{sys.executable}\nprint('v24.0.0')\n")
    # Replace only the download seam; execute the real discovery and native commands.
    destination = Path(env["HOME"]) / ".local/bin/uv.exe"
    destination.parent.mkdir(parents=True)
    installer = (
        f"[IO.File]::WriteAllText('{destination}', '{TOOL.replace(chr(39), chr(39) * 2)}')\n"
        f"& /bin/chmod 755 '{destination}'\n"
    )
    if failure == "script":
        installer = "throw 'Get-ExecutionPolicy: Microsoft.PowerShell.Security could not be loaded'"
    elif failure == "native":
        installer = "$global:LASTEXITCODE = 23"
    elif failure == "discovery":
        installer = "# Installer returned without installing uv"
    installer_path = repo.parent / "mock-install.ps1"
    installer_path.write_text(installer)
    archive = repo.parent / "uv.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for binary in ("uv.exe", "uvx.exe"):
            if failure != "zip_missing":
                bundle.writestr(binary, TOOL)
    if failure == "zip_invalid":
        archive.write_bytes(b"not a zip file")
    env["INSTALL_FAILURE"] = failure or ""
    env["MOCK_UV_ZIP"] = str(archive)
    env["INSTALL_TEMP"] = str(repo.parent / "install-temp")
    Path(env["INSTALL_TEMP"]).mkdir()
    env["TMPDIR"] = env["INSTALL_TEMP"]
    wrapper = repo.parent / "install-wrapper.ps1"
    wrapper.write_text(
        "function Import-Module { param($Name, $ErrorAction)\n"
        "if ($Name -eq 'Microsoft.PowerShell.Security' -and $env:INSTALL_FAILURE -eq 'module') "
        "{ throw 'Microsoft.PowerShell.Security could not be loaded' }\n"
        "Microsoft.PowerShell.Core\\Import-Module $Name -ErrorAction $ErrorAction\n}\n"
        "function Invoke-RestMethod { param($Uri)\n"
        "if ($Uri -ne 'https://astral.sh/uv/install.ps1') { throw 'Unexpected installer URL' }\n"
        "if ($env:INSTALL_FAILURE -eq 'download' -or $env:INSTALL_FAILURE -like 'zip_*') "
        "{ throw 'Installer download failed' }\n"
        f"[IO.File]::ReadAllText('{installer_path}')\n}}\n"
        "function Invoke-WebRequest { param($Uri, $OutFile, [switch]$UseBasicParsing)\n"
        "if (-not $env:INSTALL_FAILURE) { throw 'Successful installer must not download zip' }\n"
        "if ($Uri -ne 'https://github.com/astral-sh/uv/releases/latest/download/"
        "uv-x86_64-pc-windows-msvc.zip') { throw 'Unexpected zip URL' }\n"
        "if ($env:INSTALL_FAILURE -eq 'zip_download') { throw 'Zip download failed' }\n"
        "[IO.File]::Copy($env:MOCK_UV_ZIP, $OutFile)\n}\n"
        # Zip permissions are executable on Windows; make the fake .exe executable on Unix.
        "function Expand-Archive { param($LiteralPath, $DestinationPath)\n"
        "Microsoft.PowerShell.Archive\\Expand-Archive -LiteralPath $LiteralPath "
        "-DestinationPath $DestinationPath\n"
        "Get-ChildItem $DestinationPath -Filter '*.exe' | "
        "ForEach-Object { & /bin/chmod 755 $_.FullName }\n}\n"
        f"& '{repo / 'setup.ps1'}'\n"
        "exit $LASTEXITCODE\n"
    )
    result = subprocess.run(
        [PWSH, "-NoProfile", "-File", str(wrapper)],
        env=env,
        cwd=repo.parent,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert not list(Path(env["INSTALL_TEMP"]).glob("faultline-uv-*"))
    if failure and failure.startswith("zip_"):
        assert result.returncode == 1, result.stdout + result.stderr
        assert not calls(env)
        return
    assert result.returncode == 0, result.stdout + result.stderr
    uv_calls = [c for c in calls(env) if c["tool"] == "uv.exe"]
    assert uv_calls[0]["args"] == ["python", "install", "3.13"]
    assert len(uv_calls) == 3
    assert calls(env)[-1]["args"] == ["playwright", "install", "chromium"]
    if failure:
        assert (destination.parent / "uvx.exe").is_file()
        assert "zip" in result.stdout.lower()


@pytest.fixture
def powershell_demo(machine):
    repo, bin_dir, env = machine
    for project in ("apps/buggyshop-frontend", "tools/browser-runner", "web/inspector-ui"):
        (repo / project / "node_modules").mkdir()
    npm_bin = bin_dir / "npm tools with spaces"
    npm_cli = npm_bin / "node_modules/npm/bin/npm-cli.js"
    npm_cli.parent.mkdir(parents=True)
    npm_cli.touch()
    executable(npm_bin / "npm", TOOL)
    env["PATH"] = str(npm_bin) + os.pathsep + env["PATH"]
    service = (
        "import hashlib, threading, time\n"
        "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
        "is_uv = 'uvicorn' in sys.argv\n"
        "port = int(sys.argv[sys.argv.index('--port' if is_uv else '-p') + 1])\n"
        "app = 'buggyshop-api' if Path.cwd().name == 'buggyshop-backend' "
        "else 'faultline-orchestrator'\n"
        "token = os.environ.get('FAULTLINE_CONTROL_TOKEN', '')\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "record = {'pid': os.getpid(), 'child': child.pid, 'port': port, "
        "'cwd': os.getcwd(), 'args': sys.argv[1:], 'token_length': len(token), "
        "'token_hash': hashlib.sha256(token.encode()).hexdigest(), "
        "'runtime': os.environ.get('FAULTLINE_RUNTIME'), "
        "'backend': os.environ.get('BUGGYSHOP_BACKEND_URL'), "
        "'controller': os.environ.get('FAULTLINE_ORCHESTRATOR_URL')}\n"
        "with open(os.environ['SESSIONS'], 'a') as log: log.write(json.dumps(record)+'\\n')\n"
        "if os.environ.get('DEMO_CASE') == 'startup_exit': "
        "child.terminate(); child.wait(); sys.exit(37)\n"
        "class Handler(BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        healthy = os.environ.get('DEMO_CASE') != 'timeout'\n"
        "        self.send_response(200 if healthy else 503)\n"
        "        self.send_header('Content-Type', 'application/json'); self.end_headers()\n"
        "        name = 'foreign' if os.environ.get('DEMO_CASE') == 'wrong_identity' else app\n"
        "        self.wfile.write(json.dumps({'app': name, 'status': 'ok'}).encode())\n"
        "    def log_message(self, *_): pass\n"
        "server = HTTPServer(('127.0.0.1', port), Handler)\n"
        "threading.Thread(target=server.serve_forever, daemon=True).start()\n"
        "while True:\n"
        "    if Path(os.environ['EXIT_SERVICE']).exists() and Path.cwd().name == 'inspector-ui':\n"
        "        child.terminate(); child.wait(); sys.exit(37)\n"
        "    time.sleep(0.05)\n"
    )
    stub = (
        f"#!{sys.executable}\nimport json, os, subprocess, sys\nfrom pathlib import Path\n"
        f"service = {service!r}\n"
        "if '--version' in sys.argv: print('v24.0.0'); sys.exit(0)\n"
        "if 'uvicorn' in sys.argv or 'node_modules/next/dist/bin/next' in sys.argv: "
        "exec(service)\n"
        "with open(os.environ['CALLS'], 'a') as log:\n"
        "    log.write(json.dumps({'args': sys.argv[1:]})+'\\n')\n"
        "sys.exit(37 if os.environ.get('DEMO_CASE') == 'build' else 0)\n"
    )
    executable(bin_dir / "uv", stub)
    executable(bin_dir / "node", stub)
    env["SESSIONS"] = str(repo.parent / "sessions.jsonl")
    env["EXIT_SERVICE"] = str(repo.parent / "exit-service")
    env["DEMO_STOP"] = str(repo.parent / "stop-demo")
    # Reserve four different ephemeral ports for the fixture before releasing them.
    with socket.socket() as a, socket.socket() as b, socket.socket() as c, socket.socket() as d:
        for listener, name in zip(
            (a, b, c, d),
            ("BUGGYSHOP_API_PORT", "FAULTLINE_PORT", "BUGGYSHOP_PORT", "INSPECTOR_PORT"),
            strict=True,
        ):
            listener.bind(("127.0.0.1", 0))
            env[name] = str(listener.getsockname()[1])
    return repo, bin_dir, env


@pytest.mark.skipif(not PWSH, reason="PowerShell is optional on Unix")
@pytest.mark.parametrize(
    "case", ["stop", "service_exit", "startup_exit", "build", "timeout", "wrong_identity"]
)
def test_powershell_demo_supervises_health_credentials_and_child_trees(powershell_demo, case):
    repo, _, env = powershell_demo
    env["DEMO_CASE"] = case
    if case == "service_exit":
        env["FAULTLINE_CONTROL_TOKEN"] = "test-session-credential-preserved"
    if case in {"timeout", "wrong_identity"}:
        script = repo / "scripts/start-demo.ps1"
        script.write_text(script.read_text().replace("AddSeconds(120)", "AddSeconds(1)"))
    output = repo.parent / "powershell-demo.log"
    process = None
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        with output.open("w") as log:
            process = subprocess.Popen(
                [
                    PWSH,
                    "-NoProfile",
                    "-File",
                    str(repo / "scripts/start-demo.ps1"),
                    "-StopFile",
                    env["DEMO_STOP"],
                ],
                env=env,
                cwd=repo.parent,
                stdout=log,
                stderr=log,
            )
            if case in {"stop", "service_exit"}:
                deadline = time.monotonic() + 15
                while "FaultLine Inspector:" not in output.read_text():
                    assert process.poll() is None, output.read_text()
                    assert time.monotonic() < deadline, output.read_text()
                    time.sleep(0.05)
                Path(env["DEMO_STOP"] if case == "stop" else env["EXIT_SERVICE"]).touch()
            code = process.wait(timeout=20)
        log = output.read_text()
        assert code == (130 if case == "stop" else 1), log
        assert unrelated.poll() is None
        records = calls({"CALLS": env["SESSIONS"]})
        if case == "build":
            assert not records
            assert "command failed (exit 37)" in log
        elif case != "startup_exit":
            assert len(records) == 4, log
            assert len({record["token_hash"] for record in records}) == 1
            assert all(record["token_length"] >= 32 for record in records)
            if case == "service_exit":
                assert (
                    records[0]["token_hash"]
                    == hashlib.sha256(env["FAULTLINE_CONTROL_TOKEN"].encode()).hexdigest()
                )
            assert all(record["runtime"] == "isolated" for record in records)
            assert {record["cwd"] for record in records} == {
                str(repo / directory)
                for directory in (
                    "apps/buggyshop-backend",
                    "services/repair-orchestrator",
                    "apps/buggyshop-frontend",
                    "web/inspector-ui",
                )
            }
            assert all("127.0.0.1" in record["args"] for record in records)
            if case in {"timeout", "wrong_identity"}:
                assert "timed out" in log and "FaultLine Inspector:" not in log
            else:
                assert f"http://127.0.0.1:{env['INSPECTOR_PORT']}" in log
                assert f"http://127.0.0.1:{env['BUGGYSHOP_PORT']}" in log
        assert "test-session-credential-preserved" not in log
        for record in records:
            for pid in (record["pid"], record["child"]):
                stat = Path(f"/proc/{pid}/stat")
                assert not stat.exists() or stat.read_text().rsplit(")", 1)[1].split()[0] == "Z"
        # Rebind every service port: cleanup releases the actual listeners.
        for name in ("BUGGYSHOP_API_PORT", "FAULTLINE_PORT", "BUGGYSHOP_PORT", "INSPECTOR_PORT"):
            with socket.socket() as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                probe.bind(("127.0.0.1", int(env[name])))
    finally:
        if process is not None and process.poll() is None:
            Path(env["DEMO_STOP"]).touch()
            process.wait(timeout=10)
        unrelated.terminate()
        unrelated.wait(timeout=5)


@pytest.mark.skipif(not PWSH, reason="PowerShell is optional on Unix")
@pytest.mark.parametrize("case", ["occupied", "duplicate", "invalid"])
def test_powershell_demo_rejects_ports_before_building(powershell_demo, case):
    repo, _, env = powershell_demo
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        if case == "occupied":
            env["INSPECTOR_PORT"] = str(listener.getsockname()[1])
        elif case == "duplicate":
            env["INSPECTOR_PORT"] = env["BUGGYSHOP_PORT"]
        else:
            env["INSPECTOR_PORT"] = "65536"
        result = subprocess.run(
            [PWSH, "-NoProfile", "-File", str(repo / "scripts/start-demo.ps1")],
            env=env,
            cwd=repo.parent,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 1, result.stdout + result.stderr
        assert {"occupied": "occupied", "duplicate": "distinct", "invalid": "Invalid"}[
            case
        ] in result.stderr
        assert listener.fileno() >= 0
    assert not calls(env)
    assert not Path(env["SESSIONS"]).exists()
