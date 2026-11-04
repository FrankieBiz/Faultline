"""Fuzz and edge-case coverage for cross-platform isolation and portability.

The isolation seam (``app.isolation.darwin``, ``app.isolation.windows``) and the
portable primitives (``app.portable``) must never turn a hostile string into a
shell command, a rewritten sandbox profile, or an over-permissive resource
limit. These tests drive that boundary with command-injection payloads, long and
Unicode paths, and degenerate resource/timeout values, then assert every failure
lands in the single ``RuntimeUnavailable`` / ``CandidateRejected`` hierarchy.

Nothing here launches a sandbox, a Job Object, or a real shell: the assertions
inspect the argv/profile/JSON the adapters would hand to those mechanisms, and
the exception types they raise, so the suite runs on every host.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

import app.portable as portable
from app.isolated_runtime import (
    AggregateLimits,
    BoundedTCPTransport,
    BoundedUDSTransport,
    IsolatedRuntime,
    ManagedProcess,
    verify_cgroup_values,
)
from app.isolation.darwin import sandbox_profile
from app.isolation.windows import windows_job_script
from app.portable import normalize_relpath
from app.runtime import CandidateRejected, RuntimeUnavailable
from app.snapshots import contained_path
from shared.contracts.models import ResourceLimits

GENERATION = "0b9c8d7e-6f5a-4b3c-9d2e-1f0a9b8c7d6e"

# The PowerShell Quote-Arg safe-character whitelist embedded in the Job Object
# wrapper. PowerShell ``-match`` is case-insensitive, but the class already spans
# ``a-z`` and ``A-Z``, so the classification is identical to a Python fullmatch.
POWERSHELL_SAFE = re.compile(r"^[a-zA-Z0-9_./\\:\-]+$")


def quote_arg(value: str) -> str:
    """The Windows command-line Quote logic, mirrored exactly for fuzzing."""
    if POWERSHELL_SAFE.fullmatch(value):
        return value
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


def cgroup_values(**overrides: str) -> dict[str, str]:
    """A complete, correctly-limited cgroup v2 value set with one field mutated."""
    base = {
        "memory.max": "536870912\n",
        "memory.swap.max": "0\n",
        "pids.max": "64\n",
        "cpu.max": "100000 100000\n",
        "memory.oom.group": "1\n",
    }
    base.update(overrides)
    return base


# -- command injection / shell metacharacter defense ---------------------------


def test_windows_wrapper_disables_the_shell_and_quotes_arguments() -> None:
    """The Job Object wrapper never invokes a shell and escapes every argument."""
    script = windows_job_script()
    assert "FaultLineJob" in script
    assert "CREATE_SUSPENDED" in script
    assert "ConvertFrom-Json" in script
    assert "public static string Quote" in script


@pytest.mark.parametrize(
    "value",
    [
        "plain",
        "C:/Program/Files/app.py",
        "back\\slash\\path",
        "with-hyphen",
        "under_score.dot",
        "colon:value",
        "MiXeD_Case.123",
    ],
)
def test_powershell_quote_arg_passes_safe_characters_unchanged(value: str) -> None:
    assert quote_arg(value) == value


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("has space", '"has space"'),
        ("semi;colon", '"semi;colon"'),
        ("pipe|or", '"pipe|or"'),
        ("amp&ersand", '"amp&ersand"'),
        ("dollar$var", '"dollar$var"'),
        ("back`tick", '"back`tick"'),
        ("$(command-sub)", '"$(command-sub)"'),
        ("redirect>out", '"redirect>out"'),
        ("paren(and)close", '"paren(and)close"'),
        ("single'quote", '"single\'quote"'),
        ('embedded"quote', '"embedded\\"quote"'),
        ("line\nbreak", '"line\nbreak"'),
        ("carriage\rreturn", '"carriage\rreturn"'),
        ("null\x00byte", '"null\x00byte"'),
        ("unicode-ä-🚀", '"unicode-ä-🚀"'),
    ],
)
def test_powershell_quote_arg_quotes_and_escapes_hazardous_characters(
    value: str, expected: str
) -> None:
    assert quote_arg(value) == expected


def test_windows_command_json_round_trips_hostile_arguments(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The Job Object command is JSON-encoded, so metacharacters stay literal."""
    runtime = windows_runtime(monkeypatch, tmp_path)
    hostile = 'app"; echo hacked | nc -e sh & $(whoami) `touch x`'
    application = tmp_path / hostile
    application.mkdir()
    endpoint = runtime._backend_endpoint(GENERATION)
    argv = runtime._backend_launch_argv(endpoint, application)
    assert argv[0] == "-CommandJson"
    # The serialized command is valid JSON and decodes back byte-for-byte, so
    # no metacharacter is ever interpreted by a shell or PowerShell parser.
    assert json.loads(argv[1])[-1] == str(application)


