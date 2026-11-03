"""Adversarial fuzz and property tests for the non-executing AST policy gate.

``app.policy.validate_ast`` and ``PatchPolicy.validate`` are a policy gate, not a
sandbox: they parse without importing and must never let an adversarial AST slip
a forbidden capability past the allowlist. These tests drive that boundary with
shadowed exception handlers, exception-suppression tricks, resource/normalization
edges, and a seeded grammar fuzzer, then assert every result fails closed and
never raises an unhandled exception.
"""

from __future__ import annotations

import difflib
import random
import unicodedata
from collections.abc import Callable

import pytest

from app.policy import TARGET_FILE, PatchPolicy, validate_ast


def patch(source: str, candidate: str) -> str:
    """Build an exact unified diff transforming ``source`` into ``candidate``."""
    return "".join(
        difflib.unified_diff(
            source.splitlines(keepends=True),
            candidate.splitlines(keepends=True),
            fromfile=f"a/{TARGET_FILE}",
            tofile=f"b/{TARGET_FILE}",
        )
    )


def assert_fail_closed_invariants(syntax: bool, safe: bool, error: str | None) -> None:
    """Structural invariants every ``validate_ast`` result tuple must satisfy."""
    assert (syntax and safe) == (error is None)
    if not syntax:
        assert not safe


# -- shadowed exception handlers ----------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        # match...case pattern-matching captures shadow the exception name.
        "match value:\n    case ValueError as err:\n        pass\n"
        "try:\n    pass\nexcept ValueError:\n    pass\n",
        "match value:\n    case ValueError:\n        pass\n"
        "try:\n    pass\nexcept ValueError:\n    pass\n",
        # Walrus assignment binds the exception name to a concrete value.
        "if (ValueError := Exception):\n    pass\ntry:\n    pass\nexcept ValueError:\n    pass\n",
        # Comprehension targets are scoped Store names, not trustable aliases.
        "[x for ValueError in [Exception]]\ntry:\n    pass\nexcept ValueError:\n    pass\n",
        # ``with`` / ``async with`` item shadowing.
        "with Exception as ValueError:\n    pass\ntry:\n    pass\nexcept ValueError:\n    pass\n",
        "async def f():\n    async with factory() as ValueError:\n        pass\n"
        "try:\n    pass\nexcept ValueError:\n    pass\n",
        # for-loop targets and function signatures shadow names.
        "for ValueError in [Exception]:\n    pass\ntry:\n    pass\nexcept ValueError:\n    pass\n",
        "def f(ValueError=Exception):\n    pass\ntry:\n    pass\nexcept ValueError:\n    pass\n",
        "def f(*ValueError, **TypeError):\n    pass\ntry:\n    pass\nexcept TypeError:\n    pass\n",
        # Function and class definitions replace the builtin binding.
        "def ValueError():\n    pass\ntry:\n    pass\nexcept ValueError:\n    pass\n",
        "class ValueError:\n    pass\ntry:\n    pass\nexcept ValueError:\n    pass\n",
        # An except ``as`` name shadows the builtin for the handler body.
        "try:\n    pass\nexcept TypeError as ValueError:\n"
        "    try:\n        pass\n    except ValueError:\n        pass\n",
        # Star-unpacking and import aliases are unproven bindings.
        "ValueError, *rest = values\ntry:\n    pass\nexcept ValueError:\n    pass\n",
        "from app.orders import Order as ValueError\n"
        "try:\n    pass\nexcept ValueError:\n    pass\n",
        # PEP 695 ``type`` aliases (3.12+) can shadow a builtin exception name.
        "type ValueError = Exception\ntry:\n    pass\nexcept ValueError:\n    pass\n",
        "type Alias = Exception\ntry:\n    pass\nexcept Alias:\n    pass\n",
    ],
)
def test_shadowed_exception_handlers_fail_closed(source: str) -> None:
    """A name shadowed by any binding construct is never a trusted handler type."""
    syntax, safe, error = validate_ast(source)
    assert_fail_closed_invariants(syntax, safe, error)
    assert syntax and not safe and error


@pytest.mark.parametrize(
    "declaration",
    [
        "from typing import TypeVar\nValueError = TypeVar('ValueError')",
        "from typing import TypeAlias\nValueError: TypeAlias = Exception",
        "from typing import TypeVar, TypeAlias\nT = TypeVar('T')\nAlias: TypeAlias = int",
    ],
)
def test_typevar_and_typealias_definitions_fail_closed(declaration: str) -> None:
    """Typing-based aliases are blocked at the import gate before use."""
    source = declaration + "\ntry:\n    pass\nexcept ValueError:\n    pass\n"
    syntax, safe, error = validate_ast(source)
    assert_fail_closed_invariants(syntax, safe, error)
    assert syntax and not safe and error


