"""Trusted subprocess supervisor; liveness-pipe EOF also handles controller SIGKILL.

On POSIX the controller retains the sole write end of a close-on-exec pipe and
the supervisor owns the process group (``start_new_session``), so closing the
pipe or killing the group reaches every descendant. On Windows there is no file
descriptor passing and no ``killpg``: the controller instead writes a stop-file
and the supervisor tears the tree down with ``taskkill /T /F``, which walks the
parent-child tree that ``CREATE_NEW_PROCESS_GROUP`` rooted at this process.

The supervisor reaps its direct child. POSIX descendants must stay in the
owned process group; escaped sessions require an outer kernel boundary. On
Windows the candidate Job Object, not the parent/PID tree, owns descendants.
The Windows stop-file only handles explicit shutdown, not controller crashes.
"""

import os
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path


def _taskkill_tree(pid: int) -> bool:
    """Kill a Windows process and its descendants via ``taskkill /T /F``."""
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    executable = os.path.join(system_root, "System32", "taskkill.exe")
    try:
        result = subprocess.run(
            [executable, "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _main_posix() -> None:
    liveness_fd = int(sys.argv[1])
    inherited = tuple(int(value) for value in sys.argv[2].split(",") if value)
    command = sys.argv[3:]
    process = subprocess.Popen(command, pass_fds=inherited, start_new_session=True)
    selector = selectors.DefaultSelector()
    selector.register(liveness_fd, selectors.EVENT_READ)
    try:
        while process.poll() is None:
            if selector.select(timeout=0.1) and not os.read(liveness_fd, 1):
                break
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass  # The leader may exit between poll() and killpg().
            until = time.monotonic() + 1
            while process.poll() is None and time.monotonic() < until:
                time.sleep(0.02)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        code = process.wait()
        raise SystemExit(code if code >= 0 else 128 - code)
    finally:
        selector.close()
        os.close(liveness_fd)


def _main_windows() -> None:
    stop_file = Path(sys.argv[1])
    command = sys.argv[2:]
    # CREATE_NEW_PROCESS_GROUP roots the child tree so taskkill /T reaches it.
    # getattr keeps this source type-checkable on POSIX where the flag is absent.
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    process = subprocess.Popen(command, creationflags=creationflags)
    try:
        while process.poll() is None:
            if stop_file.exists():
                break
            time.sleep(0.05)
        # Never taskkill an already-reaped PID: it may have been reused. The
        # wrapper's Job Object closes on exit and sweeps its own descendants.
        if process.poll() is None and not _taskkill_tree(process.pid):
            process.kill()  # TerminateProcess closes the wrapper's job handle.
        code = process.wait(timeout=2)
        raise SystemExit(code if code >= 0 else 128 - code)
    finally:
        try:
            if process.poll() is not None:
                stop_file.unlink(missing_ok=True)
        except OSError:
            pass


def main() -> None:
    if os.name == "nt":
        _main_windows()
    else:
        _main_posix()


if __name__ == "__main__":
    main()
