"""Aggregate cgroup v2 limits: argv, environment, parsing, modes, and fail-closed paths.

Nothing here launches bubblewrap or contacts a systemd manager. Real scope
creation and kernel enforcement are exercised by test_resource_limits_cgroup.py.
"""

import asyncio
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import pytest
from conftest import SimulatedRuntime
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.isolated_runtime import (
    PROBE_LIMITS,
    AggregateLimits,
    BackendResources,
    Generation,
    IsolatedRuntime,
    ManagedProcess,
    disabled_limits,
    parse_cgroup_events,
    parse_unit_properties,
    probe_verdict,
    scope_cgroup,
    verify_cgroup_values,
)
from app.main import Settings, create_app
from app.model_adapter import MetaRepairAdapter, ModelSettings
from app.runtime import CandidateRejected, RuntimeExecution, RuntimeUnavailable
from app.snapshots import Snapshot
from shared.contracts.models import ExecutionRecord, ExecutionReport, ResourceLimits

INSTALLATION = "3f2b8c1e-9a4d-4e6f-8b7a-1c2d3e4f5a6b"
GENERATION = "0b9c8d7e-6f5a-4b3c-9d2e-1f0a9b8c7d6e"
UNIT = f"faultline-3f2b8c1e9a4d4e6f8b7a1c2d3e4f5a6b-{GENERATION}.scope"
MANAGER = {
    "XDG_RUNTIME_DIR": "/run/user/4242",
    "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/4242/bus",
}
EXACT = {
    "memory.max": "536870912\n",
    "memory.swap.max": "0\n",
    "pids.max": "64\n",
    "cpu.max": "100000 100000\n",
    "memory.oom.group": "1\n",
}
TOKEN = "test-controller-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
NO_PROCESS = cast(ManagedProcess, object())


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[IsolatedRuntime]:
    """A required-mode runtime with fixed tool paths; no tool is ever executed."""
    monkeypatch.delenv("FAULTLINE_AGGREGATE_LIMITS", raising=False)
    for name, address in MANAGER.items():
        monkeypatch.setenv(name, address)
    value = IsolatedRuntime(tmp_path)
    value.bwrap = "/usr/bin/bwrap"
    value.systemd_run = "/usr/bin/systemd-run"
    value.systemctl = "/usr/bin/systemctl"
    value.clear_env = "/usr/bin/env"
    value._installation = INSTALLATION
    yield value


def scope_state(load: str, active: str) -> dict[str, str]:
    return {"LoadState": load, "ActiveState": active, "ControlGroup": ""}


def test_scoped_argv_wraps_the_unchanged_namespace_profile(runtime: IsolatedRuntime) -> None:
    unscoped = runtime._sandbox(Path("/snapshot-source"))
    assert unscoped[0] == "/usr/bin/bwrap" and "--clearenv" in unscoped
    unit = runtime.scope_unit(GENERATION)
    assert unit == UNIT
    scoped = runtime._sandbox(Path("/snapshot-source"), unit=unit)
    separator = scoped.index("--")
    assert scoped[:5] == ["/usr/bin/systemd-run", "--user", "--scope", "--quiet", f"--unit={UNIT}"]
    assert scoped[6:separator] == [
        "--property",
        "MemoryMax=536870912",
        "--property",
        "MemorySwapMax=0",
        "--property",
        "TasksMax=64",
        "--property",
        "CPUQuota=100%",
        "--property",
        "OOMPolicy=kill",
    ]
    # bwrap starts from an empty environment, then runs the byte-identical profile.
    assert scoped[separator + 1 : separator + 3] == ["/usr/bin/env", "-i"]
    assert scoped[separator + 3 :] == unscoped
    probe = runtime._sandbox(Path("/snapshot-source"), unit=unit, limits=PROBE_LIMITS)
    assert {"MemoryMax=67108864", "TasksMax=16", "OOMPolicy=continue"} <= set(probe)


