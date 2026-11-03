"""Trusted entry point mounted into the isolation boundary of every host.

On Linux this file is bind-mounted at ``/trusted_backend.py`` inside the
bubblewrap namespace and reads only the inherited listener descriptor. On
macOS it runs directly under ``sandbox-exec`` with host paths; on Windows it
runs inside a Job Object and binds its own loopback port (Windows cannot pass a
listening descriptor to a child). The optional ``argv[2]``/``argv[3]`` package
and application paths let the non-namespace hosts supply real filesystem paths
while Linux keeps the ``/packages`` and ``/snapshot`` mounts.
"""

import json
import logging
import os
import sys
import traceback


class CorrelatedFormatter(logging.Formatter):
    """Retain actual backend exception and request correlation as bounded JSONL."""

    def format(self, record: logging.LogRecord) -> str:
        event = {
            "message": record.getMessage(),
            "case_id": getattr(record, "case_id", None),
            "request_id": getattr(record, "request_id", None),
            "route": getattr(record, "route", None),
            "exception_type": getattr(record, "exception_type", None),
        }
        if record.exc_info:
            event["traceback"] = "".join(traceback.format_exception(*record.exc_info))[-16384:]
        return json.dumps(event)


def _apply_rlimits() -> None:
    """Bound the candidate process where ``setrlimit`` exists; no-op on Windows.

    These are per-process bounds. On Linux they complement the aggregate cgroup
    scope; on macOS they are the native aggregate ceiling (there is no cgroup).
    Windows enforces memory and task caps through the Job Object that launched
    this interpreter, so nothing is applied here.
    """
    if os.name == "nt":
        return
    try:
        import resource
    except ImportError:
        return
    for name, value in (
        ("RLIMIT_NOFILE", (256, 256)),
        ("RLIMIT_CORE", (0, 0)),
        ("RLIMIT_CPU", (40, 40)),
        ("RLIMIT_AS", (768 * 1024 * 1024, 768 * 1024 * 1024)),
        ("RLIMIT_NPROC", (64, 64)),
    ):
        if hasattr(resource, name):
            resource.setrlimit(getattr(resource, name), value)


def main() -> None:
    """Apply resource bounds before importing any candidate application module."""
    _apply_rlimits()
    packages = sys.argv[2] if len(sys.argv) > 2 else "/packages"
    snapshot_app = sys.argv[3] if len(sys.argv) > 3 else "/snapshot/apps/buggyshop-backend"
    sys.path[:0] = [packages, snapshot_app]
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(CorrelatedFormatter())
    logger = logging.getLogger("buggyshop.api")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    # Uncaught tracebacks echo candidate source lines. Root formatting keeps every
    # record one escaped JSON line, so candidate text cannot forge a log event.
    logging.getLogger().handlers = [handler]
    import uvicorn

    target = int(sys.argv[1])
    if os.name == "nt":
        # Windows: the parent reserves a loopback port and the child binds it.
        uvicorn.run(
            "app.main:app",
            host="127.0.0.1",
            port=target,
            log_level="warning",
            access_log=False,
            log_config=None,
            lifespan="off",
            workers=1,
        )
    else:
        uvicorn.run(
            "app.main:app",
            fd=target,
            log_level="warning",
            access_log=False,
            log_config=None,
            lifespan="off",
            workers=1,
        )


if __name__ == "__main__":
    main()
