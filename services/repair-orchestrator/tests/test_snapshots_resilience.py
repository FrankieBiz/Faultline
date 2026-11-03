"""Filesystem failures must never contaminate another trial or the seeded tree."""

import asyncio
import hashlib
import os
import shutil
import stat
import subprocess
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest

from app import evaluation, snapshots
from app.evaluation import ApplicationExporter, BackendSession, measure
from app.model_adapter import deterministic_diff
from app.policy import TARGET_FILE, PatchPolicyError
from app.snapshots import SnapshotManager, contained_path


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()


@pytest.fixture
def seed(tmp_path: Path, seeded_source: str) -> tuple[Path, dict[str, Any]]:
    root = tmp_path / "repository"
    target = root / TARGET_FILE
    target.parent.mkdir(parents=True)
    target.write_text(seeded_source)
    (target.parent / "helper.py").write_text("VALUE = 1\n")
    git(root, "init", "--quiet")
    git(root, "add", ".")
    git(
        root,
        "-c",
        "user.name=FrankieBiz",
        "-c",
        "user.email=frankabisignano@gmail.com",
        "-c",
        "commit.gpgSign=false",
        "commit",
        "--quiet",
        "-m",
        "Create resilience fixture",
    )
    return root, {
        "source_commit": git(root, "rev-parse", "HEAD"),
        "fixtures": {"seeded": {"sha256": hashlib.sha256(target.read_bytes()).hexdigest()}},
    }


@pytest.mark.parametrize(
    "relative",
    [
        "",
        ".",
        "..",
        "../escape",
        "a/../../escape",
        "/escape",
        "C:\\escape",
        "C:escape",
        "\\\\host\\share",
        "a\\..\\escape",
        "bad\x00name",
    ],
)
def test_contained_path_rejects_traversal(tmp_path: Path, relative: str) -> None:
    with pytest.raises(ValueError):
        contained_path(tmp_path, relative)


@pytest.mark.parametrize("broken", [False, True])
@pytest.mark.parametrize("location", ["root", "ancestor", "parent", "leaf"])
def test_contained_path_rejects_all_symlink_components(
    tmp_path: Path, broken: bool, location: str
) -> None:
    outside = tmp_path / "outside"
    if not broken:
        outside.mkdir()
    root = tmp_path / "owned"
    if location in {"root", "ancestor"}:
        root.symlink_to(outside, target_is_directory=True)
        if location == "ancestor":
            root = root / "nested"
        relative = "file.py"
    else:
        root.mkdir()
        (root / "link").symlink_to(outside, target_is_directory=True)
        relative = "link/file.py" if location == "parent" else "link"
    with pytest.raises(ValueError, match="[Ss]ymlink"):
        contained_path(root, relative)


@pytest.mark.parametrize("job", ["../escape", "not-a-uuid", str(uuid4()).upper()])
async def test_job_identifiers_cannot_escape(tmp_path: Path, job: str) -> None:
    manager = SnapshotManager(tmp_path)
    with pytest.raises(ValueError):
        await manager.create(job, {"source_commit": "unused"})
    assert not list(tmp_path.iterdir())


async def test_rollback_is_fresh_and_preserves_readonly_seed(
    tmp_path: Path, seed: tuple[Path, dict[str, Any]]
) -> None:
    repository, manifest = seed
    live = repository / TARGET_FILE
    original = live.read_bytes()
    live.chmod(0o444)
    manager = SnapshotManager(tmp_path / "data", repository)
    job = str(uuid4())
    baseline = await manager.create(job, manifest)
    candidate = await manager.create(
        job, manifest, diff=deterministic_diff(baseline.source), base_sha256=baseline.source_sha256
    )
    (candidate.path / TARGET_FILE).write_text("corrupted candidate\n")
    (candidate.path / TARGET_FILE).chmod(0o444)
    restored = await manager.create(job, manifest)
    assert baseline.sha256 == restored.sha256 != candidate.sha256
    assert baseline.path != restored.path != candidate.path
    assert (restored.path / TARGET_FILE).read_bytes() == original == live.read_bytes()
    assert stat.S_IMODE(live.stat().st_mode) == 0o444
    assert stat.S_IMODE((restored.path / TARGET_FILE).stat().st_mode) == 0o644
    await manager.cleanup(job)
    assert not manager._job_root(job).exists()
    assert len(git(repository, "worktree", "list", "--porcelain").split("worktree ")) == 2


