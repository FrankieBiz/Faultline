"""Adversarial adapter tests, mocked platform APIs and real POSIX process trees.

Native Windows/Seatbelt enforcement still needs validation on those hosts;
passing mocks is not evidence that a host kernel enforces the boundary.
"""

from __future__ import annotations

import asyncio
import json
import os
import selectors
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest

import app.portable as portable
import app.process_supervisor as supervisor
from app.isolated_runtime import AggregateLimits, IsolatedRuntime, ManagedProcess
from app.isolation import select_runtime
from app.isolation.darwin import DARWIN_MEMORY_MAX_BYTES, DARWIN_TASKS_MAX, sandbox_profile
from app.isolation.windows import windows_job_script
from app.runtime import RuntimeUnavailable
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
            if endpoint.kind == "named-unix":
                Path(endpoint.address).unlink(missing_ok=True)


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


@pytest.mark.asyncio
async def test_darwin_fails_closed_without_sandbox_exec_or_docker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.isolation.darwin import DarwinIsolatedRuntime

    monkeypatch.setattr(shutil, "which", lambda _: None)
    runtime = DarwinIsolatedRuntime()
    assert runtime.limits_mode == "docker"
    with pytest.raises(RuntimeUnavailable, match="sandbox_exec_and_docker_unavailable"):
        await runtime.backend_preflight()


@pytest.mark.parametrize("name", ["back\\slash", "semi;colon", "dollar$name"])
def test_darwin_profile_escapes_untrusted_snapshot_paths(tmp_path: Path, name: str) -> None:
    snapshot = tmp_path / name
    profile = sandbox_profile(
        python=tmp_path / "python", packages=tmp_path, snapshot=snapshot, launcher=tmp_path
    )
    assert f"(allow file-read* (subpath {json.dumps(str(snapshot))}))" in profile
    assert len(profile.splitlines()) == 20


@pytest.mark.parametrize("name", ['quote"(allow default)', "line\nbreak"])
def test_darwin_profile_rejects_unsafe_snapshot_paths(tmp_path: Path, name: str) -> None:
    snapshot = tmp_path / name
    with pytest.raises(RuntimeUnavailable, match="sandbox_path_unsafe"):
        sandbox_profile(
            python=tmp_path / "python", packages=tmp_path, snapshot=snapshot, launcher=tmp_path
        )


def test_darwin_profile_denies_fork_escape(tmp_path: Path) -> None:
    profile = sandbox_profile(
        python=tmp_path, packages=tmp_path, snapshot=tmp_path, launcher=tmp_path
    )
    assert "(deny process-fork)" in profile
    assert "(allow process*)" not in profile


@pytest.mark.skipif(os.name == "nt", reason="Windows uses Job Objects instead of rlimits")
def test_darwin_rlimits_are_hard_and_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.isolated_backend import _apply_rlimits

    names = ("RLIMIT_NOFILE", "RLIMIT_CORE", "RLIMIT_CPU", "RLIMIT_AS", "RLIMIT_NPROC")
    setter = Mock()
    resource = SimpleNamespace(**dict(zip(names, range(5), strict=True)), setrlimit=setter)
    monkeypatch.setitem(sys.modules, "resource", resource)
    _apply_rlimits()
    assert setter.call_args_list == [
        ((0, (256, 256)),),
        ((1, (0, 0)),),
        ((2, (40, 40)),),
        ((3, (DARWIN_MEMORY_MAX_BYTES, DARWIN_MEMORY_MAX_BYTES)),),
        ((4, (DARWIN_TASKS_MAX, DARWIN_TASKS_MAX)),),
    ]
    setter.side_effect = OSError("setrlimit refused")
    with pytest.raises(OSError, match="setrlimit refused"):
        _apply_rlimits()


