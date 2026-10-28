"""Linux bubblewrap backend isolation with an external trusted browser oracle.

Only candidate Python executes in the private namespace. Trusted HTTP regression,
the frontend proxy, Chromium, and the fixed browser CLI execute outside it. This
is process/filesystem/network isolation, not a VM or a production deployer.

By default each candidate namespace also runs inside a transient systemd user
scope whose cgroup v2 memory, swap, task, and CPU limits apply to all of its
tasks together. Those limits are read back from the kernel after launch and
their enforcement is probed before readiness; they are accounting limits on a
shared kernel, not hardware isolation.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import sys
import sysconfig
import tempfile
import time
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Literal
from uuid import UUID, uuid4

import httpx
import uvicorn
from fastapi import FastAPI, Request, Response

from app.database import utcnow
from app.http_regression import regression
from app.runtime import (
    CandidateRejected,
    Phase,
    RuntimeArtifact,
    RuntimeExecution,
    RuntimeUnavailable,
)
from app.snapshots import REPOSITORY_ROOT, Snapshot, contained_path
from shared.config import REGISTRY
from shared.contracts.models import (
    AssertionResult,
    ExecutionReport,
    ExecutionVerdict,
    Observation,
    ObservationKind,
    ResourceLimits,
)

LOG_LIMIT = 256 * 1024
REPORT_LIMIT = 64 * 1024

AGGREGATE_MODES = frozenset({"required", "disabled"})
# Reasons that withhold readiness; "aggregate_limits_disabled" is informational.
BLOCKING_LIMIT_REASONS = frozenset(
    {
        "aggregate_limits_mode_invalid",
        "aggregate_limits_unavailable",
        "aggregate_limits_not_enforced",
    }
)
CGROUP_ROOT = Path("/sys/fs/cgroup")
SCOPE_LIMIT_FILES = ("memory.max", "memory.swap.max", "pids.max", "cpu.max", "memory.oom.group")
SCOPE_PROPERTIES = ("LoadState", "ActiveState", "ControlGroup")
SCOPE_RELEASE_SECONDS = 2.0
UNIT_PATTERN = re.compile(
    r"faultline-[a-z0-9]{1,64}-"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.scope"
)


@dataclass(frozen=True)
class AggregateLimits:
    """Aggregate cgroup v2 limits shared by every task in one transient user scope.

    MemorySwapMax=0 stops memory pressure moving to swap or zram, so MemoryMax
    bounds resident memory. OOMPolicy=kill sets memory.oom.group, so the kernel
    kills every task in the scope together instead of choosing one victim.
    """

    memory_max_bytes: int = 512 * 1024 * 1024
    memory_swap_max_bytes: int = 0
    tasks_max: int = 64
    cpu_quota_percent: int = 100
    oom_policy: Literal["kill", "continue"] = "kill"

    def properties(self) -> list[str]:
        """Return systemd-run property arguments built only from typed values."""
        values = (
            f"MemoryMax={self.memory_max_bytes}",
            f"MemorySwapMax={self.memory_swap_max_bytes}",
            f"TasksMax={self.tasks_max}",
            f"CPUQuota={self.cpu_quota_percent}%",
            f"OOMPolicy={self.oom_policy}",
        )
        return [argument for value in values for argument in ("--property", value)]


# The probe scope survives its OOM kill (OOMPolicy=continue) so the controller can
# read that scope's own kernel event counters while it is still alive.
PROBE_LIMITS = AggregateLimits(64 * 1024 * 1024, 0, 16, 100, "continue")
PROBE_ALLOCATION_MIB = 256
PROBE_THREADS = 64
# No rlimits apply here: only the scope's cgroup can stop the 256 MiB child or the
# 64-thread burst. Manager addresses given to systemd-run must reach neither the
# candidate environment nor bwrap's initial environment, readable at /proc/1.
PROBE_SCRIPT = f"""\
import json, os, threading, time
allowed = {{'PATH', 'HOME', 'PYTHONDONTWRITEBYTECODE', 'PYTHONUNBUFFERED', 'PWD', 'LC_CTYPE'}}
try:
    initial = open('/proc/1/environ', 'rb').read()
except PermissionError:
    initial = b''
clean = set(os.environ) <= allowed and initial == b''
child = os.fork()
if child == 0:
    held = [b'x' * (1 << 20) for _ in range({PROBE_ALLOCATION_MIB})]
    os._exit(0)
hog = os.waitstatus_to_exitcode(os.waitpid(child, 0)[1])
release, started = threading.Event(), 0
try:
    for _ in range({PROBE_THREADS}):
        threading.Thread(target=release.wait, daemon=True).start()
        started += 1
except RuntimeError:
    pass