def test_scope_names_are_canonical_and_attributable(runtime: IsolatedRuntime) -> None:
    for bad in (GENERATION.upper(), "{" + GENERATION + "}", "not-a-uuid", ""):
        with pytest.raises(RuntimeUnavailable, match="generation_identity_invalid"):
            runtime.scope_unit(bad)
    runtime._installation = None
    assert runtime.scope_unit(GENERATION) == f"faultline-evaluation-{GENERATION}.scope"
    runtime._installation = "---"
    with pytest.raises(RuntimeUnavailable, match="aggregate_limits_unavailable"):
        runtime.scope_unit(GENERATION)
    for unit in (
        "--user",
        f"other-{GENERATION}.scope",
        f"faultline-{'a' * 65}-{GENERATION}.scope",
        f"faultline-ok-{GENERATION}.service",
    ):
        with pytest.raises(RuntimeUnavailable, match="aggregate_scope_name_invalid"):
            runtime._sandbox(Path("/snapshot-source"), unit=unit)


def test_missing_systemd_run_fails_closed_for_scoped_launches(runtime: IsolatedRuntime) -> None:
    runtime.systemd_run = None
    with pytest.raises(RuntimeUnavailable, match="aggregate_limits_unavailable"):
        runtime._sandbox(Path("/snapshot-source"), unit=UNIT)
    assert runtime._sandbox(Path("/snapshot-source"))[0] == "/usr/bin/bwrap"