@pytest.mark.asyncio
async def test_darwin_memory_probe_applies_launcher_rlimits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = darwin_runtime(monkeypatch, tmp_path)
    process = SimpleNamespace(wait=AsyncMock(return_value=0), stdout=b"rlimit-enforced\n")
    start = AsyncMock(return_value=process)
    monkeypatch.setattr(ManagedProcess, "start", start)
    assert await runtime._enforcement_probe() is None
    command = start.call_args.args
    code = command[command.index("-c") + 1]
    assert "_apply_rlimits" in code
    assert code.index("_apply_rlimits") < code.index("held=[]")


@pytest.mark.asyncio
async def test_darwin_profile_preflight_generates_valid_python(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = darwin_runtime(monkeypatch, tmp_path)
    process = SimpleNamespace(wait=AsyncMock(return_value=0), stdout=b"darwin-profile-ready\n")
    start = AsyncMock(return_value=process)
    monkeypatch.setattr(ManagedProcess, "start", start)
    await runtime._profile_preflight()
    command = start.call_args.args
    compile(command[command.index("-c") + 1], "<darwin-profile-preflight>", "exec")


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["darwin", "windows"])
@pytest.mark.parametrize("status", [1, 137, -9, 0xC0000017])
async def test_enforcement_probe_rejects_abnormal_exit_even_with_success_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, platform: str, status: int
) -> None:
    runtime = (darwin_runtime if platform == "darwin" else windows_runtime)(monkeypatch, tmp_path)
    process = SimpleNamespace(
        wait=AsyncMock(return_value=status),
        stdout=b"rlimit-enforced\n" if platform == "darwin" else b"job-object-ready\n",
    )
    monkeypatch.setattr(ManagedProcess, "start", AsyncMock(return_value=process))
    assert await runtime._enforcement_probe() == "aggregate_limits_not_enforced"


@pytest.mark.asyncio
async def test_windows_requested_job_limits_are_reported_and_passed_to_wrapper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = windows_runtime(monkeypatch, tmp_path)
    limits = AggregateLimits(memory_max_bytes=96 * 1024 * 1024, tasks_max=3, cpu_quota_percent=25)
    argv = runtime._sandbox(tmp_path, limits=limits)
    assert argv[argv.index("-MemoryBytes") + 1] == str(limits.memory_max_bytes)
    assert argv[argv.index("-ActiveProcessLimit") + 1] == "3"
    assert argv[argv.index("-CpuRate") + 1] == "2500"
    observed = await runtime.verify_scope(None, NO_PROCESS, limits)
    assert observed.memory_max_bytes == limits.memory_max_bytes
    assert observed.tasks_max == 3
    assert observed.cpu_quota_percent == 25


def test_windows_job_assigns_suspended_child_and_reaps_handles_on_failure() -> None:
    script = windows_job_script()
    assert "CREATE_SUSPENDED" in script
    assert script.index("AssignProcessToJobObject(job, process.hProcess)") < script.index(
        "ResumeThread(process.hThread)"
    )
    assert "TerminateProcess(process.hProcess" in script
    assert "CloseHandle(process.hThread)" in script
    assert "CloseHandle(process.hProcess)" in script
    assert "QueryInformationJobObject" in script
    assert "observed.JobMemoryLimit" in script
    assert "observed.BasicLimitInformation.ActiveProcessLimit" in script
    assert "CREATE_BREAKAWAY_FROM_JOB" not in script
    assert "[void][FaultLineJob]::Close($job)" in script


@pytest.mark.asyncio
@pytest.mark.skipif(os.name == "nt", reason="POSIX supervisor signal semantics")
@pytest.mark.parametrize("code", [3, 42, 137])
async def test_supervisor_preserves_abnormal_exit_and_reaps(code: int) -> None:
    process = await ManagedProcess.start(sys.executable, "-I", "-c", f"raise SystemExit({code})")
    assert await process.wait(5) == code
    assert process.process.returncode == code
    assert process.liveness_fd is None
    assert all(pump.done() for pump in process.pumps)
    with pytest.raises(ChildProcessError):
        os.waitpid(process.process.pid, os.WNOHANG)