def test_windows_command_json_escapes_null_bytes_and_newlines() -> None:
    """JSON neutralizes the characters that would truncate or split a command."""
    command = ["python", "-c", "a\x00b", "line1\nline2; rm -rf /"]
    encoded = json.dumps(command)
    assert "\x00" not in encoded and "\\u0000" in encoded
    assert "\\n" in encoded and ";" in encoded
    assert json.loads(encoded) == command


def test_darwin_launch_argv_is_shell_free(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """sandbox-exec argv is a list, so hostile characters are never interpreted."""
    runtime = darwin_runtime(monkeypatch, tmp_path)
    sandbox = runtime._sandbox(tmp_path)
    assert all(isinstance(token, str) for token in sandbox)
    endpoint = portable.backend_endpoint(GENERATION)
    try:
        launch = runtime._backend_launch_argv(endpoint, tmp_path)
        assert all(isinstance(token, str) for token in launch)
        assert "; rm -rf /" not in " ".join(sandbox)
    finally:
        if endpoint.socket is not None:
            endpoint.socket.close()
            if endpoint.kind == "named-unix":
                Path(endpoint.address).unlink(missing_ok=True)


def test_linux_sandbox_argv_is_shell_free(tmp_path: Path) -> None:
    """The bwrap/systemd-run profile is an argv list, never a shell string."""
    runtime = IsolatedRuntime(tmp_path)
    runtime.bwrap = "/usr/bin/bwrap"
    argv = runtime._sandbox(tmp_path)
    assert argv[0] == "/usr/bin/bwrap" and "--clearenv" in argv
    # A hostile snapshot path stays a single token; nothing concatenates it.
    hostile = tmp_path / "semi;pipe|dollar$ amp& paren( )"
    hostile.mkdir()
    argv = runtime._sandbox(hostile)
    assert str(hostile) in argv


def test_candidate_environment_is_never_propagated_on_darwin_or_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Hostile environment keys/values never reach a Darwin or Windows candidate."""
    for name, value in (
        ("META_API_KEY", "secret; rm -rf /"),
        ("FAULTLINE_CONTROL_TOKEN", "token\n$(whoami)"),
        ("LD_PRELOAD", "/tmp/evil.so"),
        ("PYTHONPATH", ".;/attacker &"),
        ("PATH", "/tmp/evil:/usr/bin"),
    ):
        monkeypatch.setenv(name, value)
    # The native adapters hand the trusted launcher an empty environment, so
    # nothing attacker-controlled is inherited or interpolated into a command.
    for runtime in (
        darwin_runtime(monkeypatch, tmp_path),
        windows_runtime(monkeypatch, tmp_path),
    ):
        assert runtime.scope_environment(None) == {}


@pytest.mark.parametrize(
    "name",
    [
        'injected") (allow network*) (subpath "x',
        "line\nbreak",
        "carriage\rreturn",
        "null\x00byte",
    ],
)
def test_sandbox_profile_rejects_path_injection(name: str) -> None:
    """A path that could rewrite the deny-by-default profile fails closed."""
    with pytest.raises(RuntimeUnavailable, match="sandbox_path_unsafe"):
        sandbox_profile(
            python=Path("/usr/bin/python"),
            packages=Path("/pkg"),
            snapshot=Path(name),
            launcher=Path("/launch"),
        )


def test_sandbox_profile_keeps_inert_metacharacters_literal(tmp_path: Path) -> None:
    """Pipes, semicolons, and spaces are literal inside a quoted subpath."""
    snapshot = tmp_path / "semi;pipe|space dir & dollar$"
    snapshot.mkdir()
    profile = sandbox_profile(
        python=Path("/usr/bin/python"),
        packages=Path("/pkg"),
        snapshot=snapshot,
        launcher=Path("/launch"),
    )
    assert f'(allow file-read* (subpath "{snapshot}"))' in profile
    assert "(deny default)" in profile
    # Only the fixed loopback-only allow survives; no injected directive sneaks in.
    assert profile.count("(allow network*") == 1


# -- long paths and unicode ---------------------------------------------------


def test_sandbox_profile_handles_long_unicode_and_space_paths(tmp_path: Path) -> None:
    deep = tmp_path
    for _ in range(8):
        deep = deep / "segment with spaces and ünïcødé 🚀"
    long_path = deep / ("nested-leaf-" * 24)  # far past the 260-char Windows MAX_PATH
    assert len(str(long_path)) > 260
    profile = sandbox_profile(
        python=long_path / "python",
        packages=long_path / "packages",
        snapshot=long_path,
        launcher=long_path / "isolated_backend.py",
    )
    assert f'(allow file-read* (subpath "{long_path}"))' in profile


def test_macos_endpoint_socket_name_is_short_and_free_of_separators(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The filesystem socket uses a short UUID prefix, immune to the 108-byte cap."""
    monkeypatch.setattr(portable, "IS_MACOS", True)
    monkeypatch.setattr(portable, "IS_WINDOWS", False)
    endpoint = portable.backend_endpoint(GENERATION, runtime_dir=tmp_path)
    try:
        assert endpoint.kind == "named-unix"
        name = Path(endpoint.address).name
        assert name == f"flt-{GENERATION[:8]}.sock"
        assert "/" not in name and ".." not in name
    finally:
        if endpoint.socket is not None:
            endpoint.socket.close()


def test_windows_argv_round_trips_long_unicode_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = windows_runtime(monkeypatch, tmp_path)
    application = tmp_path / "déep-nësted-🚀-with spaces"
    for _ in range(12):
        application = application / "segment with spaces 🚀"
    application = application / "app.py"
    assert len(str(application)) > 260
    endpoint = runtime._backend_endpoint(GENERATION)
    command = json.loads(runtime._backend_launch_argv(endpoint, application)[1])
    assert command[-1] == str(application)


# -- resource exhaustion edge cases -------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"memory_max_bytes": -1},
        {"tasks_max": -1},
        {"cpu_quota_percent": -1},
        {"memory_swap_max_bytes": -1},
        {"tasks_max": 0},
        {"cpu_quota_percent": 0},
    ],
)
def test_resource_limits_reject_negative_and_nonpositive_limits(overrides: dict[str, int]) -> None:
    base = {
        "mode": "windows-job",
        "memory_max_bytes": 536870912,
        "memory_swap_max_bytes": 0,
        "tasks_max": 64,
        "cpu_quota_percent": 100,
        "verified": True,
    }
    with pytest.raises(ValidationError):
        ResourceLimits.model_validate_json(json.dumps({**base, **overrides}))