def test_shadowed_handler_alias_resolves_to_catch_all(seeded_source: str) -> None:
    """A walrus-bound ``Exception`` alias is a catch-all, not a specific handler."""
    source = "if (Errors := Exception):\n    pass\n"
    source += "try:\n    pass\nexcept Errors:\n    pass\n"
    syntax, safe, error = validate_ast(source)
    assert syntax and not safe and error and "Catch-all" in error
    candidate = seeded_source + "\n" + source
    result = PatchPolicy().validate(patch(seeded_source, candidate), seeded_source)
    assert not result.is_valid and not result.ast_safe


# -- exception suppression tricks ---------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "def f():\n    try:\n        raise ValueError\n    finally:\n        return 1\n",
        "def f():\n    try:\n        try:\n            raise ValueError\n"
        "        except Exception:\n            raise\n    finally:\n        return 1\n",
        "for x in [1]:\n    try:\n        pass\n    except Exception:\n        raise\n"
        "    finally:\n        break\n",
        "for x in [1]:\n    try:\n        pass\n    except Exception:\n        raise\n"
        "    finally:\n        continue\n",
    ],
)
def test_finally_control_flow_suppresses_exceptions(source: str) -> None:
    """return/break/continue in a finally suite discard an escaping exception."""
    syntax, safe, error = validate_ast(source)
    assert_fail_closed_invariants(syntax, safe, error)
    assert syntax and not safe and error


def test_raise_in_finally_is_not_silent_suppression() -> None:
    """A ``raise`` in finally replaces, not swallows, the in-flight exception."""
    source = "def f():\n    try:\n        pass\n    finally:\n        raise ValueError\n"
    assert validate_ast(source) == (True, True, None)


@pytest.mark.parametrize(
    "source",
    [
        "try:\n    1 / 0\nexcept* Exception:\n    pass\n",
        "try:\n    1 / 0\nexcept* BaseException as exc:\n    pass\n",
        "try:\n    1 / 0\nexcept* (ValueError, Exception):\n    pass\n",
        "try:\n    1 / 0\nexcept* ValueError:\n    pass\nexcept* Exception:\n    pass\n",
    ],
)
def test_exception_group_catch_all_is_rejected(source: str) -> None:
    """``except*`` with a catch-all type suppresses grouped failures and fails shut."""
    syntax, safe, error = validate_ast(source)
    assert_fail_closed_invariants(syntax, safe, error)
    assert syntax and not safe and error


@pytest.mark.parametrize(
    "source",
    [
        "try:\n    1 / 0\nexcept* ValueError:\n    pass\n",
        "try:\n    1 / 0\nexcept* (TypeError, ValueError) as exc:\n    raise exc\n",
        "try:\n    1 / 0\nexcept* Exception as exc:\n    raise exc\n",
    ],
)
def test_exception_group_specific_handlers_and_reraises_are_allowed(source: str) -> None:
    assert validate_ast(source) == (True, True, None)


def test_bare_exception_group_handler_is_invalid_syntax() -> None:
    assert validate_ast("try:\n    1 / 0\nexcept*:\n    pass\n") == (
        False,
        False,
        "Candidate contains invalid Python syntax",
    )


@pytest.mark.parametrize(
    "source",
    [
        "try:\n    1 / 0\nexcept Exception as exc:\n    raise TypeError('invalid') from exc\n",
        "try:\n    1 / 0\nexcept Exception as exc:\n    raise TypeError('invalid') from None\n",
        "try:\n    1 / 0\nexcept Exception as exc:\n    raise ValueError from exc\n",
    ],
)
def test_wrapped_reraise_does_not_admit_catch_all(source: str) -> None:
    """Only a bare ``raise`` or ``raise <name>`` admits a catch-all handler."""
    syntax, safe, error = validate_ast(source)
    assert_fail_closed_invariants(syntax, safe, error)
    assert syntax and not safe and error


@pytest.mark.parametrize(
    "source",
    [
        "try:\n    1 / 0\nexcept Exception as exc:\n    raise\n",
        "try:\n    1 / 0\nexcept Exception as exc:\n    raise exc\n",
        "try:\n    1 / 0\nexcept Exception as exc:\n    print(exc)\n    raise\n",
    ],
)
def test_straight_line_diagnostic_reraises_admit_catch_all(source: str) -> None:
    assert validate_ast(source) == (True, True, None)


# -- AST resource and normalization edges -------------------------------------


def nested_parens(depth: int) -> str:
    return "(" * depth + "1" + ")" * depth


def nested_lists(depth: int) -> str:
    return "[" * depth + "]" * depth


