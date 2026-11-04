"""Linux demo ownership and native foreground launchers, without process environments."""

from __future__ import annotations

import http.client
import importlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

# Order matches scripts/start-demo.sh.
SERVICE_DIRS = (
    "apps/buggyshop-backend",
    "services/repair-orchestrator",
    "apps/buggyshop-frontend",
    "web/inspector-ui",
)
PORT_NAMES = ("BUGGYSHOP_API_PORT", "FAULTLINE_PORT", "BUGGYSHOP_PORT", "INSPECTOR_PORT")
DEFAULT_PORTS = (8000, 9000, 3000, 4000)
START_TIMEOUT = 240.0
STOP_TIMEOUT = 10.0


@contextmanager
def launch_lock(root: Path) -> Iterator[Callable[[], None]]:
    """Serialize this installation's startup; release at readiness or on any failure."""
    path = root / "data/demo.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep the inode after release: unlinking would let contenders lock different files.
    with path.open("a+b") as lock:
        if os.name == "nt":
            msvcrt = importlib.import_module("msvcrt")

            # Windows locks a byte range starting at the current file position.
            lock.seek(0, os.SEEK_END)
            if lock.tell() == 0:
                lock.write(b"\0")
                lock.flush()

            def set_lock(acquire: bool) -> None:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK if acquire else msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            def set_lock(acquire: bool) -> None:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB if acquire else fcntl.LOCK_UN)

        try:
            set_lock(True)
        except OSError:
            raise RuntimeError("Demo launch already in progress for this installation.") from None

        held = True

        def release() -> None:
            nonlocal held
            if held:
                set_lock(False)
                held = False

        try:
            yield release
        finally:
            release()


@dataclass(frozen=True)
class Process:
    pid: int
    parent: int
    started: str
    cwd: Path
    argv: tuple[str, ...]
    ports: frozenset[int]


def _socket_ports() -> dict[str, int]:
    result: dict[str, int] = {}
    for name in ("tcp", "tcp6"):
        path = Path(f"/proc/net/{name}")
        try:
            content = path.read_text()
        except OSError:
            continue
        for line in content.splitlines()[1:]:
            fields = line.split()
            if len(fields) > 9 and fields[3] == "0A":  # TCP_LISTEN, including wildcard listeners
                result[f"socket:[{fields[9]}]"] = int(fields[1].rsplit(":", 1)[1], 16)
    return result


def _read_process(pid: int, sockets: dict[str, int]) -> Process | None:
    directory = Path(f"/proc/{pid}")
    try:
        stat = (directory / "stat").read_text().rsplit(")", 1)[1].split()
        cwd = (directory / "cwd").resolve(strict=True)
        argv = tuple((directory / "cmdline").read_bytes().decode(errors="replace").split("\0")[:-1])
        ports = set()
        for fd in (directory / "fd").iterdir():
            try:
                port = sockets.get(os.readlink(fd))
                if port is not None:
                    ports.add(port)
            except OSError:
                continue
        after = (directory / "stat").read_text().rsplit(")", 1)[1].split()
        if after[19] != stat[19] or not argv:
            return None
        return Process(pid, int(stat[1]), stat[19], cwd, argv, frozenset(ports))
    except (OSError, ValueError, IndexError):
        return None


def processes() -> dict[int, Process]:
    """Snapshot readable cwd, argv, ancestry, start times and listening socket ownership."""
    sockets = _socket_ports()
    result = {}
    for directory in Path("/proc").iterdir():
        if directory.name.isdecimal():
            process = _read_process(int(directory.name), sockets)
            if process is not None:
                result[process.pid] = process
    return result


def _ancestors(process: Process, snapshot: dict[int, Process]) -> list[Process]:
    result = [process]
    seen = {process.pid}
    while process.parent in snapshot and process.parent not in seen:
        process = snapshot[process.parent]
        seen.add(process.pid)
        result.append(process)
    return result


