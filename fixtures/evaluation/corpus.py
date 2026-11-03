"""Hash-pinned evaluation corpus: unfamiliar defects and candidate repair patches.

Run ``python -m fixtures.evaluation.corpus --write`` from the repository root
after authoring a case. Verification reads bytes only; it never imports or
executes a variant. Expected failures record what the independent oracle
measured when the case was authored, so drift is reported, not hidden.
"""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Literal, TypedDict, cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = "fixtures/evaluation/cases.json"
TARGET_FILE = "apps/buggyshop-backend/app/routes/checkout.py"
ALLOWED_ROOTS = frozenset({("fixtures", "evaluation"), ("fixtures", "seeds")})
PATCH_KINDS = frozenset({"correct", "wrong", "out_of_policy"})


class HoldoutCase(TypedDict):
    """A complete checkout variant containing one authored contract defect."""

    id: str
    title: str
    defect_class: str
    path: str
    sha256: str
    expected_failures: list[str]


class PatchCase(TypedDict):
    """A candidate diff against the registered seed and the gate expected to decide it."""

    id: str
    title: str
    kind: Literal["correct", "wrong", "out_of_policy"]
    path: str
    sha256: str
    expected_failures: list[str]


class Corpus(TypedDict):
    """Versioned case list; every file is content-addressed."""

    schema_version: Literal["1.0"]
    corpus_version: str
    target_file: str
    incident_request: dict[str, object]
    holdout: list[HoldoutCase]
    patches: list[PatchCase]


def _read(root: Path, relative: str) -> bytes:
    """Read an ordinary evaluation or registered-seed file, never other sources."""
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or path.parts[:2] not in ALLOWED_ROOTS:
        raise ValueError(f"Corpus path is outside the trusted fixture directories: {relative}")
    candidate = root / path
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError(f"Missing or symlinked corpus file: {relative}")
    return candidate.read_bytes()


def _require_string(owner: str, field: str, value: object) -> str:
    """Reject a missing, non-string, or blank required metadata field."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"Evaluation corpus {owner} {field} must be a non-empty string")
    return value


def _require_failure_ids(owner: str, value: object) -> None:
    """Reject an ``expected_failures`` field that is not a list of strings."""
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"Evaluation corpus {owner} expected_failures must be a list of strings")


def load_corpus(root: Path = REPOSITORY_ROOT) -> Corpus:
    """Return the corpus only when its shape is sound and every hash matches.

    The metadata is content-addressed, not trusted: before a single byte is
    read from disk, every case identifier, path, digest, expected-failure list,
    patch kind, and the incident request are validated so a malformed corpus
    fails closed with a clear ``ValueError`` instead of a deep KeyError,
    TypeError, or a silently wrong trial record.
    """
    loaded: object = json.loads((root / CASES_PATH).read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("Evaluation corpus must be a JSON object")
    if loaded.get("schema_version") != "1.0" or loaded.get("target_file") != TARGET_FILE:
        raise ValueError("Unsupported evaluation corpus metadata")
    holdout, patches = loaded.get("holdout"), loaded.get("patches")
    if not isinstance(holdout, list) or not isinstance(patches, list):
        raise ValueError("Evaluation corpus must list holdout and patch cases")
    incident = loaded.get("incident_request")
    if not isinstance(incident, dict):
        raise ValueError("Evaluation corpus incident_request must be a JSON object")
    if not isinstance(incident.get("items"), list):
        raise ValueError("Evaluation corpus incident_request requires an items list")
    for case in [*holdout, *patches]:
        if not isinstance(case, dict):
            raise ValueError("Every evaluation case must be a JSON object")
        case_id = _require_string("case", "id", case.get("id"))
        _require_string(case_id, "path", case.get("path"))
        _require_string(case_id, "sha256", case.get("sha256"))
        _require_failure_ids(case_id, case.get("expected_failures"))
    for case in holdout:
        _require_string(case["id"], "defect_class", case.get("defect_class"))
    for case in patches:
        kind = case.get("kind")
        if not isinstance(kind, str) or kind not in PATCH_KINDS:
            raise ValueError(f"Evaluation corpus patch kind is unknown for case {case.get('id')!r}")
    identifiers = [case["id"] for case in [*holdout, *patches]]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Evaluation case identifiers must be unique")
    for case in [*holdout, *patches]:
        if hashlib.sha256(_read(root, case["path"])).hexdigest() != case["sha256"]:
            raise ValueError(f"Evaluation case bytes differ from the corpus: {case['id']}")
    return cast(Corpus, loaded)


def case_bytes(case: HoldoutCase | PatchCase, root: Path = REPOSITORY_ROOT) -> bytes:
    """Read one case and recheck its content address immediately before use."""
    content = _read(root, case["path"])
    if hashlib.sha256(content).hexdigest() != case["sha256"]:
        raise ValueError(f"Evaluation case bytes changed: {case['id']}")
    return content


def write_hashes(root: Path = REPOSITORY_ROOT) -> None:
    """Refresh content addresses after deliberate authoring; metadata is unchanged."""
    path = root / CASES_PATH
    loaded: Corpus = json.loads(path.read_text(encoding="utf-8"))
    for case in [*loaded["holdout"], *loaded["patches"]]:
        case["sha256"] = hashlib.sha256(_read(root, case["path"])).hexdigest()
    path.write_text(json.dumps(loaded, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    """Verify the corpus or deliberately refresh its hashes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Refresh recorded SHA-256 values")
    if parser.parse_args().write:
        write_hashes()
    corpus = load_corpus()
    print(
        f"Evaluation corpus verified: {len(corpus['holdout'])} holdout defects, "
        f"{len(corpus['patches'])} candidate patches"
    )


if __name__ == "__main__":
    main()