@pytest.mark.asyncio
@pytest.mark.skipif(os.name == "nt", reason="POSIX supervisor signal semantics")
async def test_supervisor_reports_sigkill_exit_and_reaps() -> None:
    process = await ManagedProcess.start(
        sys.executable, "-I", "-c", "import os,signal; os.kill(os.getpid(),signal.SIGKILL)"
    )
    assert await process.wait(5) == 128 + signal.SIGKILL
    assert process.liveness_fd is None
    assert all(pump.done() for pump in process.pumps)


@pytest.mark.asyncio
@pytest.mark.skipif(os.name == "nt", reason="POSIX supervisor signal semantics")
@pytest.mark.parametrize("stop_mode", ["stop", "timeout", "cancel"])
async def test_supervisor_escalates_when_sigterm_is_ignored(stop_mode: str) -> None:
    process = await ManagedProcess.start(
        sys.executable,
        "-I",
        "-u",
        "-c",
        "import signal,time,threading; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        "threading.Thread(target=lambda: time.sleep(60),daemon=True).start(); "
        "print('ready'); time.sleep(60)",
    )
    try:
        async with asyncio.timeout(5):
            while b"ready" not in process.stdout:
                assert process.process.returncode is None
                await asyncio.sleep(0.01)
        async with asyncio.timeout(5):
            if stop_mode == "stop":
                await process.stop()
            elif stop_mode == "timeout":
                with pytest.raises(TimeoutError):
                    await process.wait(0.01)
            else:
                waiter = asyncio.create_task(process.wait(60))
                await asyncio.sleep(0)
                waiter.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await waiter
        assert process.process.returncode == 128 + signal.SIGKILL
        assert all(pump.done() for pump in process.pumps)
    finally:
        await process.stop()


@pytest.mark.asyncio
async def test_stop_timeout_does_not_claim_reaped_or_delete_windows_stop_request(
    tmp_path: Path,
) -> None:
    stop_file = tmp_path / "stop-request" / "stop"
    stop_file.parent.mkdir()
    child = SimpleNamespace(wait=AsyncMock(side_effect=TimeoutError), returncode=None)
    process = ManagedProcess(cast(Any, child), stop_file=stop_file)
    with pytest.raises(TimeoutError):
        await process.stop()
    assert child.returncode is None
    assert stop_file.exists(), "an unreaped supervisor must still see the stop request"
    child.wait.side_effect = None
    child.returncode = 1
    await process.stop()
    assert not stop_file.parent.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["darwin", "windows"])
async def test_probe_timeout_fails_preflight_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, platform: str
) -> None:
    from app.runtime import RuntimeUnavailable

    runtime = (darwin_runtime if platform == "darwin" else windows_runtime)(monkeypatch, tmp_path)
    process = SimpleNamespace(wait=AsyncMock(side_effect=TimeoutError), stdout=b"")
    monkeypatch.setattr(ManagedProcess, "start", AsyncMock(return_value=process))
    monkeypatch.setattr(runtime, "_profile_preflight", AsyncMock())
    with pytest.raises(RuntimeUnavailable, match="aggregate_limits_not_enforced"):
        await runtime.backend_preflight()
    assert runtime._backend_ready is False
    assert runtime._limits_preflight == "failed"


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group signals")
@pytest.mark.parametrize("race", [False, True])
def test_posix_sweeps_grandchildren_after_leader_exit_and_reaps(
    monkeypatch: pytest.MonkeyPatch, race: bool
) -> None:
    child = Mock(pid=1234)
    child.poll.side_effect = [None, None, 7] if race else [7, 7]
    child.wait.return_value = 7
    selector = Mock()
    selector.select.return_value = [object()]
    kill = Mock(side_effect=ProcessLookupError if race else None)
    monkeypatch.setattr(sys, "argv", ["supervisor", "99", "", "candidate"])
    monkeypatch.setattr(subprocess, "Popen", Mock(return_value=child))
    monkeypatch.setattr(selectors, "DefaultSelector", Mock(return_value=selector))
    monkeypatch.setattr(os, "read", Mock(return_value=b""))
    monkeypatch.setattr(os, "close", Mock())
    monkeypatch.setattr(os, "killpg", kill, raising=False)
    with pytest.raises(SystemExit) as exit_info:
        supervisor._main_posix()
    assert exit_info.value.code == 7
    assert kill.call_args_list[-1].args == (1234, signal.SIGKILL)
    child.wait.assert_called_once_with()
    selector.close.assert_called_once_with()