def test_only_manager_addresses_reach_systemd_run(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in MANAGER.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("META_API_KEY", "test-only-model-credential")
    monkeypatch.setenv("FAULTLINE_CONTROL_TOKEN", "test-only-control-token")
    runtime = IsolatedRuntime()
    assert runtime.scope_environment(UNIT) == MANAGER
    assert runtime.scope_environment(None) == {}
    status = json.dumps(runtime.resource_limits_status)
    assert "/run/user/4242" not in status and "test-only" not in status
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS")
    assert IsolatedRuntime().scope_environment(UNIT) == {"XDG_RUNTIME_DIR": "/run/user/4242"}


class FakeSystemctl:
    """A completed systemctl process with fixed output; it is never actually run."""

    def __init__(self, code: int, output: bytes) -> None:
        self.returncode = code
        self.output = output

    async def communicate(self) -> tuple[bytes, bytes]:
        return self.output, b""

    async def wait(self) -> int:
        return self.returncode

    def kill(self) -> None:
        raise AssertionError("A completed process is never killed")


@pytest.mark.asyncio
async def test_manager_queries_receive_only_manager_addresses(runtime: IsolatedRuntime) -> None:
    captured: dict[str, Any] = {}

    async def spawn(*args: str, **kwargs: Any) -> FakeSystemctl:
        captured.update(args=args, env=kwargs["env"])
        return FakeSystemctl(0, b"LoadState=not-found\nActiveState=inactive\nControlGroup=\n")

    with patch.object(asyncio, "create_subprocess_exec", spawn):
        await runtime.release_scope(UNIT)
    assert captured["args"][:3] == ("/usr/bin/systemctl", "--user", "--no-pager")
    assert captured["args"][-1] == UNIT
    assert captured["env"] == MANAGER

    async def failing(*args: str, **kwargs: Any) -> FakeSystemctl:
        return FakeSystemctl(1, b"")

    with patch.object(asyncio, "create_subprocess_exec", failing):
        with pytest.raises(RuntimeUnavailable, match="aggregate_limits_unavailable"):
            await runtime._systemctl("show", UNIT)
    runtime.manager_environment = {}
    with pytest.raises(RuntimeUnavailable, match="aggregate_limits_unavailable"):
        await runtime._systemctl("show", UNIT)


def test_kernel_values_must_equal_configuration() -> None:
    assert verify_cgroup_values(EXACT, AggregateLimits()) == ResourceLimits(
        mode="cgroup-v2-scope",
        memory_max_bytes=536870912,
        memory_swap_max_bytes=0,
        tasks_max=64,
        cpu_quota_percent=100,
        verified=True,
    )
    equivalent = verify_cgroup_values({**EXACT, "cpu.max": "50000 50000\n"}, AggregateLimits())
    assert equivalent.cpu_quota_percent == 100
    probe = {**EXACT, "memory.max": "67108864\n", "pids.max": "16\n", "memory.oom.group": "0\n"}
    assert verify_cgroup_values(probe, PROBE_LIMITS).tasks_max == 16


@pytest.mark.parametrize(
    "name,value",
    [
        ("memory.max", "max\n"),
        ("memory.max", "536870913\n"),
        ("memory.max", "-1\n"),
        ("memory.max", "٥\n"),
        ("memory.swap.max", "max\n"),
        ("pids.max", "max\n"),
        ("pids.max", "65\n"),
        ("cpu.max", "max 100000\n"),
        ("cpu.max", "50000 100000\n"),
        ("cpu.max", "100000 0\n"),
        ("cpu.max", "100000\n"),
        ("memory.oom.group", "0\n"),
    ],
)
def test_unlimited_or_mismatched_kernel_values_fail_closed(name: str, value: str) -> None:
    with pytest.raises(RuntimeUnavailable, match="aggregate_limits_unverified"):
        verify_cgroup_values({**EXACT, name: value}, AggregateLimits())


@pytest.mark.parametrize("missing", sorted(EXACT))
def test_missing_limit_file_fails_closed(missing: str) -> None:
    values = {name: value for name, value in EXACT.items() if name != missing}
    with pytest.raises(RuntimeUnavailable, match="aggregate_limits_unverified"):
        verify_cgroup_values(values, AggregateLimits())


def test_manager_and_event_parsing_are_exact() -> None:
    control_group = f"/user.slice/user-1000.slice/app.slice/{UNIT}"
    output = f"LoadState=loaded\nActiveState=active\nControlGroup={control_group}\nOther=x=y\n"
    assert parse_unit_properties(output) == {
        "LoadState": "loaded",
        "ActiveState": "active",
        "ControlGroup": control_group,
    }
    with pytest.raises(RuntimeUnavailable, match="aggregate_limits_unavailable"):
        parse_unit_properties("LoadState=loaded\nActiveState=active\n")
    events = parse_cgroup_events("low 0\nhigh 0\nmax 18\noom 1\noom_kill 1\n")
    assert events == {"low": 0, "high": 0, "max": 18, "oom": 1, "oom_kill": 1}
    with pytest.raises(RuntimeUnavailable, match="aggregate_limits_unverified"):
        parse_cgroup_events("oom one\n")


def test_control_group_paths_are_exact_and_contained(tmp_path: Path) -> None:
    with patch("app.isolated_runtime.CGROUP_ROOT", tmp_path):
        (tmp_path / "cgroup.controllers").write_text("cpu memory pids\n")
        directory = tmp_path / "user.slice" / UNIT
        directory.mkdir(parents=True)
        assert scope_cgroup(f"/user.slice/{UNIT}", UNIT) == directory
        for bad in (
            f"user.slice/{UNIT}",
            f"/user.slice/../user.slice/{UNIT}",
            "/user.slice/other.scope",
            f"/missing/{UNIT}",
            "",
        ):
            with pytest.raises(RuntimeUnavailable, match="aggregate_limits_unverified"):
                scope_cgroup(bad, UNIT)
        (tmp_path / "cgroup.controllers").unlink()  # Not a cgroup v2 hierarchy.
        with pytest.raises(RuntimeUnavailable, match="aggregate_limits_unverified"):
            scope_cgroup(f"/user.slice/{UNIT}", UNIT)


ENFORCED: dict[str, object] = {
    "environment_clean": True,
    "hog_exit_code": -9,
    "threads_started": 13,
}


def test_probe_requires_scope_counters_for_both_limits() -> None:
    memory, tasks = {"oom": 1, "oom_kill": 1}, {"max": 1}
    assert probe_verdict(ENFORCED, memory, tasks) is None
    not_enforced: list[tuple[dict[str, object], dict[str, int], dict[str, int]]] = [
        ({**ENFORCED, "hog_exit_code": 0}, memory, tasks),  # The allocation survived.
        ({**ENFORCED, "hog_exit_code": 1}, memory, tasks),  # MemoryError, not a cgroup kill.
        (ENFORCED, {"oom": 0, "oom_kill": 1}, tasks),  # Killed, but not at this scope's max.
        (ENFORCED, {"oom": 1, "oom_kill": 0}, tasks),
        ({**ENFORCED, "threads_started": 64}, memory, tasks),  # No task bound.
        ({**ENFORCED, "threads_started": 16}, memory, tasks),
        (ENFORCED, memory, {"max": 0}),  # Thread creation failed for another reason.
    ]
    for observed, memory_events, pids_events in not_enforced:
        assert probe_verdict(observed, memory_events, pids_events) == (
            "aggregate_limits_not_enforced"
        )
    for malformed in (
        {**ENFORCED, "environment_clean": False},
        {**ENFORCED, "hog_exit_code": True},
        {"hog_exit_code": -9, "threads_started": 13},
        [ENFORCED],
    ):
        assert probe_verdict(malformed, memory, tasks) == "aggregate_limits_unavailable"


def test_resource_limits_contract_is_strict_and_honest() -> None:
    scope = {
        "mode": "cgroup-v2-scope",
        "memory_max_bytes": 536870912,
        "memory_swap_max_bytes": 0,
        "tasks_max": 64,
        "cpu_quota_percent": 100,
        "verified": True,
    }
    assert ResourceLimits.model_validate_json(json.dumps(scope)).tasks_max == 64
    disabled = disabled_limits()
    assert ResourceLimits.model_validate_json(disabled.model_dump_json()) == disabled
    for invalid in (
        {**disabled.model_dump(), "verified": True},
        {**disabled.model_dump(), "memory_max_bytes": 1},
        {**scope, "tasks_max": None},
        {**scope, "memory_max_bytes": "536870912"},
        {**scope, "tasks_max": True},
        {**scope, "memory_max_bytes": -1},
        {**scope, "mode": "cgroup-v1"},
        {**scope, "extra": 1},
    ):
        with pytest.raises(ValidationError):
            ResourceLimits.model_validate_json(json.dumps(invalid))


REPORT: dict[str, Any] = {
    "execution_id": "execution-1",
    "case_id": "case-1",
    "scenario_id": "scripted_checkout_repair",
    "verdict": "failed",
    "duration_ms": 1.0,
    "observations": [],
    "assertions": [],
    "raw_logs": "",
}


def test_older_execution_records_load_without_limits() -> None:
    record = {
        "schema_version": "1.0",
        "job_id": "job-1",
        "phase": "baseline",
        "app_generation_id": GENERATION,
        "candidate_snapshot_sha256": "0" * 64,
        "runtime_kind": "isolated-browser",
        "artifact_ids": [],
        "started_at": "2026-10-27T12:00:00Z",
        "finished_at": "2026-10-27T12:00:01Z",
        "report": REPORT,
    }
    assert ExecutionRecord.model_validate_json(json.dumps(record)).resource_limits is None
    limited = {**record, "resource_limits": disabled_limits().model_dump()}
    loaded = ExecutionRecord.model_validate_json(json.dumps(limited))
    assert loaded.resource_limits == disabled_limits()
    report = ExecutionReport.model_validate_json(json.dumps(REPORT))
    assert RuntimeExecution(report, GENERATION, "0" * 64, 1, ()).resource_limits is None


@pytest.mark.asyncio
async def test_disabled_mode_names_no_scope_and_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FAULTLINE_AGGREGATE_LIMITS", "disabled")
    runtime = IsolatedRuntime(tmp_path)
    assert runtime.scope_unit(GENERATION) is None
    assert runtime.scope_environment(None) == {}
    assert await runtime.verify_scope(None, NO_PROCESS) == disabled_limits()
    await runtime.release_scope(None)
    status = runtime.resource_limits_status
    assert status["requested"] == "disabled" and status["mode"] == "disabled"
    assert status["configured"] is None


@pytest.mark.asyncio
async def test_required_mode_never_accepts_an_unscoped_launch(runtime: IsolatedRuntime) -> None:
    with pytest.raises(RuntimeUnavailable, match="aggregate_limits_unverified"):
        await runtime.verify_scope(None, NO_PROCESS)
    status = runtime.resource_limits_status
    assert status["mode"] == "cgroup-v2-scope"
    assert status["configured"] == {
        "memory_max_bytes": 536870912,
        "memory_swap_max_bytes": 0,
        "tasks_max": 64,
        "cpu_quota_percent": 100,
        "oom_policy": "kill",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["", "REQUIRED", "off", "required ", "true"])
async def test_unknown_mode_withholds_readiness(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: str
) -> None:
    monkeypatch.setenv("FAULTLINE_AGGREGATE_LIMITS", value)
    runtime = IsolatedRuntime(tmp_path)
    with pytest.raises(RuntimeUnavailable, match="aggregate_limits_mode_invalid"):
        runtime.scope_unit(GENERATION)
    await runtime.reconcile(INSTALLATION)
    assert not runtime.ready
    assert runtime.readiness_reason == "aggregate_limits_mode_invalid"
    status = runtime.resource_limits_status
    assert status["requested"] == "invalid" and status["mode"] is None
    assert status["configured"] is None and status["enforcement_preflight"] == "not_run"


class Completed:
    """A trusted preflight process that already exited successfully."""

    stdout = bytearray(b"ok\n")

    async def wait(self, timeout: float) -> int:
        return 0


def browser_ready(runtime: IsolatedRuntime, root: Path) -> None:
    """Make browser prerequisites present so only aggregate limits decide readiness."""
    runtime.node = "/usr/bin/node"
    for path in (
        runtime.next_cli,
        runtime.runner_cli,
        root / "apps/buggyshop-frontend/.next/BUILD_ID",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test-only\n")


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["systemd_run", "systemctl", "clear_env", "manager"])
async def test_required_mode_without_a_manager_is_not_ready(
    runtime: IsolatedRuntime, tmp_path: Path, missing: str
) -> None:
    if missing == "manager":
        runtime.manager_environment = {}
    else:
        setattr(runtime, missing, None)
    browser_ready(runtime, tmp_path)
    with (
        patch.object(IsolatedRuntime, "_profile_preflight", AsyncMock()),
        patch.object(IsolatedRuntime, "_release_leftover_scopes", AsyncMock()),
        patch.object(ManagedProcess, "start", AsyncMock(return_value=Completed())) as start,
    ):
        await runtime.reconcile(INSTALLATION)
        with pytest.raises(RuntimeUnavailable, match="aggregate_limits_unavailable"):
            await runtime.backend_preflight()
    start.assert_not_awaited()  # Neither the probe nor Chromium launched.
    assert not runtime.ready and not runtime._backend_ready
    assert runtime.readiness_reason == "aggregate_limits_unavailable"
    assert runtime.resource_limits_status["enforcement_preflight"] == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,probe,ready,reason,preflight",
    [
        ("required", None, True, None, "passed"),
        (
            "required",
            "aggregate_limits_not_enforced",
            False,
            "aggregate_limits_not_enforced",
            "failed",
        ),
        (
            "required",
            "aggregate_limits_unavailable",
            False,
            "aggregate_limits_unavailable",
            "failed",
        ),
        ("disabled", "unused", True, None, "disabled"),
    ],
)
async def test_readiness_follows_the_enforcement_preflight(
    runtime: IsolatedRuntime,
    tmp_path: Path,
    mode: str,
    probe: str | None,
    ready: bool,
    reason: str | None,
    preflight: str,
) -> None:
    runtime.aggregate_mode = mode
    browser_ready(runtime, tmp_path)
    enforcement = AsyncMock(return_value=probe)
    with (
        patch.object(IsolatedRuntime, "_profile_preflight", AsyncMock()),
        patch.object(IsolatedRuntime, "_release_leftover_scopes", AsyncMock()),
        patch.object(IsolatedRuntime, "_enforcement_probe", enforcement),
        patch.object(ManagedProcess, "start", AsyncMock(return_value=Completed())),
    ):
        await runtime.reconcile(INSTALLATION)
    assert runtime.ready is ready and runtime._backend_ready is ready
    assert runtime.readiness_reason == reason
    status = runtime.resource_limits_status
    assert status["enforcement_preflight"] == preflight
    if mode == "disabled":
        enforcement.assert_not_awaited()
        assert status["reason"] == "aggregate_limits_disabled"
    else:
        enforcement.assert_awaited_once()


