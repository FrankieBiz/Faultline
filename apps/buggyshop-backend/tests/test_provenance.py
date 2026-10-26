"""Check exact fixture bytes and fail closed on stale or modified provenance."""

import json
from pathlib import Path

import pytest

from fixtures.provenance import (
    FIXTURE_PATHS,
    REPOSITORY_ROOT,
    TARGET_FILE,
    build_manifest,
    file_sha256,
    verify_manifest,
)


def copy_fixture_tree(destination: Path) -> None:
    """Copy only trusted source snapshots and the runtime target for tamper tests."""
    for relative_path in [*FIXTURE_PATHS.values(), TARGET_FILE]:
        path = destination / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((REPOSITORY_ROOT / relative_path).read_bytes())
    manifest = build_manifest(destination)
    (destination / "fixtures/manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_committed_manifest_and_live_seed_match() -> None:
    manifest = verify_manifest()
    for source in manifest["fixtures"].values():
        assert len(source["sha256"]) == 64
        assert file_sha256(REPOSITORY_ROOT / source["path"]) == source["sha256"]
    assert file_sha256(REPOSITORY_ROOT / TARGET_FILE) == manifest["fixtures"]["seeded"]["sha256"]
    assert manifest["fixtures"]["healthy"]["sha256"] != manifest["fixtures"]["seeded"]["sha256"]


def test_seed_changes_only_optional_discount_lookup() -> None:
    healthy = (REPOSITORY_ROOT / FIXTURE_PATHS["healthy"]).read_bytes()
    seeded = (REPOSITORY_ROOT / FIXTURE_PATHS["seeded"]).read_bytes()
    assert (
        healthy.replace(b"discounts.get(coupon_code, 0)", b"discounts.get(coupon_code)") == seeded
    )
    compile(healthy, FIXTURE_PATHS["healthy"], "exec")
    compile(seeded, FIXTURE_PATHS["seeded"], "exec")


@pytest.mark.parametrize("name", ["healthy", "seeded"])
def test_altered_reference_fails_provenance(tmp_path: Path, name: str) -> None:
    copy_fixture_tree(tmp_path)
    path = tmp_path / FIXTURE_PATHS[name]
    path.write_bytes(path.read_bytes() + b"\n# changed bytes\n")
    with pytest.raises(ValueError):
        verify_manifest(tmp_path)


def test_changed_live_route_fails_provenance(tmp_path: Path) -> None:
    copy_fixture_tree(tmp_path)
    (tmp_path / TARGET_FILE).write_bytes((tmp_path / FIXTURE_PATHS["healthy"]).read_bytes())
    with pytest.raises(ValueError, match="does not match the seeded"):
        verify_manifest(tmp_path)


def test_changed_metadata_fails_provenance(tmp_path: Path) -> None:
    copy_fixture_tree(tmp_path)
    path = tmp_path / "fixtures/manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["coupon_percentages"]["TENOFF"] = 99
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match trusted"):
        verify_manifest(tmp_path)


@pytest.mark.parametrize("revision", [None, 1, "HEAD", "--help", "a" * 39])
def test_invalid_pinned_revision_is_rejected(tmp_path: Path, revision: object) -> None:
    copy_fixture_tree(tmp_path)
    path = tmp_path / "fixtures/manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["source_commit"] = revision
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="Pinned source commit"):
        verify_manifest(tmp_path)


def test_symlinked_fixture_is_rejected(tmp_path: Path) -> None:
    copy_fixture_tree(tmp_path)
    path = tmp_path / FIXTURE_PATHS["healthy"]
    other_path = tmp_path / "reference.py"
    path.rename(other_path)
    path.symlink_to(other_path)
    with pytest.raises(ValueError, match="Symlinked fixture"):
        verify_manifest(tmp_path)