def nested_unary(depth: int) -> str:
    return "-" * depth + "1"


def nested_binary(depth: int) -> str:
    return "1 + (" * depth + "1" + ")" * depth


def nested_call(depth: int) -> str:
    return "f(" * depth + "1" + ")" * depth


@pytest.mark.parametrize(
    "builder",
    [nested_parens, nested_lists, nested_unary, nested_binary, nested_call],
)
@pytest.mark.parametrize("depth", [8, 32, 128, 512, 2000])
def test_deeply_nested_expressions_never_crash_the_host(
    builder: Callable[[int], str], depth: int
) -> None:
    """Parser recursion limits fail closed without an unhandled RecursionError."""
    syntax, safe, error = validate_ast(builder(depth))
    assert_fail_closed_invariants(syntax, safe, error)


def _alias_chain(count: int) -> str:
    """A chain of aliases deep enough to overflow a recursive resolver."""
    lines = ["a0 = Exception"] + [f"a{i} = a{i - 1}" for i in range(1, count)]
    return "\n".join(lines) + f"\ntry:\n    pass\nexcept a{count - 1}:\n    pass\n"


@pytest.mark.parametrize("count", [1200, 3000])
def test_deep_alias_chain_fails_closed_without_recursion_error(count: int) -> None:
    """An adversarial alias chain must not escape as an unhandled RecursionError."""
    syntax, safe, error = validate_ast(_alias_chain(count))
    assert_fail_closed_invariants(syntax, safe, error)
    assert syntax and not safe and error


def test_patch_policy_deep_alias_chain_fails_closed() -> None:
    """A compact single-line chain that fits the diff budget still fails shut."""
    count = 1500
    chain = "a0=Exception;" + "".join(f"a{i}=a{i - 1};" for i in range(1, count))
    source = chain + f"\ntry:\n    pass\nexcept a{count - 1}:\n    pass\n"
    base = "x = 1\n"
    result = PatchPolicy().validate(patch(base, source), base)
    assert not result.is_valid and not result.ast_safe


def fullwidth(text: str) -> str:
    """The fullwidth (U+FF01..U+FF5E) spelling of ASCII text, NFKC-normalized back."""
    return "".join(
        chr(0xFF10 + ord(ch) - ord("0"))
        if "0" <= ch <= "9"
        else chr(0xFF21 + ord(ch) - ord("A"))
        if "A" <= ch <= "Z"
        else chr(0xFF41 + ord(ch) - ord("a"))
        if "a" <= ch <= "z"
        else ch
        for ch in text
    )


@pytest.mark.parametrize(
    ("name", "expression"),
    [
        ("eval", "eval('1+1')"),
        ("exec", "exec('pass')"),
        ("open", "open('/etc/passwd')"),
        ("input", "input('prompt')"),
        ("os", "os.system('id')"),
        ("globals", "globals()"),
        ("vars", "vars()"),
    ],
)
def test_fullwidth_homoglyphs_of_dangerous_names_are_blocked(name: str, expression: str) -> None:
    """NFKC normalization makes the parser report the ASCII dangerous name."""
    assert unicodedata.normalize("NFKC", fullwidth(name)) == name
    source = fullwidth(expression) + "\n"
    syntax, safe, error = validate_ast(source)
    assert_fail_closed_invariants(syntax, safe, error)
    assert syntax and not safe and error


def test_fullwidth_homoglyph_of_dangerous_attribute_is_blocked() -> None:
    assert unicodedata.normalize("NFKC", fullwidth("system")) == "system"
    syntax, safe, error = validate_ast(f"obj.{fullwidth('system')}('id')\n")
    assert syntax and not safe and error


def test_cyrillic_confusable_is_not_a_dangerous_name_bypass() -> None:
    """A Cyrillic ``е`` is a distinct identifier, harmless and not ``eval``."""
    assert unicodedata.normalize("NFKC", "\u0435") != "e"
    assert validate_ast("\u0435val('1+1')\n") == (True, True, None)


@pytest.mark.parametrize(
    "docstring",
    [
        "\"eval('id'); __import__('os').system('rm -rf /')\"",
        'r"\\x00 \\n \\u2603 \\N{SNOWMAN} \\t"',
        '"""import os\neval("1")\nopen("/etc/passwd")"""',
        "'back\\\\slash and \\'quote\\''",
        'b"\\x00\\x01\\x02 raw bytes"',
        '"unicode: \u2603 \U0001f680 \u00e9"',
    ],
)
def test_exotic_docstrings_and_raw_strings_are_inert(docstring: str) -> None:
    """Dangerous text inside a string literal is data, never a capability."""
    assert validate_ast(docstring + "\nresult = 1\n") == (True, True, None)