def _service_root(
    process: Process, index: int, port: int, snapshot: dict[int, Process]
) -> Path | None:
    suffix = Path(SERVICE_DIRS[index])
    if process.cwd.parts[-len(suffix.parts) :] != suffix.parts:
        return None
    root = process.cwd.parents[len(suffix.parts) - 1]
    if not (root / "scripts/start-demo.sh").is_file():
        return None
    for owner in _ancestors(process, snapshot):
        if owner.cwd != process.cwd:
            break
        argv = owner.argv
        if index < 2:
            valid = (
                any(Path(arg).name == "uvicorn" for arg in argv)
                and "app.main:app" in argv
                and any(
                    a == "--port" and b == str(port) for a, b in zip(argv, argv[1:], strict=False)
                )
            )
        else:
            # Next replaces argv with its process title once listening.
            valid = bool(argv) and (
                argv[0].startswith("next-server (v")
                or ("node_modules/next/dist/bin/next" in argv and "start" in argv)
            )
        if valid:
            return root
    return None


def _occupied(port: int) -> bool:
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


def _healthy(index: int, port: int) -> bool:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
    try:
        connection.request("GET", "/healthz" if index < 2 else "/")
        response = connection.getresponse()
        if response.status != 200:
            return False
        if index < 2:
            body = json.loads(response.read(65536))
            app = ("buggyshop-api", "faultline-orchestrator")[index]
            return isinstance(body, dict) and body.get("app") == app and body.get("status") == "ok"
        return True
    except (OSError, http.client.HTTPException, ValueError):
        return False
    finally:
        connection.close()


@dataclass(frozen=True)
class Stack:
    occupied: frozenset[int]
    owners: tuple[Process, ...]
    root: Path | None
    foreign: frozenset[int]
    active: bool


def inspect_stack(ports: tuple[int, ...], snapshot: dict[int, Process]) -> Stack:
    occupied = frozenset(port for port in ports if _occupied(port))
    owners: dict[int, Process] = {}
    roots = set()
    foreign = set()
    for index, port in enumerate(ports):
        if port not in occupied:
            continue
        listeners = [p for p in snapshot.values() if port in p.ports]
        if not listeners:
            foreign.add(port)
        for process in listeners:
            root = _service_root(process, index, port, snapshot)
            if root is None:
                foreign.add(port)
            else:
                roots.add(root)
                owners[process.pid] = process
    if len(roots) > 1:
        foreign.update(occupied)
    root = next(iter(roots)) if len(roots) == 1 else None
    active = (
        len(occupied) == 4
        and not foreign
        and root is not None
        and all(_healthy(index, port) for index, port in enumerate(ports))
    )
    return Stack(occupied, tuple(owners.values()), root, frozenset(foreign), active)


def _launcher(process: Process, root: Path) -> bool:
    return (
        process.cwd == root
        and len(process.argv) >= 2
        and (
            Path(process.argv[0]).name in {"bash", "sh"}
            and (root / process.argv[1]).resolve() == root / "scripts/start-demo.sh"
        )
    )


def ensure_build_unused(root: Path, snapshot: dict[int, Process]) -> None:
    """The existing launcher builds .next; never rebuild a running worktree's files."""
    directories = {root / directory for directory in SERVICE_DIRS}
    if any(p.cwd in directories and p.ports or _launcher(p, root) for p in snapshot.values()):
        raise RuntimeError(
            "This worktree already has demo services or a launcher running on other ports. "
            "Use their port settings or a separate worktree; no build was started."
        )