def test_resource_limits_memory_floor_is_zero() -> None:
    """The schema admits a zero memory ceiling (``ge=0``) but never a negative one."""
    record = {
        "mode": "windows-job",
        "memory_max_bytes": 0,
        "memory_swap_max_bytes": 0,
        "tasks_max": 64,
        "cpu_quota_percent": 100,
        "verified": True,
    }
    assert ResourceLimits.model_validate_json(json.dumps(record)).memory_max_bytes == 0


@pytest.mark.parametrize(
    "memory",
    ["0MB", "invalid", True, 1.5, None, [], {}],
)
def test_resource_limits_reject_non_integer_memory(memory: object) -> None:
    record = {
        "mode": "windows-job",
        "memory_max_bytes": memory,
        "memory_swap_max_bytes": 0,
        "tasks_max": 64,
        "cpu_quota_percent": 100,
        "verified": True,
    }
    with pytest.raises(ValidationError):
        ResourceLimits.model_validate_json(json.dumps(record))


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("memory.max", "0MB\n"),
        ("memory.max", "-1GB\n"),
        ("memory.max", "invalid\n"),
        ("memory.max", "٥\n"),
        ("memory.max", "512MiB\n"),
        ("pids.max", "-64\n"),
        ("pids.max", "many\n"),
        ("cpu.max", "quota period\n"),
        ("memory.oom.group", "yes\n"),
    ],
)
def test_cgroup_parsing_rejects_invalid_memory_and_limit_strings(name: str, value: str) -> None:
    with pytest.raises(RuntimeUnavailable, match="aggregate_limits_unverified"):
        verify_cgroup_values(cgroup_values(**{name: value}), AggregateLimits())


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("memory.max", "0\n"),
        ("memory.max", "536870913\n"),
        ("pids.max", "0\n"),
        ("pids.max", "65\n"),
        ("cpu.max", "100000 0\n"),
        ("memory.swap.max", "1\n"),
        ("memory.oom.group", "0\n"),
    ],
)
def test_cgroup_parsing_rejects_zero_and_mismatched_limits(name: str, value: str) -> None:
    with pytest.raises(RuntimeUnavailable, match="aggregate_limits_unverified"):
        verify_cgroup_values(cgroup_values(**{name: value}), AggregateLimits())


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [0, -1])
async def test_timeout_at_or_below_zero_is_immediate(timeout: float) -> None:
    """A non-positive timeout raises ``TimeoutError`` at once, never a hang."""
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(timeout):
            await asyncio.sleep(0.01)


