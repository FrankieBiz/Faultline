"""Cross-platform runtime unification: routing, the endpoint seam, and error envelopes.

Covers the three surfaces the unify change touches: ``select_runtime`` routing
(which evaluation now uses on every host), the platform-aware backend endpoint
seam (which ``ProjectRuntime._launch_service`` now binds through instead of a
hard-coded abstract Unix socket), and the consistent capability/error envelope
``faultline run`` emits when a host cannot run a sandboxed project reproduction.

No sandbox, Job Object, or bubblewrap namespace is launched here: the assertions
inspect routing, transport selection, inherited descriptors, and the exact
reason codes and messages each platform reports, so the suite runs on every host.
"""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

import app.portable as portable
from app.isolated_runtime import (
    BackendResources,
    BoundedTCPTransport,
    IsolatedRuntime,
    ManagedProcess,
)
from app.isolation import select_runtime
from app.isolation.darwin import DarwinIsolatedRuntime
from app.isolation.windows import WindowsIsolatedRuntime
from app.runtime import RuntimeUnavailable

GENERATION = "0b9c8d7e-6f5a-4b3c-9d2e-1f0a9b8c7d6e"


# -- select_runtime routing ----------------------------------------------------


def test_select_runtime_routes_to_the_host_engine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """One seam returns the Linux engine, then the Darwin/Windows adapters."""
    monkeypatch.setattr(portable, "IS_WINDOWS", False)
    monkeypatch.setattr(portable, "IS_MACOS", False)
    linux = select_runtime(tmp_path)
    assert isinstance(linux, IsolatedRuntime)
    assert not isinstance(linux, (DarwinIsolatedRuntime, WindowsIsolatedRuntime))
    assert linux.limits_mode == "cgroup-v2-scope"

    monkeypatch.setattr(portable, "IS_MACOS", True)
    darwin = select_runtime(tmp_path)
    assert isinstance(darwin, DarwinIsolatedRuntime)
    assert darwin.limits_mode in {"rlimits", "docker"}

    monkeypatch.setattr(portable, "IS_MACOS", False)
    monkeypatch.setattr(portable, "IS_WINDOWS", True)
    windows = select_runtime(tmp_path)
    assert isinstance(windows, WindowsIsolatedRuntime)
    assert windows.limits_mode == "windows-job"


def test_select_runtime_honors_the_explicit_repository_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(portable, "IS_WINDOWS", False)
    monkeypatch.setattr(portable, "IS_MACOS", False)
    assert select_runtime(tmp_path).root == tmp_path.resolve()


def test_isolated_backend_launcher_selects_the_host_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Evaluation's launcher must pick the adapter for the host, not always Linux."""
    from app.evaluation import IsolatedBackendLauncher

    monkeypatch.setattr(portable, "IS_WINDOWS", False)
    monkeypatch.setattr(portable, "IS_MACOS", False)
    assert type(IsolatedBackendLauncher().runtime).__name__ == "IsolatedRuntime"

    monkeypatch.setattr(portable, "IS_MACOS", True)
    assert isinstance(IsolatedBackendLauncher().runtime, DarwinIsolatedRuntime)

    monkeypatch.setattr(portable, "IS_MACOS", False)
    monkeypatch.setattr(portable, "IS_WINDOWS", True)
    assert isinstance(IsolatedBackendLauncher().runtime, WindowsIsolatedRuntime)


# -- cross-platform endpoint generation ----------------------------------------


def test_linux_endpoint_is_abstract_unix_for_every_generation() -> None:
    if portable.current_host() != "linux":
        pytest.skip("abstract Unix sockets are Linux-only")
    for generation in (str(uuid4()) for _ in range(16)):
        endpoint = portable.backend_endpoint(generation)
        try:
            assert endpoint.kind == "abstract-unix"
            assert endpoint.address == "\0faultline-" + generation
            assert endpoint.socket is not None
            assert endpoint.socket.family == socket.AF_UNIX
        finally:
            if endpoint.socket is not None:
                endpoint.socket.close()


def test_macos_endpoint_is_named_unix_for_every_generation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(portable, "IS_MACOS", True)
    monkeypatch.setattr(portable, "IS_WINDOWS", False)
    for generation in (str(uuid4()) for _ in range(16)):
        endpoint = portable.backend_endpoint(generation, runtime_dir=tmp_path)
        try:
            assert endpoint.kind == "named-unix"
            assert endpoint.address == str(tmp_path / f"flt-{generation[:8]}.sock")
            assert endpoint.socket is not None
            name = Path(endpoint.address).name
            assert name == f"flt-{generation[:8]}.sock"
            assert len(name) < 108  # immune to the AF_UNIX path-length cap
        finally:
            if endpoint.socket is not None:
                endpoint.socket.close()


def test_windows_endpoint_is_loopback_tcp_for_every_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(portable, "IS_WINDOWS", True)
    for _ in range(16):
        endpoint = portable.backend_endpoint(str(uuid4()))
        assert endpoint.kind == "tcp"
        assert endpoint.socket is None
        assert 1 <= int(endpoint.address) <= 65535


# -- ProjectRuntime._launch_service endpoint seam ------------------------------


