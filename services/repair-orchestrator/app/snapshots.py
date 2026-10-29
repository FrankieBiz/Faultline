"""Disposable seed worktrees and staged-index exports; never execute Python."""

import asyncio
import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from app.policy import TARGET_FILE, PatchPolicy, PatchPolicyError
from fixtures.provenance import FixtureManifest, verify_manifest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
BACKEND_APP = "apps/buggyshop-backend/app/"


def contained_path(root: Path, relative: str) -> Path:
    """Resolve an ordinary contained path without following symlink components."""
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("Path must be a nonempty contained relative path")
    candidate = root
    for part in path.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError("Symlinked paths are forbidden")
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise ValueError("Path escapes its owned directory")
    return candidate


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
        self.data_root = data_root.resolve()
        self.repository_root = repository_root.resolve()

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

    async def manifest(self) -> FixtureManifest:
        """Verify pinned source identities before any baseline preparation."""
        return await asyncio.to_thread(verify_manifest, self.repository_root)

    def _job_root(self, job_id: str) -> Path:
        if str(UUID(job_id)) != job_id:
            raise ValueError("Job directory requires a canonical server UUID")
        return contained_path(self.data_root, f"jobs/{job_id}/runtime")

    async def create(
        self,
        job_id: str,
        manifest: FixtureManifest,
        *,
        diff: str | None = None,
        base_sha256: str | None = None,
    ) -> Snapshot:
        """Apply a validated patch in a fresh seed and export the staged index."""
        seed_commit = manifest.get("source_commit")
        if seed_commit is None:
            raise PatchPolicyError("A pinned seed commit is required")
        generation = str(uuid4())
        owned = self._job_root(job_id)
        owned.mkdir(parents=True, exist_ok=True)
        worktree = contained_path(owned, f"worktrees/{generation}")
        worktree.parent.mkdir(parents=True, exist_ok=True)
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
        exported = contained_path(owned, f"snapshots/{generation}")
        exported.mkdir(parents=True, exist_ok=False)
        await self._git(worktree, "checkout-index", f"--prefix={exported}/", "--", *sorted(paths))
        entries: list[tuple[str, str, str]] = []
        for name in sorted(paths):
            path = contained_path(exported, name)
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
        owned = self._job_root(job_id)
        worktrees = contained_path(owned, "worktrees")
        if worktrees.exists():
            for path in worktrees.iterdir():
                if path.is_symlink() or str(UUID(path.name)) != path.name:
                    raise ValueError("Unexpected path in owned worktree directory")
                await self._git(self.repository_root, "worktree", "remove", "--force", str(path))
        if owned.exists():
            shutil.rmtree(owned)
