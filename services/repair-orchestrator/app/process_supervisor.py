"""Trusted subprocess supervisor; liveness-pipe EOF also handles controller SIGKILL.

On POSIX the controller retains the sole write end of a close-on-exec pipe and
the supervisor owns the process group (``start_new_session``), so closing the
pipe or killing the group reaches every descendant. On Windows there is no file
descriptor passing and no ``killpg``: the controller instead writes a stop-file
and the supervisor tears the tree down with ``taskkill /T /F``, which walks the
parent-child tree that ``CREATE_NEW_PROCESS_GROUP`` rooted at this process.

Either way the guarantee is the same: if the controller exits or cancels, the
child and every descendant are reaped, never left orphaned.
"""

import os
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path


def _taskkill_tree(pid: int) -> None:
    """Kill a Windows process and its descendants via ``taskkill /T /F``."""
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    executable = os.path.join(system_root, "System32", "taskkill.exe")
    subprocess.run(
        [executable, "/PID", str(pid), "/T", "/F"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


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
            os.killpg(process.pid, signal.SIGTERM)
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
                _taskkill_tree(process.pid)
                break
            time.sleep(0.05)
        # A child that exited may still have left grandchildren running; the
        # group tree is the ownership boundary, so always sweep it on exit too.
        _taskkill_tree(process.pid)
        code = process.wait()
        raise SystemExit(code if code >= 0 else 128 - code)
    finally:
        try:
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