release.set()
report = {{'environment_clean': clean, 'hog_exit_code': hog, 'threads_started': started}}
print(json.dumps(report), flush=True)
time.sleep(10)
"""


def disabled_limits() -> ResourceLimits:
    """The explicit operator opt-out record: no aggregate quota, nothing verified."""
    return ResourceLimits(
        mode="disabled",
        memory_max_bytes=None,
        memory_swap_max_bytes=None,
        tasks_max=None,
        cpu_quota_percent=None,
        verified=False,
    )


def parse_unit_properties(output: str) -> dict[str, str]:
    """Parse ``systemctl show`` KEY=VALUE lines; a missing property fails closed."""
    state: dict[str, str] = {}
    for line in output.splitlines():
        key, separator, value = line.partition("=")
        if separator and key in SCOPE_PROPERTIES:
            state[key] = value
    if set(state) != set(SCOPE_PROPERTIES):
        raise RuntimeUnavailable("aggregate_limits_unavailable")
    return state


def parse_cgroup_events(text: str) -> dict[str, int]:
    """Parse a cgroup v2 ``*.events`` file of ``name count`` lines."""
    events: dict[str, int] = {}
    for line in text.splitlines():
        name, _, count = line.partition(" ")
        if not (count.isascii() and count.isdecimal()):
            raise RuntimeUnavailable("aggregate_limits_unverified")
        events[name] = int(count)
    return events


def scope_cgroup(control_group: str, unit: str) -> Path:
    """Map a manager-reported ControlGroup to its cgroup v2 directory, exactly."""
    path = PurePosixPath(control_group)
    if (
        not path.is_absolute()
        or path.name != unit
        or ".." in path.parts
        or not (CGROUP_ROOT / "cgroup.controllers").is_file()
    ):
        raise RuntimeUnavailable("aggregate_limits_unverified")
    directory = CGROUP_ROOT.joinpath(*path.parts[1:])
    if not directory.is_dir():
        raise RuntimeUnavailable("aggregate_limits_unverified")
    return directory


def verify_cgroup_values(values: Mapping[str, str], limits: AggregateLimits) -> ResourceLimits:
    """Compare raw cgroup v2 limit files with configuration; ``max`` never matches."""

    def integer(text: str) -> int:
        value = text.strip()
        if not (value.isascii() and value.isdecimal()):
            raise RuntimeUnavailable("aggregate_limits_unverified")
        return int(value)

    try:
        memory = integer(values["memory.max"])
        swap = integer(values["memory.swap.max"])
        tasks = integer(values["pids.max"])
        group = integer(values["memory.oom.group"])
        quota_text, period_text = values["cpu.max"].split()
        quota, period = integer(quota_text), integer(period_text)
    except (KeyError, ValueError):
        raise RuntimeUnavailable("aggregate_limits_unverified") from None
    if (
        memory != limits.memory_max_bytes
        or swap != limits.memory_swap_max_bytes
        or tasks != limits.tasks_max
        or group != (1 if limits.oom_policy == "kill" else 0)
        or period <= 0
        or quota * 100 != limits.cpu_quota_percent * period
    ):
        raise RuntimeUnavailable("aggregate_limits_unverified")
    return ResourceLimits(
        mode="cgroup-v2-scope",
        memory_max_bytes=memory,
        memory_swap_max_bytes=swap,
        tasks_max=tasks,
        cpu_quota_percent=quota * 100 // period,
        verified=True,
    )


def process_parents() -> dict[int, int]:
    """Map visible PIDs to parent PIDs from nonsecret /proc stat fields only."""
    parents: dict[int, int] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            parents[int(entry.name)] = int(
                (entry / "stat").read_text().rsplit(")", 1)[1].split()[1]
            )
        except (OSError, IndexError, ValueError):
            pass
    return parents


def confirm_membership(directory: Path, control_group: str, supervisor: int) -> None:
    """Require the scope to hold exactly the supervised launch and its descendants."""
    members = {int(value) for value in (directory / "cgroup.procs").read_text().split()}
    parents = process_parents()
    launched = [pid for pid, parent in parents.items() if parent == supervisor]
    if len(launched) != 1 or launched[0] not in members:
        raise RuntimeUnavailable("aggregate_limits_unverified")
    tree = set(launched)
    while added := {pid for pid, parent in parents.items() if parent in tree} - tree:
        tree |= added
    expected = f"0::{control_group}\n"
    if not members <= tree or any(
        Path(f"/proc/{pid}/cgroup").read_text() != expected for pid in tree
    ):
        raise RuntimeUnavailable("aggregate_limits_unverified")


def probe_verdict(
    observed: object, memory_events: Mapping[str, int], pids_events: Mapping[str, int]
) -> str | None:
    """Judge enforcement from in-scope output and the probe scope's own counters.

    The scope's ``oom`` counter rises only when this cgroup reaches its own
    memory.max; a global OOM kill or an rlimit cannot raise it. ``pids.events``
    ``max`` likewise counts only forks refused by this cgroup's pids.max.
    """
    if not isinstance(observed, dict):
        return "aggregate_limits_unavailable"
    clean = observed.get("environment_clean")
    hog = observed.get("hog_exit_code")
    threads = observed.get("threads_started")
    if type(clean) is not bool or type(hog) is not int or type(threads) is not int or not clean:
        return "aggregate_limits_unavailable"
    memory_enforced = (
        hog == -signal.SIGKILL
        and memory_events.get("oom", 0) >= 1
        and memory_events.get("oom_kill", 0) >= 1
    )
    tasks_enforced = 0 <= threads < PROBE_LIMITS.tasks_max and pids_events.get("max", 0) >= 1
    return None if memory_enforced and tasks_enforced else "aggregate_limits_not_enforced"


class BoundedUDSTransport(httpx.AsyncBaseTransport):
    """Bound every untrusted backend response before HTTPX buffers or decodes it."""

    def __init__(self, uds: str) -> None:
        self.inner: httpx.AsyncBaseTransport = httpx.AsyncHTTPTransport(uds=uds)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        async with asyncio.timeout(3):
            return await self._bounded_request(request)

    async def _bounded_request(self, request: httpx.Request) -> httpx.Response:
        response = await self.inner.handle_async_request(request)
        try:
            # Compressed bodies could expand after a raw-byte cap; the fixture
            # requires plain JSON, so reject unsupported compression outright.
            if response.headers.get("content-encoding", "identity") != "identity":
                raise RuntimeUnavailable("backend_compressed_response_forbidden")
            content = bytearray()
            async for chunk in response.aiter_raw():
                if len(content) + len(chunk) > REPORT_LIMIT:
                    raise RuntimeUnavailable("backend_response_limit")
                content.extend(chunk)
            return httpx.Response(
                response.status_code,
                headers=response.headers,
                content=bytes(content),
                request=request,
            )
        finally:
            await response.aclose()

    async def aclose(self) -> None:
        await self.inner.aclose()


@dataclass
class ManagedProcess:
    """Own every process and pipe task until an observed, reaped exit."""

    process: asyncio.subprocess.Process
    pumps: list[asyncio.Task[None]] = field(default_factory=list)
    stdout: bytearray = field(default_factory=bytearray)
    stderr: bytearray = field(default_factory=bytearray)
    overflow: bool = False
    liveness_fd: int | None = None

    @classmethod
    async def start(
        cls,
        *args: str,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        pass_fds: tuple[int, ...] = (),
    ) -> ManagedProcess:
        read_fd, write_fd = os.pipe2(os.O_CLOEXEC)
        supervisor = Path(__file__).with_name("process_supervisor.py")
        spawn = asyncio.create_task(
            asyncio.create_subprocess_exec(
                sys.executable,
                "-I",
                str(supervisor),
                str(read_fd),
                ",".join(str(fd) for fd in pass_fds),
                *args,
                cwd=cwd,
                env=env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
                pass_fds=(read_fd, *pass_fds),
            )
        )
        try:
            process = await asyncio.shield(spawn)
        except BaseException:
            os.close(write_fd)
            try:
                process = await spawn
                await process.communicate()
            finally:
                os.close(read_fd)
            raise
        os.close(read_fd)
        owned = cls(process, liveness_fd=write_fd)

        async def drain(stream: asyncio.StreamReader, target: bytearray) -> None:
            while chunk := await stream.read(8192):
                remaining = LOG_LIMIT - len(target)
                target.extend(chunk[: max(0, remaining)])
                if len(chunk) > remaining:
                    owned.overflow = True
                    owned.request_stop()

        assert process.stdout is not None and process.stderr is not None
        owned.pumps = [
            asyncio.create_task(drain(process.stdout, owned.stdout)),
            asyncio.create_task(drain(process.stderr, owned.stderr)),
        ]
        return owned

    def request_stop(self) -> None:
        if self.liveness_fd is not None:
            os.close(self.liveness_fd)
            self.liveness_fd = None

    async def stop(self) -> None:
        """Close the sole liveness writer, then confirm supervisor cleanup/reap."""
        self.request_stop()
        async with asyncio.timeout(4):
            await self.process.wait()
            await asyncio.gather(*self.pumps)

    async def wait(self, timeout: float) -> int:
        try:
            async with asyncio.timeout(timeout):
                result = await self.process.wait()
                await asyncio.gather(*self.pumps)
                if self.overflow:
                    raise RuntimeUnavailable("trusted_process_output_limit")
                return result
        finally:
            await asyncio.shield(self.stop())


@dataclass
class BackendResources:
    """One namespaced candidate backend, each part registered before creation."""

    unit: str | None = None
    listener: socket.socket | None = None
    process: ManagedProcess | None = None
    client: httpx.AsyncClient | None = None
    resource_limits: ResourceLimits | None = None

    def logs(self) -> str:
        """Decode the backend's bounded stderr captured so far."""
        if self.process is None:
            return ""
        return bytes(self.process.stderr).decode("utf-8", errors="replace")


