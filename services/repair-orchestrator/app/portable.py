"""Platform-neutral process and transport primitives for the isolation runtime.

This module must stay free of any ``app`` imports so both the trusted runtime
and the per-platform isolation adapters can import it without a cycle. It
replaces the Linux-only ``os.pipe2`` / abstract-socket / ``killpg`` calls that
previously leaked into the runtime hot path.

The three hosts FaultLine supports divide cleanly along two axes:

* **process model** — POSIX (Linux, macOS) vs Windows.
* **aggregate resource enforcement** — cgroup v2 scopes (Linux), ``setrlimit``
  plus optional Docker (macOS), Windows Job Objects (Windows).

Nothing here is a security boundary on its own; each adapter still has to prove
its own containment before readiness.
"""

from __future__ import annotations

import os
import shutil
import socket
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

IS_WINDOWS = os.name == "nt"
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

Host = Literal["linux", "darwin", "windows"]


def current_host() -> Host:
    """Return the canonical host tag used to select an isolation adapter."""
    if IS_WINDOWS:
        return "windows"
    if IS_MACOS:
        return "darwin"
    return "linux"


def portable_pipe() -> tuple[int, int]:
    """Create a close-on-exec pipe without the Linux-only ``os.pipe2``.

    ``os.pipe2(os.O_CLOEXEC)`` does not exist on macOS or Windows. ``os.pipe``
    followed by ``set_inheritable`` is equivalent everywhere, including Linux.
    """
    read_fd, write_fd = os.pipe()
    try:
        os.set_inheritable(read_fd, False)
        os.set_inheritable(write_fd, False)
    except (AttributeError, OSError):
        # POSIX: best-effort close-on-exec is enough; the supervisor owns the
        # write end and the controller explicitly closes it in every exit path.
        pass
    return read_fd, write_fd


def clear_close_on_exec(fd: int) -> None:
    """Make a descriptor inheritable again where a child must receive it."""
    if not IS_WINDOWS and hasattr(os, "set_inheritable"):
        os.set_inheritable(fd, True)


@dataclass(frozen=True)
class BackendEndpoint:
    """A candidate backend's listener plus the address its client dials.

    On Linux the address is an abstract ``\\0``-prefixed Unix socket (immune to
    filesystem symlink redirection and the 108-byte path limit). On macOS the
    address is a filesystem Unix socket under a private temp directory (macOS
    has no abstract namespace). On Windows there is no usable Unix socket, so
    ``socket`` is ``None`` and ``address`` is a loopback TCP port the child
    binds itself.
    """

    socket: socket.socket | None
    address: str
    kind: Literal["abstract-unix", "named-unix", "tcp"]


def backend_endpoint(generation_id: str, *, runtime_dir: Path | None = None) -> BackendEndpoint:
    """Create the candidate-transport listener for this host.

    ``generation_id`` must already be a canonical UUID (the caller validates it).
    On Windows the child process binds the port itself because Windows cannot
    pass a listening descriptor to a child; the parent therefore only reserves a
    free loopback port and returns no socket.
    """
    if IS_WINDOWS:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind(("127.0.0.1", 0))
            port = int(probe.getsockname()[1])
        finally:
            probe.close()
        return BackendEndpoint(None, str(port), "tcp")
    if IS_MACOS:
        directory = runtime_dir or Path(tempfile.gettempdir())
        directory.mkdir(parents=True, exist_ok=True)
        # A short name keeps the AF_UNIX path well under the 108-byte limit.
        path = directory / f"flt-{generation_id[:8]}.sock"
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(path))
        listener.listen(16)
        return BackendEndpoint(listener, str(path), "named-unix")
    # Linux: the abstract namespace keeps the socket out of the filesystem.
    address = "\0faultline-" + generation_id
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(address)
    listener.listen(16)
    return BackendEndpoint(listener, address, "abstract-unix")


def is_portable_runtime() -> bool:
    """Whether this host can use a native (non-container) isolation adapter."""
    return IS_LINUX or IS_MACOS or IS_WINDOWS


