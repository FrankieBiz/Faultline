"""Exact diff application and non-executing syntax/capability policy gates."""

import ast
import difflib
import hashlib
from collections.abc import Callable

import pytest

from app.model_adapter import deterministic_diff
from app.policy import (
    TARGET_FILE,
    PatchPolicy,
    parse_unified_diff,
    recount_unified_diff,
    validate_ast,
)


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


@pytest.mark.parametrize(
    "source",
    [
        "from typing import sys as safe\nsafe.modules['io'].FileIO('file', 'w')\n",
        "from typing import sys\n",
        "import typing as safe\nsafe.sys.modules['io'].FileIO('file', 'w')\n",
        "import fastapi as safe\nsafe.responses.FileResponse('file')\n",
        "from fastapi import responses as safe\nsafe.FileResponse('file')\n",
        "from app.orders import RLock as safe\n",
    ],
)
def test_transitive_module_capabilities_are_rejected(source: str, seeded_source: str) -> None:
    result = PatchPolicy().validate(patch(seeded_source, seeded_source + source), seeded_source)
    assert result.syntax_valid and not result.ast_safe and not result.is_valid


def test_only_seed_import_symbols_and_aliases_are_accepted() -> None:
    syntax_valid, safe, error = validate_ast(
        "from typing import cast as typed\n"
        "from uuid import uuid4\n"
        "from fastapi import HTTPException\n"
        "from app.catalog import get_product\n"
        "from app.orders import LineItem, Order, create_order\n"
        "from app.schemas import CheckoutRequest\n"
    )
    assert syntax_valid and safe and error is None


def test_private_class_pattern_attributes_are_rejected() -> None:
    syntax_valid, safe, error = validate_ast(
        "match value:\n    case object(__dict__=hidden):\n        pass\n"
    )
    assert syntax_valid and not safe
    assert error is not None


def test_recount_repairs_only_derivable_hunk_metadata(seeded_source: str) -> None:
    correct = deterministic_diff(seeded_source)
    # Models commonly miscount hunk lengths and starts; the content is unchanged.
    miscounted = correct.replace("@@ -40,7 +40,7 @@", "@@ -38,9 +38,9 @@")
    assert not PatchPolicy().validate(miscounted, seeded_source).is_valid
    recounted = recount_unified_diff(miscounted, seeded_source)
    assert recounted == correct
    assert PatchPolicy().validate(recounted, seeded_source).is_valid
    assert recount_unified_diff(correct, seeded_source) == correct


def test_recount_restores_blank_context_and_drops_trailing_blank_lines(
    seeded_source: str,
) -> None:
    correct = deterministic_diff(seeded_source)
    stripped = correct.replace("\n \n", "\n\n", 1) + "\n\n"
    assert stripped != correct
    assert recount_unified_diff(stripped, seeded_source) == correct


@pytest.mark.parametrize(
    "change",
    [
        # Content that does not occur in the source is never matched fuzzily.
        lambda diff: diff.replace("raise HTTPException", "raise ValueError"),
        # A malformed header or non-diff body line is left for the parser to reject.
        lambda diff: diff.replace("@@ -40,7 +40,7 @@", "@@ forty @@"),
        lambda diff: diff.replace("     total = subtotal", "*    total = subtotal"),
        # A line number too long for int() is rejected as malformed, not raised.
        lambda diff: diff.replace("@@ -40,7 +40,7 @@", f"@@ -{'9' * 5000},7 +40,7 @@"),
    ],
)
def test_recount_never_alters_content_or_invents_matches(
    seeded_source: str, change: Callable[[str], str]
) -> None:
    altered = change(deterministic_diff(seeded_source))
    assert recount_unified_diff(altered, seeded_source) == altered
    assert not PatchPolicy().validate(altered, seeded_source).is_valid


def test_recount_refuses_ambiguous_relocation() -> None:
    source = "a = 1\nb = 2\na = 1\nb = 2\n"
    diff = f"--- a/{TARGET_FILE}\n+++ b/{TARGET_FILE}\n@@ -9,2 +9,2 @@\n a = 1\n-b = 2\n+b = 3\n"
    assert recount_unified_diff(diff, source) == diff