@dataclass(frozen=True)
class BackendHandle:
    """A ready backend-only session and its aggregate-limit record."""

    client: httpx.AsyncClient
    logs: Callable[[], str]
    resource_limits: ResourceLimits | None


@dataclass
class Generation:
    snapshot: Snapshot
    directory: Path
    backend: BackendResources = field(default_factory=BackendResources)
    frontend: ManagedProcess | None = None
    runner: ManagedProcess | None = None
    bridge_server: uvicorn.Server | None = None
    bridge_task: asyncio.Task[None] | None = None
    bridge_socket: socket.socket | None = None
    frontend_url: str = ""


class IsolatedRuntime:
    """Execute only application exports in a fresh Linux namespace per generation.

    ``FAULTLINE_AGGREGATE_LIMITS=required`` (the default) runs every candidate
    backend in a transient systemd user scope whose cgroup v2 limits are read
    back after launch and whose enforcement is probed before readiness.
    ``disabled`` runs without aggregate limits and says so in readiness and in
    every execution. Any other value withholds readiness.
    """

    kind = "isolated-browser"

    def __init__(self, repository_root: Path = REPOSITORY_ROOT) -> None:
        self.root = repository_root.resolve()
        self.launcher = Path(__file__).with_name("isolated_backend.py")
        self.python = Path(sys.base_prefix).resolve()
        self.packages = Path(sysconfig.get_path("purelib")).resolve()
        self.bwrap = shutil.which("bwrap")
        self.node = shutil.which("node")
        self.systemd_run = shutil.which("systemd-run")
        self.systemctl = shutil.which("systemctl")
        self.clear_env = shutil.which("env")
        self.next_cli = self.root / "apps/buggyshop-frontend/node_modules/next/dist/bin/next"
        self.runner_cli = self.root / "tools/browser-runner/dist/cli.js"
        # Only user-manager addresses reach systemd-run; `env -i` drops them before bwrap.
        self.manager_environment = {
            name: os.environ[name]
            for name in ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")
            if os.environ.get(name)
        }
        self.aggregate_mode = os.environ.get("FAULTLINE_AGGREGATE_LIMITS", "required")
        self.limits = AggregateLimits()
        self.generations: dict[str, Generation] = {}
        self._preflight = False
        self._backend_ready = False
        self._installation: str | None = None
        self._limits_preflight: Literal["not_run", "passed", "failed", "disabled"] = "not_run"
        self._limits_reason: str | None = None
        self._limits_probe: dict[str, int | bool | None] | None = None

    @property
    def ready(self) -> bool:
        return self._preflight

    @property
    def readiness_reason(self) -> str | None:
        """The specific reason candidates cannot run, or None once ready."""
        if self._preflight:
            return None
        if self._limits_reason in BLOCKING_LIMIT_REASONS:
            return self._limits_reason
        return "isolated_runtime_unavailable"

    @property
    def resource_limits_status(self) -> dict[str, object]:
        """Describe aggregate limits for readiness; manager addresses never appear."""
        requested = self.aggregate_mode if self.aggregate_mode in AGGREGATE_MODES else "invalid"
        return {
            "requested": requested,
            "mode": {"required": "cgroup-v2-scope", "disabled": "disabled"}.get(requested),
            "configured": asdict(self.limits) if requested == "required" else None,
            "enforcement_preflight": self._limits_preflight,
            "probe": self._limits_probe,
            "reason": self._limits_reason,
        }

    def scope_unit(self, generation_id: str) -> str | None:
        """Name one backend scope, or return None only when limits are disabled.

        The name joins a sanitized installation prefix (``evaluation`` before any
        reconciliation) with the canonical generation UUID, so reconciliation
        can select exactly this installation's scopes and nothing else.
        """
        if self.aggregate_mode == "disabled":
            return None
        if self.aggregate_mode != "required":
            raise RuntimeUnavailable("aggregate_limits_mode_invalid")
        try:
            canonical = str(UUID(generation_id)) == generation_id
        except ValueError:
            canonical = False
        if not canonical:
            raise RuntimeUnavailable("generation_identity_invalid")
        return f"{self._unit_prefix()}{generation_id}.scope"

    def _unit_prefix(self) -> str:
        if self._installation is None:
            return "faultline-evaluation-"
        installation = re.sub(r"[^a-z0-9]", "", self._installation.lower())[:64]
        if not installation:
            raise RuntimeUnavailable("aggregate_limits_unavailable")
        return f"faultline-{installation}-"

    def scope_environment(self, unit: str | None) -> dict[str, str]:
        """Return the only variables systemd-run needs; unscoped launches get none."""
        return dict(self.manager_environment) if unit is not None else {}

    def _sandbox(
        self, snapshot: Path, *, unit: str | None = None, limits: AggregateLimits | None = None
    ) -> list[str]:
        """Return a complete namespace launch argv prefix, optionally in a scope.

        Without ``unit`` this is the unscoped namespace profile. With a unit,
        systemd-run creates the limited scope and execs in place, so the
        supervisor's process group still owns bwrap; ``env -i`` then empties
        bwrap's initial environment, which a candidate could otherwise read at
        /proc/1/environ. A candidate launch pairs this with ``scope_unit``,
        ``scope_environment``, ``verify_scope``, and ``release_scope``.
        """
        if self.bwrap is None:
            raise RuntimeUnavailable("bubblewrap_unavailable")
        args = [
            self.bwrap,
            "--unshare-all",
            # --unshare-all only tries a user namespace; setuid bwrap would skip it.
            "--unshare-user",
            "--die-with-parent",
            "--new-session",
            "--clearenv",
            "--cap-drop",
            "ALL",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--size",
            "16777216",
            "--tmpfs",
            "/tmp",
            "--size",
            "1048576",
            "--tmpfs",
            "/run",
            "--ro-bind",
            "/usr",
            "/usr",
        ]
        for name in ("/lib", "/lib64"):
            if Path(name).exists():
                args.extend(("--ro-bind", name, name))
        args.extend(
            (
                "--ro-bind",
                str(self.python),
                "/python",
                "--ro-bind",
                str(self.packages),
                "/packages",
                "--ro-bind",
                str(snapshot),
                "/snapshot",
                "--ro-bind",
                str(self.launcher),
                "/trusted_backend.py",
                "--setenv",
                "PATH",
                "/python/bin:/usr/bin",
                "--setenv",
                "HOME",
                "/tmp",
                "--setenv",
                "PYTHONDONTWRITEBYTECODE",
                "1",
                "--setenv",
                "PYTHONUNBUFFERED",
                "1",
                "--remount-ro",
                "/dev",
                "--remount-ro",
                "/proc",
                "--remount-ro",
                "/",
                "--chdir",
                "/tmp",
            )
        )
        if unit is None:
            return args
        if not UNIT_PATTERN.fullmatch(unit):
            raise RuntimeUnavailable("aggregate_scope_name_invalid")
        if self.systemd_run is None or self.clear_env is None:
            raise RuntimeUnavailable("aggregate_limits_unavailable")
        return [
            self.systemd_run,
            "--user",
            "--scope",
            "--quiet",
            f"--unit={unit}",
            "--description=FaultLine isolated candidate scope",
            *(limits or self.limits).properties(),
            "--",
            self.clear_env,
            "-i",
            *args,
        ]

    async def _systemctl(self, *args: str) -> str:
        """Run one bounded trusted user-manager command; any failure is unavailability."""
        if self.systemctl is None or not self.manager_environment:
            raise RuntimeUnavailable("aggregate_limits_unavailable")
        process = await asyncio.create_subprocess_exec(
            self.systemctl,
            "--user",
            "--no-pager",
            *args,
            env=self.manager_environment,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        output = b""
        try:
            async with asyncio.timeout(3):
                output, _ = await process.communicate()
        except TimeoutError:
            pass
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        if process.returncode != 0 or len(output) > REPORT_LIMIT:
            raise RuntimeUnavailable("aggregate_limits_unavailable")
        return output.decode("utf-8", errors="replace")

    async def _scope_state(self, unit: str) -> dict[str, str]:
        return parse_unit_properties(
            await self._systemctl("show", f"--property={','.join(SCOPE_PROPERTIES)}", unit)
        )

    async def _live_scope(self, unit: str) -> tuple[Path, str]:
        """Resolve an active scope's cgroup v2 directory and manager ControlGroup."""
        state = await self._scope_state(unit)
        if state["LoadState"] != "loaded" or state["ActiveState"] != "active":
            raise RuntimeUnavailable("aggregate_limits_unverified")
        return scope_cgroup(state["ControlGroup"], unit), state["ControlGroup"]

    async def verify_scope(
        self, unit: str | None, process: ManagedProcess, limits: AggregateLimits | None = None
    ) -> ResourceLimits:
        """Read a launched scope back from systemd and the kernel before trusting it.

        Requires an active unit whose cgroup v2 limit files equal configuration
        and whose membership is exactly the supervised launch's process tree;
        returns the kernel's values. Disabled mode returns the explicit
        unverified ``disabled`` record. A required launch without a unit fails.
        """
        if unit is None:
            if self.aggregate_mode == "disabled":
                return disabled_limits()
            raise RuntimeUnavailable("aggregate_limits_unverified")
        expected = limits or self.limits
        until = time.monotonic() + 3
        while True:
            try:
                directory, control_group = await self._live_scope(unit)
                values = {name: (directory / name).read_text() for name in SCOPE_LIMIT_FILES}
                verified = verify_cgroup_values(values, expected)
                confirm_membership(directory, control_group, process.process.pid)
                return verified
            except (OSError, ValueError, RuntimeUnavailable):
                if process.process.returncode is not None or time.monotonic() > until:
                    raise RuntimeUnavailable("aggregate_limits_unverified") from None
            await asyncio.sleep(0.05)

    async def release_scope(self, unit: str | None, *, grace: float = 1.0) -> None:
        """Confirm a scope is gone, SIGKILLing only that unit's cgroup if it lingers.

        OOM-killed scopes stay loaded as failed until reset, so absence is
        confirmed only after reset-failed. Raises (bounded) without discarding
        the caller's ownership, which keeps the quarantine path available.
        """
        if unit is None:
            return
        if not UNIT_PATTERN.fullmatch(unit):
            raise RuntimeUnavailable("aggregate_scope_name_invalid")
        started = time.monotonic()
        killed = False
        while True:
            try:
                state = await self._scope_state(unit)
                if state["LoadState"] == "not-found":
                    return
                if state["ActiveState"] == "failed":
                    await self._systemctl("reset-failed", unit)
                elif not killed and time.monotonic() - started >= grace:
                    killed = True
                    await self._systemctl("kill", "--signal=SIGKILL", unit)
            except RuntimeUnavailable:
                pass
            if time.monotonic() - started > grace + SCOPE_RELEASE_SECONDS:
                raise RuntimeUnavailable("aggregate_scope_cleanup_unconfirmed")
            await asyncio.sleep(0.05)

    async def _release_leftover_scopes(self) -> None:
        """Release scopes named for this installation only; other units are untouched."""
        prefix = self._unit_prefix()
        output = await self._systemctl(
            "list-units", "--all", "--plain", "--no-legend", "--type=scope", f"{prefix}*"
        )
        for line in output.splitlines():
            name = line.split(maxsplit=1)[0] if line.strip() else ""
            if name.startswith(prefix) and UNIT_PATTERN.fullmatch(name):
                await self.release_scope(name, grace=0)

    async def _profile_preflight(self) -> None:
        # The exact interpreter profile must launch without mounting project/home.
        host_net = os.stat("/proc/self/ns/net").st_ino
        host_user = os.stat("/proc/self/ns/user").st_ino
        with tempfile.TemporaryDirectory(prefix="faultline-preflight-") as directory:
            empty = Path(directory)
            process = await ManagedProcess.start(
                *self._sandbox(empty),
                "/python/bin/python3.13",
                "-I",
                "-c",
                "import os,socket; assert not os.path.exists('/home'); "
                f"assert os.stat('/proc/self/ns/net').st_ino != {host_net}; "
                f"assert os.stat('/proc/self/ns/user').st_ino != {host_user}; "
                "assert not os.path.exists('/snapshot/.env'); "
                "assert os.statvfs('/').f_flag & os.ST_RDONLY; "
                "assert os.statvfs('/dev').f_flag & os.ST_RDONLY; "
                "assert os.statvfs('/tmp').f_blocks * os.statvfs('/tmp').f_frsize <= 16777216; "
                "assert os.statvfs('/run').f_blocks * os.statvfs('/run').f_frsize <= 1048576; "
                "print('isolated-profile-ready')",
                env={},
            )
            if (
                await process.wait(5) != 0
                or bytes(process.stdout).strip() != b"isolated-profile-ready"
            ):
                raise RuntimeUnavailable("isolated_profile_unavailable")

    async def _enforcement_probe(self) -> str | None:
        """Prove the kernel enforces scope memory and task limits; return a failure reason.

        A forked child allocates 256 MiB without rlimits under a 64 MiB,
        no-swap scope; the parent then starts up to 64 threads under
        TasksMax=16. The controller reads that live scope's own memory.events
        and pids.events, so the verdict rests on kernel cgroup counters.
        """
        if not (
            self.systemd_run and self.systemctl and self.clear_env and self.manager_environment
        ):
            return "aggregate_limits_unavailable"
        try:
            unit = f"{self._unit_prefix()}{uuid4()}.scope"
        except RuntimeUnavailable:
            return "aggregate_limits_unavailable"
        with tempfile.TemporaryDirectory(prefix="faultline-limits-") as directory:
            process = await ManagedProcess.start(
                *self._sandbox(Path(directory), unit=unit, limits=PROBE_LIMITS),
                "/python/bin/python3.13",
                "-I",
                "-c",
                PROBE_SCRIPT,
                env=self.scope_environment(unit),
            )
            try:
                until = time.monotonic() + 5
                while b"\n" not in process.stdout:
                    if process.process.returncode is not None or time.monotonic() > until:
                        return "aggregate_limits_unavailable"
                    await asyncio.sleep(0.02)
                observed: object = json.loads(bytes(process.stdout).partition(b"\n")[0])
                verified = await self.verify_scope(unit, process, PROBE_LIMITS)
                scope, _ = await self._live_scope(unit)
                memory = parse_cgroup_events((scope / "memory.events").read_text())
                tasks = parse_cgroup_events((scope / "pids.events").read_text())
            except (OSError, ValueError, RuntimeUnavailable):
                return "aggregate_limits_unavailable"
            finally:
                await process.stop()
                await self.release_scope(unit)
        probe: dict[str, int | bool | None] = {
            "memory_max_bytes": verified.memory_max_bytes,
            "memory_swap_max_bytes": verified.memory_swap_max_bytes,
            "tasks_max": verified.tasks_max,
            "allocation_attempt_bytes": PROBE_ALLOCATION_MIB * 1024 * 1024,
            "thread_attempts": PROBE_THREADS,
            "oom_events": memory.get("oom", 0),
            "oom_kill_events": memory.get("oom_kill", 0),
            "pids_max_events": tasks.get("max", 0),
        }
        if isinstance(observed, dict):
            for key in ("environment_clean", "hog_exit_code", "threads_started"):
                value = observed.get(key)
                if type(value) in (int, bool):
                    probe[key] = value
        self._limits_probe = probe
        return probe_verdict(observed, memory, tasks)

    async def backend_preflight(self) -> None:
        """Prove the backend sandbox profile and, unless disabled, aggregate limits.

        Needs no browser or frontend build. Raises ``RuntimeUnavailable`` with
        the specific reason; readiness status records the aggregate outcome.
        """
        self._backend_ready = False
        self._limits_preflight, self._limits_reason, self._limits_probe = "not_run", None, None
        if self.aggregate_mode not in AGGREGATE_MODES:
            self._limits_reason = "aggregate_limits_mode_invalid"
            raise RuntimeUnavailable(self._limits_reason)
        if self.aggregate_mode == "disabled":
            self._limits_preflight, self._limits_reason = "disabled", "aggregate_limits_disabled"
        if not self.bwrap or not self.launcher.is_file():
            raise RuntimeUnavailable("bubblewrap_unavailable")
        await self._profile_preflight()
        if self.aggregate_mode == "required":
            reason = await self._enforcement_probe()
            self._limits_preflight = "failed" if reason else "passed"
            self._limits_reason = reason
            if reason is not None:
                raise RuntimeUnavailable(reason)
        self._backend_ready = True

    async def reconcile(self, installation_id: str) -> None:
        """Release this installation's leftovers, then run every preflight.

        Reconciliation owns this installation's scope prefix exclusively: any
        leftover scope named for it is killed and confirmed gone. Unavailable
        containment withholds readiness; unconfirmed cleanup raises.
        """
        self._preflight = False
        self._backend_ready = False
        self._limits_preflight, self._limits_reason, self._limits_probe = "not_run", None, None
        if self._installation is not None and self._installation != installation_id:
            raise RuntimeUnavailable("installation_identity_mismatch")
        for job_id in tuple(self.generations):
            await self.cleanup(installation_id, job_id)
        self._installation = installation_id
        if self.aggregate_mode in AGGREGATE_MODES:
            try:
                await self._release_leftover_scopes()
            except RuntimeUnavailable as exc:
                # An unreachable manager owns no scopes; required mode fails its probe below.
                if str(exc) != "aggregate_limits_unavailable":
                    raise
        try:
            await self.backend_preflight()
        except RuntimeUnavailable as exc:
            if str(exc) == "aggregate_scope_cleanup_unconfirmed":
                raise
            return
        required = [
            self.next_cli,
            self.runner_cli,
            self.root / "apps/buggyshop-frontend/.next/BUILD_ID",
        ]
        if not self.node or not all(path.is_file() for path in required):
            return
        # Query actual Chromium availability without launching or importing candidate code.
        process = await ManagedProcess.start(
            self.node,
            "--input-type=module",
            "-e",
            "import {chromium} from '@playwright/test'; "
            "const browser=await chromium.launch({headless:true}); await browser.close();",
            cwd=self.root / "tools/browser-runner",
            env=self._trusted_environment(),
        )
        self._preflight = await process.wait(5) == 0

    def _trusted_environment(self) -> dict[str, str]:
        # Never propagate control/model credentials or load a project environment file.
        env = {"PATH": os.defpath, "NODE_ENV": "production", "NEXT_TELEMETRY_DISABLED": "1"}
        # Playwright uses HOME only to locate its installed, trusted browser cache.
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(Path.home() / ".cache/ms-playwright")
        return env

    async def prepare(self, installation_id: str, job_id: str, snapshot: Snapshot) -> None:
        if not self.ready or installation_id != self._installation:
            raise RuntimeUnavailable("isolated_runtime_unavailable")
        if job_id in self.generations:
            raise RuntimeUnavailable("job_runtime_already_exists")
        await self._activate(job_id, snapshot)

    async def activate(self, job_id: str, snapshot: Snapshot) -> None:
        await self.cleanup(self._installation or "", job_id)
        await self._activate(job_id, snapshot)

    async def _activate(self, job_id: str, snapshot: Snapshot) -> None:
        if not self.ready or str(UUID(job_id)) != job_id:
            raise RuntimeUnavailable("isolated_runtime_unavailable")
        self._verify_snapshot(snapshot)
        if snapshot.path.parent.name != "snapshots" or snapshot.path.name != snapshot.generation_id:
            raise RuntimeUnavailable("snapshot_owned_layout_required")
        # Name the scope before anything exists, so cleanup can confirm its absence.
        backend = BackendResources(unit=self.scope_unit(snapshot.generation_id))
        directory = contained_path(snapshot.path.parents[1], f"isolated/{snapshot.generation_id}")
        directory.mkdir(parents=True, mode=0o700, exist_ok=False)
        owned = Generation(snapshot, directory, backend)
        self.generations[job_id] = owned  # Register intent before creating resources.
        try:
            await self._launch_backend(backend, snapshot.path, snapshot.generation_id)
            assert backend.client is not None
            bridge_url = await self._bridge(owned)
            port = self._free_port()
            assert self.node is not None
            owned.frontend = await ManagedProcess.start(
                self.node,
                str(self.next_cli),
                "start",
                "-p",
                str(port),
                "-H",
                "127.0.0.1",
                cwd=self.root / "apps/buggyshop-frontend",
                env={**self._trusted_environment(), "BUGGYSHOP_BACKEND_URL": bridge_url},
            )
            owned.frontend_url = f"http://127.0.0.1:{port}"
            async with httpx.AsyncClient(timeout=1, trust_env=False) as client:
                until = time.monotonic() + 10
                while time.monotonic() < until:
                    if owned.frontend.process.returncode is not None:
                        raise CandidateRejected("trusted_frontend_failed")
                    try:
                        response = await client.get(f"{owned.frontend_url}/api/products")
                        if (
                            response.status_code == 200
                            and response.json()
                            == (await backend.client.get("/api/products")).json()
                        ):
                            return
                    except (httpx.HTTPError, ValueError):
                        pass
                    await asyncio.sleep(0.1)
                raise CandidateRejected("trusted_frontend_readiness_timeout")
        except BaseException:
            await asyncio.shield(self.cleanup(self._installation or "", job_id))
            raise

    async def _launch_backend(
        self, backend: BackendResources, application: Path, generation_id: str
    ) -> None:
        """Start one candidate backend through the single scoped sandbox launch path.

        ``backend`` must already be registered with its owner, so teardown can
        confirm every part, including a scope that was named but never created.
        Readiness failure is the candidate's; unverifiable limits are not.
        """
        # Abstract sockets avoid Linux's 108-byte filesystem pathname limit
        # and cannot be redirected with an untrusted filesystem symlink.
        socket_name = "\0faultline-" + generation_id
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        backend.listener = listener
        listener.bind(socket_name)
        listener.listen(16)
        backend.process = await ManagedProcess.start(
            *self._sandbox(application, unit=backend.unit),
            "/python/bin/python3.13",
            "-I",
            "-u",
            "/trusted_backend.py",
            str(listener.fileno()),
            env=self.scope_environment(backend.unit),
            pass_fds=(listener.fileno(),),
        )
        backend.client = httpx.AsyncClient(
            transport=BoundedUDSTransport(socket_name),
            base_url="http://isolated-backend",
            timeout=3,
            follow_redirects=False,
        )
        if backend.unit is not None:
            await self._await_scope(backend.unit, backend.process)
        await self._wait_backend(backend)
        try:
            backend.resource_limits = await self.verify_scope(backend.unit, backend.process)
        except RuntimeUnavailable:
            # The scope was already observed active with configured limits, so a
            # backend that has since exited failed in candidate code.
            if backend.process.process.returncode is not None:
                raise CandidateRejected("isolated_backend_failed") from None
            raise

    async def _await_scope(self, unit: str, process: ManagedProcess) -> None:
        """See the scope active with configured limits before the candidate serves.

        systemd-run creates the scope before it execs the sandbox, so a launch
        whose scope is never observed is a trusted-infrastructure failure, not a
        candidate verdict. A candidate that exits before the first observation
        is also reported as infrastructure: an unverifiable launch never counts
        against a patch, and it never yields a green result either.
        """
        until = time.monotonic() + 3
        while time.monotonic() < until:
            try:
                directory, _ = await self._live_scope(unit)
                verify_cgroup_values(
                    {name: (directory / name).read_text() for name in SCOPE_LIMIT_FILES},
                    self.limits,
                )
                return
            except (OSError, ValueError, RuntimeUnavailable):
                if process.process.returncode is not None:
                    break
            await asyncio.sleep(0.02)
        raise RuntimeUnavailable("aggregate_limits_unavailable")

    async def _stop_backend(self, backend: BackendResources) -> None:
        """Stop the backend, then confirm its scope is gone rather than assuming it."""
        if backend.process is not None:
            await backend.process.stop()
        await self.release_scope(backend.unit)

    @staticmethod
    async def _close_backend(backend: BackendResources) -> None:
        if backend.listener is not None:
            backend.listener.close()
        if backend.client is not None:
            await backend.client.aclose()

    @asynccontextmanager
    async def backend_session(self, application: Path) -> AsyncIterator[BackendHandle]:
        """Run one candidate backend alone through the activation sandbox path.

        ``application`` may contain only ``apps/buggyshop-backend/app/**/*.py``.
        It is mounted read-only in the same scoped namespace with verified
        aggregate limits; exit stops the backend and confirms its scope is gone.
        Requires a passed ``backend_preflight`` (``reconcile`` runs one).
        """
        if not self._backend_ready:
            raise RuntimeUnavailable("isolated_runtime_unavailable")
        root = self._verify_application(application)
        generation_id = str(uuid4())
        backend = BackendResources(unit=self.scope_unit(generation_id))
        try:
            await self._launch_backend(backend, root, generation_id)
            assert backend.client is not None
            yield BackendHandle(backend.client, backend.logs, backend.resource_limits)
        finally:
            await asyncio.shield(self._release_session(backend))

    async def _release_session(self, backend: BackendResources) -> None:
        await self._stop_backend(backend)
        await self._close_backend(backend)

    @staticmethod
    def _application_entries(root: Path) -> list[tuple[str, str, str]]:
        """Hash every application file; symlinks and non-Python files are rejected."""
        application = contained_path(root, "apps/buggyshop-backend/app")
        entries: list[tuple[str, str, str]] = []
        for path in sorted(application.rglob("*")):
            if path.is_symlink():
                raise CandidateRejected("snapshot_symlink_forbidden")
            if path.is_file():
                if path.suffix != ".py":
                    raise CandidateRejected("snapshot_nonapplication_file")
                entries.append(
                    (
                        path.relative_to(root).as_posix(),
                        "100644",
                        hashlib.sha256(path.read_bytes()).hexdigest(),
                    )
                )
        return entries

    @staticmethod
    def _verify_application(application: Path) -> Path:
        """Admit a mount root whose only files are backend application Python."""
        if application.is_symlink():
            raise CandidateRejected("snapshot_symlink_forbidden")
        root = application.resolve()
        try:
            backend = contained_path(root, "apps/buggyshop-backend/app")
        except ValueError:
            raise CandidateRejected("snapshot_symlink_forbidden") from None
        if not backend.is_dir():
            raise CandidateRejected("application_tree_missing")
        for path in root.rglob("*"):
            if path.is_symlink():
                raise CandidateRejected("snapshot_symlink_forbidden")
            if path.is_dir():
                continue
            if not path.is_file() or path.suffix != ".py" or not path.is_relative_to(backend):
                raise CandidateRejected("snapshot_nonapplication_file")
        return root

    @staticmethod
    def _verify_snapshot(snapshot: Snapshot) -> None:
        """Recompute the application export identity immediately before mounting."""
        entries = IsolatedRuntime._application_entries(snapshot.path)
        actual = hashlib.sha256(json.dumps(entries, separators=(",", ":")).encode()).hexdigest()
        target = contained_path(snapshot.path, REGISTRY["scripted_checkout_repair"].target_file)
        if (
            actual != snapshot.sha256
            or hashlib.sha256(target.read_bytes()).hexdigest() != snapshot.source_sha256
        ):
            raise CandidateRejected("snapshot_identity_mismatch")

    @staticmethod
    def _free_port() -> int:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])

    async def _wait_backend(self, backend: BackendResources) -> None:
        assert backend.client is not None and backend.process is not None
        until = time.monotonic() + 5
        while time.monotonic() < until:
            if backend.process.process.returncode is not None:
                raise CandidateRejected("isolated_backend_failed")
            try:
                response = await backend.client.get("/healthz")
                if response.status_code == 200 and response.json() == {
                    "status": "ok",
                    "app": "buggyshop-api",
                }:
                    return
            except (httpx.HTTPError, ValueError):
                pass
            await asyncio.sleep(0.05)
        raise CandidateRejected("isolated_backend_readiness_timeout")

    async def _bridge(self, owned: Generation) -> str:
        app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
        client = owned.backend.client
        assert client is not None

        @app.api_route("/{path:path}", methods=["GET", "POST"])
        async def forward(path: str, request: Request) -> Response:
            # Only backend API/health requests are ever forwarded to the private UDS.
            if not (path.startswith("api/") or path == "healthz"):
                return Response(status_code=404)
            body = bytearray()
            async with asyncio.timeout(3):
                async for chunk in request.stream():
                    if len(body) + len(chunk) > 16 * 1024:
                        return Response(status_code=413)
                    body.extend(chunk)
            response = await client.request(
                request.method,
                "/" + path,
                params=request.query_params,
                content=bytes(body),
                headers={
                    key: value
                    for key, value in request.headers.items()
                    if key.lower() in {"content-type", "x-faultline-case-id"}
                },
            )
            if len(response.content) > REPORT_LIMIT:
                return Response(status_code=502)
            return Response(
                response.content,
                status_code=response.status_code,
                headers={
                    key: value
                    for key, value in response.headers.items()
                    if key.lower() in {"content-type", "x-request-id"}
                },
            )

        listener = socket.socket()
        owned.bridge_socket = listener
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(16)
        listener.setblocking(False)
        server = BridgeServer(
            uvicorn.Config(
                app,
                log_level="warning",
                access_log=False,
                lifespan="off",
                log_config=None,
            )
        )
        # The controller owns process-wide signal handlers, not the embedded bridge.
        owned.bridge_server = server
        owned.bridge_task = asyncio.create_task(server.serve(sockets=[listener]))
        until = time.monotonic() + 3
        while not server.started:
            if owned.bridge_task.done():
                owned.bridge_task.result()
                raise RuntimeUnavailable("bridge_failed")
            if time.monotonic() > until:
                raise RuntimeUnavailable("bridge_readiness_timeout")
            await asyncio.sleep(0.01)
        return f"http://127.0.0.1:{listener.getsockname()[1]}"

    async def execute(
        self, job_id: str, execution_id: str, phase: Phase, snapshot: Snapshot, timeout_ms: int
    ) -> RuntimeExecution:
        owned = self.generations.get(job_id)
        if (
            owned is None
            or owned.snapshot != snapshot
            or owned.backend.client is None
            or owned.backend.resource_limits is None
        ):
            raise RuntimeUnavailable("generation_not_active")
        assert self.node is not None and owned.backend.process is not None
        started = time.monotonic()
        case_id = str(uuid4())
        evidence_dir = owned.directory / f"evidence-{execution_id}"
        try:
            async with asyncio.timeout(timeout_ms / 1000):
                owned.runner = await ManagedProcess.start(
                    self.node,
                    str(self.runner_cli),
                    "--base-url",
                    owned.frontend_url,
                    "--execution-id",
                    execution_id,
                    "--case-id",
                    case_id,
                    "--artifacts-dir",
                    str(evidence_dir),
                    "--timeout-ms",
                    str(min(timeout_ms, 20000)),
                    cwd=self.root / "tools/browser-runner",
                    env=self._trusted_environment(),
                )
                code = await owned.runner.wait(timeout_ms / 1000)
                if code not in {0, 1, 2, 3}:
                    raise RuntimeUnavailable("browser_runner_failed")
                report_path = contained_path(evidence_dir, "report.json")
                if not report_path.is_file() or report_path.stat().st_size > REPORT_LIMIT:
                    raise RuntimeUnavailable("browser_report_missing_or_oversized")
                report = ExecutionReport.model_validate_json(report_path.read_bytes())
                if report.execution_id != execution_id or report.case_id != case_id:
                    raise RuntimeUnavailable("browser_identity_mismatch")
                expected = {0: "passed", 1: "failed", 2: "error", 3: "error"}[code]
                if report.verdict.value != expected:
                    raise RuntimeUnavailable("browser_exit_disagreement")
                artifacts = self._artifacts(evidence_dir, execution_id)
                if code == 3:
                    report = report.model_copy(update={"verdict": ExecutionVerdict.TIMED_OUT})
                if phase == "baseline" and code == 1:
                    await self._baseline(report, owned, case_id)
                elif phase == "verification" and code == 0:
                    report.assertions.extend(await regression(owned.backend.client))
                    checks = {item.id: item.passed for item in report.assertions}
                    report.assertions.append(
                        AssertionResult(
                            id="confirmation.checkout",
                            passed=checks.get("checkout.confirmation_shown") is True
                            and checks.get("checkout.confirmation_matches_order") is True,
                            expected="actual browser confirmation matches created order",
                            observed="browser oracle confirmation assertions",
                            duration_ms=0.0,
                        )
                    )
                    if not all(item.passed for item in report.assertions):
                        report = report.model_copy(update={"verdict": ExecutionVerdict.FAILED})
                        code = 1
                report = report.model_copy(
                    update={"duration_ms": (time.monotonic() - started) * 1000}
                )
                logs = owned.backend.logs()
                artifacts.append(
                    RuntimeArtifact(
                        "logs", "text/plain", logs.encode() or b"No backend exceptions observed.\n"
                    )
                )
                return RuntimeExecution(
                    report,
                    snapshot.generation_id,
                    snapshot.sha256,
                    code,
                    tuple(artifacts),
                    owned.backend.resource_limits,
                )
        finally:
            if owned.runner is not None:
                await asyncio.shield(owned.runner.stop())
                owned.runner = None

    def _artifacts(self, root: Path, execution_id: str) -> list[RuntimeArtifact]:
        manifest_path = contained_path(root, "artifacts.json")
        if not manifest_path.is_file() or manifest_path.stat().st_size > REPORT_LIMIT:
            raise RuntimeUnavailable("artifact_manifest_missing_or_oversized")
        manifest = json.loads(manifest_path.read_bytes())
        if manifest.get("execution_id") != execution_id:
            raise RuntimeUnavailable("artifact_manifest_identity_mismatch")
        roles = {
            "failure_screenshot": "screenshot",
            "final_screenshot": "screenshot",
            "trace": "trace",
            "network_log": "requests",
        }
        limits = {"screenshot": 10 * 1024 * 1024, "trace": 25 * 1024 * 1024, "requests": 16 * 1024}
        results: list[RuntimeArtifact] = []
        seen: set[str] = set()
        for entry in manifest.get("artifacts", []):
            role = roles.get(entry.get("role"))
            if role is None:
                continue
            path = contained_path(root, entry["relative_path"])
            if role in seen or not path.is_file() or not 0 < path.stat().st_size <= limits[role]:
                raise RuntimeUnavailable("artifact_missing_duplicate_or_oversized")
            content = path.read_bytes()
            if (
                len(content) != entry["size_bytes"]
                or hashlib.sha256(content).hexdigest() != entry["sha256"]
            ):
                raise RuntimeUnavailable("artifact_checksum_mismatch")
            results.append(RuntimeArtifact(role, entry["content_type"], content))
            seen.add(role)
        if seen != {"screenshot", "trace", "requests"}:
            raise RuntimeUnavailable("required_browser_evidence_missing")
        return results

    async def _baseline(self, report: ExecutionReport, owned: Generation, case_id: str) -> None:
        """Correlate actual browser HTTP failure with actual server JSON logs."""
        client = owned.backend.client
        assert client is not None
        confirmation = next(
            (item for item in report.assertions if item.id == "checkout.confirmation_shown"), None
        )
        visible = (
            confirmation is not None
            and not confirmation.passed
            and confirmation.observed.startswith("failure alert:")
        )
        response = await client.get("/api/orders", headers={"X-Faultline-Case-Id": case_id})
        no_order = response.status_code == 200 and response.json() == {"orders": []}
        for name, passed, observed in (
            (
                "checkout.failure_visible",
                visible,
                confirmation.observed if confirmation else "UI outcome missing",
            ),
            ("checkout.no_order_on_failure", no_order, response.text[:1024]),
        ):
            report.assertions.append(
                AssertionResult(
                    id=name,
                    passed=passed,
                    expected="measured baseline failure evidence",
                    observed=observed,
                    duration_ms=0.0,
                )
            )
        fingerprint = REGISTRY[report.scenario_id].error_fingerprint
        # Let the independent stderr reader drain logs already emitted with the response.
        await asyncio.sleep(0.05)
        for line in owned.backend.logs().splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if (
                event.get("case_id") != case_id
                or event.get("route") != "/api/checkout"
                or event.get("exception_type") != "TypeError"
                or fingerprint not in event.get("message", "")
            ):
                continue
            request_id = event.get("request_id")
            http = next(
                (
                    entry
                    for entry in report.observations
                    if entry.kind == ObservationKind.HTTP_ERROR
                    and isinstance(entry.data.get("request"), dict)
                    and entry.data["request"].get("request_id") == request_id
                    and entry.data["request"].get("status") == 500
                ),
                None,
            )
            if http is None:
                continue
            http.source = "POST /api/checkout"
            http.data.update(status=500, request_id=request_id, case_id=case_id)
            report.observations.append(
                Observation(
                    id=str(uuid4()),
                    kind=ObservationKind.SERVER_EXCEPTION,
                    source=REGISTRY[report.scenario_id].target_file,
                    message=event["message"],
                    timestamp=utcnow(),
                    data={
                        "request_id": request_id,
                        "case_id": case_id,
                        "exception_type": "TypeError",
                        "traceback": event.get("traceback"),
                    },
                )
            )

    async def cleanup(self, installation_id: str, job_id: str) -> None:
        if self._installation is not None and installation_id != self._installation:
            raise RuntimeUnavailable("installation_identity_mismatch")
        owned = self.generations.get(job_id)
        if owned is None:
            return
        # Do not forget ownership or remove the directory until every cleanup succeeds.
        for process in (owned.runner, owned.frontend):
            if process is not None:
                await process.stop()
        await self._stop_backend(owned.backend)
        if owned.bridge_server is not None:
            owned.bridge_server.should_exit = True
        if owned.bridge_task is not None:
            async with asyncio.timeout(3):
                await owned.bridge_task
        if owned.bridge_socket is not None:
            owned.bridge_socket.close()
        await self._close_backend(owned.backend)
        shutil.rmtree(owned.directory)
        self.generations.pop(job_id)


class BridgeServer(uvicorn.Server):
    """Leave controller signal ownership intact."""

    @contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield
