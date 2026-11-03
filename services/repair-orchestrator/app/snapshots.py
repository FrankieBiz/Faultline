"""Disposable seed worktrees and staged-index exports; never execute Python."""

import asyncio
import hashlib
import json
import os
import shutil
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from weakref import WeakValueDictionary

from app.policy import TARGET_FILE, PatchPolicy, PatchPolicyError
from app.portable import normalize_relpath

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
BACKEND_APP = "apps/buggyshop-backend/app/"


def contained_path(root: Path, relative: str) -> Path:
    """Resolve an ordinary contained path without following symlink components.

    ``relative`` is normalized to forward slashes first, so a Windows-style
    separator, drive letter, or UNC prefix is rejected identically on every host
    instead of being treated as a literal filename on POSIX.
    """
    path = Path(normalize_relpath(relative))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("Path must be a nonempty contained relative path")
    if any(parent.is_symlink() for parent in (root, *root.parents)):
        raise ValueError("Symlinked paths are forbidden")
    candidate = root
    for part in path.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError("Symlinked paths are forbidden")
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise ValueError("Path escapes its owned directory")
    return candidate


def make_tree_writable(root: Path) -> None:
    """Permit disposal of owned directories without chmod through symlinks.

    File modes are left alone on POSIX: deletion needs writable directories,
    not writable files. Windows also requires clearing the read-only file bit.
    This is only for disposable trees, never the repository or retained evidence.
    """

    def writable(path: Path) -> None:
        metadata = path.lstat()
        if stat.S_ISDIR(metadata.st_mode):
            path.chmod(stat.S_IMODE(metadata.st_mode) | stat.S_IRWXU)
        elif os.name == "nt" and stat.S_ISREG(metadata.st_mode):
            path.chmod(stat.S_IMODE(metadata.st_mode) | stat.S_IWUSR)

    writable(root)
    for directory, directories, files in os.walk(root, followlinks=False):
        for name in directories:
            writable(Path(directory) / name)
        if os.name == "nt":
            for name in files:
                writable(Path(directory) / name)


def remove_owned_tree(root: Path) -> None:
    """Remove a disposable tree, including read-only entries and dangling links.

    Reject a substituted root or ancestor; links *inside* the tree are unlinked
    by rmtree without visiting their targets. Missing trees make cleanup idempotent.
    """
    contained_path(root.parent, root.name)
    if not root.exists():
        return
    make_tree_writable(root)
    shutil.rmtree(root)


@dataclass(frozen=True)
class Snapshot:
    """Content-addressed export and the exact seeded/current target bytes."""

    path: Path
    worktree: Path
    generation_id: str
    sha256: str
    source: str
    source_sha256: str
    seed_commit: str


class SnapshotManager:
    """Create fresh detached attempts and export only trusted application paths."""

    def __init__(self, data_root: Path, repository_root: Path = REPOSITORY_ROOT) -> None:
        self.data_root = data_root.absolute()
        self.repository_root = repository_root.resolve()
        self._locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()

    def _job_lock(self, job_id: str) -> asyncio.Lock:
        """Serialize creation and disposal for one job within this manager."""
        lock = self._locks.get(job_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[job_id] = lock
        return lock

    async def _git(self, root: Path, *args: str, data: bytes | None = None) -> bytes:
        process = await asyncio.create_subprocess_exec(
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
            "-C",
            str(root),
            *args,
            stdin=asyncio.subprocess.PIPE if data is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(data), timeout=5)
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        if process.returncode != 0:
            err_msg = stderr.decode(errors="replace").strip()
            detail = f": {err_msg}" if err_msg else ""
            raise PatchPolicyError(f"Git rejected the disposable snapshot operation{detail}")
        return stdout

    async def manifest(self) -> Mapping[str, Any]:
        """Verify pinned source identities before any baseline preparation."""
        from fixtures.provenance import verify_manifest

        return await asyncio.to_thread(verify_manifest, self.repository_root)

    def _job_root(self, job_id: str) -> Path:
        if str(UUID(job_id)) != job_id:
            raise ValueError("Job directory requires a canonical server UUID")
        return contained_path(self.data_root, f"jobs/{job_id}/runtime")

    async def create(
        self,
        job_id: str,
        manifest: Mapping[str, Any],
        *,
        diff: str | None = None,
        base_sha256: str | None = None,
    ) -> Snapshot:
        """Apply a validated patch in a fresh seed and export the staged index."""
        async with self._job_lock(job_id):
            return await self._create(job_id, manifest, diff=diff, base_sha256=base_sha256)

    async def _create(
        self,
        job_id: str,
        manifest: Mapping[str, Any],
        *,
        diff: str | None,
        base_sha256: str | None,
    ) -> Snapshot:
        seed_commit = manifest.get("source_commit")
        if seed_commit is None:
            raise PatchPolicyError("A pinned seed commit is required")
        generation = str(uuid4())
        owned = self._job_root(job_id)
        owned.mkdir(parents=True, exist_ok=True)
        worktree = contained_path(owned, f"worktrees/{generation}")
        worktree.parent.mkdir(parents=True, exist_ok=True)
        exported = contained_path(owned, f"snapshots/{generation}")
        # Exclusive reservations prevent even a generation collision from
        # overwriting or cleaning up an existing trial.
        exported.mkdir(parents=True, exist_ok=False, mode=0o700)
        worktree_owned = False
        try:
            worktree.mkdir(mode=0o700)
            worktree_owned = True
            return await self._populate(
                worktree, exported, generation, seed_commit, manifest, diff, base_sha256
            )
        except BaseException as error:
            if worktree_owned:
                try:
                    await self._remove_worktree(worktree)
                except Exception as cleanup_error:
                    error.add_note(f"Worktree cleanup failed: {cleanup_error}")
            try:
                remove_owned_tree(exported)
            except Exception as cleanup_error:
                error.add_note(f"Snapshot cleanup failed: {cleanup_error}")
            raise

    async def _populate(
        self,
        worktree: Path,
        exported: Path,
        generation: str,
        seed_commit: str,
        manifest: Mapping[str, Any],
        diff: str | None,
        base_sha256: str | None,
    ) -> Snapshot:
        await self._git(
            self.repository_root, "worktree", "add", "--detach", str(worktree), seed_commit
        )
        if await self._git(worktree, "status", "--porcelain", "--untracked-files=all"):
            raise PatchPolicyError("Fresh seed worktree is not clean")
        target = contained_path(worktree, TARGET_FILE)
        if not target.is_file():
            raise PatchPolicyError("Missing existing repair target")
        source = target.read_text(encoding="utf-8")
        seeded_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        if seeded_hash != manifest["fixtures"]["seeded"]["sha256"]:
            raise PatchPolicyError("Seed source hash differs from the manifest")
        if diff is not None:
            if not diff.endswith("\n"):
                diff = diff + "\n"
            result = PatchPolicy().validate(diff, source, base_sha256=base_sha256)
            if not result.is_valid:
                raise PatchPolicyError(result.error_message or "Patch failed policy")
            # Recheck immediately before Git applicability and staged mutation.
            if hashlib.sha256(target.read_bytes()).hexdigest() != base_sha256:
                raise PatchPolicyError("Proposal base hash is stale")
            await self._git(
                worktree, "apply", "--unidiff-zero", "--check", "--index", data=diff.encode()
            )
            await self._git(worktree, "apply", "--unidiff-zero", "--index", data=diff.encode())
            changed = await self._git(worktree, "diff", "--cached", "--name-only", "-z")
            if changed != TARGET_FILE.encode() + b"\x00":
                raise PatchPolicyError("Staged candidate changed an unexpected file set")
            if await self._git(worktree, "diff", "--name-only", "-z"):
                raise PatchPolicyError("Candidate worktree diverges from its staged index")
        staged = await self._git(worktree, "ls-files", "--stage", "-z", "--", BACKEND_APP)
        paths: list[str] = []
        for entry in staged.split(b"\x00"):
            if not entry:
                continue
            metadata, name = entry.decode("utf-8").split("\t", 1)
            if metadata.split()[0] != "100644" or not name.endswith(".py"):
                raise PatchPolicyError(
                    "Candidate export requires ordinary Python application files"
                )
            if not contained_path(worktree, name).is_file():
                raise PatchPolicyError("Candidate export contains an invalid path")
            paths.append(name)
        if TARGET_FILE not in paths:
            raise PatchPolicyError("Candidate export omits the repair target")
        await self._git(worktree, "checkout-index", f"--prefix={exported}/", "--", *sorted(paths))
        entries: list[tuple[str, str, str]] = []
        for name in sorted(paths):
            path = contained_path(exported, name)
            # Restore the accepted Git mode independently of the host umask.
            path.chmod(0o644)
            entries.append((name, "100644", hashlib.sha256(path.read_bytes()).hexdigest()))
        source_bytes = contained_path(exported, TARGET_FILE).read_bytes()
        if len(source_bytes) > 32 * 1024:
            raise PatchPolicyError("Exported target exceeds the policy size cap")
        snapshot_hash = hashlib.sha256(
            json.dumps(entries, separators=(",", ":")).encode()
        ).hexdigest()
        return Snapshot(
            exported,
            worktree,
            generation,
            snapshot_hash,
            source_bytes.decode("utf-8"),
            hashlib.sha256(source_bytes).hexdigest(),
            seed_commit,
        )

    async def cleanup(self, job_id: str) -> None:
        """Dispose only UUID-owned worktrees/snapshots, retaining job evidence."""
        async with self._job_lock(job_id):
            await self._cleanup(job_id)

    async def _remove_worktree(self, path: Path) -> None:
        contained_path(path.parent, path.name)
        gitfile = path / ".git"
        if path.exists() and gitfile.is_file() and not gitfile.is_symlink():
            make_tree_writable(path)
            await self._git(
                self.repository_root, "worktree", "remove", "--force", "--force", str(path)
            )
            return
        # Interrupted `worktree add` can register a path before writing .git.
        # Git can unregister a missing directory, but refuses an existing tree
        # with a missing gitfile. Dispose our reservation before unregistering.
        registered = path.resolve() in await self._registered_worktrees()
        remove_owned_tree(path)
        if registered:
            await self._git(
                self.repository_root, "worktree", "remove", "--force", "--force", str(path)
            )

    async def _registered_worktrees(self) -> set[Path]:
        listing = await self._git(self.repository_root, "worktree", "list", "--porcelain", "-z")
        return {
            Path(os.fsdecode(field.removeprefix(b"worktree ")))
            for field in listing.split(b"\x00")
            if field.startswith(b"worktree ")
        }

    async def _cleanup(self, job_id: str) -> None:
        owned = self._job_root(job_id)
        if owned.exists():
            make_tree_writable(owned)
        worktrees = contained_path(owned, "worktrees")
        paths = set(worktrees.iterdir()) if worktrees.exists() else set()
        # Recover missing directories too, without globally pruning a different
        # job's interrupted worktree from this shared repository.
        paths.update(
            path
            for path in await self._registered_worktrees()
            if path.parent == worktrees.resolve()
        )
        # Validate the complete set before deleting any generation.
        for path in paths:
            if path.is_symlink() or str(UUID(path.name)) != path.name:
                raise ValueError("Unexpected path in owned worktree directory")
        for path in paths:
            await self._remove_worktree(path)
        remove_owned_tree(owned)