@pytest.mark.asyncio
async def test_unconfirmed_probe_cleanup_raises_from_reconcile(runtime: IsolatedRuntime) -> None:
    failure = RuntimeUnavailable("aggregate_scope_cleanup_unconfirmed")
    with (
        patch.object(IsolatedRuntime, "_profile_preflight", AsyncMock()),
        patch.object(IsolatedRuntime, "_release_leftover_scopes", AsyncMock()),
        patch.object(IsolatedRuntime, "_enforcement_probe", AsyncMock(side_effect=failure)),
    ):
        with pytest.raises(RuntimeUnavailable, match="cleanup_unconfirmed"):
            await runtime.reconcile(INSTALLATION)
    assert not runtime.ready


@pytest.mark.asyncio
async def test_reconcile_releases_only_this_installations_scopes(runtime: IsolatedRuntime) -> None:
    listing = "\n".join(
        [
            f"{UNIT} loaded failed failed FaultLine isolated candidate scope",
            f"faultline-0000000000000000-{GENERATION}.scope loaded active running other",
            "faultline-3f2b8c1e9a4d4e6f8b7a1c2d3e4f5a6b-not-a-generation.scope loaded active "
            "running x",
            f"user-3f2b8c1e9a4d4e6f8b7a1c2d3e4f5a6b-{GENERATION}.scope loaded active "
            "running unrelated",
            "",
        ]
    )
    systemctl = AsyncMock(return_value=listing)
    with (
        patch.object(runtime, "_systemctl", systemctl),
        patch.object(IsolatedRuntime, "release_scope", AsyncMock()) as release,
    ):
        await runtime._release_leftover_scopes()
    systemctl.assert_awaited_once_with(
        "list-units", "--all", "--plain", "--no-legend", "--type=scope", f"{UNIT[:43]}*"
    )
    release.assert_awaited_once_with(UNIT, grace=0)


