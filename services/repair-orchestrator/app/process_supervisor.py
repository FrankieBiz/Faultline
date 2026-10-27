"""Trusted subprocess supervisor; liveness-pipe EOF also handles controller SIGKILL.

The controller retains the sole write end. No child inherits either end. If the
controller exits or cancels, EOF sends SIGTERM so Playwright can close Chromium,
then kills the remaining process group and reaps its immediate child.
"""

import os
import selectors
import signal
import subprocess
import sys
import time


def main() -> None:
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


if __name__ == "__main__":
    main()