def detect_host() -> Host:
    """Return the host tag by reading the interpreter's platform at call time.

    ``current_host`` freezes its answer at import via ``IS_WINDOWS`` /
    ``IS_MACOS``. The CLI and tests call this instead, so a reassigned
    ``sys.platform`` (or a simulated host) is honored.
    """
    if os.name == "nt" or sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


def _which(name: str) -> str | None:
    """Locate a binary, treating a broken platform shim as simply "absent".

    ``shutil.which`` branches on ``sys.platform``; on a host whose platform
    module is inconsistent with the running interpreter (for example a
    simulated ``win32`` on POSIX, where the ``_winapi`` extension cannot load)
    it can raise ``AttributeError``. Capability reporting must never crash the
    CLI, so a failed lookup is reported as the tool not being present.
    """
    try:
        return shutil.which(name)
    except (AttributeError, OSError):
        return None


@dataclass(frozen=True)
class PlatformCapabilities:
    """The isolation engine this host will use and what it can enforce.

    ``engine`` names the adapter ``select_runtime`` picks; ``mode`` is the
    ``ResourceLimits.mode`` that engine reports. ``native`` is True when the
    platform's own mechanism (bwrap, sandbox-exec, or a PowerShell Job Object)
    is installed; ``docker`` is True when a Docker/Podman fallback exists.
    ``missing`` lists the absent native tools. This record is a capability
    description only: it never launches a process or claims enforcement.
    """

    host: str
    engine: str
    mode: str
    summary: str
    native: bool
    docker: bool
    missing: tuple[str, ...] = ()


def platform_capabilities(host: Host | None = None) -> PlatformCapabilities:
    """Describe the active isolation engine and this host's capabilities.

    Only the binaries each adapter needs are located; nothing is executed, so
    this is safe to call from the CLI before any Linux-only runtime module is
    imported.
    """
    current = host or detect_host()
    if current == "darwin":
        sandbox_exec = _which("sandbox-exec")
        docker = _which("docker") or _which("podman")
        if sandbox_exec:
            return PlatformCapabilities(
                host="darwin",
                engine="sandbox-exec",
                mode="rlimits",
                summary="sandbox-exec + setrlimit"
                + ("; Docker fallback available" if docker else "; no Docker fallback"),
                native=True,
                docker=docker is not None,
            )
        if docker:
            return PlatformCapabilities(
                host="darwin",
                engine="docker",
                mode="docker",
                summary="Docker container (sandbox-exec unavailable)",
                native=False,
                docker=True,
                missing=("sandbox-exec",),
            )
        return PlatformCapabilities(
            host="darwin",
            engine="sandbox-exec",
            mode="rlimits",
            summary="no isolation backend available (sandbox-exec and Docker both missing)",
            native=False,
            docker=False,
            missing=("sandbox-exec", "docker"),
        )
    if current == "windows":
        pwsh = _which("pwsh") or _which("powershell.exe") or _which("powershell")
        if pwsh:
            return PlatformCapabilities(
                host="windows",
                engine="windows-job",
                mode="windows-job",
                summary="Windows Job Objects (PowerShell wrapper)",
                native=True,
                docker=False,
            )
        return PlatformCapabilities(
            host="windows",
            engine="windows-job",
            mode="windows-job",
            summary="no isolation backend available (PowerShell missing)",
            native=False,
            docker=False,
            missing=("pwsh",),
        )
    # Linux: bubblewrap is the native engine; Docker is the fallback.
    bwrap = _which("bwrap")
    docker = _which("docker") or _which("podman")
    if bwrap:
        return PlatformCapabilities(
            host="linux",
            engine="bubblewrap",
            mode="cgroup-v2-scope",
            summary="bubblewrap + cgroup v2 (systemd user scope)",
            native=True,
            docker=docker is not None,
        )
    if docker:
        return PlatformCapabilities(
            host="linux",
            engine="docker",
            mode="docker",
            summary="Docker container (bubblewrap unavailable)",
            native=False,
            docker=True,
            missing=("bwrap",),
        )
    return PlatformCapabilities(
        host="linux",
        engine="bubblewrap",
        mode="cgroup-v2-scope",
        summary="no isolation backend available (bubblewrap and Docker both missing)",
        native=False,
        docker=False,
        missing=("bwrap", "docker"),
    )
