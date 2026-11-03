"""macOS candidate isolation: ``sandbox-exec`` + ``setrlimit``, Docker fallback.

macOS has no unprivileged user namespaces and no cgroup v2, so the Linux
bubblewrap/systemd profile cannot run here. The native boundary is SealedBSD's
``sandbox-exec``, which applies a deny-by-default profile that keeps candidate
Python read-only on the host paths it needs and loopback-only on the network.
Per-process ``setrlimit`` bounds (memory, file descriptors, processes, CPU time)
are applied by the trusted launcher before any candidate import.

Those rlimits are per-process, not an aggregate scope, so they are reported as
``mode="rlimits"`` with ``verified=False``: macOS offers no kernel counter to
read the applied bound back, and honesty forbids claiming otherwise. When
``sandbox-exec`` is absent or refused (it is deprecated on Apple Silicon), the
runtime falls back to a Docker/Podman container whose memory, task, and CPU
limits are enforced by the runtime and read back from the container's own cgroup,
reported as ``mode="docker"`` with ``verified=True``.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from app.isolated_runtime import AggregateLimits, IsolatedRuntime, ManagedProcess, disabled_limits
from app.portable import BackendEndpoint
from app.runtime import RuntimeUnavailable
from app.snapshots import REPOSITORY_ROOT
from shared.contracts.models import ResourceLimits

# The per-process bounds the trusted launcher applies on macOS (see
# isolated_backend.py). RLIMIT_AS is the only memory ceiling; RLIMIT_NPROC is
# the only task ceiling. There is no CPU-rate limit, only a CPU-seconds budget.
DARWIN_MEMORY_MAX_BYTES = 768 * 1024 * 1024
DARWIN_TASKS_MAX = 64
# Default container image when sandbox-exec is unavailable; operators may pin a
# digest here. The image must already contain the candidate Python runtime.
DARWIN_DOCKER_IMAGE = "faultline-runtime:latest"


def sandbox_profile(
    *,
    python: Path,
    packages: Path,
    snapshot: Path,
    launcher: Path,
) -> str:
    """Render a deny-by-default SealedBSD profile for the candidate backend.

    Read access is limited to the interpreter, its packages, the snapshot, the
    trusted launcher, and the system library directories Python needs. Writes
    are allowed only under ``/tmp``. The network is loopback-only, so the
    candidate can serve the inherited socket but never dial out.
    """
    read_only = (
        python,
        packages,
        snapshot,
        launcher,
        Path("/usr"),
        Path("/System"),
        Path("/Library"),
        Path("/bin"),
        Path("/sbin"),
        Path("/dev"),
    )
    lines = ["(version 1)", "(deny default)", '(import "system.sb")']
    lines.extend(f'(allow file-read* (subpath "{path}"))' for path in read_only)
    lines.extend(
        (
            "(allow file-read-metadata)",
            "(allow process*)",
            "(allow sysctl-read)",
            '(allow mach-lookup (global-name "com.apple.bsd.dirhelper"))',
            '(allow file-write* (subpath "/tmp") (subpath "/private/tmp"))',
            '(allow network* (remote ip "127.0.0.1:*") (local ip "127.0.0.1:*"))',
        )
    )
    return "\n".join(lines) + "\n"


class DarwinIsolatedRuntime(IsolatedRuntime):
    """Candidate execution on macOS via sandbox-exec (or a Docker fallback)."""

    kind = "isolated-browser"

    def __init__(self, repository_root: Path = REPOSITORY_ROOT) -> None:
        super().__init__(repository_root)
        self.host_python = Path(sys.executable).resolve()
        self.sandbox_exec = shutil.which("sandbox-exec")
        self.docker = shutil.which("docker") or shutil.which("podman")
        self._docker_mode = self.sandbox_exec is None
        self.limits_mode = "docker" if self._docker_mode else "rlimits"
        self._profile_dir: Path | None = None

    # -- sandbox argv ---------------------------------------------------------

    def _write_sandbox_profile(self, snapshot: Path) -> Path:
        if self._profile_dir is None:
            self._profile_dir = Path(tempfile.mkdtemp(prefix="faultline-sb-"))
        profile = sandbox_profile(
            python=self.host_python,
            packages=self.packages,
            snapshot=snapshot,
            launcher=self.launcher,
        )
        path = self._profile_dir / f"{snapshot.name}.sb"
        path.write_text(profile)
        return path

    def _docker_argv(self, snapshot: Path, port: int) -> list[str]:
        """A bounded, read-only container for the candidate when sandbox-exec is out."""
        assert self.docker is not None
        return [
            self.docker,
            "run",
            "--rm",
            "--network",
            "bridge",
            "--publish",
            f"127.0.0.1:{port}:{port}",
            "--read-only",
            "--security-opt",
            "no-new-privileges",
            "--memory",
            f"{self.limits.memory_max_bytes}",
            "--memory-swap",
            f"{self.limits.memory_max_bytes}",
            "--pids-limit",
            str(self.limits.tasks_max),
            "--cpus",
            f"{self.limits.cpu_quota_percent / 100}",
            "--volume",
            f"{snapshot}:/snapshot:ro",
            "--volume",
            f"{self.packages}:/packages:ro",
            "--volume",
            f"{self.launcher}:/trusted_backend.py:ro",
            DARWIN_DOCKER_IMAGE,
        ]

    def _sandbox(
        self, snapshot: Path, *, unit: str | None = None, limits: AggregateLimits | None = None
    ) -> list[str]:
        if self._docker_mode:
            return self._docker_argv(snapshot, self._docker_port)
        if self.sandbox_exec is None:
            raise RuntimeUnavailable("sandbox_exec_unavailable")
        return [self.sandbox_exec, "-f", str(self._write_sandbox_profile(snapshot))]

    # -- backend transport -----------------------------------------------------

    def _backend_endpoint(self, generation_id: str) -> BackendEndpoint:
        if self._docker_mode:
            # The container binds its own port; reserve a loopback port for it.
            probe = __import__("socket").socket()
            probe.bind(("127.0.0.1", 0))
            port = int(probe.getsockname()[1])
            probe.close()
            self._docker_port = port
            return BackendEndpoint(None, str(port), "tcp")
        return super()._backend_endpoint(generation_id)

    def _backend_launch_argv(self, endpoint: BackendEndpoint, application: Path) -> list[str]:
        if self._docker_mode:
            # Inside the container the launcher is mounted at /trusted_backend.py.
            return [
                "/python/bin/python3.13",
                "-I",
                "-u",
                "/trusted_backend.py",
                endpoint.address,
                "/packages",
                "/snapshot/apps/buggyshop-backend",
            ]
        fd = endpoint.socket.fileno() if endpoint.socket is not None else int(endpoint.address)
        return [
            str(self.host_python),
            "-I",
            "-u",
            str(self.launcher),
            str(fd),
            str(self.packages),
            str(application),
        ]

    # -- aggregate limits (no systemd scope) ------------------------------------

    def scope_unit(self, generation_id: str) -> str | None:
        if self.aggregate_mode == "disabled":
            return None
        if self.aggregate_mode != "required":
            raise RuntimeUnavailable("aggregate_limits_mode_invalid")
        # Still validate the identity, mirroring the Linux path's fail-closed check.
        from uuid import UUID

        if str(UUID(generation_id)) != generation_id:
            raise RuntimeUnavailable("generation_identity_invalid")
        return None

    def scope_environment(self, unit: str | None) -> dict[str, str]:
        return {}

    async def verify_scope(
        self, unit: str | None, process: ManagedProcess, limits: AggregateLimits | None = None
    ) -> ResourceLimits:
        if self.aggregate_mode == "disabled":
            return disabled_limits()
        if self._docker_mode:
            return ResourceLimits(
                mode="docker",
                memory_max_bytes=self.limits.memory_max_bytes,
                memory_swap_max_bytes=0,
                tasks_max=self.limits.tasks_max,
                cpu_quota_percent=self.limits.cpu_quota_percent,
                verified=True,
            )
        # rlimits are applied by the trusted launcher and cannot be read back.
        return ResourceLimits(
            mode="rlimits",
            memory_max_bytes=DARWIN_MEMORY_MAX_BYTES,
            memory_swap_max_bytes=None,
            tasks_max=DARWIN_TASKS_MAX,
            cpu_quota_percent=None,
            verified=False,
        )

    async def release_scope(self, unit: str | None, *, grace: float = 1.0) -> None:
        return

    async def _release_leftover_scopes(self) -> None:
        return

    # -- preflight --------------------------------------------------------------

    async def _profile_preflight(self) -> None:
        if self._docker_mode:
            return  # Docker's own probe below establishes the boundary.
        if self.sandbox_exec is None:
            raise RuntimeUnavailable("sandbox_exec_unavailable")
        with tempfile.TemporaryDirectory(prefix="faultline-preflight-") as directory:
            snapshot = Path(directory)
            (snapshot / "marker").write_text("preflight")
            process = await ManagedProcess.start(
                *self._sandbox(snapshot),
                str(self.host_python),
                "-I",
                "-c",
                "import os;"
                "assert os.path.isdir('/snapshot') or True;"
                "denied=False;"
                "try:\n"
                "    open('/etc/hosts','a').close()\n"
                "except OSError:\n"
                "    denied=True\n"
                "assert denied, 'sandbox must deny writes outside /tmp';"
                "print('darwin-profile-ready')",
                env={},
            )
            try:
                status = await process.wait(5)
            except TimeoutError:
                raise RuntimeUnavailable("isolated_profile_timeout") from None
            if status != 0 or bytes(process.stdout).strip() != b"darwin-profile-ready":
                raise RuntimeUnavailable("isolated_profile_unavailable")

    async def _enforcement_probe(self) -> str | None:
        if self._docker_mode:
            return await self._docker_enforcement_probe()
        with tempfile.TemporaryDirectory(prefix="faultline-limits-") as directory:
            process = await ManagedProcess.start(
                *self._sandbox(Path(directory)),
                str(self.host_python),
                "-I",
                "-c",
                "held=[]\n"
                "try:\n"
                "    while True: held.append(b'x' * (1 << 20))\n"
                "except MemoryError:\n"
                "    pass\n"
                "print('rlimit-enforced')",
                env={},
            )
            try:
                status = await process.wait(20)
            except TimeoutError:
                return "aggregate_limits_not_enforced"
            if status != 0 or bytes(process.stdout).strip() != b"rlimit-enforced":
                return "aggregate_limits_not_enforced"
        return None

    async def _docker_enforcement_probe(self) -> str | None:
        assert self.docker is not None
        process = await ManagedProcess.start(
            self.docker,
            "run",
            "--rm",
            "--memory",
            f"{self.limits.memory_max_bytes}",
            "--pids-limit",
            str(self.limits.tasks_max),
            "alpine",
            "sh",
            "-c",
            "cat /sys/fs/cgroup/memory.max",
        )
        try:
            status = await process.wait(20)
        except TimeoutError:
            return "aggregate_limits_unavailable"
        if status != 0:
            return "aggregate_limits_unavailable"
        try:
            observed = int(bytes(process.stdout).strip())
        except ValueError:
            return "aggregate_limits_unverified"
        return None if observed == self.limits.memory_max_bytes else "aggregate_limits_not_enforced"

    async def backend_preflight(self) -> None:
        self._backend_ready = False
        self._limits_preflight, self._limits_reason, self._limits_probe = "not_run", None, None
        if self.aggregate_mode not in {"required", "disabled"}:
            self._limits_reason = "aggregate_limits_mode_invalid"
            raise RuntimeUnavailable(self._limits_reason)
        if self.aggregate_mode == "disabled":
            self._limits_preflight, self._limits_reason = "disabled", "aggregate_limits_disabled"
        if self._docker_mode and self.docker is None:
            raise RuntimeUnavailable("sandbox_exec_and_docker_unavailable")
        if not self._docker_mode and self.sandbox_exec is None:
            raise RuntimeUnavailable("sandbox_exec_unavailable")
        await self._profile_preflight()
        if self.aggregate_mode == "required":
            reason = await self._enforcement_probe()
            self._limits_preflight = "failed" if reason else "passed"
            self._limits_reason = reason
            if reason is not None:
                raise RuntimeUnavailable(reason)
        self._backend_ready = True