@pytest.mark.asyncio
async def test_failed_scopes_are_reset_before_absence_is_confirmed(
    runtime: IsolatedRuntime,
) -> None:
    states = iter([scope_state("loaded", "failed"), scope_state("not-found", "inactive")])
    systemctl = AsyncMock(return_value="")
    with (
        patch.object(runtime, "_scope_state", AsyncMock(side_effect=lambda unit: next(states))),
        patch.object(runtime, "_systemctl", systemctl),
    ):
        await runtime.release_scope(UNIT)
    systemctl.assert_awaited_once_with("reset-failed", UNIT)


@pytest.mark.asyncio
async def test_lingering_scopes_are_killed_once_by_unit(runtime: IsolatedRuntime) -> None:
    states = iter([scope_state("loaded", "active")] * 2 + [scope_state("not-found", "inactive")])
    systemctl = AsyncMock(return_value="")
    with (
        patch.object(runtime, "_scope_state", AsyncMock(side_effect=lambda unit: next(states))),
        patch.object(runtime, "_systemctl", systemctl),
    ):
        await runtime.release_scope(UNIT, grace=0)
    systemctl.assert_awaited_once_with("kill", "--signal=SIGKILL", UNIT)


@pytest.mark.asyncio
@pytest.mark.parametrize("unreachable", [False, True])
async def test_unconfirmed_scope_removal_raises_within_its_bound(
    runtime: IsolatedRuntime, unreachable: bool
) -> None:
    state = AsyncMock(
        side_effect=RuntimeUnavailable("aggregate_limits_unavailable") if unreachable else None,
        return_value=scope_state("loaded", "active"),
    )
    with (
        patch("app.isolated_runtime.SCOPE_RELEASE_SECONDS", 0.2),
        patch.object(runtime, "_scope_state", state),
        patch.object(runtime, "_systemctl", AsyncMock(return_value="")),
    ):
        with pytest.raises(RuntimeUnavailable, match="aggregate_scope_cleanup_unconfirmed"):
            await asyncio.wait_for(runtime.release_scope(UNIT, grace=0), 2)
    with pytest.raises(RuntimeUnavailable, match="aggregate_scope_name_invalid"):
        await runtime.release_scope("--all")