def _project_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    from app.project_runtime import ProjectRuntime

    run: Any = SimpleNamespace(
        command=lambda port: ["node", "server.js", str(port)],
        project=SimpleNamespace(health="/health"),
    )
    runtime = ProjectRuntime(tmp_path, run)
    monkeypatch.setattr(runtime, "_sandbox", Mock(return_value=["/sandbox"]))
    monkeypatch.setattr(runtime, "scope_environment", Mock(return_value={}))
    monkeypatch.setattr(runtime, "verify_scope", AsyncMock(return_value=None))
    return runtime


@pytest.mark.asyncio
async def test_launch_service_inherits_an_abstract_unix_listener(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The Linux seam passes the inherited listener descriptor, not a port."""
    from app.project_runtime import SessionResources

    runtime = _project_runtime(monkeypatch, tmp_path)
    endpoint = portable.backend_endpoint(GENERATION)
    listener = endpoint.socket
    assert listener is not None
    monkeypatch.setattr(runtime, "_backend_endpoint", Mock(return_value=endpoint))

    class _Sentinel(Exception):
        pass

    async def explode(*args: Any, **kwargs: Any) -> None:
        raise _Sentinel

    start = AsyncMock(side_effect=explode)
    monkeypatch.setattr(ManagedProcess, "start", start)
    owned = SessionResources(BackendResources(unit=None))
    try:
        with pytest.raises(_Sentinel):
            await runtime._launch_service(owned, SimpleNamespace(path=tmp_path), GENERATION)
        runtime._backend_endpoint.assert_called_once_with(GENERATION)
        args = list(start.call_args.args)
        assert args[0] == "/sandbox"
        assert args[1:5] == ["/python/bin/python3.13", "-I", "-u", "/trusted_backend.py"]
        assert args[5] == str(listener.fileno())
        assert args[6] == "8765"
        assert json.loads(args[7]) == ["node", "server.js", "8765"]
        assert start.call_args.kwargs["pass_fds"] == (listener.fileno(),)
        assert owned.backend.listener is listener
        assert owned.backend.socket_path is None
    finally:
        listener.close()


@pytest.mark.asyncio
async def test_launch_service_uses_loopback_tcp_on_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A Windows endpoint reserves a port the child binds; no descriptor is passed."""
    from app.project_runtime import SessionResources

    runtime = _project_runtime(monkeypatch, tmp_path)
    endpoint = SimpleNamespace(socket=None, address="54321", kind="tcp")
    monkeypatch.setattr(runtime, "_backend_endpoint", Mock(return_value=endpoint))
    process = SimpleNamespace(process=SimpleNamespace(returncode=1))
    start = AsyncMock(return_value=process)
    monkeypatch.setattr(ManagedProcess, "start", start)
    owned = SessionResources(BackendResources(unit=None))
    try:
        with pytest.raises(RuntimeUnavailable, match="dev_service_exited"):
            await runtime._launch_service(owned, SimpleNamespace(path=tmp_path), GENERATION)
        runtime._backend_endpoint.assert_called_once_with(GENERATION)
        args = list(start.call_args.args)
        assert args[5] == "54321"
        assert start.call_args.kwargs["pass_fds"] == ()
        assert owned.backend.listener is None
        client = owned.backend.client
        assert client is not None
        assert str(client.base_url) == "http://127.0.0.1:54321"
        assert isinstance(client._transport, BoundedTCPTransport)
    finally:
        if owned.backend.client is not None:
            await owned.backend.client.aclose()


# -- capability and error envelopes -------------------------------------------


def _stub_which(native: str) -> Any:
    def which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name == native else None

    return which


@pytest.mark.parametrize(
    ("platform", "host", "native", "engine", "mode"),
    [
        ("darwin", "darwin", "sandbox-exec", "sandbox-exec", "rlimits"),
        ("win32", "windows", "pwsh", "windows-job", "windows-job"),
    ],
)
def test_run_reports_a_consistent_capability_envelope(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    platform: str,
    host: str,
    native: str,
    engine: str,
    mode: str,
) -> None:
    """The non-Linux guard names the host, engine, mode, and cross-platform commands."""
    from app import cli

    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(shutil, "which", _stub_which(native))
    assert cli.cmd_run(argparse.Namespace()) == 30
    error = capsys.readouterr().err
    assert f"not available on {host}" in error
    assert f"Active isolation engine: {engine} ({mode})" in error
    assert "check, test, scan, init, and gate run natively on this platform." in error


@pytest.mark.asyncio
async def test_adapter_failures_collapse_into_a_single_reason_envelope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Missing boundaries report one specific reason code, never a silent host run."""
    monkeypatch.delenv("FAULTLINE_AGGREGATE_LIMITS", raising=False)
    darwin = DarwinIsolatedRuntime(tmp_path)
    darwin.sandbox_exec = None
    darwin.docker = None
    darwin._docker_mode = True
    with pytest.raises(RuntimeUnavailable, match="sandbox_exec_and_docker_unavailable"):
        await darwin.backend_preflight()

    monkeypatch.setattr(portable, "IS_WINDOWS", True)
    windows = WindowsIsolatedRuntime(tmp_path)
    windows.pwsh = None
    with pytest.raises(RuntimeUnavailable, match="powershell_unavailable"):
        windows._sandbox(tmp_path)
