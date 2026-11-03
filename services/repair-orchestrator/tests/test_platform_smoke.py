"""Cross-platform isolation-engine detection and CLI dispatch smoke tests.

These tests simulate Darwin, Windows, and Linux hosts by reassigning
``sys.platform`` and stubbing ``shutil.which``, so they exercise the platform
capability report and the ``faultline run``/``status``/``version`` reporting
without launching a sandbox or requiring any host isolation binary.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from app import portable

REPO_ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = Path(__file__).resolve().parents[1]


def _fake_which(present: set[str]) -> Any:
    def which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in present else None

    return which


@pytest.mark.parametrize(
    ("platform", "expected"),
    [("linux", "linux"), ("darwin", "darwin"), ("win32", "windows")],
)
def test_detect_host_reads_reassigned_platform(
    monkeypatch: pytest.MonkeyPatch, platform: str, expected: str
) -> None:
    """The CLI's host detection honors a reassigned interpreter platform."""
    monkeypatch.setattr(sys, "platform", platform)
    assert portable.detect_host() == expected


def test_darwin_sandbox_exec_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(shutil, "which", _fake_which({"sandbox-exec", "docker"}))
    capabilities = portable.platform_capabilities()
    assert capabilities.host == "darwin"
    assert (capabilities.engine, capabilities.mode) == ("sandbox-exec", "rlimits")
    assert capabilities.native is True
    assert capabilities.docker is True
    assert capabilities.missing == ()
    assert "Docker fallback available" in capabilities.summary


def test_darwin_docker_fallback_without_sandbox_exec(monkeypatch: pytest.MonkeyPatch) -> None:
    """sandbox-exec is deprecated on Apple Silicon; Docker is the safe fallback."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(shutil, "which", _fake_which({"docker"}))
    capabilities = portable.platform_capabilities()
    assert (capabilities.engine, capabilities.mode) == ("docker", "docker")
    assert capabilities.native is False
    assert capabilities.docker is True
    assert capabilities.missing == ("sandbox-exec",)


def test_darwin_no_backend_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(shutil, "which", _fake_which(set()))
    capabilities = portable.platform_capabilities()
    assert capabilities.native is False
    assert capabilities.docker is False
    assert capabilities.missing == ("sandbox-exec", "docker")
    assert "no isolation backend available" in capabilities.summary


def test_windows_job_object_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(shutil, "which", _fake_which({"pwsh"}))
    capabilities = portable.platform_capabilities()
    assert capabilities.host == "windows"
    assert (capabilities.engine, capabilities.mode) == ("windows-job", "windows-job")
    assert capabilities.native is True
    assert "Job Objects" in capabilities.summary


def test_windows_without_powershell_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(shutil, "which", _fake_which(set()))
    capabilities = portable.platform_capabilities()
    assert capabilities.native is False
    assert capabilities.missing == ("pwsh",)
    assert "PowerShell missing" in capabilities.summary


def test_linux_bubblewrap_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", _fake_which({"bwrap"}))
    capabilities = portable.platform_capabilities()
    assert capabilities.host == "linux"
    assert (capabilities.engine, capabilities.mode) == ("bubblewrap", "cgroup-v2-scope")
    assert capabilities.native is True


def test_linux_docker_fallback_without_bubblewrap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", _fake_which({"docker"}))
    capabilities = portable.platform_capabilities()
    assert (capabilities.engine, capabilities.mode) == ("docker", "docker")
    assert capabilities.native is False
    assert capabilities.missing == ("bwrap",)


def test_linux_no_backend_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", _fake_which(set()))
    capabilities = portable.platform_capabilities()
    assert capabilities.native is False
    assert capabilities.missing == ("bwrap", "docker")
    assert "no isolation backend available" in capabilities.summary


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_run_command_reports_engine_without_linux_imports(platform: str) -> None:
    """``faultline run`` exits 30 on non-Linux, names the engine, and never
    imports the Linux-only runtime modules."""
    script = """
import sys
from app import cli
import argparse
sys.platform = sys.argv[1]
assert cli.cmd_run(argparse.Namespace()) == 30
assert "app.run" not in sys.modules
assert "app.isolated_runtime" not in sys.modules
assert "app.project_runtime" not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", script, platform],
        cwd=SERVICE_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "faultline run:" in result.stderr
    assert "isolation engine" in result.stderr.lower()
    assert "check, test, scan, init, and gate" in result.stderr


def test_version_reports_isolation_engine(capsys: pytest.CaptureFixture[str]) -> None:
    from app import cli

    assert cli.cmd_version(argparse.Namespace()) == 0
    output = capsys.readouterr().out
    assert "Platform:" in output
    assert "Isolation:" in output


def test_status_reports_isolation_engine(capsys: pytest.CaptureFixture[str]) -> None:
    from app import cli

    with patch(
        "app.cli._api_request",
        return_value={
            "status": "ready",
            "runtime_ready": True,
            "quarantined": False,
            "model": {"model": "muse-spark-1.3", "provider": "meta"},
            "resource_limits": None,
        },
    ):
        assert cli.cmd_status(argparse.Namespace()) == 0
    output = capsys.readouterr().out
    assert "Platform:" in output
    assert "Isolation:" in output