def owned_snapshot(root: Path) -> Snapshot:
    return Snapshot(root, root, GENERATION, "0" * 64, "", "0" * 64, "test-only")


@pytest.mark.asyncio
async def test_cleanup_keeps_ownership_until_scope_absence_is_confirmed(
    runtime: IsolatedRuntime, tmp_path: Path
) -> None:
    directory = tmp_path / "owned-generation"
    directory.mkdir()
    owned = Generation(owned_snapshot(tmp_path), directory, BackendResources(unit=UNIT))
    runtime.generations["test-job"] = owned
    failure = RuntimeUnavailable("aggregate_scope_cleanup_unconfirmed")
    with patch.object(runtime, "release_scope", AsyncMock(side_effect=failure)):
        with pytest.raises(RuntimeUnavailable, match="cleanup_unconfirmed"):
            await runtime.cleanup(INSTALLATION, "test-job")
    assert runtime.generations["test-job"] is owned and directory.is_dir()
    with patch.object(runtime, "release_scope", AsyncMock()) as release:
        await runtime.cleanup(INSTALLATION, "test-job")
    release.assert_awaited_once_with(UNIT)
    assert not runtime.generations and not directory.exists()


@pytest.mark.asyncio
async def test_execute_refuses_a_generation_without_a_limits_record(
    runtime: IsolatedRuntime, tmp_path: Path
) -> None:
    snap = owned_snapshot(tmp_path)
    client = httpx.AsyncClient()
    backend = BackendResources(unit=UNIT, client=client)
    runtime.generations["test-job"] = Generation(snap, tmp_path, backend)
    try:
        with pytest.raises(RuntimeUnavailable, match="generation_not_active"):
            await runtime.execute("test-job", str(uuid4()), "baseline", snap, 1000)
    finally:
        await client.aclose()


