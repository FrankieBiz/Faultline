"""Install real wheels in separate clean environments and run outside the checkout."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROJECTS = {
    "backend": ROOT / "apps/buggyshop-backend",
    "orchestrator": ROOT / "services/repair-orchestrator",
}


@dataclass(frozen=True)
class Installation:
    root: Path
    python: Path
    faultline: Path
    env: dict[str, str] = field(repr=False)

    def run(self, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.faultline), *args],
            cwd=cwd,
            env=self.env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )


def checked(argv: list[str], cwd: Path, env: dict[str, str]) -> str:
    result = subprocess.run(
        argv, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", timeout=180
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


@pytest.fixture(scope="module")
def installations() -> Iterator[dict[str, Installation]]:
    uv = shutil.which("uv")
    assert uv is not None, "Distribution tests require uv, as does make check"
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("PYTHON", "UV_PROJECT", "FAULTLINE_", "GIT_"))
        and key != "VIRTUAL_ENV"
    }
    env.update(PYTHONNOUSERSITE="1", PYTHONUTF8="1", NO_COLOR="1")
    # Do not let pytest --basetemp put the installation or caller inside the checkout.
    with tempfile.TemporaryDirectory(prefix="faultline-distribution-") as temporary:
        root = Path(temporary).resolve()
        assert not root.is_relative_to(ROOT)
        installed = {}
        for name, project in PROJECTS.items():
            wheel_dir = root / f"{name}-dist"
            # The default builds an sdist, then a wheel from that sdist. This also
            # verifies that external shared sources survive the source archive.
            checked(
                [
                    uv,
                    "build",
                    "--project",
                    str(project),
                    "--python",
                    sys.executable,
                    "--no-sources",
                    "--out-dir",
                    str(wheel_dir),
                ],
                root,
                env,
            )
            wheels = list(wheel_dir.glob("*.whl"))
            assert len(wheels) == 1
            venv = root / f"{name}-venv"
            checked([uv, "venv", "--python", sys.executable, str(venv)], root, env)
            scripts = venv / ("Scripts" if os.name == "nt" else "bin")
            python = scripts / ("python.exe" if os.name == "nt" else "python")
            checked([uv, "pip", "install", "--python", str(python), str(wheels[0])], root, env)
            installed[name] = Installation(
                root,
                python,
                scripts / ("faultline.exe" if os.name == "nt" else "faultline"),
                env,
            )
        yield installed


@pytest.mark.parametrize("distribution", PROJECTS)
def test_installed_imports(installations: dict[str, Installation], distribution: str) -> None:
    installation = installations[distribution]
    modules = (
        "app.main"
        if distribution == "backend"
        else "app.cli_check, app.project, app.run, shared.config, shared.contracts.models"
    )
    checked(
        [
            str(installation.python),
            "-I",
            "-c",
            f"import sys, app; import {modules}; "
            "from pathlib import Path; "
            "assert Path(app.__file__).is_relative_to(sys.prefix); "
            f"assert all(not p or not Path(p).is_relative_to({str(ROOT)!r}) for p in sys.path)",
        ],
        installation.root,
        installation.env,
    )


@pytest.mark.parametrize("command", [None, "check", "gate", "init", "run"])
def test_installed_help(installations: dict[str, Installation], command: str | None) -> None:
    installation = installations["orchestrator"]
    args = [command, "--help"] if command else ["--help"]
    result = installation.run(*args, cwd=installation.root)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "usage: faultline" in result.stdout
    if command:
        assert f"faultline {command}" in result.stdout
    else:
        for name in ("check", "gate", "init", "run"):
            assert name in result.stdout


@pytest.fixture
def service() -> Iterator[int]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = b'{"ready":true}'
            self.send_response(503 if self.path == "/broken" else 200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def assert_check(result: subprocess.CompletedProcess[str], *, passed: bool) -> None:
    assert result.returncode in (0, 1), result.stdout + result.stderr
    assert result.stdout.strip().startswith("{"), result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert len(report["checks"]) == 1, report
    check = report["checks"][0]
    assert check["passed"] is passed, report
    assert len(check["sessions"]) == 2, report
    assert check["repair"]["status"] == "not_requested"
    # Preserve the existing Linux prerequisite policy, even for a live-only check.
    missing = sys.platform == "linux" and not report["sandbox"]["prerequisites_available"]
    assert report["errors"] == (
        ["Sandbox prerequisites missing; run faultline doctor."] if missing else []
    ), report
    assert report["passed"] is (passed and not missing), report
    assert result.returncode == (0 if passed and not missing else 1), report


@pytest.mark.parametrize("route", ["/health", "/broken"])
@pytest.mark.parametrize("foreign_caller", [False, True])
def test_installed_check_outside_repository(
    installations: dict[str, Installation], service: int, route: str, foreign_caller: bool
) -> None:
    installation = installations["orchestrator"]
    with tempfile.TemporaryDirectory(
        dir=installation.root, prefix="synthetic project "
    ) as directory:
        project = Path(directory)
        (project / "source").mkdir()
        config = project / "faultline.toml"
        config.write_text(
            'schema = 1\n[project]\nname = "external"\nroot = "source"\n'
            'dev_command = "must-not-execute-project-code"\n'
            '[[invariants.rule]]\nid = "health"\nexpected_status = 200\n'
            f'target = "http://127.0.0.1:{{port}}{route}"\n',
            encoding="utf-8",
        )
        cwd = installation.root if foreign_caller else project
        result = installation.run(
            "check",
            "--config",
            str(config.relative_to(cwd)),
            "--port",
            str(service),
            "--json",
            cwd=cwd,
        )
        assert_check(result, passed=route == "/health")
        assert sorted(p.name for p in project.iterdir()) == ["faultline.toml", "source"]


def test_installed_init_in_blank_directory(
    installations: dict[str, Installation], service: int
) -> None:
    installation = installations["orchestrator"]
    with tempfile.TemporaryDirectory(dir=installation.root, prefix="blank project ") as directory:
        project = Path(directory)
        assert list(project.iterdir()) == []
        result = installation.run("init", cwd=project)
        assert result.returncode == 0, result.stdout + result.stderr
        config = project / "faultline.toml"
        data = tomllib.loads(config.read_text(encoding="utf-8"))
        assert data["schema"] == 1
        assert data["project"]["root"] == "."
        assert sorted(p.name for p in project.iterdir()) == ["faultline.toml"]
        checked(
            [
                str(installation.python),
                "-I",
                "-c",
                "from pathlib import Path; from app.cli_check import validate_config; "
                "assert validate_config(Path('faultline.toml')).root == Path.cwd()",
            ],
            project,
            installation.env,
        )
        assert_check(
            installation.run("check", "--port", str(service), "--json", cwd=project), passed=True
        )
        original = config.read_bytes()
        result = installation.run("init", cwd=project)
        assert result.returncode == 0, result.stdout + result.stderr
        assert config.read_bytes() == original
