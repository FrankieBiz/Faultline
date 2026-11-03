"""Contrarian fuzzing of the hash-pinned evaluation corpus and its fail-closed gate.

The corpus is content-addressed but *not* trusted: ``load_corpus`` is the single
entry point that both the ``holdout`` and ``patches`` suites read before any
backend starts or any trial record is checkpointed. This file throws hostile
metadata and hostile patch files at that boundary and asserts four properties:

1. Tampered, malformed, or missing SHA-256 digests fail closed for *every* case
   in both suites (never a silent pass, never a deep ``TypeError``).
2. Paths that traverse directories, point outside the trusted fixture roots,
   name a non-existent file, or are symlinks are rejected before a byte is read.
3. Holdout cases with a non-string defect id, a non-``list[str]``
   ``expected_failures``, a missing/invalid ``incident_request``, or an unknown
   patch ``kind`` fail closed with a clear ``ValueError`` instead of a KeyError,
   an unhashable-id ``TypeError``, or a silently wrong ``matches_corpus``.
4. Patch files whose unified-diff headers are tampered are rejected by the
   independent policy gate even when their digest is re-pinned to match, and a
   malformed corpus aborts ``run_evaluation`` *before* any checkpoint, work
   tree, or ledger is written.

No backend, sandbox, or provider is launched; corpus integrity and policy are
verified directly.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from test_evaluation import HostLauncher

from app.evaluation import run_evaluation
from app.model_adapter import MetaRepairAdapter, ModelSettings
from app.policy import TARGET_FILE, PatchPolicy, PatchPolicyError, parse_unified_diff
from app.snapshots import REPOSITORY_ROOT
from fixtures.evaluation.corpus import CASES_PATH, case_bytes, load_corpus

SEEDED_PATH = "fixtures/seeds/checkout_seeded.py"


def _corpus_copy(tmp_path: Path) -> Path:
    """Copy ``cases.json`` and every referenced file into ``tmp_path`` as a repo root."""
    cases = json.loads((REPOSITORY_ROOT / CASES_PATH).read_text(encoding="utf-8"))
    for case in [*cases["holdout"], *cases["patches"]]:
        source = REPOSITORY_ROOT / case["path"]
        destination = tmp_path / case["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    (tmp_path / CASES_PATH).write_text(json.dumps(cases, indent=2) + "\n", encoding="utf-8")
    return tmp_path


def _mutate(tmp_path: Path, mutate: Callable[[dict[str, Any]], None]) -> Path:
    """Copy a fresh corpus, apply ``mutate`` to the JSON, and return the repo root."""
    root = _corpus_copy(tmp_path)
    cases = json.loads((root / CASES_PATH).read_text(encoding="utf-8"))
    mutate(cases)
    (root / CASES_PATH).write_text(json.dumps(cases, indent=2) + "\n", encoding="utf-8")
    return root


def test_untampered_copy_loads_identically(tmp_path: Path) -> None:
    assert load_corpus(_corpus_copy(tmp_path)) == load_corpus()


# --- 1. tampered / malformed SHA-256 digests ----------------------------------


@pytest.mark.parametrize(
    "bad_digest",
    [
        "0" * 64,  # valid-length but wrong content
        "f" * 63,  # one digit short
        "f" * 65,  # one digit long
        "",  # empty
        "not-a-hex-digest",
        "Z" * 64,  # non-hex alphabet
        "a" * 64,  # wrong content, valid hex
        12345,  # non-string
        None,  # missing
    ],
)
def test_every_case_rejects_tampered_or_malformed_sha256(tmp_path: Path, bad_digest: Any) -> None:
    root = _corpus_copy(tmp_path)
    cases = json.loads((root / CASES_PATH).read_text(encoding="utf-8"))
    for section in ("holdout", "patches"):
        for index in range(len(cases[section])):
            current = json.loads((root / CASES_PATH).read_text(encoding="utf-8"))
            current[section][index]["sha256"] = bad_digest
            (root / CASES_PATH).write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
            with pytest.raises(ValueError):
                load_corpus(root)


def test_tampered_file_bytes_fail_closed_for_every_case(tmp_path: Path) -> None:
    root = _corpus_copy(tmp_path)
    cases = json.loads((root / CASES_PATH).read_text(encoding="utf-8"))
    for case in [*cases["holdout"], *cases["patches"]]:
        (root / case["path"]).write_text((root / case["path"]).read_text() + " ")
        with pytest.raises(ValueError, match="differ"):
            load_corpus(root)
        # Restore the pristine bytes so the next case mutates exactly one file.
        shutil.copyfile(REPOSITORY_ROOT / case["path"], root / case["path"])


# --- 2. path traversal, non-existent files, and symlinks ----------------------


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",  # absolute
        "../../etc/passwd",  # traversal out of the repository
        "../seeds/checkout_seeded.py",  # traversal into a sibling directory
        "fixtures/evaluation/../../seeds/checkout_seeded.py",  # embedded ``..``
        "fixtures/other/checkout.py",  # outside the trusted fixture roots
        "apps/buggyshop-backend/app/routes/checkout.py",  # real file, wrong root
        "fixtures/evaluation/holdout/does_not_exist.py",  # within a root but absent
        "fixtures",  # a directory, not an ordinary file
    ],
)
def test_malicious_or_missing_patch_paths_fail_closed(tmp_path: Path, path: str) -> None:
    root = _mutate(tmp_path, lambda cases: cases["patches"][0].__setitem__("path", path))
    with pytest.raises(ValueError):
        load_corpus(root)


@pytest.mark.parametrize("bad_path", [123, None, ["a", "b"], {"path": "x"}])
def test_non_string_path_fails_closed(tmp_path: Path, bad_path: Any) -> None:
    root = _mutate(tmp_path, lambda cases: cases["patches"][0].__setitem__("path", bad_path))
    with pytest.raises(ValueError, match="path must be a non-empty string"):
        load_corpus(root)


def test_symlinked_corpus_file_fails_closed(tmp_path: Path) -> None:
    root = _corpus_copy(tmp_path)
    case = json.loads((root / CASES_PATH).read_text())["patches"][0]
    target = root / case["path"]
    target.unlink()
    outside = root / "outside.bin"
    outside.write_bytes(b"outside bytes")
    target.symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        load_corpus(root)


# --- 3. holdout / patch metadata shape ----------------------------------------


@pytest.mark.parametrize("bad_id", [None, 123, "", [], {}])
def test_non_string_or_blank_defect_id_fails_closed(tmp_path: Path, bad_id: Any) -> None:
    root = _mutate(tmp_path, lambda cases: cases["holdout"][0].__setitem__("id", bad_id))
    with pytest.raises(ValueError):
        load_corpus(root)


def test_duplicate_defect_ids_fail_closed(tmp_path: Path) -> None:
    def duplicate(cases: dict[str, Any]) -> None:
        cases["holdout"][1]["id"] = cases["holdout"][0]["id"]

    root = _mutate(tmp_path, duplicate)
    with pytest.raises(ValueError, match="unique"):
        load_corpus(root)


@pytest.mark.parametrize(
    "bad_failures",
    [
        None,
        "regression.missing_coupon",  # a string, not a list
        {"failure": "regression.missing_coupon"},
        123,
        [1, 2],  # list of non-strings
        ["regression.missing_coupon", 7],
        [None],
    ],
)
def test_invalid_expected_failures_fails_closed(tmp_path: Path, bad_failures: Any) -> None:
    root = _mutate(
        tmp_path, lambda cases: cases["holdout"][0].__setitem__("expected_failures", bad_failures)
    )
    with pytest.raises(ValueError, match="expected_failures"):
        load_corpus(root)


@pytest.mark.parametrize("bad_kind", [None, "", "hack", "CORRECT", "correct ", 1, ["correct"]])
def test_unknown_patch_kind_fails_closed(tmp_path: Path, bad_kind: Any) -> None:
    root = _mutate(tmp_path, lambda cases: cases["patches"][0].__setitem__("kind", bad_kind))
    with pytest.raises(ValueError, match="kind"):
        load_corpus(root)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda cases: cases.pop("incident_request"),
        lambda cases: cases.__setitem__("incident_request", None),
        lambda cases: cases.__setitem__("incident_request", "not-a-dict"),
        lambda cases: cases.__setitem__("incident_request", []),
        lambda cases: cases.__setitem__("incident_request", {}),  # missing items
        lambda cases: cases["incident_request"].__setitem__("items", None),
        lambda cases: cases["incident_request"].__setitem__("items", "trail-mug"),
    ],
)
def test_missing_or_malformed_incident_request_fails_closed(
    tmp_path: Path, mutate: Callable[[dict[str, Any]], None]
) -> None:
    root = _mutate(tmp_path, mutate)
    with pytest.raises(ValueError, match="incident_request"):
        load_corpus(root)


def test_non_object_case_fails_closed(tmp_path: Path) -> None:
    root = _mutate(tmp_path, lambda cases: cases["holdout"].__setitem__(0, "not-a-case"))
    with pytest.raises(ValueError, match="JSON object"):
        load_corpus(root)


def test_non_list_suite_fails_closed(tmp_path: Path) -> None:
    root = _mutate(tmp_path, lambda cases: cases.__setitem__("patches", "not-a-list"))
    with pytest.raises(ValueError, match="holdout and patch cases"):
        load_corpus(root)


def test_case_bytes_rechecks_the_hash_after_load(tmp_path: Path) -> None:
    root = _corpus_copy(tmp_path)
    loaded = load_corpus(root)
    case = loaded["patches"][0]
    (root / case["path"]).write_text("tampered after load")
    with pytest.raises(ValueError, match="changed"):
        case_bytes(case, root)


# --- 4. non-unified diff headers in patch files -------------------------------


@pytest.mark.parametrize(
    "hostile",
    [
        f"--- a/other_module.py\n+++ b/{TARGET_FILE}\n@@ -1 +1 @@\n-a\n+b\n",
        f"--- a/{TARGET_FILE}\n+++ b/other_module.py\n@@ -1 +1 @@\n-a\n+b\n",
        "diff --git a/other.py b/other.py\n--- a/other.py\n+++ b/other.py\n",
        "Binary files a/x and b/x differ\n",
        "old mode 100644\nnew mode 100755\n",
        f"+++ b/{TARGET_FILE}\n@@ -1 +1 @@\n-a\n+b\n",  # missing ``---``
        f"--- a/{TARGET_FILE}\n@@ -1 +1 @@\n-a\n+b\n",  # missing ``+++``
        "GIT binary patch\n",
        "diff --git a/x b/x\nrename from x\nrename to y\n",
    ],
)
def test_non_unified_diff_headers_fail_closed(seeded_source: str, hostile: str) -> None:
    """A patch whose header is not a canonical single-file unified diff is rejected."""
    assert not PatchPolicy().validate(hostile, seeded_source).is_valid
    with pytest.raises(PatchPolicyError):
        parse_unified_diff(hostile, seeded_source)


def test_rehashed_header_tamper_is_still_rejected_by_policy(tmp_path: Path) -> None:
    """The policy gate is a second defense the digest layer cannot see through."""
    root = _corpus_copy(tmp_path)
    cases = json.loads((root / CASES_PATH).read_text(encoding="utf-8"))
    patch = cases["patches"][0]
    original = (root / patch["path"]).read_text(encoding="utf-8")
    tampered = original.replace(f"--- a/{TARGET_FILE}", "--- a/other_module.py", 1)
    assert tampered != original
    # Re-pin the digest so ``load_corpus`` cannot catch it; the policy gate must.
    patch["sha256"] = hashlib.sha256(tampered.encode()).hexdigest()
    (root / patch["path"]).write_text(tampered, encoding="utf-8")
    (root / CASES_PATH).write_text(json.dumps(cases, indent=2) + "\n", encoding="utf-8")

    assert load_corpus(root) is not None  # integrity layer sees only matching bytes
    seeded = (REPOSITORY_ROOT / SEEDED_PATH).read_text(encoding="utf-8")
    assert not PatchPolicy().validate(tampered, seeded).is_valid
    with pytest.raises(PatchPolicyError):
        parse_unified_diff(tampered, seeded)


# --- 5. evaluation fails closed before touching trial records or ledgers ------


def _tamper_sha256(cases: dict[str, Any]) -> None:
    cases["patches"][0]["sha256"] = "0" * 64


def _non_string_id(cases: dict[str, Any]) -> None:
    cases["holdout"][0]["id"] = 12345


def _bad_expected_failures(cases: dict[str, Any]) -> None:
    cases["holdout"][0]["expected_failures"] = "regression.missing_coupon"


def _missing_incident(cases: dict[str, Any]) -> None:
    cases.pop("incident_request")


@pytest.mark.parametrize(
    "mutate",
    [_tamper_sha256, _non_string_id, _bad_expected_failures, _missing_incident],
    ids=["sha256", "non-string-id", "expected-failures", "missing-incident"],
)
async def test_run_evaluation_fails_closed_before_checkpoint(
    tmp_path: Path, mutate: Callable[[dict[str, Any]], None]
) -> None:
    """A malformed corpus raises a clear ValueError before any checkpoint or work tree."""
    root = _mutate(tmp_path, mutate)
    checkpoints: list[dict[str, Any]] = []
    with pytest.raises(ValueError):
        await run_evaluation(
            launcher=HostLauncher(),
            adapter=MetaRepairAdapter(ModelSettings()),
            work_root=tmp_path / "work",
            suites={"patches"},
            repository_root=root,
            checkpoint=lambda partial: checkpoints.append(partial),
        )
    assert checkpoints == []
    assert not (tmp_path / "work").exists()
