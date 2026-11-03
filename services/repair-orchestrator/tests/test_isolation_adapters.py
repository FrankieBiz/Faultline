"""Multiplatform isolation adapters: host selection, argv, profiles, and modes.

Nothing here launches a sandbox or contacts a real systemd / Docker / Job
Object. These tests assert the adapters build the correct argv, profile, and
limit records so the platform-specific mechanisms can be verified on their own
hosts, and that the Linux seam refactor preserves the abstract-socket backend.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, cast

import pytest

import app.portable as portable
from app.isolated_runtime import IsolatedRuntime, ManagedProcess
from app.isolation import select_runtime
from app.isolation.darwin import DARWIN_MEMORY_MAX_BYTES, DARWIN_TASKS_MAX, sandbox_profile
from app.isolation.windows import windows_job_script
from shared.contracts.models import ResourceLimits

GENERATION = "0b9c8d7e-6f5a-4b3c-9d2e-1f0a9b8c7d6e"
NO_PROCESS = cast(ManagedProcess, object())


def test_current_host_matches_platform() -> None:
    if os.name == "nt":
        assert portable.current_host() == "windows"
    elif sys.platform == "darwin":
        assert portable.current_host() == "darwin"
    else:
        assert portable.current_host() == "linux"


def test_select_runtime_returns_linux_engine_on_linux() -> None:
    if portable.current_host() != "linux":
        pytest.skip("selection differs by host; asserted on Linux")
    assert isinstance(select_runtime(), IsolatedRuntime)


def test_portable_pipe_is_close_on_exec() -> None:
    read_fd, write_fd = portable.portable_pipe()
    try:
        assert read_fd >= 0 and write_fd >= 0
        if hasattr(os, "get_inheritable"):
            assert os.get_inheritable(read_fd) is False
            assert os.get_inheritable(write_fd) is False
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_backend_endpoint_is_abstract_unix_on_linux() -> None:
    if portable.current_host() != "linux":
        pytest.skip("abstract Unix sockets are Linux-only")
    endpoint = portable.backend_endpoint(GENERATION)
    try:
        assert endpoint.kind == "abstract-unix"
        assert endpoint.address.startswith("\0faultline-")
        assert endpoint.socket is not None
    finally:
        if endpoint.socket is not None:
            endpoint.socket.close()


def test_backend_endpoint_is_named_unix_on_macos(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(portable, "IS_MACOS", True)
    monkeypatch.setattr(portable, "IS_WINDOWS", False)
    endpoint = portable.backend_endpoint(GENERATION, runtime_dir=tmp_path)
    try:
        assert endpoint.kind == "named-unix"
        assert endpoint.address == str(tmp_path / f"flt-{GENERATION[:8]}.sock")
        assert endpoint.socket is not None
    finally:
        if endpoint.socket is not None:
            endpoint.socket.close()


def test_backend_endpoint_is_tcp_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(portable, "IS_WINDOWS", True)
    endpoint = portable.backend_endpoint(GENERATION)
    assert endpoint.kind == "tcp"
    assert endpoint.socket is None
    assert 1 <= int(endpoint.address) <= 65535


def test_sandbox_profile_is_deny_by_default(tmp_path: Path) -> None:
    profile = sandbox_profile(
        python=tmp_path / "python",
        packages=tmp_path / "packages",
        snapshot=tmp_path / "snapshot",
        launcher=tmp_path / "isolated_backend.py",
    )
    assert profile.startswith("(version 1)\n")
    assert "(deny default)" in profile
    assert '(import "system.sb")' in profile
    assert '(allow file-read* (subpath "' + str(tmp_path / "snapshot") + '"))' in profile
    assert "127.0.0.1:*" in profile
    assert '(allow file-write* (subpath "/tmp")' in profile


def test_windows_job_script_wires_the_job_object() -> None:
    script = windows_job_script()
    for token in (
        "CreateJobObject",
        "SetInformationJobObject",
        "AssignProcessToJobObject",
        "TerminateJobObject",
        "0x2000",  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        "SetMemoryAndProcessLimits",
        "SetCpuRate",
        "ConvertFrom-Json",
    ):
        assert token in script


def darwin_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    from app.isolation.darwin import DarwinIsolatedRuntime

    monkeypatch.delenv("FAULTLINE_AGGREGATE_LIMITS", raising=False)
    runtime = DarwinIsolatedRuntime(tmp_path)
    runtime.sandbox_exec = "/usr/bin/sandbox-exec"
    runtime._docker_mode = False
    runtime.limits_mode = "rlimits"
    return runtime


def windows_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    from app.isolation.windows import WindowsIsolatedRuntime

    monkeypatch.delenv("FAULTLINE_AGGREGATE_LIMITS", raising=False)
    monkeypatch.setattr(portable, "IS_WINDOWS", True)
    runtime = WindowsIsolatedRuntime(tmp_path)
    runtime.pwsh = "C:/Program Files/PowerShell/7/pwsh.exe"
    return runtime


def test_darwin_sandbox_argv_uses_sandbox_exec(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = darwin_runtime(monkeypatch, tmp_path)
    argv = runtime._sandbox(tmp_path)
    assert argv[0] == "/usr/bin/sandbox-exec" and argv[1] == "-f"
    assert Path(argv[2]).read_text().startswith("(version 1)\n")


def test_darwin_scope_unit_and_limits(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runtime = darwin_runtime(monkeypatch, tmp_path)
    assert runtime.scope_unit(GENERATION) is None
    assert runtime.scope_environment(None) == {}
    assert runtime.limits_mode == "rlimits"


@pytest.mark.asyncio
async def test_darwin_verify_scope_reports_unverified_rlimits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = darwin_runtime(monkeypatch, tmp_path)
    limits = await runtime.verify_scope(None, NO_PROCESS)
    assert limits.mode == "rlimits"
    assert limits.verified is False
    assert limits.memory_max_bytes == DARWIN_MEMORY_MAX_BYTES
    assert limits.tasks_max == DARWIN_TASKS_MAX
    assert limits.cpu_quota_percent is None and limits.memory_swap_max_bytes is None
    await runtime.release_scope(None)


def test_darwin_docker_fallback_argv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runtime = darwin_runtime(monkeypatch, tmp_path)
    runtime._docker_mode = True
    runtime.docker = "/usr/local/bin/docker"
    runtime._docker_port = 8765
    argv = runtime._sandbox(tmp_path)
    assert argv[:2] == ["/usr/local/bin/docker", "run"]
    assert "--publish" in argv and "127.0.0.1:8765:8765" in argv
    assert "--memory" in argv and "--pids-limit" in argv and "--cpus" in argv
    assert "--read-only" in argv


def test_darwin_backend_launch_argv_uses_host_python(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = darwin_runtime(monkeypatch, tmp_path)
    endpoint = portable.backend_endpoint(GENERATION)
    try:
        argv = runtime._backend_launch_argv(endpoint, tmp_path)
        assert argv[0] == str(runtime.host_python)
        assert str(runtime.launcher) in argv
        assert str(runtime.packages) in argv
        assert str(tmp_path) in argv
    finally:
        if endpoint.socket is not None:
            endpoint.socket.close()


def test_windows_sandbox_argv_wraps_powershell(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = windows_runtime(monkeypatch, tmp_path)
    argv = runtime._sandbox(tmp_path)
    assert argv[0] == runtime.pwsh
    assert "-File" in argv
    wrapper = Path(argv[argv.index("-File") + 1])
    assert wrapper.name == "faultline-job.ps1"
    assert "CreateJobObject" in wrapper.read_text()
    assert "-MemoryBytes" in argv and "-ActiveProcessLimit" in argv and "-CpuRate" in argv


def test_windows_backend_launch_argv_serializes_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = windows_runtime(monkeypatch, tmp_path)
    endpoint = runtime._backend_endpoint(GENERATION)
    argv = runtime._backend_launch_argv(endpoint, tmp_path)
    assert argv[0] == "-CommandJson"
    command = json.loads(argv[1])
    assert command[0] == str(runtime.host_python)
    assert endpoint.address in command
    assert runtime._backend_pass_fds(endpoint) == ()


@pytest.mark.asyncio
async def test_windows_verify_scope_reports_windows_job(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = windows_runtime(monkeypatch, tmp_path)
    limits = await runtime.verify_scope(None, NO_PROCESS)
    assert limits.mode == "windows-job" and limits.verified is True
    assert limits.memory_max_bytes == 512 * 1024 * 1024
    assert limits.cpu_quota_percent == 100


@pytest.mark.asyncio
async def test_linux_backend_seam_preserves_abstract_socket(tmp_path: Path) -> None:
    if portable.current_host() != "linux":
        pytest.skip("abstract sockets are Linux-only")
    runtime = IsolatedRuntime(tmp_path)
    endpoint = runtime._backend_endpoint(GENERATION)
    client = runtime._backend_client(endpoint)
    try:
        assert endpoint.kind == "abstract-unix"
        argv = runtime._backend_launch_argv(endpoint, tmp_path)
        assert argv[:4] == ["/python/bin/python3.13", "-I", "-u", "/trusted_backend.py"]
        assert endpoint.socket is not None
        assert runtime._backend_pass_fds(endpoint) == (endpoint.socket.fileno(),)
        assert client.base_url == "http://isolated-backend"
    finally:
        await client.aclose()
        if endpoint.socket is not None:
            endpoint.socket.close()


def test_resource_limits_new_modes_are_strict() -> None:
    base = {"memory_max_bytes": 536870912, "tasks_max": 64, "verified": True}
    for mode, extra in (
        ("rlimits", {"cpu_quota_percent": None, "memory_swap_max_bytes": None}),
        ("windows-job", {"cpu_quota_percent": 100, "memory_swap_max_bytes": 0}),
        ("docker", {"cpu_quota_percent": 100, "memory_swap_max_bytes": 0}),
    ):
        loaded = ResourceLimits.model_validate_json(json.dumps({"mode": mode, **base, **extra}))
        assert loaded.mode == mode and loaded.memory_max_bytes == 536870912
    for bad in (
        {"mode": "rlimits", "memory_max_bytes": None, "tasks_max": 64, "verified": False},
        {"mode": "windows-job", "memory_max_bytes": 1, "tasks_max": None, "verified": True},
        {
            "mode": "docker",
            "memory_max_bytes": 1,
            "tasks_max": 64,
            "verified": False,
            "memory_swap_max_bytes": -1,
        },
    ):
        with pytest.raises(ValueError):
            ResourceLimits.model_validate_json(json.dumps(bad))


@pytest.mark.asyncio
async def test_disabled_mode_is_shared_across_adapters(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.isolation.darwin import DarwinIsolatedRuntime

    monkeypatch.setenv("FAULTLINE_AGGREGATE_LIMITS", "disabled")
    runtime = DarwinIsolatedRuntime(tmp_path)
    assert runtime.scope_unit(GENERATION) is None
    assert (await runtime.verify_scope(None, NO_PROCESS)).mode == "disabled"


def test_darwin_fails_closed_without_sandbox_exec_or_docker() -> None:
    from app.isolation.darwin import DarwinIsolatedRuntime

    runtime = DarwinIsolatedRuntime()
    runtime.sandbox_exec = None
    runtime.docker = None
    runtime._docker_mode = True
    assert runtime.limits_mode == "docker"