# -- exception mapping --------------------------------------------------------


def test_runtime_exception_hierarchy_is_a_single_runtime_error_family() -> None:
    """Every isolation failure collapses into ``RuntimeError`` subclasses."""
    assert issubclass(RuntimeUnavailable, RuntimeError)
    assert issubclass(CandidateRejected, RuntimeError)
    for reason in (
        "sandbox_exec_unavailable",
        "powershell_unavailable",
        "aggregate_limits_mode_invalid",
        "generation_identity_invalid",
    ):
        assert str(RuntimeUnavailable(reason)) == reason


def test_darwin_scope_unit_rejects_a_non_canonical_generation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = darwin_runtime(monkeypatch, tmp_path)
    for bad in ("", "not-a-uuid", "{" + GENERATION + "}", GENERATION.upper()):
        with pytest.raises(RuntimeUnavailable, match="generation_identity_invalid"):
            runtime.scope_unit(bad)


@pytest.mark.parametrize(
    "mode",
    ["", "REQUIRED", "off", "required ", "true", "sometimes"],
)
def test_unknown_aggregate_mode_fails_closed_across_adapters(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: str
) -> None:
    for runtime in (
        darwin_runtime(monkeypatch, tmp_path),
        windows_runtime(monkeypatch, tmp_path),
    ):
        runtime.aggregate_mode = mode
        with pytest.raises(RuntimeUnavailable, match="aggregate_limits_mode_invalid"):
            runtime.scope_unit(GENERATION)