def application_tree(root: Path) -> Path:
    app = root / "apps/buggyshop-backend/app/routes"
    app.mkdir(parents=True)
    (app.parent / "main.py").write_text("app = None\n")
    (app / "checkout.py").write_text("VALUE = 1\n")
    return root


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("nothing", None),
        ("missing", "application_tree_missing"),
        ("symlink", "snapshot_symlink_forbidden"),
        ("root_symlink", "snapshot_symlink_forbidden"),
        ("nonpython", "snapshot_nonapplication_file"),
        ("outside", "snapshot_nonapplication_file"),
        ("dotenv", "snapshot_nonapplication_file"),
        ("fifo", "snapshot_nonapplication_file"),
    ],
)
def test_backend_sessions_mount_only_application_python(
    tmp_path: Path, mutation: str, reason: str | None
) -> None:
    root = application_tree(tmp_path / "tree")
    app = root / "apps/buggyshop-backend/app"
    target: Path = root
    if mutation == "missing":
        target = tmp_path / "empty"
        target.mkdir()
    elif mutation == "symlink":
        (app / "linked.py").symlink_to(app / "main.py")
    elif mutation == "root_symlink":
        target = tmp_path / "link"
        target.symlink_to(root)
    elif mutation == "nonpython":
        (app / "data.json").write_text("{}\n")
    elif mutation == "outside":
        (root / "apps/buggyshop-backend/conftest.py").write_text("x = 1\n")
    elif mutation == "dotenv":
        (root / ".env").write_text("TEST_ONLY=1\n")
    elif mutation == "fifo":
        os.mkfifo(app / "pipe.py")
    if reason is None:
        assert IsolatedRuntime._verify_application(target) == root.resolve()
    else:
        with pytest.raises(CandidateRejected, match=reason):
            IsolatedRuntime._verify_application(target)


@pytest.mark.asyncio
async def test_backend_session_requires_a_passed_backend_preflight(
    runtime: IsolatedRuntime, tmp_path: Path
) -> None:
    root = application_tree(tmp_path)
    with pytest.raises(RuntimeUnavailable, match="isolated_runtime_unavailable"):
        async with runtime.backend_session(root):
            pytest.fail("A session must not start before preflight")


