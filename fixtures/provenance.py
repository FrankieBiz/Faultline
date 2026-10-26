"""Generate and verify SHA-256 provenance for the controlled checkout fixture.

Run ``python -m fixtures.provenance --write`` from the repository root. Once the
source is committed, add ``--source-commit HEAD`` to pin the containing revision.
Verification reads source bytes and Git objects, never imports checkout code,
and never modifies the live route or either reference snapshot.
"""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Literal, NotRequired, TypedDict

from shared.config import REGISTRY

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TARGET_FILE = "apps/buggyshop-backend/app/routes/checkout.py"
SCENARIO_ID = "scripted_checkout_repair"
FIXTURE_PATHS: dict[str, str] = {
    "healthy": "fixtures/seeds/checkout_healthy.py",
    "seeded": "fixtures/seeds/checkout_seeded.py",
}


class FixtureSource(TypedDict):
    """Content address and byte size of one trusted reference file."""

    path: str
    sha256: str
    size_bytes: int


class FixtureManifest(TypedDict):
    """Versioned source identities and the explicit fixture business policy."""

    schema_version: str
    fixture_version: str
    scenario_version: str
    scenario_id: str
    target_file: str
    error_fingerprint: str
    currency: Literal["USD"]
    discount_rounding: str
    coupon_percentages: dict[str, int]
    fixtures: dict[str, FixtureSource]
    source_commit: NotRequired[str]


def file_sha256(path: Path) -> str:
    """Hash exact file bytes without newline or encoding normalization."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_bytes(root: Path, relative_path: str) -> bytes:
    """Read an ordinary contained source file, rejecting symlinked parents."""
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Source path is not repository-relative: {relative_path}")
    candidate = root
    for part in relative.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError(f"Symlinked fixture source: {relative_path}")
    if not candidate.is_file() or not candidate.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Missing or uncontained fixture source: {relative_path}")
    return candidate.read_bytes()


def _git(root: Path, *arguments: str) -> bytes:
    """Read Git metadata with fixed argument boundaries and a bounded wait."""
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        timeout=10,
    ).stdout


def build_manifest(
    repository_root: Path = REPOSITORY_ROOT, *, source_commit: str | None = None
) -> FixtureManifest:
    """Describe healthy and seeded bytes and optionally bind a real revision.

    A revision is recorded only after both snapshots and the seeded live route
    are proven to match that commit. No fabricated or future commit IDs occur.
    """
    sources: dict[str, FixtureSource] = {}
    for name, relative_path in FIXTURE_PATHS.items():
        source = _source_bytes(repository_root, relative_path)
        sources[name] = {
            "path": relative_path,
            "sha256": hashlib.sha256(source).hexdigest(),
            "size_bytes": len(source),
        }
    live_source = _source_bytes(repository_root, TARGET_FILE)
    if hashlib.sha256(live_source).hexdigest() != sources["seeded"]["sha256"]:
        raise ValueError("Live checkout route does not match the seeded reference")

    manifest: FixtureManifest = {
        "schema_version": "1.0",
        "fixture_version": "checkout-optional-coupon-v1",
        "scenario_version": "1.0",
        "scenario_id": SCENARIO_ID,
        "target_file": TARGET_FILE,
        "error_fingerprint": REGISTRY[SCENARIO_ID].error_fingerprint,
        "currency": "USD",
        "discount_rounding": "floor to whole cents using integer arithmetic",
        "coupon_percentages": {"TENOFF": 10, "FIFTEEN": 15},
        "fixtures": sources,
    }
    if source_commit is not None:
        revision = (
            _git(
                repository_root,
                "rev-parse",
                "--verify",
                "--end-of-options",
                f"{source_commit}^{{commit}}",
            )
            .decode("ascii")
            .strip()
        )
        for relative_path in [*FIXTURE_PATHS.values(), TARGET_FILE]:
            committed = _git(repository_root, "show", f"{revision}:{relative_path}")
            if committed != _source_bytes(repository_root, relative_path):
                raise ValueError(f"Source differs from pinned commit: {relative_path}")
        manifest["source_commit"] = revision
    return manifest


def verify_manifest(
    repository_root: Path = REPOSITORY_ROOT, manifest_path: Path | None = None
) -> FixtureManifest:
    """Fail closed on altered metadata, source, live seed, or pinned Git bytes."""
    path = (
        manifest_path if manifest_path is not None else repository_root / "fixtures/manifest.json"
    )
    loaded: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("Fixture manifest must be a JSON object")
    source_commit = loaded.get("source_commit")
    if "source_commit" in loaded and not isinstance(source_commit, str):
        raise ValueError("Pinned source commit must be a string")
    if isinstance(source_commit, str) and (
        len(source_commit) != 40 or any(char not in "0123456789abcdef" for char in source_commit)
    ):
        raise ValueError("Pinned source commit must be a full Git SHA-1")
    expected = build_manifest(repository_root, source_commit=source_commit)
    if loaded != expected:
        raise ValueError("Fixture manifest does not match trusted source bytes or metadata")
    return expected


def main() -> None:
    """Write deterministic provenance or verify the existing manifest."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Generate fixtures/manifest.json")
    parser.add_argument("--source-commit", help="Pin a commit that contains these exact sources")
    arguments = parser.parse_args()
    if arguments.source_commit and not arguments.write:
        parser.error("--source-commit requires --write")
    if arguments.write:
        manifest = build_manifest(source_commit=arguments.source_commit)
        (REPOSITORY_ROOT / "fixtures/manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    else:
        verify_manifest()
    print("Fixture provenance verified")


if __name__ == "__main__":
    main()
