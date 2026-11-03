"""Per-platform isolation adapters for the candidate execution runtime.

``IsolatedRuntime`` remains the Linux engine (bubblewrap + systemd + cgroup v2).
``DarwinIsolatedRuntime`` (``sandbox-exec`` + ``setrlimit``, Docker fallback)
and ``WindowsIsolatedRuntime`` (Job Objects + ``taskkill``) override the same
platform seam so the trusted oracle and orchestration run on every host.
``select_runtime`` picks the right engine for the current host; Linux returns
the base engine unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from app.portable import current_host
from app.snapshots import REPOSITORY_ROOT

if TYPE_CHECKING:
    from app.isolated_runtime import IsolatedRuntime


def select_runtime(repository_root: Path | None = None) -> IsolatedRuntime:
    """Return the isolation runtime for the current host.

    The import is lazy so importing this package does not force the heavy
    runtime, and so the ``isolation`` -> ``isolated_runtime`` -> ``isolation``
    cycle cannot form at module load time.
    """
    from app.isolated_runtime import IsolatedRuntime

    root = repository_root or REPOSITORY_ROOT
    host = current_host()
    if host == "darwin":
        from app.isolation.darwin import DarwinIsolatedRuntime

        return DarwinIsolatedRuntime(root)
    if host == "windows":
        from app.isolation.windows import WindowsIsolatedRuntime

        return WindowsIsolatedRuntime(root)
    return IsolatedRuntime(root)


__all__ = ["select_runtime", "current_host"]
