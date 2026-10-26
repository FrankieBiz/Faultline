"""Exact diff application and non-executing syntax/capability policy gates."""

import ast
import difflib
import hashlib

import pytest

from app.model_adapter import deterministic_diff
from app.policy import TARGET_FILE, PatchPolicy, parse_unified_diff, validate_ast


def patch(source: str, candidate: str) -> str:
    return "".join(
        difflib.unified_diff(
            source.splitlines(keepends=True),
            candidate.splitlines(keepends=True),
            fromfile=f"a/{TARGET_FILE}",
            tofile=f"b/{TARGET_FILE}",
        )
    )


def test_fallback_is_exact_single_file_applicable_python(seeded_source: str) -> None:
    diff = deterministic_diff(seeded_source)
    result = PatchPolicy().validate(
        diff, seeded_source, base_sha256=hashlib.sha256(seeded_source.encode()).hexdigest()
    )
    assert result.is_valid and result.syntax_valid and result.ast_safe
    parsed = parse_unified_diff(diff, seeded_source)
    assert len(parsed.hunks) == 1
    assert parsed.target_file == TARGET_FILE
    assert "discounts.get(coupon_code, 0)" in parsed.patched_source
    ast.parse(parsed.patched_source)


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "../checkout.py",
        "app/routes/checkout.py",
        "apps/buggyshop-backend/app/routes/../checkout.py",
        "./apps/buggyshop-backend/app/routes/checkout.py",
        '"apps/buggyshop-backend/app/routes/checkout.py"',
    ],
)
def test_only_canonical_target_is_allowed(seeded_source: str, path: str) -> None:
    diff = deterministic_diff(seeded_source).replace(TARGET_FILE, path)
    assert not PatchPolicy().validate(diff, seeded_source).is_valid


@pytest.mark.parametrize(
    "suffix",
    [
        "--- a/other.py\n+++ b/other.py\n@@ -1 +1 @@\n-a\n+b\n",
        "diff --git a/other.py b/other.py\n",
        "Binary files a/file and b/file differ\n",
        "GIT binary patch\n",
        "old mode 100644\nnew mode 100755\n",
        "rename from file\nrename to checkout.py\n",
    ],
)
def test_multifile_and_metadata_are_rejected(seeded_source: str, suffix: str) -> None:
    assert (
        not PatchPolicy()
        .validate(deterministic_diff(seeded_source) + suffix, seeded_source)
        .is_valid
    )


@pytest.mark.parametrize("diff", ["", "not a diff", "x" * 16385, "\x00", "\r\n"])
def test_empty_malformed_and_oversized_diffs(seeded_source: str, diff: str) -> None:
    assert not PatchPolicy().validate(diff, seeded_source).is_valid


def test_stale_base_and_mismatching_context(seeded_source: str) -> None:
    diff = deterministic_diff(seeded_source)
    assert not PatchPolicy().validate(diff, seeded_source, base_sha256="0" * 64).is_valid
    assert (
        not PatchPolicy()
        .validate(diff.replace("subtotal - discount", "subtotal + discount"), seeded_source)
        .is_valid
    )
    assert not PatchPolicy().validate(diff, "a" * 32769).is_valid


def test_syntax_errors_are_classified(seeded_source: str) -> None:
    result = PatchPolicy().validate(
        patch(seeded_source, seeded_source + "def broken(:\n"), seeded_source
    )
    assert not result.is_valid and not result.syntax_valid and not result.ast_safe


@pytest.mark.parametrize(
    "source",
    [
        "import os\nos.system('id')\n",
        "import subprocess as safe\nsafe.run(['id'])\n",
        "from os import system as harmless\nharmless('id')\n",
        "eval('1+1')\n",
        "exec('pass')\n",
        "import socket\nsocket.socket()\n",
        "__import__('os')\n",
        "x = eval\nx('1')\n",
        "getattr(object, '__class__')\n",
        "x.__class__.__mro__\n",
        "import importlib\n",
        "open('/tmp/secret')\n",
        "from typing import *\n",
        "from . import something\n",
    ],
)
def test_unsafe_calls_imports_and_aliases(source: str) -> None:
    syntax_valid, safe, error = validate_ast(source)
    assert syntax_valid and not safe and error


def test_noop_and_change_limit() -> None:
    source = "x = 1\n" * 60
    assert not PatchPolicy().validate(patch(source, "x = 2\n" * 60), source).is_valid
    diff = f"--- a/{TARGET_FILE}\n+++ b/{TARGET_FILE}\n@@ -1 +1 @@\n-x = 1\n+x = 1\n"
    assert not PatchPolicy().validate(diff, "x = 1\n").is_valid


def test_multiple_hunks_and_insert_delete_coordinates() -> None:
    source = "".join(f"v{i} = {i}\n" for i in range(30))
    candidate = source.replace("v1 = 1\n", "v1 = 42\n").replace("v28 = 28\n", "v28 = 99\n")
    assert parse_unified_diff(patch(source, candidate), source).patched_source == candidate
    source = "a = 1\n"
    for candidate in ["b = 2\n" + source, source + "b = 2\n", ""]:
        assert parse_unified_diff(patch(source, candidate), source).patched_source == candidate


def test_git_header_and_no_newline_marker() -> None:
    source = "value = 1"
    diff = (
        f"diff --git a/{TARGET_FILE} b/{TARGET_FILE}\nindex abc1234..def1234 100644\n"
        f"--- a/{TARGET_FILE}\n+++ b/{TARGET_FILE}\n@@ -1 +1 @@\n"
        "-value = 1\n\\ No newline at end of file\n"
        "+value = 2\n\\ No newline at end of file\n"
    )
    assert parse_unified_diff(diff, source).patched_source == "value = 2"


@pytest.mark.parametrize(
    "replacement", ["@@ -999,7 +999,7 @@", "@@ -44,8 +44,7 @@", "@@ -44,7 +43,7 @@"]
)
def test_bad_hunk_coordinates(seeded_source: str, replacement: str) -> None:
    import re

    diff = re.sub(r"@@[^\n]*@@", replacement, deterministic_diff(seeded_source), count=1)
    assert not PatchPolicy().validate(diff, seeded_source).is_valid