def test_windows_taskkill_is_bounded_and_forceful(monkeypatch: pytest.MonkeyPatch) -> None:
    run = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(subprocess, "run", run)
    assert supervisor._taskkill_tree(1234) is True
    assert run.call_args.args[0][1:] == ["/PID", "1234", "/T", "/F"]
    assert run.call_args.kwargs["timeout"] == 2


@pytest.mark.parametrize("failure", ["timeout", "denied", "nonzero"])
def test_windows_force_kills_wrapper_if_taskkill_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str
) -> None:
    stop_file = tmp_path / "stop"
    stop_file.touch()
    child = Mock(pid=1234)
    child.poll.side_effect = [None, None, 1]
    child.wait.return_value = 1
    run = Mock(return_value=SimpleNamespace(returncode=1))
    if failure == "timeout":
        run.side_effect = subprocess.TimeoutExpired("taskkill", 2)
    elif failure == "denied":
        run.side_effect = PermissionError("denied")
    monkeypatch.setattr(sys, "argv", ["supervisor", str(stop_file), "wrapper"])
    monkeypatch.setattr(subprocess, "Popen", Mock(return_value=child))
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(SystemExit) as exit_info:
        supervisor._main_windows()
    assert exit_info.value.code == 1
    child.kill.assert_called_once_with()
    child.wait.assert_called_once_with(timeout=2)
    assert not stop_file.exists()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name == "nt", reason="POSIX process exit semantics")
async def test_concurrent_abnormal_exits_release_every_pipe_and_reap() -> None:
    async def run(code: int) -> None:
        process = await ManagedProcess.start(
            sys.executable, "-I", "-c", f"raise SystemExit({code})"
        )
        try:
            assert await process.wait(10) == code
            assert process.liveness_fd is None
            assert all(pump.done() for pump in process.pumps)
            with pytest.raises(ChildProcessError):
                os.waitpid(process.process.pid, os.WNOHANG)
        finally:
            await process.stop()

    await asyncio.gather(*(run(code) for code in range(1, 17)))


@pytest.mark.skipif(os.name != "nt", reason="requires real Windows Job Objects")
@pytest.mark.parametrize("probe", ["memory", "process", "exit"])
def test_native_windows_job_limits_and_exit_status(tmp_path: Path, probe: str) -> None:
    """Exercise the generated P/Invoke wrapper on Windows, including readback."""
    pwsh = shutil.which("pwsh") or shutil.which("powershell.exe")
    if pwsh is None:
        pytest.skip("PowerShell is unavailable")
    wrapper = tmp_path / "job.ps1"
    wrapper.write_text(windows_job_script())
    code = {
        "memory": "try:\n    bytearray(256 << 20)\nexcept MemoryError:\n    print('bounded')\n",
        "process": (
            "import subprocess,sys\ntry:\n"
            "    child=subprocess.Popen([sys.executable,'-I','-c','pass'])\n"
            "    child.wait()\nexcept OSError:\n    print('bounded')\n"
        ),
        "exit": "raise SystemExit(42)",
    }[probe]
    result = subprocess.run(
        [
            pwsh,
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(wrapper),
            "-MemoryBytes",
            str(128 << 20),
            "-ActiveProcessLimit",
            "1",
            "-CommandJson",
            json.dumps([sys.executable, "-I", "-u", "-c", code]),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == (42 if probe == "exit" else 0), result.stderr
    if probe != "exit":
        assert result.stdout.strip() == "bounded", result.stderr
