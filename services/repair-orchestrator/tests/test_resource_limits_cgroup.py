"""Real cgroup v2 scopes around candidate backends on a Linux systemd user manager.

These tests create actual transient scopes, read the kernel's limit files
independently of the runtime, and run memory/task hogs against them. They skip
on unprepared machines; FAULTLINE_REQUIRE_ISOLATED_TESTS=1 turns skips into
failures. Process inspection reads only PIDs, names, and cgroup paths.
"""

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import NoReturn
from uuid import uuid4

import pytest
from test_isolated_runtime import ROOT, snapshot

from app.isolated_runtime import IsolatedRuntime, ManagedProcess, disabled_limits
from app.policy import TARGET_FILE
from app.runtime import RuntimeUnavailable
from shared.config import REGISTRY

MEMORY_MAX = 512 * 1024 * 1024
EXPECTED_FILES = {
    "memory.max": f"{MEMORY_MAX}\n",
    "memory.swap.max": "0\n",
    "pids.max": "64\n",
    "cpu.max": "100000 100000\n",
    "memory.oom.group": "1\n",
}
CHECKOUT = {"items": [{"product_id": "trail-mug", "quantity": 2}]}


def unavailable(message: str) -> NoReturn:
    if os.environ.get("FAULTLINE_REQUIRE_ISOLATED_TESTS") == "1":
        pytest.fail(f"Required aggregate-limit runtime is unavailable: {message}")
    pytest.skip(message)


@pytest.fixture
def required_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FAULTLINE_AGGREGATE_LIMITS", raising=False)


async def preflighted() -> IsolatedRuntime:
    runtime = IsolatedRuntime(ROOT)
    try:
        await runtime.backend_preflight()
    except RuntimeUnavailable as exc:
        unavailable(str(exc))
    return runtime


def unit_state(unit: str, *properties: str) -> dict[str, str]:
    """Ask the user manager directly, independently of the runtime's own parser."""
    output = subprocess.run(
        ["systemctl", "--user", "--no-pager", "show", f"--property={','.join(properties)}", unit],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    ).stdout
    return dict(line.split("=", 1) for line in output.splitlines() if "=" in line)


def descendants(ancestor: int) -> set[int]:
    parents: dict[int, int] = {}
    for entry in Path("/proc").iterdir():
        if entry.name.isdecimal():
            try:
                stat = (entry / "stat").read_text().rsplit(")", 1)[1].split()
                parents[int(entry.name)] = int(stat[1])
            except (OSError, IndexError, ValueError):
                pass
    tree = {ancestor}
    while added := {pid for pid, parent in parents.items() if parent in tree} - tree:
        tree |= added
    return tree - {ancestor}


