"""Contrarian audit of the multiplatform isolation adapters.

``test_isolation_adapters.py`` and ``test_isolation_fuzz.py`` cover the happy
contract and the hostile-input surface. This file is the adversarial second
look: it probes the six mechanisms the adapters actually lean on for their
boundary, and pins down the properties a regression would silently break.

Probed here, per the audit brief:

* **windows.py — PowerShell command building.** The generated C# ``Quote``
  routine must round-trip every argument through the real Windows
  ``CommandLineToArgvW`` algorithm, and the launcher must never hand the
  candidate a shell to interpret. ``CreateProcessW`` is called with a non-null
  ``lpApplicationName``, so a hostile ``argv[0]`` cannot redirect the executable.
* **windows.py — process tree kill.** ``taskkill /T /F`` is bounded, its argv is
  exact, and the supervisor refuses to taskkill a PID it has already reaped
  (PID-reuse guard).
* **windows.py — Job Object handle cleanup.** The job handle is non-inheritable
  and the process/thread handles are closed in ``finally``, so a candidate child
  can never close the kill-on-close handle to escape the job. Cleanup ordering
  (terminate job, then close handles) is asserted exactly.
* **darwin.py — seatbelt profile escaping.** ``_safe_sandbox_path`` rejects the
  four characters that can rewrite a deny-by-default profile, and ``json.dumps``
  neutralizes backslashes and control characters so none ever reach the
  s-expression parser as a directive.
* **darwin.py — POSIX ``setrlimit`` bounds.** The launcher's bounds are
  irreversible (soft == hard) and the memory/task ceilings agree with the
  ``DARWIN_*`` constants used by the probe.
* **darwin.py — unix socket path length.** The macOS filesystem socket name is
  short and separator-free, but the 108-byte ``sockaddr_un`` limit is still
  bounded by the *directory*, which the adapter does not itself constrain.

Like the sibling suites, nothing here launches a real sandbox, Job Object, or
shell: the assertions inspect the exact argv/profile/PowerShell text the
adapters would emit, so the suite runs unchanged on Linux, macOS, and Windows.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest

import app.portable as portable
import app.process_supervisor as supervisor
from app.isolated_runtime import AggregateLimits
from app.isolation.darwin import (
    DARWIN_MEMORY_MAX_BYTES,
    DARWIN_TASKS_MAX,
    _safe_sandbox_path,
    sandbox_profile,
)
from app.isolation.windows import windows_job_script
from app.portable import backend_endpoint
from app.runtime import RuntimeUnavailable

GENERATION = "0b9c8d7e-6f5a-4b3c-9d2e-1f0a9b8c7d6e"

# macOS ``sockaddr_un.sun_path`` is 104 bytes; Linux caps the filesystem variant
# at 108. Both are the reason the socket name, not just the path, matters.
SUN_PATH_BYTES = 108


# -- Windows command-line quoting round-trip (mirrors the C# ``Quote``) ---------


def quote_csharp(value: str) -> str:
    """The generated C# ``Quote`` exactly: always wrap, escape slashes/quotes."""
    result = ['"']
    slashes = 0
    for char in value:
        if char == "\\":
            slashes += 1
            continue
        if char == '"':
            result.append("\\" * (slashes * 2 + 1))
        else:
            result.append("\\" * slashes)
        result.append(char)
        slashes = 0
    result.append("\\" * (slashes * 2))
    result.append('"')
    return "".join(result)


