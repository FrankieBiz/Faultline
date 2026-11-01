"""Controller imports and installation locking without Unix-only modules."""

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest


def test_controller_imports_without_fcntl() -> None:
    script = """
import builtins
original_import = builtins.__import__
def portable_import(name, *args, **kwargs):
    if name == "fcntl":
        raise ModuleNotFoundError(name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = portable_import
from app.main import app
assert app is not None
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[3])},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("failure", [None, "contended", "worker"])
async def test_windows_run_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str | None
) -> None:
    from app import run

    monkeypatch.setattr(run, "fcntl", None)
    lock_file = tmp_path / "data/.run.lock"
    descriptors = []

    def locking(fd: int, mode: int, count: int) -> None:
        assert os.lseek(fd, 0, os.SEEK_CUR) == 0
        assert count == 1
        assert lock_file.read_bytes() == b"\0"
        descriptors.append(fd)
        if failure == "contended" and mode == 1:
            raise OSError("already locked")

    windows_lock = SimpleNamespace(locking=Mock(side_effect=locking), LK_NBLCK=1, LK_UNLCK=2)
    monkeypatch.setitem(sys.modules, "msvcrt", windows_lock)
    worker = AsyncMock(return_value={"outcome": "verified"})
    if failure == "worker":
        worker.side_effect = ValueError("worker failed")
    monkeypatch.setattr(run, "_run_project", worker)
    project: Any = object()
    if failure:
        error, message = (
            (RuntimeError, "another run owns this data directory")
            if failure == "contended"
            else (ValueError, "worker failed")
        )
        with pytest.raises(error, match=message):
            await run.run_project(tmp_path, project, lock_file.parent, detect=True)
    else:
        assert await run.run_project(tmp_path, project, lock_file.parent, detect=True) == {
            "outcome": "verified"
        }
    if failure == "contended":
        worker.assert_not_awaited()
        assert windows_lock.locking.call_count == 1
    else:
        worker.assert_awaited_once_with(tmp_path, project, lock_file.parent, detect=True)
        assert [call.args[1:] for call in windows_lock.locking.call_args_list] == [(1, 1), (2, 1)]
    for fd in descriptors:
        with pytest.raises(OSError):
            os.fstat(fd)
