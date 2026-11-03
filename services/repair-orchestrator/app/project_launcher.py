"""Trusted namespace entry point: forward an inherited UDS to a loopback dev service.

This file runs with isolated Python and uses only the standard library. The
candidate never inherits the listener. All project writes stay on bounded tmpfs.
"""

import json
import os
import selectors
import shutil
import socket
import subprocess
import sys
import threading
from collections.abc import Mapping

# The only variables a project dev command may inherit from the launcher's own
# environment. Every API key, token, and control credential is excluded by
# name, so no host secret can cross into project code even if the enclosing
# sandbox profile were ever weakened. PATH/HOME arrive via the bubblewrap
# ``--setenv`` values; the two PYTHON flags are the isolation profile's own.
_PROJECT_ENVIRONMENT_ALLOWLIST = frozenset(
    {
        "PATH",
        "HOME",
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONUNBUFFERED",
    }
)

# Fixed, operator-independent values project tooling requires. None names a
# credential; they pin offline and telemetry-disabled behavior for uv and
# Next.js so a hostile dev_command cannot phone home or sync dependencies.
_PROJECT_ENVIRONMENT_FIXED = {
    "PYTHONPATH": "/packages",
    "UV_OFFLINE": "1",
    "UV_NO_SYNC": "1",
    "UV_CACHE_DIR": "/tmp/uv-cache",
    "NEXT_TELEMETRY_DISABLED": "1",
}


def build_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """Return the scrubbed environment for the project's dev command.

    Only the fixed allowlist above may cross into project code. This function
    deliberately reads a caller-supplied mapping rather than ``os.environ`` so
    tests can feed it hostile host environments (Linux, macOS, and Windows
    spellings alike) and prove no secret survives into the ``Popen`` call.
    """
    environment = {
        name: environ[name] for name in _PROJECT_ENVIRONMENT_ALLOWLIST if name in environ
    }
    environment.update(_PROJECT_ENVIRONMENT_FIXED)
    return environment


def relay(connection: socket.socket, port: int) -> None:
    try:
        with connection, socket.create_connection(("127.0.0.1", port), timeout=3) as upstream:
            with selectors.DefaultSelector() as selector:
                selector.register(connection, selectors.EVENT_READ, upstream)
                selector.register(upstream, selectors.EVENT_READ, connection)
                while True:
                    events = selector.select(timeout=10)
                    if not events:
                        return
                    for key, _ in events:
                        source = key.fileobj
                        assert isinstance(source, socket.socket)
                        data = source.recv(65536)
                        if not data:
                            return
                        key.data.sendall(data)
    except OSError:
        connection.close()


def main() -> None:
    listener = socket.socket(fileno=int(sys.argv[1]))
    port = int(sys.argv[2])
    command = json.loads(sys.argv[3])
    shutil.copytree("/snapshot", "/tmp/project")
    # Dependency mounts are read-only and separate from the source export.
    for name in ("node_modules", ".venv"):
        if os.path.isdir("/dependencies/" + name):
            os.symlink("/dependencies/" + name, "/tmp/project/" + name)
    process = subprocess.Popen(
        command, cwd="/tmp/project", close_fds=True, env=build_environment(os.environ)
    )
    listener.settimeout(0.2)
    while process.poll() is None:
        try:
            connection, _ = listener.accept()
        except TimeoutError:
            continue
        threading.Thread(target=relay, args=(connection, port), daemon=True).start()
    sys.exit(process.returncode)


if __name__ == "__main__":
    main()