@pytest.mark.parametrize("failure", ["hash", "policy", "export", "cancel"])
async def test_failed_creation_discards_only_its_generation(
    tmp_path: Path,
    seed: tuple[Path, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    repository, manifest = seed
    manager = SnapshotManager(tmp_path / "data", repository)
    job = str(uuid4())
    baseline = await manager.create(job, manifest)
    registered = git(repository, "worktree", "list", "--porcelain")
    original_git = manager._git

    async def failing_git(root: Path, *args: str, data: bytes | None = None) -> bytes:
        result = await original_git(root, *args, data=data)
        if args[0] == "checkout-index":
            if failure == "cancel":
                raise asyncio.CancelledError
            raise OSError("injected export failure")
        return result

    kwargs: dict[str, Any] = {}
    expected: type[BaseException] = PatchPolicyError
    if failure == "hash":
        manifest = {**manifest, "fixtures": {"seeded": {"sha256": "0" * 64}}}
    elif failure == "policy":
        kwargs = {"diff": "invalid", "base_sha256": baseline.source_sha256}
    else:
        monkeypatch.setattr(manager, "_git", failing_git)
        expected = asyncio.CancelledError if failure == "cancel" else OSError
    with pytest.raises(expected):
        await manager.create(job, manifest, **kwargs)
    assert git(repository, "worktree", "list", "--porcelain") == registered
    assert list((manager._job_root(job) / "snapshots").iterdir()) == [baseline.path]
    assert list((manager._job_root(job) / "worktrees").iterdir()) == [baseline.worktree]
    assert (baseline.path / TARGET_FILE).read_text() == baseline.source
    await manager.cleanup(job)


async def test_cleanup_readonly_directories_and_broken_links_does_not_touch_outside(
    tmp_path: Path, seed: tuple[Path, dict[str, Any]]
) -> None:
    repository, manifest = seed
    manager = SnapshotManager(tmp_path / "data", repository)
    job = str(uuid4())
    snapshot = await manager.create(job, manifest)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_text("untouched")
    sentinel.chmod(0o444)
    (snapshot.path / "outside").symlink_to(outside, target_is_directory=True)
    (snapshot.path / "broken").symlink_to(tmp_path / "missing")
    (snapshot.worktree / "broken").symlink_to(tmp_path / "missing")
    for tree in (snapshot.path, snapshot.worktree):
        (tree / TARGET_FILE).chmod(0o444)
        (tree / TARGET_FILE).parent.chmod(0o555)
    evidence = manager._job_root(job).parent / "evidence"
    evidence.mkdir()
    (evidence / "report").write_text("retained")
    await manager.cleanup(job)
    await manager.cleanup(job)
    assert not snapshot.path.exists() and not snapshot.worktree.exists()
    assert sentinel.read_text() == "untouched"
    assert stat.S_IMODE(sentinel.stat().st_mode) == 0o444
    assert (evidence / "report").read_text() == "retained"


async def test_concurrent_jobs_and_candidates_have_independent_bytes(
    tmp_path: Path, seed: tuple[Path, dict[str, Any]]
) -> None:
    repository, manifest = seed
    manager = SnapshotManager(tmp_path / "data", repository)
    jobs = [str(uuid4()), str(uuid4())]
    results = await asyncio.gather(*(manager.create(job, manifest) for job in jobs * 3))
    assert len({item.path for item in results}) == 6
    assert len({item.worktree for item in results}) == 6
    (results[0].path / TARGET_FILE).write_text("changed")
    assert all((item.path / TARGET_FILE).read_text() == item.source for item in results[1:])
    await manager.cleanup(jobs[0])
    assert all(item.path.exists() for item in results[1::2])
    await manager.cleanup(jobs[1])


async def test_cleanup_waits_for_inflight_creation(
    tmp_path: Path, seed: tuple[Path, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, manifest = seed
    manager = SnapshotManager(tmp_path / "data", repository)
    job = str(uuid4())
    entered, release, cleanup_started = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original_git = manager._git

    async def blocked_git(root: Path, *args: str, data: bytes | None = None) -> bytes:
        result = await original_git(root, *args, data=data)
        if args[0] == "checkout-index":
            entered.set()
            await release.wait()
        return result

    async def cleanup() -> None:
        cleanup_started.set()
        await manager.cleanup(job)

    monkeypatch.setattr(manager, "_git", blocked_git)
    creation = asyncio.create_task(manager.create(job, manifest))
    await asyncio.wait_for(entered.wait(), 5)
    disposal = asyncio.create_task(cleanup())
    await asyncio.wait_for(cleanup_started.wait(), 5)
    try:
        assert not disposal.done()
        # Another job is independent of the blocked job's lock.
        other = str(uuid4())
        monkeypatch.setattr(manager, "_git", original_git)
        other_snapshot = await manager.create(other, manifest)
    finally:
        release.set()
        await asyncio.gather(creation, disposal)
    assert not manager._job_root(job).exists()
    assert other_snapshot.path.exists()
    await manager.cleanup(other)


@pytest.mark.parametrize("kind", ["symlink", "broken", "executable", "non_python"])
async def test_git_export_rejects_unsafe_entries_without_leaking_worktrees(
    tmp_path: Path, seed: tuple[Path, dict[str, Any]], kind: str
) -> None:
    repository, manifest = seed
    helper = (repository / TARGET_FILE).parent / "helper.py"
    if kind in {"symlink", "broken"}:
        helper.unlink()
        helper.symlink_to("checkout.py" if kind == "symlink" else "missing.py")
    elif kind == "executable":
        helper.chmod(0o755)
    else:
        helper.rename(helper.with_suffix(".txt"))
    git(repository, "add", ".")
    git(
        repository,
        "-c",
        "user.name=FrankieBiz",
        "-c",
        "user.email=frankabisignano@gmail.com",
        "-c",
        "commit.gpgSign=false",
        "commit",
        "--quiet",
        "-m",
        "Add rejected fixture entry",
    )
    manifest["source_commit"] = git(repository, "rev-parse", "HEAD")
    manager = SnapshotManager(tmp_path / "data", repository)
    job = str(uuid4())
    with pytest.raises(PatchPolicyError, match="ordinary Python"):
        await manager.create(job, manifest)
    assert len(git(repository, "worktree", "list", "--porcelain").split("worktree ")) == 2
    assert not list((manager._job_root(job) / "snapshots").iterdir())
    with pytest.raises(ValueError, match="ordinary Python"):
        ApplicationExporter(repository, manifest["source_commit"], tmp_path / "trials")


@pytest.mark.parametrize("location", ["data", "runtime", "worktrees", "snapshots"])
async def test_snapshot_creation_rejects_symlinked_owned_directories(
    tmp_path: Path, seed: tuple[Path, dict[str, Any]], location: str
) -> None:
    repository, manifest = seed
    data, outside = tmp_path / "data", tmp_path / "outside"
    outside.mkdir()
    manager = SnapshotManager(data, repository)
    job = str(uuid4())
    root = data if location == "data" else data / "jobs" / job / "runtime"
    if location in {"worktrees", "snapshots"}:
        root /= location
    root.parent.mkdir(parents=True, exist_ok=True)
    root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="[Ss]ymlink"):
        await manager.create(job, manifest)
    assert not list(outside.iterdir())
    assert len(git(repository, "worktree", "list", "--porcelain").split("worktree ")) == 2


async def test_cleanup_validates_every_worktree_before_deleting_any(
    tmp_path: Path, seed: tuple[Path, dict[str, Any]]
) -> None:
    repository, manifest = seed
    manager = SnapshotManager(tmp_path / "data", repository)
    job = str(uuid4())
    snapshot = await manager.create(job, manifest)
    unexpected = snapshot.worktree.parent / "not-a-generation"
    unexpected.mkdir()
    with pytest.raises(ValueError):
        await manager.cleanup(job)
    assert snapshot.worktree.exists() and snapshot.path.exists()
    unexpected.rmdir()
    await manager.cleanup(job)


async def test_cleanup_handles_readonly_generation_parent(
    tmp_path: Path, seed: tuple[Path, dict[str, Any]]
) -> None:
    repository, manifest = seed
    manager = SnapshotManager(tmp_path / "data", repository)
    job = str(uuid4())
    snapshot = await manager.create(job, manifest)
    snapshot.worktree.parent.chmod(0o555)
    await manager.cleanup(job)
    assert not manager._job_root(job).exists()


async def test_failed_worktree_disposal_does_not_leave_a_partial_export(
    tmp_path: Path, seed: tuple[Path, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, manifest = seed
    manager = SnapshotManager(tmp_path / "data", repository)
    job = str(uuid4())
    original_git = manager._git

    async def failing_git(root: Path, *args: str, data: bytes | None = None) -> bytes:
        if args[:2] == ("worktree", "remove"):
            raise OSError("injected disposal failure")
        result = await original_git(root, *args, data=data)
        if args[0] == "checkout-index":
            raise OSError("injected export failure")
        return result

    monkeypatch.setattr(manager, "_git", failing_git)
    with pytest.raises(OSError, match="export failure") as caught:
        await manager.create(job, manifest)
    assert any("disposal failure" in note for note in caught.value.__notes__)
    assert not list((manager._job_root(job) / "snapshots").iterdir())
    monkeypatch.setattr(manager, "_git", original_git)
    await manager.cleanup(job)
    assert len(git(repository, "worktree", "list", "--porcelain").split("worktree ")) == 2


@pytest.mark.parametrize("missing", ["gitfile", "directory"])
async def test_interrupted_registration_is_removed_without_global_pruning(
    tmp_path: Path,
    seed: tuple[Path, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
) -> None:
    repository, manifest = seed
    manager = SnapshotManager(tmp_path / "data", repository)
    job = str(uuid4())
    original_git = manager._git

    async def interrupted_git(root: Path, *args: str, data: bytes | None = None) -> bytes:
        result = await original_git(root, *args, data=data)
        if args[:2] == ("worktree", "add"):
            worktree = Path(args[-2])
            if missing == "gitfile":
                (worktree / ".git").unlink()
            else:
                shutil.rmtree(worktree)
            raise asyncio.CancelledError
        return result

    monkeypatch.setattr(manager, "_git", interrupted_git)
    with pytest.raises(asyncio.CancelledError):
        await manager.create(job, manifest)
    assert len(git(repository, "worktree", "list", "--porcelain").split("worktree ")) == 2


async def test_cleanup_recovers_missing_worktree_without_pruning_another_job(
    tmp_path: Path, seed: tuple[Path, dict[str, Any]]
) -> None:
    repository, manifest = seed
    manager = SnapshotManager(tmp_path / "data", repository)
    jobs = [str(uuid4()), str(uuid4())]
    first = await manager.create(jobs[0], manifest)
    second = await manager.create(jobs[1], manifest)
    shutil.rmtree(first.worktree)
    shutil.rmtree(second.worktree)
    await manager.cleanup(jobs[0])
    listing = git(repository, "worktree", "list", "--porcelain")
    assert str(first.worktree) not in listing
    assert str(second.worktree) in listing
    assert second.path.exists()
    await manager.cleanup(jobs[1])


async def test_snapshot_generation_collision_preserves_existing_snapshot(
    tmp_path: Path, seed: tuple[Path, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, manifest = seed
    manager = SnapshotManager(tmp_path / "data", repository)
    job = str(uuid4())
    generation = uuid4()
    monkeypatch.setattr(snapshots, "uuid4", lambda: generation)
    first = await manager.create(job, manifest)
    with pytest.raises(FileExistsError):
        await manager.create(job, manifest)
    assert first.path.exists() and first.worktree.exists()
    assert (first.path / TARGET_FILE).read_text() == first.source
    await manager.cleanup(job)


@pytest.fixture
def exporter(seed: tuple[Path, dict[str, Any]], tmp_path: Path) -> ApplicationExporter:
    repository, manifest = seed
    return ApplicationExporter(repository, manifest["source_commit"], tmp_path / "trials")


def test_export_collision_does_not_overwrite_existing_trial(
    exporter: ApplicationExporter, monkeypatch: pytest.MonkeyPatch
) -> None:
    generation = uuid4()
    monkeypatch.setattr(evaluation, "uuid4", lambda: generation)
    first = exporter.export("first")
    with pytest.raises(FileExistsError):
        exporter.export("second")
    assert (first / TARGET_FILE).read_text() == "first"


def test_export_failure_removes_partial_tree(
    exporter: ApplicationExporter, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = Path.write_bytes
    count = 0

    def fail_write(path: Path, content: bytes) -> int:
        nonlocal count
        count += 1
        result = original(path, content)
        if count == 2:
            raise OSError("injected disk failure")
        return result

    monkeypatch.setattr(Path, "write_bytes", fail_write)
    with pytest.raises(OSError, match="disk failure"):
        exporter.export("candidate")
    assert not list(exporter.work_root.iterdir())


@pytest.mark.parametrize("name", ["../escape.py", "C:\\escape.py", "/escape.py"])
def test_export_rejects_unsafe_entry_names_and_cleans_partial_tree(
    exporter: ApplicationExporter, name: str
) -> None:
    exporter.files[name] = b"forbidden"
    with pytest.raises(ValueError):
        exporter.export("candidate")
    assert not list(exporter.work_root.iterdir())


def test_exports_keep_git_modes_with_restrictive_umask(
    exporter: ApplicationExporter,
) -> None:
    previous = os.umask(0o077)
    try:
        application = exporter.export("candidate")
    finally:
        os.umask(previous)
    assert stat.S_IMODE(application.stat().st_mode) == 0o700
    assert all(
        stat.S_IMODE((application / name).stat().st_mode) == 0o644 for name in exporter.files
    )


def test_tree_disposal_surfaces_errors_instead_of_ignoring_them(
    exporter: ApplicationExporter, monkeypatch: pytest.MonkeyPatch
) -> None:
    application = exporter.export("candidate")

    def fail(root: Path) -> None:
        raise PermissionError("injected cleanup failure")

    monkeypatch.setattr(shutil, "rmtree", fail)
    with pytest.raises(PermissionError, match="cleanup failure"):
        snapshots.remove_owned_tree(application)
    assert application.exists()


@pytest.mark.parametrize("broken", [False, True])
def test_export_rejects_symlinked_work_root(
    exporter: ApplicationExporter, tmp_path: Path, broken: bool
) -> None:
    outside = tmp_path / "outside"
    if not broken:
        outside.mkdir()
    exporter.work_root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="[Ss]ymlink"):
        exporter.export("candidate")
    assert not outside.exists() if broken else not list(outside.iterdir())


async def test_measure_cancellation_cleans_readonly_trial_and_leaves_other_trial(
    exporter: ApplicationExporter,
) -> None:
    other = exporter.export("other trial")
    entered = asyncio.Event()
    applications: list[Path] = []

    class Launcher:
        kind = "test"

        @asynccontextmanager
        async def session(self, application: Path) -> AsyncGenerator[BackendSession]:
            applications.append(application)
            (application / TARGET_FILE).chmod(0o444)
            (application / TARGET_FILE).parent.chmod(0o555)
            entered.set()
            await asyncio.Event().wait()
            yield  # type: ignore[misc]

    task = asyncio.create_task(measure(Launcher(), exporter, "cancelled trial", {}))
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not applications[0].exists()
    assert (other / TARGET_FILE).read_text() == "other trial"


async def test_overlapping_measurements_are_independent(
    exporter: ApplicationExporter, monkeypatch: pytest.MonkeyPatch
) -> None:
    applications: list[Path] = []
    ready = asyncio.Event()

    class Session:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(201)), base_url="http://trial"
        )
        logs: Callable[[], str] = staticmethod(lambda: "")

    class Launcher:
        kind = "test"

        @asynccontextmanager
        async def session(self, application: Path) -> AsyncGenerator[BackendSession]:
            applications.append(application)
            if len(applications) == 2:
                ready.set()
            await asyncio.wait_for(ready.wait(), 5)
            source = (application / TARGET_FILE).read_text()
            await asyncio.sleep(0)
            assert (application / TARGET_FILE).read_text() == source
            yield Session()

    async def regression(client: httpx.AsyncClient) -> list[Any]:
        return []

    monkeypatch.setattr(evaluation, "regression", regression)
    try:
        results = await asyncio.gather(
            measure(Launcher(), exporter, "trial one", {}),
            measure(Launcher(), exporter, "trial two", {}),
        )
    finally:
        await Session.client.aclose()
    assert [item.symptom_status for item in results] == [201, 201]
    assert len(set(applications)) == 2
    assert not any(path.exists() for path in applications)