@pytest.mark.parametrize(
    "handler",
    [
        "except:",
        "except Exception:",
        "except BaseException as error:",
        "except (KeyError, Exception):",
    ],
)
def test_catch_all_handlers_are_rejected_before_execution(seeded_source: str, handler: str) -> None:
    old = "    total = subtotal - discount\n"
    suppressed = seeded_source.replace(
        old,
        f"    try:\n        total = subtotal - discount\n    {handler}\n        total = subtotal\n",
    )
    result = PatchPolicy().validate(patch(seeded_source, suppressed), seeded_source)
    assert not result.is_valid and not result.ast_safe
    assert result.error_message and "Catch-all" in result.error_message


def test_specific_exception_handlers_remain_allowed(seeded_source: str) -> None:
    old = "    total = subtotal - discount\n"
    specific = seeded_source.replace(
        old,
        "    try:\n        total = subtotal - discount\n"
        "    except TypeError:\n        total = subtotal\n",
    )
    # Policy admits it; the independent oracle is what rejects this wrong repair.
    assert PatchPolicy().validate(patch(seeded_source, specific), seeded_source).is_valid


@pytest.mark.parametrize(
    "handler,body",
    [
        ("except Exception as err:", "raise"),
        ("except BaseException as err:", "raise err"),
        ("except:", "raise"),
        ("except (TypeError, ValueError) as exc:", "raise exc"),
        ("except ValueError as exc:", "raise TypeError('invalid') from exc"),
    ],
)
def test_exception_aliases_and_reraises_are_allowed(handler: str, body: str) -> None:
    assert validate_ast(f"try:\n    value = 1\n{handler}\n    {body}\n") == (True, True, None)


@pytest.mark.parametrize("alias", ["os", "eval", "__hidden"])
def test_exception_alias_bindings_cannot_bypass_forbidden_names(alias: str) -> None:
    syntax, safe, error = validate_ast(f"try:\n    pass\nexcept ValueError as {alias}:\n    pass\n")
    assert syntax and not safe and error


@pytest.mark.parametrize(
    "body",
    [
        "if flag:\n        raise",
        "return\nraise",
        "try:\n    raise\nexcept:\n    pass",
        "def nested():\n        raise",
    ],
)
def test_nested_or_unreachable_raise_does_not_admit_catch_all(body: str) -> None:
    source = "def checkout():\n    try:\n        pass\n    except Exception as err:\n"
    source += "\n".join("        " + line for line in body.splitlines()) + "\n"
    syntax, safe, error = validate_ast(source)
    assert syntax and not safe and error


@pytest.mark.parametrize(
    "declaration,handler",
    [
        ("AnyError = Exception", "except AnyError:"),
        ("First = BaseException\nSecond = First", "except Second as err:"),
        ("Errors = (TypeError, Exception)", "except Errors:"),
        ("Errors = Exception", "except (TypeError, Errors) as exc:"),
        ("Errors: type = Exception", "except Errors:"),
        ("First, Second = (ValueError, Exception)", "except Second:"),
        ("Errors = Exception", "except* Errors as exc:"),
    ],
)
def test_catch_all_type_aliases_cannot_suppress_failures(declaration: str, handler: str) -> None:
    source = declaration + f"\ntry:\n    1 / 0\n{handler}\n    pass\n"
    syntax, safe, error = validate_ast(source)
    assert syntax and not safe and error and "Catch-all" in error


@pytest.mark.parametrize(
    "source",
    ["return 1\n", "break\n", "continue\n", "await work()\n", "nonlocal missing\n"],
)
def test_compiler_level_syntax_errors_are_classified(source: str) -> None:
    assert validate_ast(source) == (False, False, "Candidate contains invalid Python syntax")


@pytest.mark.parametrize(
    "declaration,handler,body",
    [
        ("AnyError = Exception", "except AnyError as err:", "raise err"),
        ("Specific = ValueError", "except Specific as err:", "pass"),
        ("Specific, Broad = (ValueError, Exception)", "except Specific as err:", "pass"),
        ("Errors = (TypeError, ValueError)", "except Errors as exc:", "raise exc"),
        ("", "except Exception as err:", "print('failed')\nraise"),
        ("from fastapi import HTTPException as HttpError", "except HttpError as err:", "raise err"),
    ],
)
def test_trusted_handler_aliases_and_diagnostic_reraises(
    declaration: str,
    handler: str,
    body: str,
) -> None:
    source = declaration + f"\ntry:\n    1 / 0\n{handler}\n"
    source += "\n".join("    " + line for line in body.splitlines()) + "\n"
    assert validate_ast(source) == (True, True, None)