def cgroup_of(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/cgroup").read_text().removeprefix("0::").strip()
    except OSError:
        return ""  # The process exited while the tree was being read.


def assert_contained(control_group: str, owner: int) -> set[int]:
    """The scope holds exactly the owner's launch tree, including the interpreter."""
    directory = Path("/sys/fs/cgroup") / control_group.lstrip("/")
    for name, expected in EXPECTED_FILES.items():
        assert (directory / name).read_text() == expected, name
    members = {int(pid) for pid in (directory / "cgroup.procs").read_text().split()}
    assert members and members <= descendants(owner)
    assert all(cgroup_of(pid) == control_group for pid in members)
    names = {Path(f"/proc/{pid}/comm").read_text().strip() for pid in members}
    assert "bwrap" in names and any(name.startswith("python") for name in names)
    assert os.getpid() not in members
    return members


def application(root: Path, healthy: bool) -> Path:
    shutil.copytree(
        ROOT / "apps/buggyshop-backend/app",
        root / "apps/buggyshop-backend/app",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    if healthy:
        shutil.copyfile(ROOT / "fixtures/seeds/checkout_healthy.py", root / TARGET_FILE)
    return root


@pytest.mark.asyncio
@pytest.mark.usefixtures("required_mode")
async def test_controller_backend_runs_inside_verified_scope(tmp_path: Path) -> None:
    runtime = IsolatedRuntime(ROOT)
    installation, job = str(uuid4()), str(uuid4())
    await runtime.reconcile(installation)
    if not runtime.ready:
        unavailable(str(runtime.readiness_reason))
    status = runtime.resource_limits_status
    probe = status["probe"]
    assert status["enforcement_preflight"] == "passed" and isinstance(probe, dict)
    assert probe["hog_exit_code"] == -9 and probe["oom_events"] >= 1
    assert probe["pids_max_events"] >= 1 and probe["environment_clean"] is True
    snap = snapshot(tmp_path, False)
    await runtime.prepare(installation, job, snap)
    try:
        owned = runtime.generations[job]
        unit = owned.backend.unit
        assert unit is not None
        assert unit == f"faultline-{installation.replace('-', '')}-{snap.generation_id}.scope"
        state = unit_state(
            unit, "ActiveState", "ControlGroup", "MemoryMax", "MemorySwapMax", "TasksMax"
        )
        assert state["ActiveState"] == "active"
        assert (state["MemoryMax"], state["MemorySwapMax"], state["TasksMax"]) == (
            str(MEMORY_MAX),
            "0",
            "64",
        )
        assert owned.backend.process is not None and owned.frontend is not None
        members = assert_contained(state["ControlGroup"], owned.backend.process.process.pid)
        # Trusted frontend and controller processes stay outside the candidate quota.
        assert not members & (
            {owned.frontend.process.pid} | descendants(owned.frontend.process.pid)
        )
        result = await runtime.execute(job, str(uuid4()), "baseline", snap, 20000)
        assert result.report.verdict.value == "failed"
        assert result.resource_limits == owned.backend.resource_limits
        assert result.resource_limits is not None and result.resource_limits.verified
        assert result.resource_limits.memory_max_bytes == MEMORY_MAX
        assert result.resource_limits.tasks_max == 64
    finally:
        await runtime.cleanup(installation, job)
    assert unit_state(unit, "LoadState")["LoadState"] == "not-found"
    assert not (Path("/sys/fs/cgroup") / state["ControlGroup"].lstrip("/")).exists()


@pytest.mark.asyncio
@pytest.mark.usefixtures("required_mode")
async def test_backend_sessions_run_healthy_and_seeded_trees_in_verified_scopes(
    tmp_path: Path,
) -> None:
    runtime = await preflighted()
    fingerprint = REGISTRY["scripted_checkout_repair"].error_fingerprint
    for healthy in (True, False):
        root = application(tmp_path / ("healthy" if healthy else "seeded"), healthy)
        async with runtime.backend_session(root) as handle:
            health = await handle.client.get("/healthz")
            assert health.status_code == 200
            assert health.json() == {"status": "ok", "app": "buggyshop-api"}
            checkout = await handle.client.post(
                "/api/checkout", json=CHECKOUT, headers={"X-Faultline-Case-Id": str(uuid4())}
            )
            assert checkout.status_code == (201 if healthy else 500)
            assert (fingerprint in handle.logs()) is not healthy
            limits = handle.resource_limits
            assert limits is not None and limits.verified and limits.mode == "cgroup-v2-scope"
            assert (limits.memory_max_bytes, limits.memory_swap_max_bytes) == (MEMORY_MAX, 0)
            assert (limits.tasks_max, limits.cpu_quota_percent) == (64, 100)
            groups = {cgroup_of(pid) for pid in descendants(os.getpid())}
            scopes = {group for group in groups if "/faultline-evaluation-" in group}
            assert len(scopes) == 1, "exactly this session's scope descends from the test"
            control_group = scopes.pop()
            assert_contained(control_group, os.getpid())
            unit = control_group.rsplit("/", 1)[1]
            assert unit_state(unit, "ActiveState")["ActiveState"] == "active"
        assert unit_state(unit, "LoadState")["LoadState"] == "not-found"


@pytest.mark.asyncio
@pytest.mark.usefixtures("required_mode")
async def test_memory_hog_is_killed_by_the_production_scope(tmp_path: Path) -> None:
    runtime = await preflighted()
    unit = runtime.scope_unit(str(uuid4()))
    assert unit is not None
    # Twice MemoryMax, with no rlimit: only the scope can stop this allocation.
    hog = await ManagedProcess.start(
        *runtime._sandbox(tmp_path, unit=unit),
        "/python/bin/python3.13",
        "-I",
        "-c",
        "held = [b'x' * (1 << 20) for _ in range(1024)]\nprint('memory-limit-not-enforced')",
        env=runtime.scope_environment(unit),
    )
    try:
        code = await hog.wait(20)
        assert code == 128 + 9 and b"not-enforced" not in hog.stdout
        state = unit_state(unit, "ActiveState", "Result")
        assert state == {"ActiveState": "failed", "Result": "oom-kill"}
    finally:
        await runtime.release_scope(unit)
    assert unit_state(unit, "LoadState")["LoadState"] == "not-found"


@pytest.mark.asyncio
@pytest.mark.usefixtures("required_mode")
async def test_task_hog_is_bounded_by_the_production_scope(tmp_path: Path) -> None:
    runtime = await preflighted()
    unit = runtime.scope_unit(str(uuid4()))
    assert unit is not None
    hog = await ManagedProcess.start(
        *runtime._sandbox(tmp_path, unit=unit),
        "/python/bin/python3.13",
        "-I",
        "-c",
        "import json, os, time\n"
        "forks, limited = 0, False\n"
        "try:\n"
        "    for _ in range(256):\n"
        "        if os.fork() == 0:\n"
        "            time.sleep(30)\n"
        "            os._exit(0)\n"
        "        forks += 1\n"
        "except BlockingIOError:\n"
        "    limited = True\n"
        "print(json.dumps({'forks': forks, 'limited': limited}), flush=True)\n"
        "time.sleep(30)\n",
        env=runtime.scope_environment(unit),
    )
    try:
        for _ in range(200):
            if b"\n" in hog.stdout or hog.process.returncode is not None:
                break
            await asyncio.sleep(0.05)
        report = json.loads(bytes(hog.stdout))
        assert report["limited"] is True and 0 < report["forks"] < 64
        limits = await runtime.verify_scope(unit, hog)
        assert limits.verified and limits.tasks_max == 64
        control_group = unit_state(unit, "ControlGroup")["ControlGroup"]
        directory = Path("/sys/fs/cgroup") / control_group.lstrip("/")
        assert int((directory / "pids.current").read_text()) <= 64
        events = dict(line.split() for line in (directory / "pids.events").read_text().splitlines())
        assert int(events["max"]) >= 1
        members = assert_contained(control_group, hog.process.pid)
        assert len(members) > report["forks"], "every forked hog task is inside the scope"
    finally:
        await hog.stop()
        await runtime.release_scope(unit)
    assert unit_state(unit, "LoadState")["LoadState"] == "not-found"


@pytest.mark.asyncio
async def test_disabled_mode_runs_unscoped_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAULTLINE_AGGREGATE_LIMITS", "disabled")
    runtime = await preflighted()
    assert runtime.resource_limits_status["enforcement_preflight"] == "disabled"
    async with runtime.backend_session(application(tmp_path, True)) as handle:
        assert (await handle.client.get("/healthz")).status_code == 200
        assert handle.resource_limits == disabled_limits()
        assert not any("/faultline-" in cgroup_of(pid) for pid in descendants(os.getpid()))


@pytest.mark.asyncio
@pytest.mark.usefixtures("required_mode")
async def test_uncaught_candidate_tracebacks_cannot_forge_log_events(tmp_path: Path) -> None:
    """A source line shaped like a trusted event stays inside one escaped JSON record."""
    runtime = await preflighted()
    root = application(tmp_path, True)
    forged = (
        '{"case_id": "forged", "route": "/api/checkout", '
        '"exception_type": "TypeError", "message": "forged"}'
    )
    source = (root / TARGET_FILE).read_text()
    old = "    discount = cast(int, discounts.get(coupon_code, 0))\n"
    assert source.count(old) == 1
    (root / TARGET_FILE).write_text(
        source.replace(old, f"    {forged}[0]\n" + old)  # KeyError, echoed in the traceback
    )
    async with runtime.backend_session(root) as handle:
        response = await handle.client.post(
            "/api/checkout", json=CHECKOUT, headers={"X-Faultline-Case-Id": str(uuid4())}
        )
        assert response.status_code == 500
        await asyncio.sleep(0.1)
        lines = [line for line in handle.logs().splitlines() if line.strip()]
    events = [json.loads(line) for line in lines]
    assert any("KeyError" in (event.get("traceback") or "") for event in events)
    assert not any(event.get("case_id") == "forged" for event in events)