def parse_command_line(cmdline: str) -> list[str]:
    """A faithful ``CommandLineToArgvW`` mirror, for round-tripping ``Quote``."""
    args: list[str] = []
    index = 0
    length = len(cmdline)
    while index < length:
        while index < length and cmdline[index] in " \t":
            index += 1
        if index >= length:
            break
        current: list[str] = []
        in_quotes = False
        while index < length:
            char = cmdline[index]
            if char == "\\":
                cursor = index
                while cursor < length and cmdline[cursor] == "\\":
                    cursor += 1
                count = cursor - index
                if cursor < length and cmdline[cursor] == '"':
                    current.append("\\" * (count // 2))
                    if count % 2 == 1:
                        current.append('"')
                    else:
                        in_quotes = not in_quotes
                    index = cursor + 1
                else:
                    current.append("\\" * count)
                    index = cursor
            elif char == '"':
                if in_quotes and index + 1 < length and cmdline[index + 1] == '"':
                    current.append('"')
                    index += 2
                else:
                    in_quotes = not in_quotes
                    index += 1
            elif char in " \t" and not in_quotes:
                index += 1
                break
            else:
                current.append(char)
                index += 1
        args.append("".join(current))
    return args


def windows_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    from app.isolation.windows import WindowsIsolatedRuntime

    monkeypatch.delenv("FAULTLINE_AGGREGATE_LIMITS", raising=False)
    monkeypatch.setattr(portable, "IS_WINDOWS", True)
    runtime = WindowsIsolatedRuntime(tmp_path)
    runtime.pwsh = "C:/Program Files/PowerShell/7/pwsh.exe"
    return runtime


# -- 1. PowerShell command building --------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "",
        "plain",
        "C:/Program Files/Python313/python.exe",
        "has space",
        "semi;colon",
        "pipe|or",
        "amp&ersand",
        "dollar$var",
        "back`tick",
        "$(command-sub)",
        "redirect>out",
        "paren(and)close",
        "single'quote",
        'embedded"quote',
        "line\nbreak",
        "carriage\rreturn",
        "null\x00byte",
        "unicode-ä-🚀",
        "back\\slash",
        "trailing\\",
        "two\\\\back",
        'back\\"quote',
        '\\\\"',
        'a"b"c',
    ],
)
def test_csharp_quote_round_trips_through_windows_argv_parser(value: str) -> None:
    """``Quote`` output must survive the real Windows argument parser losslessly."""
    assert parse_command_line(quote_csharp(value)) == [value]


def test_csharp_quote_always_double_quotes_so_spaces_never_split() -> None:
    """Every argument, even the trivial one, is quoted so whitespace stays inert."""
    assert quote_csharp("plain") == '"plain"'
    assert quote_csharp("a b") == '"a b"'
    assert quote_csharp("") == '""'


def test_windows_launcher_never_reaches_a_shell() -> None:
    """The Job Object wrapper builds an argv and calls CreateProcessW, not a shell."""
    script = windows_job_script()
    assert "CreateProcessW(" in script
    for shell_token in ("cmd.exe", "Invoke-Expression", "iex ", "sh -c", "Start-Process"):
        assert shell_token not in script
    # The only data entry into the command is JSON, decoded then split into argv.
    assert "ConvertFrom-Json" in script


def test_windows_create_process_uses_fixed_application_name() -> None:
    """A non-null ``lpApplicationName`` stops argv[0] from redirecting the binary."""
    script = windows_job_script()
    assert "CreateProcessW(argv[0], command, IntPtr.Zero, IntPtr.Zero, true," in script


def test_windows_command_json_is_the_single_injection_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The child argv arrives only via one JSON argument, in a fixed order."""
    runtime = windows_runtime(monkeypatch, tmp_path)
    endpoint = runtime._backend_endpoint(GENERATION)
    application = tmp_path / "apps/buggyshop-backend/app"
    application.mkdir(parents=True)
    argv = runtime._backend_launch_argv(endpoint, application)
    assert argv == [
        "-CommandJson",
        json.dumps(
            [
                str(runtime.host_python),
                "-I",
                "-u",
                str(runtime.launcher),
                endpoint.address,
                str(runtime.packages),
                str(application),
            ]
        ),
    ]


# -- 2. process tree kill (taskkill /T /F) -------------------------------------


def test_taskkill_argv_is_exact_and_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """``taskkill /PID <pid> /T /F`` with a two-second timeout, never a shell."""
    run = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    assert supervisor._taskkill_tree(4321) is True
    assert run.call_args.args[0][1:] == ["/PID", "4321", "/T", "/F"]
    assert run.call_args.kwargs["timeout"] == 2
    assert run.call_args.kwargs["check"] is False


def test_taskkill_falls_back_to_default_system_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without ``SystemRoot`` the resolver uses ``C:\\Windows``, never a cwd binary."""
    run = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.delenv("SystemRoot", raising=False)
    supervisor._taskkill_tree(1)
    assert run.call_args.args[0][0].startswith(r"C:\Windows")