@pytest.mark.asyncio
async def test_backend_session_yields_limits_and_confirms_scope_release(
    runtime: IsolatedRuntime, tmp_path: Path
) -> None:
    root = application_tree(tmp_path)
    runtime._backend_ready = True
    verified = verify_cgroup_values(EXACT, AggregateLimits())
    launched: list[BackendResources] = []

    async def launch(backend: BackendResources, application: Path, generation_id: str) -> None:
        assert application == root.resolve()
        assert backend.unit == f"faultline-3f2b8c1e9a4d4e6f8b7a1c2d3e4f5a6b-{generation_id}.scope"
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))
        backend.client = httpx.AsyncClient(transport=transport, base_url="http://test")
        backend.resource_limits = verified
        launched.append(backend)

    with (
        patch.object(runtime, "_launch_backend", launch),
        patch.object(runtime, "release_scope", AsyncMock()) as release,
    ):
        async with runtime.backend_session(root) as handle:
            assert (await handle.client.get("/healthz")).json() == {"ok": True}
            assert handle.resource_limits == verified and handle.logs() == ""
        release.assert_awaited_once_with(launched[0].unit)
        assert handle.client.is_closed

        async def rejected(backend: BackendResources, application: Path, _: str) -> None:
            launched.append(backend)
            raise CandidateRejected("isolated_backend_failed")

        with patch.object(runtime, "_launch_backend", rejected):
            with pytest.raises(CandidateRejected, match="isolated_backend_failed"):
                async with runtime.backend_session(root):
                    pytest.fail("A rejected backend must not yield a session")
        assert release.await_args_list[-1].args == (launched[-1].unit,)


class LimitedRuntime(SimulatedRuntime):
    """A simulation exposing the optional readiness capabilities of IsolatedRuntime."""

    def __init__(self, ready: bool, reason: str | None, status: dict[str, object]) -> None:
        super().__init__()
        self.ready = ready
        self.readiness_reason = reason
        self.resource_limits_status = status


def readiness(tmp_path: Path, runtime: Any) -> dict[str, Any]:
    adapter = MetaRepairAdapter(ModelSettings())
    app = create_app(
        Settings(data_dir=tmp_path, control_token=TOKEN), adapter=adapter, runtime=runtime
    )
    with TestClient(app) as client:
        body: dict[str, Any] = client.get("/api/faultline/readiness", headers=HEADERS).json()
        return body


def test_readiness_surfaces_the_specific_aggregate_limit_reason(tmp_path: Path) -> None:
    status: dict[str, object] = {
        "requested": "required",
        "mode": "cgroup-v2-scope",
        "configured": None,
        "enforcement_preflight": "failed",
        "probe": None,
        "reason": "aggregate_limits_unavailable",
    }
    body = readiness(tmp_path, LimitedRuntime(False, "aggregate_limits_unavailable", status))
    assert body["status"] == "blocked" and body["runtime_ready"] is False
    assert body["reason"] == "aggregate_limits_unavailable"
    assert body["resource_limits"] == status


def test_readiness_states_when_aggregate_limits_are_disabled(tmp_path: Path) -> None:
    status: dict[str, object] = {
        "requested": "disabled",
        "mode": "disabled",
        "configured": None,
        "enforcement_preflight": "disabled",
        "probe": None,
        "reason": "aggregate_limits_disabled",
    }
    body = readiness(tmp_path / "disabled", LimitedRuntime(True, None, status))
    assert body["runtime_ready"] is True and body["reason"] is None
    assert body["resource_limits"]["mode"] == "disabled"
    plain = SimulatedRuntime()
    plain.ready = False
    body = readiness(tmp_path / "plain", plain)
    assert body["resource_limits"] is None
    assert body["reason"] == "isolated_runtime_unavailable"


def test_real_runtime_reports_an_invalid_mode_through_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAULTLINE_AGGREGATE_LIMITS", "sometimes")
    body = readiness(tmp_path, IsolatedRuntime(tmp_path))
    assert body["status"] == "blocked"
    assert body["reason"] == "aggregate_limits_mode_invalid"
    assert body["resource_limits"]["requested"] == "invalid"
    assert "sometimes" not in json.dumps(body)
