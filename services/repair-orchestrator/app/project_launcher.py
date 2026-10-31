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
    environment = {
        **os.environ,
        "PYTHONPATH": "/packages",
        "UV_OFFLINE": "1",
        "UV_NO_SYNC": "1",
        "UV_CACHE_DIR": "/tmp/uv-cache",
        "NEXT_TELEMETRY_DISABLED": "1",
    }
    process = subprocess.Popen(command, cwd="/tmp/project", close_fds=True, env=environment)
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