@pytest.mark.parametrize("handler", ["factory()", "types[0]", "unknown", "first"])
def test_unresolved_handler_types_fail_closed(handler: str) -> None:
    source = f"first = second\nsecond = first\ntry:\n    pass\nexcept {handler}:\n    pass\n"
    syntax, safe, error = validate_ast(source)
    assert syntax and not safe and error


@pytest.mark.parametrize(
    "source",
    [
        (
            "for ValueError in [Exception]:\n"
            "    try:\n"
            "        pass\n"
            "    except ValueError:\n"
            "        pass\n"
        ),
        (
            "def f(ValueError=Exception):\n"
            "    try:\n"
            "        pass\n"
            "    except ValueError:\n"
            "        pass\n"
        ),
        (
            "def f(*ValueError, **TypeError):\n"
            "    try:\n"
            "        pass\n"
            "    except TypeError:\n"
            "        pass\n"
        ),
        (
            "[ValueError for ValueError in [Exception]]\n"
            "try:\n"
            "    pass\n"
            "except ValueError:\n"
            "    pass\n"
        ),
        (
            "with factory() as ValueError:\n"
            "    try:\n"
            "        pass\n"
            "    except ValueError:\n"
            "        pass\n"
        ),
        (
            "match value:\n"
            "    case {'error': ValueError}:\n"
            "        try:\n"
            "            pass\n"
            "        except ValueError:\n"
            "            pass\n"
        ),
        "def ValueError():\n    pass\ntry:\n    pass\nexcept ValueError:\n    pass\n",
        "class ValueError:\n    pass\ntry:\n    pass\nexcept ValueError:\n    pass\n",
        (
            "try:\n"
            "    pass\n"
            "except TypeError as ValueError:\n"
            "    try:\n"
            "        pass\n"
            "    except ValueError:\n"
            "        pass\n"
        ),
        "ValueError, *rest = values\ntry:\n    pass\nexcept ValueError:\n    pass\n",
        (
            "from app.orders import Order as ValueError\n"
            "try:\n"
            "    pass\n"
            "except ValueError:\n"
            "    pass\n"
        ),
        (
            "def f():\n"
            "    try:\n"
            "        pass\n"
            "    except Exception:\n"
            "        raise\n"
            "    finally:\n"
            "        return 1\n"
        ),
        (
            "def f():\n"
            "    try:\n"
            "        try:\n"
            "            pass\n"
            "        except Exception:\n"
            "            raise\n"
            "    finally:\n"
            "        return 1\n"
        ),
        (
            "for x in [1]:\n"
            "    try:\n"
            "        pass\n"
            "    except Exception:\n"
            "        raise\n"
            "    finally:\n"
            "        break\n"
        ),
        (
            "for x in [1]:\n"
            "    try:\n"
            "        pass\n"
            "    except Exception:\n"
            "        raise\n"
            "    finally:\n"
            "        continue\n"
        ),
        (
            "for outer in [1]:\n"
            "    try:\n        pass\n    except Exception:\n        raise\n"
            "    finally:\n        for inner in []:\n            pass\n"
            "        else:\n            break\n"
        ),
    ],
)
def test_non_assignment_bindings_and_finally_suppression_fail_closed(
    source: str, seeded_source: str
) -> None:
    syntax, safe, error = validate_ast(source)
    assert syntax and not safe and error
    result = PatchPolicy().validate(
        patch(seeded_source, seeded_source + "\n" + source), seeded_source
    )
    assert not result.is_valid and not result.ast_safe


@pytest.mark.parametrize(
    "suite",
    [
        "def nested():\n    return 1",
        "for x in [1]:\n    break",
        "for x in [1]:\n    continue",
        "print('cleanup')",
    ],
)
def test_finally_local_control_flow_and_diagnostics_remain_allowed(suite: str) -> None:
    source = "try:\n    pass\nexcept Exception:\n    raise\nfinally:\n"
    source += "\n".join("    " + line for line in suite.splitlines()) + "\n"
    assert validate_ast(source) == (True, True, None)