def stop_stack(
    root: Path, ports: tuple[int, ...], stack: Stack, snapshot: dict[int, Process]
) -> None:
    """Signal only a verified launcher; its own trap owns all service cleanup."""
    if stack.root != root:
        raise RuntimeError("Demo belongs to another worktree; restart it from that installation.")
    launchers = [p for p in snapshot.values() if _launcher(p, root)]
    owned = [
        launcher
        for launcher in launchers
        if all(launcher in _ancestors(owner, snapshot) for owner in stack.owners)
    ]
    if len(owned) != 1 or not stack.owners:
        raise RuntimeError(
            "Cannot verify one owning start-demo.sh launcher. Stop these services from their "
            "original terminal; no process was stopped."
        )
    launcher = owned[0]
    descendants = [p for p in snapshot.values() if launcher in _ancestors(p, snapshot)]
    if any(p.ports - set(ports) for p in descendants):
        raise RuntimeError("Demo launcher also owns other ports; no process was stopped.")
    ensure_build_unused(root, {pid: p for pid, p in snapshot.items() if p not in descendants})
    # A pidfd prevents PID reuse between the identity recheck and delivery of SIGTERM.
    with os.fdopen(os.pidfd_open(launcher.pid), "rb") as handle:  # type: ignore[attr-defined]
        current = _read_process(launcher.pid, {})
        if current is None or (current.started, current.cwd, current.argv) != (
            launcher.started,
            launcher.cwd,
            launcher.argv,
        ):
            raise RuntimeError("Demo launcher changed during inspection; retry discovery.")
        signal.pidfd_send_signal(handle.fileno(), signal.SIGTERM)  # type: ignore[attr-defined]
    deadline = time.monotonic() + STOP_TIMEOUT
    while time.monotonic() < deadline:
        current_processes = processes()
        if all(
            p.pid not in current_processes or current_processes[p.pid].started != p.started
            for p in descendants
        ) and not any(_occupied(port) for port in ports):
            return
        time.sleep(0.1)
    raise RuntimeError("Demo did not stop cleanly; no replacement was started.")


def start_demo(root: Path, ports: tuple[int, ...], ready: Callable[[], None]) -> int:
    """Keep the existing launcher in the foreground and preserve its cleanup trap."""
    env = {**os.environ, **dict(zip(PORT_NAMES, map(str, ports), strict=True))}
    windows = sys.platform == "win32"
    stop_file = root / "data" / f"demo-stop-{uuid.uuid4().hex}"
    command = ["bash", str(root / "scripts/start-demo.sh")]
    if windows:
        # Let the selected PowerShell version discover its own standard modules;
        # a caller's PowerShell 7 paths can break Windows PowerShell 5.1 imports.
        env.pop("PSModulePath", None)
        shell = shutil.which("pwsh") or shutil.which("powershell.exe")
        if shell is None:
            raise RuntimeError("PowerShell is required for the demo (pwsh or powershell.exe).")
        command = [
            shell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(root / "scripts/start-demo.ps1"),
            "-StopFile",
            str(stop_file),
        ]
        stop_file.parent.mkdir(parents=True, exist_ok=True)
    with subprocess.Popen(
        command,
        cwd=root,
        env=env,
        start_new_session=not windows,
        # Only the CLI handles console Ctrl+C; it asks PowerShell to unwind its
        # finally block rather than killing the supervisor ahead of its children.
        creationflags=0x00000200 if windows else 0,  # CREATE_NEW_PROCESS_GROUP
    ) as process:
        try:
            deadline = time.monotonic() + START_TIMEOUT
            while time.monotonic() < deadline:
                code = process.poll()
                if code is not None:
                    raise RuntimeError(f"Demo launcher exited during startup (code {code}).")
                if sys.platform in {"darwin", "win32"}:
                    # This foreground invocation owns the launcher, but cannot attest
                    # service process ownership through Linux /proc on these platforms.
                    active = all(_healthy(index, port) for index, port in enumerate(ports))
                else:
                    stack = inspect_stack(ports, processes())
                    active = stack.active and stack.root == root
                if active:
                    ready()
                    return process.wait()
                time.sleep(0.5)
            raise RuntimeError("Demo startup timed out; stopping this launcher's session.")
        finally:
            try:
                if process.poll() is None:
                    if windows:
                        stop_file.touch()
                        try:
                            process.wait(timeout=STOP_TIMEOUT)
                        except subprocess.TimeoutExpired:
                            # A stuck supervisor cannot poll StopFile. Kill only this
                            # invocation's process tree, including build children.
                            subprocess.run(
                                ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                                check=False,
                                capture_output=True,
                            )
                            process.wait()
                    else:
                        process.terminate()
                        # The launcher's trap owns child cleanup.
                        process.wait()
            finally:
                if windows:
                    stop_file.unlink(missing_ok=True)