@pytest.mark.parametrize("failure", ["timeout", "missing"])
def test_taskkill_reports_failure_instead_of_crashing(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """A hanging or absent taskkill is a False, so the caller can force-kill."""
    run = Mock()
    if failure == "timeout":
        run.side_effect = subprocess.TimeoutExpired("taskkill", 2)
    else:
        run.side_effect = OSError("no such file")
    monkeypatch.setattr(subprocess, "run", run)
    assert supervisor._taskkill_tree(4321) is False


def test_supervisor_never_taskkills_an_already_reaped_pid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A reaped PID may be reused; the supervisor must not taskkill it."""
    stop_file = tmp_path / "stop"
    stop_file.touch()
    child = Mock(pid=1234)
    child.poll.return_value = 0  # already exited before the loop starts
    child.wait.return_value = 0
    taskkill = Mock(return_value=True)
    monkeypatch.setattr(sys, "argv", ["supervisor", str(stop_file), "wrapper"])
    monkeypatch.setattr(subprocess, "Popen", Mock(return_value=child))
    monkeypatch.setattr(supervisor, "_taskkill_tree", taskkill)
    with pytest.raises(SystemExit) as exit_info:
        supervisor._main_windows()
    assert exit_info.value.code == 0
    taskkill.assert_not_called()


# -- 3. Job Object memory handle cleanup ----------------------------------------


def test_job_handle_is_non_inheritable_so_candidates_cannot_escape() -> None:
    """Only the wrapper owns the kill-on-close handle; the child must not inherit it."""
    script = windows_job_script()
    # NULL security attributes -> non-inheritable job, process, and thread handles.
    assert "CreateJobObject(IntPtr.Zero, null)" in script
    assert "CreateProcessW(argv[0], command, IntPtr.Zero, IntPtr.Zero, true," in script
    # No code path re-marks the job handle inheritable before CreateProcessW.
    assert "SetHandleInformation" not in script


def test_job_cleanup_terminates_job_then_closes_both_handles() -> None:
    """Cleanup order: sweep descendants, wait bounded, then close thread+process."""
    script = windows_job_script()
    assert script.index("TerminateJobObject(job, 1);") < script.index(
        "TerminateProcess(process.hProcess, 1);"
    )
    assert script.index("TerminateProcess(process.hProcess, 1);") < script.index(
        "WaitForSingleObject(process.hProcess, 5000)"
    )
    assert script.index("CloseHandle(process.hThread);") < script.index(
        "CloseHandle(process.hProcess);"
    )


def test_job_readback_frees_native_memory_in_finally() -> None:
    """``Query`` frees its HGlobal buffer and each setter frees its pin, on every path."""
    script = windows_job_script()
    assert "Marshal.FreeHGlobal(buffer);" in script
    assert script.count("GCHandle.Alloc(") == 2
    assert script.count("handle.Free();") == 2


def test_powershell_finally_closes_the_job_handle_after_run() -> None:
    """The wrapper's ``finally`` closes the job, sweeping stragglers on any exit."""
    script = windows_job_script()
    assert "[void][FaultLineJob]::Close($job)" in script
    assert script.index("exit $code") < script.index("[void][FaultLineJob]::Close($job)")


# -- 4. seatbelt profile escaping -------------------------------------------------


@pytest.mark.parametrize("name", ['quote"', "line\nbreak", "carriage\rreturn", "null\x00byte"])
def test_safe_sandbox_path_rejects_profile_terminators(name: str) -> None:
    """The four characters that can rewrite the deny-by-default profile fail closed."""
    with pytest.raises(RuntimeUnavailable, match="sandbox_path_unsafe"):
        _safe_sandbox_path(Path(name))


@pytest.mark.parametrize("name", ["semi;pipe|space &", "dollar$paren( )", "unicode-ä-🚀"])
def test_safe_sandbox_path_keeps_inert_metacharacters_literal(name: str) -> None:
    """Inert characters round-trip through the quoted s-expression unchanged."""
    assert _safe_sandbox_path(Path(name)) == json.dumps(name, ensure_ascii=False)


def test_safe_sandbox_path_escapes_backslash_not_injects_it() -> None:
    """A backslash is permitted but JSON-escaped; it cannot terminate the string."""
    assert _safe_sandbox_path(Path("a\\b")) == '"a\\\\b"'
    profile = sandbox_profile(
        python=Path("/p"), packages=Path("/pkg"), snapshot=Path("a\\b"), launcher=Path("/l")
    )
    assert "(deny default)" in profile
    assert profile.count("(allow network*") == 1
    assert "(allow default)" not in profile


def test_safe_sandbox_path_neutralizes_control_characters() -> None:
    """Tabs and other controls are escaped, so none can start a fresh directive line."""
    assert _safe_sandbox_path(Path("tab\there")) == '"tab\\there"'
    assert _safe_sandbox_path(Path("ctl\x01x")) == '"ctl\\u0001x"'
    assert "\t" not in _safe_sandbox_path(Path("tab\there"))


def test_profile_is_strictly_deny_by_default(tmp_path: Path) -> None:
    """The profile admits only the exact read/write/network set, nothing broad."""
    profile = sandbox_profile(
        python=tmp_path / "python",
        packages=tmp_path / "packages",
        snapshot=tmp_path / "snapshot",
        launcher=tmp_path / "isolated_backend.py",
    )
    lines = profile.splitlines()
    assert lines[0] == "(version 1)"
    assert lines[1] == "(deny default)"
    assert "(allow process*)" not in profile
    assert '(allow file-write* (subpath "/tmp") (subpath "/private/tmp"))' in profile
    assert '(allow network* (remote ip "127.0.0.1:*") (local ip "127.0.0.1:*"))' in profile


def test_profile_never_grants_fork_or_write_outside_tmp(tmp_path: Path) -> None:
    """The candidate is a single process and may only write under /tmp."""
    profile = sandbox_profile(
        python=tmp_path, packages=tmp_path, snapshot=tmp_path, launcher=tmp_path
    )
    assert "(deny process-fork)" in profile
    assert "(allow process-fork)" not in profile
    # No write allow lists any path except the two tmp spellings.
    for line in profile.splitlines():
        if line.startswith("(allow file-write*"):
            assert line == '(allow file-write* (subpath "/tmp") (subpath "/private/tmp"))'


# -- 5. POSIX setrlimit bounds ----------------------------------------------------


def test_rlimits_are_irreversible_soft_equals_hard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every bound has soft == hard, so the candidate can never raise it back."""
    from app.isolated_backend import _apply_rlimits

    setter = Mock()
    names = ("RLIMIT_NOFILE", "RLIMIT_CORE", "RLIMIT_CPU", "RLIMIT_AS", "RLIMIT_NPROC")
    resource = SimpleNamespace(**dict(zip(names, range(5), strict=True)), setrlimit=setter)
    monkeypatch.setitem(sys.modules, "resource", resource)
    _apply_rlimits()
    for call in setter.call_args_list:
        soft, hard = call.args[1]
        assert soft == hard, f"{call.args[0]} must be a hard, irreversible bound"


def test_rlimits_memory_and_tasks_match_darwin_constants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The launcher's ceilings must equal the probe's DARWIN_* constants, else the
    enforcement probe would test a different bound than the launcher applies."""
    from app.isolated_backend import _apply_rlimits

    setter = Mock()
    names = ("RLIMIT_NOFILE", "RLIMIT_CORE", "RLIMIT_CPU", "RLIMIT_AS", "RLIMIT_NPROC")
    resource = SimpleNamespace(**dict(zip(names, range(5), strict=True)), setrlimit=setter)
    monkeypatch.setitem(sys.modules, "resource", resource)
    _apply_rlimits()
    applied = {call.args[0]: call.args[1] for call in setter.call_args_list}
    assert applied[resource.RLIMIT_AS] == (DARWIN_MEMORY_MAX_BYTES, DARWIN_MEMORY_MAX_BYTES)
    assert applied[resource.RLIMIT_NPROC] == (DARWIN_TASKS_MAX, DARWIN_TASKS_MAX)


def test_rlimits_are_a_noop_when_resource_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """No ``resource`` module (Windows, or exotic POSIX) means the Job Object/Docker
    owns the boundary; the launcher must not crash on the missing import."""
    from app.isolated_backend import _apply_rlimits

    monkeypatch.setitem(sys.modules, "resource", None)
    _apply_rlimits()  # must return silently, not raise


def test_rlimits_setrlimit_failure_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A refused bound aborts the launch: running unbounded is never an option."""
    from app.isolated_backend import _apply_rlimits

    setter = Mock(side_effect=OSError("setrlimit refused"))
    names = ("RLIMIT_NOFILE", "RLIMIT_CORE", "RLIMIT_CPU", "RLIMIT_AS", "RLIMIT_NPROC")
    resource = SimpleNamespace(**dict(zip(names, range(5), strict=True)), setrlimit=setter)
    monkeypatch.setitem(sys.modules, "resource", resource)
    with pytest.raises(OSError, match="setrlimit refused"):
        _apply_rlimits()


# -- 6. unix socket path length limits ---------------------------------------------


def test_macos_socket_name_is_short_and_separator_free(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The filesystem socket uses a 15-byte name immune to traversal and quoting."""
    monkeypatch.setattr(portable, "IS_MACOS", True)
    monkeypatch.setattr(portable, "IS_WINDOWS", False)
    endpoint = backend_endpoint(GENERATION, runtime_dir=tmp_path)
    try:
        assert endpoint.kind == "named-unix"
        name = Path(endpoint.address).name
        assert name == f"flt-{GENERATION[:8]}.sock"
        assert "/" not in name and ".." not in name
        assert len(name.encode()) == len("flt-12345678.sock")
    finally:
        if endpoint.socket is not None:
            endpoint.socket.close()


def test_macos_socket_path_stays_under_unix_limit_for_short_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The whole ``sockaddr_un`` path, not just the name, must fit the kernel cap."""
    monkeypatch.setattr(portable, "IS_MACOS", True)
    monkeypatch.setattr(portable, "IS_WINDOWS", False)
    endpoint = backend_endpoint(GENERATION, runtime_dir=tmp_path)
    try:
        assert len(endpoint.address.encode("utf-8")) < SUN_PATH_BYTES
    finally:
        if endpoint.socket is not None:
            endpoint.socket.close()


def test_macos_socket_limit_is_driven_by_the_directory_not_the_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Contrarian finding: the short *name* does not bound the *path*. A long
    ``runtime_dir`` still overruns ``sockaddr_un``, and ``backend_endpoint``
    surfaces that as an uncaught ``OSError`` rather than a fail-closed reason.
    The adapter avoids this only because it uses the (short) default temp dir."""
    long_dir = tmp_path / ("x" * 60) / ("y" * 60)
    monkeypatch.setattr(portable, "IS_MACOS", True)
    monkeypatch.setattr(portable, "IS_WINDOWS", False)
    with pytest.raises(OSError):
        backend_endpoint(GENERATION, runtime_dir=long_dir)


# -- cross-platform honesty of the reported limits ---------------------------------


@pytest.mark.asyncio
async def test_windows_verify_scope_reports_no_swap_and_configured_cpu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Windows Jobs have no swap field and report the exact CPU rate requested."""
    runtime = windows_runtime(monkeypatch, tmp_path)
    limits = AggregateLimits(memory_max_bytes=96 * 1024 * 1024, tasks_max=3, cpu_quota_percent=25)
    record = await runtime.verify_scope(None, cast(Any, object()), limits)
    assert record.mode == "windows-job"
    assert record.memory_swap_max_bytes == 0
    assert record.cpu_quota_percent == 25
    assert record.memory_max_bytes == 96 * 1024 * 1024
    assert record.tasks_max == 3


@pytest.mark.asyncio
async def test_darwin_verify_scope_reports_no_swap_and_no_cpu_rate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """rlimits have no swap field and no CPU-rate (only a CPU-seconds budget)."""
    from app.isolation.darwin import DarwinIsolatedRuntime

    monkeypatch.delenv("FAULTLINE_AGGREGATE_LIMITS", raising=False)
    runtime = DarwinIsolatedRuntime(tmp_path)
    runtime.sandbox_exec = "/usr/bin/sandbox-exec"
    runtime._docker_mode = False
    record = await runtime.verify_scope(None, cast(Any, object()))
    assert record.mode == "rlimits"
    assert record.verified is False
    assert record.memory_swap_max_bytes is None
    assert record.cpu_quota_percent is None
    assert record.memory_max_bytes == DARWIN_MEMORY_MAX_BYTES
    assert record.tasks_max == DARWIN_TASKS_MAX
