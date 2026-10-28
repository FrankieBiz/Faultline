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
from typing import Literal, TypedDict

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = "fixtures/evaluation/cases.json"
TARGET_FILE = "apps/buggyshop-backend/app/routes/checkout.py"
ALLOWED_ROOTS = frozenset({("fixtures", "evaluation"), ("fixtures", "seeds")})


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


def load_corpus(root: Path = REPOSITORY_ROOT) -> Corpus:
    """Return the corpus only when every recorded hash matches the file bytes."""
    loaded: Corpus = json.loads((root / CASES_PATH).read_text(encoding="utf-8"))
    if loaded.get("schema_version") != "1.0" or loaded.get("target_file") != TARGET_FILE:
        raise ValueError("Unsupported evaluation corpus metadata")
    identifiers = [case["id"] for case in [*loaded["holdout"], *loaded["patches"]]]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Evaluation case identifiers must be unique")
    for case in [*loaded["holdout"], *loaded["patches"]]:
        if hashlib.sha256(_read(root, case["path"])).hexdigest() != case["sha256"]:
            raise ValueError(f"Evaluation case bytes differ from the corpus: {case['id']}")
    return loaded


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