def test_fstring_with_forbidden_call_is_still_flagged() -> None:
    """Names interpolated into f-strings remain AST nodes and are still checked."""
    syntax, safe, error = validate_ast("message = f\"{eval('1+1')}\"\n")
    assert syntax and not safe and error


# -- fail-closed invariants over a seeded grammar fuzzer ----------------------


_TOKENS = [
    "import os",
    "from typing import cast",
    "from fastapi import HTTPException",
    "eval('x')",
    "exec('x')",
    "open('x')",
    "__import__('os')",
    "getattr(x, 'y')",
    "x.__class__",
    "try:",
    "except Exception:",
    "except ValueError as err:",
    "except:",
    "except* Exception:",
    "finally:",
    "return",
    "break",
    "continue",
    "raise",
    "with Exception as ValueError:",
    "async with factory() as x:",
    "match x:",
    "case ValueError as err:",
    "case _:",
    "lambda: 1",
    "yield 1",
    "await work()",
    "nonlocal x",
    "global x",
    "del x",
    "ValueError = Exception",
    "if (ValueError := Exception):",
    "[x for ValueError in [Exception]]",
    "1 / 0",
    "class ValueError:",
    "def ValueError():",
    "type ValueError = Exception",
    "x.y.z",
    "x['k']",
    "f'{eval}'",
    "assert x",
    "pass",
    "...",
    "None",
    "True",
]


def _random_source(rng: random.Random) -> str:
    """A mostly-invalid, adversarial source composed from the token grammar."""
    lines = [rng.choice(_TOKENS) for _ in range(rng.randint(1, 12))]
    if rng.random() < 0.5:
        lines = ["def f():" if rng.random() < 0.5 else "for x in [1]:"] + [
            "    " + line for line in lines
        ]
    return "\n".join(lines) + "\n"


def test_validate_ast_never_raises_for_generated_corpus() -> None:
    """``validate_ast`` must return a result tuple for any adversarial source."""
    rng = random.Random(20241103)
    for _ in range(500):
        source = _random_source(rng)
        syntax, safe, error = validate_ast(source)
        assert_fail_closed_invariants(syntax, safe, error)


def test_patch_policy_never_raises_and_preserves_invariant() -> None:
    """``PatchPolicy.validate`` is total: it returns a result, never an exception."""
    rng = random.Random(0xC0FFEE)
    policy = PatchPolicy()
    for _ in range(300):
        diff = _random_source(rng)
        source = _random_source(rng)
        base = "0" * 64 if rng.random() < 0.2 else None
        result = policy.validate(diff, source, base_sha256=base)
        assert result.target_file == TARGET_FILE
        assert result.is_valid == (result.syntax_valid and result.ast_safe)


@pytest.mark.parametrize("source", ["\ud800", "\udfff lone surrogate"])
def test_lone_surrogate_source_with_base_hash_fails_closed(source: str) -> None:
    """A lone surrogate must not escape as an encode crash before UTF-8 gating."""
    syntax, safe, error = validate_ast(source)
    assert_fail_closed_invariants(syntax, safe, error)
    policy = PatchPolicy()
    result = policy.validate("--- a\n", source, base_sha256="0" * 64)
    assert not result.is_valid and not result.ast_safe
    assert result.error_message == "Patch and source must be valid UTF-8"


@pytest.mark.parametrize("source", ["a\x00b", "\x00", "x\x00y"])
def test_nul_byte_source_fails_closed(source: str) -> None:
    """NUL bytes are rejected by the parser and the diff gate, never executed."""
    syntax, safe, error = validate_ast(source)
    assert_fail_closed_invariants(syntax, safe, error)
    policy = PatchPolicy()
    assert not policy.validate("--- a\n", source, base_sha256="0" * 64).is_valid
    assert not policy.validate("--- a\n", source).is_valid


@pytest.mark.parametrize(
    "source",
    [
        "try:\n    pass\nexcept Exception:\n    pass\n",
        "def f():\n    try:\n        pass\n    except Exception:\n        raise\n"
        "    finally:\n        return 1\n",
        "if (Errors := Exception):\n    pass\ntry:\n    pass\nexcept Errors:\n    pass\n",
        "\uff45\uff56\uff41\uff4c('1+1')\n",
    ],
)
def test_adversarial_snippets_fail_closed_through_patch_policy(
    seeded_source: str, source: str
) -> None:
    """End-to-end: a patch appending an unsafe snippet is rejected, not executed."""
    candidate = seeded_source + "\n" + source
    result = PatchPolicy().validate(patch(seeded_source, candidate), seeded_source)
    assert not result.is_valid and not result.ast_safe