def test_darwin_fails_closed_without_sandbox_exec(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A missing native boundary is unavailability, never a silent host run."""
    runtime = darwin_runtime(monkeypatch, tmp_path)
    runtime._docker_mode = False
    runtime.sandbox_exec = None
    with pytest.raises(RuntimeUnavailable, match="sandbox_exec_unavailable"):
        runtime._sandbox(tmp_path)


@pytest.mark.asyncio
async def test_darwin_fails_closed_without_sandbox_exec_or_docker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With both boundaries absent, preflight withholds readiness fail-closed."""
    runtime = darwin_runtime(monkeypatch, tmp_path)
    runtime.sandbox_exec = None
    runtime.docker = None
    runtime._docker_mode = True
    with pytest.raises(RuntimeUnavailable, match="sandbox_exec_and_docker_unavailable"):
        await runtime.backend_preflight()


def test_windows_fails_closed_without_powershell(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = windows_runtime(monkeypatch, tmp_path)
    runtime.pwsh = None
    with pytest.raises(RuntimeUnavailable, match="powershell_unavailable"):
        runtime._sandbox(tmp_path)


class _TimingOutProcess:
    """A trusted preflight process whose wait never completes."""

    async def wait(self, timeout: float) -> int:
        raise TimeoutError


@pytest.mark.asyncio
async def test_darwin_profile_preflight_maps_timeout_to_runtime_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = darwin_runtime(monkeypatch, tmp_path)
    with patch.object(ManagedProcess, "start", AsyncMock(return_value=_TimingOutProcess())):
        with pytest.raises(RuntimeUnavailable, match="isolated_profile_timeout"):
            await runtime._profile_preflight()


@pytest.mark.asyncio
async def test_windows_profile_preflight_maps_timeout_to_runtime_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = windows_runtime(monkeypatch, tmp_path)
    with patch.object(ManagedProcess, "start", AsyncMock(return_value=_TimingOutProcess())):
        with pytest.raises(RuntimeUnavailable, match="isolated_profile_timeout"):
            await runtime._profile_preflight()


def test_resource_limits_honest_modes_reject_missing_floor() -> None:
    """rlimits / windows-job / docker must always report a memory and task floor."""
    for mode in ("rlimits", "windows-job", "docker"):
        record = {
            "mode": mode,
            "memory_max_bytes": None,
            "memory_swap_max_bytes": 0,
            "tasks_max": 64,
            "cpu_quota_percent": None,
            "verified": False,
        }
        with pytest.raises(ValidationError):
            ResourceLimits.model_validate_json(json.dumps(record))


# -- cross-platform path normalization -----------------------------------------


def test_normalize_relpath_converts_backslashes_to_forward() -> None:
    """A Windows-spelled manifest or patch path collapses to forward slashes."""
    assert normalize_relpath("apps/buggyshop-backend/app/routes/checkout.py") == (
        "apps/buggyshop-backend/app/routes/checkout.py"
    )
    assert normalize_relpath(r"apps\buggyshop-backend\app\routes\checkout.py") == (
        "apps/buggyshop-backend/app/routes/checkout.py"
    )
    assert normalize_relpath(r"a\b/c") == "a/b/c"
    assert normalize_relpath("./a/./b") == "a/b"
    assert normalize_relpath("a//b") == "a/b"


@pytest.mark.parametrize(
    "relative",
    [
        "",
        ".",
        "..",
        "../escape",
        "a/../../etc/passwd",
        "..\\..\\etc\\passwd",
        "/etc/passwd",
        "C:\\Windows\\System32",
        "C:relative",
        "\\\\server\\share\\file",
        "a\x00b",
    ],
)
def test_normalize_relpath_rejects_absolute_parent_and_nul(relative: str) -> None:
    """Absolute, drive-letter, UNC, parent-traversing, and NUL paths fail closed."""
    with pytest.raises(ValueError):
        normalize_relpath(relative)


def test_normalize_relpath_fuzz_never_emits_a_separator_or_escape() -> None:
    """Every hostile spelling either fails closed or yields forward slashes only."""
    hostile = [
        "a\\b",
        "a/b",
        "a\\b/c",
        "./x",
        "x/./y",
        "..\\..",
        "C:\\x",
        "C:x",
        "/x",
        "//x",
        "x\\",
        "\\x",
        "a..b",
        "..a",
        "a..",
        "x/..",
        "x/../..",
        "dir/subdir/file.py",
        "apps\\buggyshop-backend\\app\\routes\\checkout.py",
    ]
    for value in hostile:
        try:
            result = normalize_relpath(value)
        except ValueError:
            continue
        assert "\\" not in result
        assert not result.startswith("/")
        assert ".." not in result.split("/")
        assert result != ""


# -- malformed manifest / snapshot entries --------------------------------------


def test_contained_path_normalizes_a_windows_manifest_entry(tmp_path: Path) -> None:
    """A backslash-separated manifest entry resolves identically on every host."""
    (tmp_path / "apps").mkdir()
    (tmp_path / "apps" / "checkout.py").write_text("x = 1\n")
    resolved = contained_path(tmp_path, "apps\\checkout.py")
    assert resolved == tmp_path / "apps" / "checkout.py"
    assert resolved.is_file()


@pytest.mark.parametrize(
    "relative",
    [
        "../escape",
        "..\\escape",
        "C:\\Windows\\System32",
        "\\\\server\\share",
        "/etc/passwd",
        "a\x00b",
        "a/../../b",
    ],
)
def test_contained_path_rejects_malformed_manifest_entries(tmp_path: Path, relative: str) -> None:
    """An escaping or Windows-absolute manifest entry never escapes its root."""
    with pytest.raises(ValueError):
        contained_path(tmp_path, relative)


def test_artifacts_reject_an_escaping_manifest_relative_path(tmp_path: Path) -> None:
    """A browser evidence manifest cannot smuggle a path outside its directory."""
    runtime = IsolatedRuntime(tmp_path)
    (tmp_path / "artifacts.json").write_text(
        json.dumps(
            {
                "execution_id": "exec-1",
                "artifacts": [
                    {
                        "role": "failure_screenshot",
                        "relative_path": "..\\..\\secrets.txt",
                        "size_bytes": 1,
                        "sha256": "00" * 32,
                        "content_type": "image/png",
                    }
                ],
            }
        )
    )
    with pytest.raises((ValueError, RuntimeUnavailable)):
        runtime._artifacts(tmp_path, "exec-1")


# -- bounded transport address validation ---------------------------------------


@pytest.mark.parametrize("port", ["", "abc", "0", "-1", "65536", "1.5", "80abc"])
def test_bounded_tcp_transport_rejects_malformed_ports(port: str) -> None:
    """A non-integer or out-of-range loopback port fails before any dial."""
    with pytest.raises(RuntimeUnavailable, match="backend_port_invalid"):
        BoundedTCPTransport(port)


def test_bounded_tcp_transport_accepts_valid_ports() -> None:
    assert BoundedTCPTransport("1").port == 1
    assert BoundedTCPTransport("65535").port == 65535
    assert BoundedTCPTransport("8000").port == 8000


def test_bounded_uds_transport_rejects_an_empty_socket_address() -> None:
    with pytest.raises(RuntimeUnavailable, match="backend_transport_invalid"):
        BoundedUDSTransport("")
