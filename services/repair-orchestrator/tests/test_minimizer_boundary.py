"""Source boundaries survive exact diff application and payload minimization.

The retained minimizer operates on JSON keys/list items, not Python fragments.
Embedded diffs must remain opaque strings; the policy validates the entire
applied module, including compiler context, before any execution is permitted.
"""

import ast
import copy
import difflib
from io import StringIO
from typing import Any

import pytest

from app.minimizer import DeltaDebugger
from app.policy import TARGET_FILE, PatchPolicy, parse_unified_diff, recount_unified_diff


def patch(source: str, candidate: str, *, context: int = 3) -> str:
    """Use physical LF lines, as Git does, including explicit EOF markers."""
    lines = difflib.unified_diff(
        StringIO(source).readlines(),
        StringIO(candidate).readlines(),
        fromfile=f"a/{TARGET_FILE}",
        tofile=f"b/{TARGET_FILE}",
        n=context,
    )
    return "".join(
        line if line.endswith("\n") else line + "\n\\ No newline at end of file\n" for line in lines
    )


SOURCES = [
    pytest.param(
        "def checkout():\n"
        "    return (\n"
        "        (1 + 2) * (\n"
        "            3 + SENTINEL\n"
        "        )\n"
        "    )\n",
        id="nested-parentheses",
    ),
    pytest.param(
        "def checkout():\n"
        "    return dict(\n"
        "        items=list(\n"
        "            (SENTINEL, 2),\n"
        "        ),\n"
        "        total=3,\n"
        "    )\n",
        id="multiline-calls-and-trailing-commas",
    ),
    pytest.param(
        "def checkout():\n"
        '    """Checkout documentation.\n'
        "\n"
        "        Preserve SENTINEL and this indentation.\n"
        '    """\n'
        "    return 1\n",
        id="multiline-docstring",
    ),
    pytest.param(
        '"""Module documentation with SENTINEL.\n'
        "@@ -1 +1 @@\n"
        "--- a/this-is-string-data\n"
        '"""\n'
        "def checkout():\n"
        "    return 1\n",
        id="diff-metadata-inside-docstring",
    ),
    pytest.param(
        "def checkout():\n"
        "    if True:\n"
        "        return [\n"
        "            (item, SENTINEL)\n"
        "            for item in (1, 2,)\n"
        "            if item > 0\n"
        "        ]\n"
        "    return []\n",
        id="nested-comprehension",
    ),
    pytest.param(
        "def checkout():\n\tif True:\n\t\treturn (SENTINEL,)\n\treturn ()\n",
        id="tab-indentation",
    ),
    pytest.param(
        "def checkout():\n    return 1 + \\\n        SENTINEL\n",
        id="explicit-line-continuation",
    ),
    pytest.param(
        "def checkout():\n    value = (SENTINEL,); return value\n",
        id="semicolon-statements-and-singleton-tuple",
    ),
    pytest.param(
        "@decorate(\n    SENTINEL,\n)\ndef checkout(\n    value=(1, 2,),\n):\n    return value\n",
        id="multiline-decorator-and-signature",
    ),
    pytest.param(
        'def checkout():\n    return f"total: {(SENTINEL + 1):04d}"\n',
        id="nested-fstring-expression",
    ),
    pytest.param(
        'def checkout():\n    label = "café ☃"; return SENTINEL\n',
        id="utf8-column-offsets",
    ),
    pytest.param("def checkout():\n    return (SENTINEL,)", id="no-final-newline"),
]


@pytest.mark.parametrize("template", SOURCES)
@pytest.mark.parametrize("context", [0, 3])
def test_complete_statement_diff_preserves_exact_source(template: str, context: int) -> None:
    source = template.replace("SENTINEL", "10")
    candidate = template.replace("SENTINEL", "20")
    diff = patch(source, candidate, context=context)

    assert parse_unified_diff(diff, source).patched_source == candidate
    assert PatchPolicy().validate(diff, source).is_valid
    recounted = recount_unified_diff(diff, source)
    assert parse_unified_diff(recounted, source).patched_source == candidate
    assert PatchPolicy().validate(recounted, source).is_valid
    compile(ast.parse(candidate), TARGET_FILE, "exec", dont_inherit=True)


@pytest.mark.parametrize("template", SOURCES)
@pytest.mark.asyncio
async def test_payload_minimizer_keeps_embedded_diff_opaque(template: str) -> None:
    source = template.replace("SENTINEL", "10")
    candidate = template.replace("SENTINEL", "20")
    diff = patch(source, candidate)
    payload = {"patch": diff, "analytics": "noise", "metadata": {"unused": True}}
    original = copy.deepcopy(payload)
    observed: list[str] = []

    async def oracle(value: dict[str, Any]) -> bool:
        if "patch" not in value:
            return False
        observed.append(value["patch"])
        assert value["patch"] == diff
        assert parse_unified_diff(value["patch"], source).patched_source == candidate
        return PatchPolicy().validate(value["patch"], source).is_valid

    result = await DeltaDebugger().minimize_async(payload, oracle, "boundary")

    assert result.minimal_payload == {"patch": diff}
    assert result.original_payload == original == payload
    assert observed


@pytest.mark.parametrize(
    "separator", ["\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"]
)
@pytest.mark.parametrize("location", ["docstring", "comment", "string"])
@pytest.mark.parametrize("context", [0, 3])
def test_non_lf_characters_do_not_split_source_lines(
    separator: str, location: str, context: int
) -> None:
    text = {
        "docstring": f'    """First{separator}second."""\n',
        "comment": f"    # First{separator}second.\n",
        "string": f'    label = "first{separator}second"\n',
    }[location]
    source = "def checkout():\n" + text + "    return 10\n"
    candidate = source.replace("return 10", "return 20")
    diff = patch(source, candidate, context=context)

    assert PatchPolicy().validate(diff, source).is_valid
    assert parse_unified_diff(diff, source).patched_source == candidate
    recounted = recount_unified_diff(diff, source)
    assert parse_unified_diff(recounted, source).patched_source == candidate
    assert PatchPolicy().validate(recounted, source).is_valid


def test_form_feed_indentation_is_preserved() -> None:
    source = "def checkout():\n\f    return 10\n"
    candidate = source.replace("10", "20")
    diff = patch(source, candidate)

    assert PatchPolicy().validate(diff, source).is_valid
    assert parse_unified_diff(diff, source).patched_source == candidate
    assert recount_unified_diff(diff, source) == diff


@pytest.mark.parametrize(
    "candidate",
    [
        "def checkout():\n    return (\n        1 + (2 * 3)\n",
        "def checkout():\n    return dict(\n        first=1,\n",
        'def checkout():\n    """Unterminated docstring.\n    return 1\n',
        "def checkout():\n    return dict(\n        first=1\n        second=2,\n    )\n",
        "def checkout():\n    return (1,\n",
        "def checkout():\nreturn 1\n",
        "def checkout():\n    if True:\n    return 1\n",
        "def checkout():\n    if True:\n        return 1\n      return 2\n",
        "def checkout():\n\tif True:\n        return 1\n",
        "return (1,)\n",
        "break\n",
        "await work(\n    1,\n)\n",
    ],
)
def test_incomplete_statements_and_invalid_indentation_fail_closed(candidate: str) -> None:
    source = "def checkout():\n    return 10\n"
    diff = patch(source, candidate)
    # Applicability is separate from Python validity: gate the complete module.
    assert parse_unified_diff(diff, source).patched_source == candidate
    result = PatchPolicy().validate(diff, source)

    assert not result.is_valid
    assert not result.syntax_valid
    assert not result.ast_safe
    assert result.error_message == "Candidate contains invalid Python syntax"


@pytest.mark.parametrize("indent", ["", "  ", "\t"])
def test_recount_does_not_repair_stripped_python_indentation(indent: str) -> None:
    source = "def checkout():\n    if True:\n        return 10\n"
    candidate = source.replace("10", "20")
    diff = patch(source, candidate)
    damaged = diff.replace("-        return 10\n", f"-{indent}return 10\n")

    assert not PatchPolicy().validate(recount_unified_diff(damaged, source), source).is_valid


@pytest.mark.asyncio
async def test_oracle_cannot_mutate_embedded_diff_or_original_payload() -> None:
    source = "def checkout():\n    return 10\n"
    diff = patch(source, source.replace("10", "20"))
    payload = {"patches": [{"diff": diff}], "noise": True}
    original = copy.deepcopy(payload)

    async def oracle(value: dict[str, Any]) -> bool:
        patches = value.get("patches")
        if not patches:
            return False
        assert patches[0]["diff"] == diff
        patches[0]["diff"] = patches[0]["diff"].replace("+    return", "+return")
        return True

    result = await DeltaDebugger().minimize_async(payload, oracle, "boundary")

    assert payload == original
    assert result.original_payload == original
    assert result.minimal_payload == {"patches": [{"diff": diff}]}


@pytest.mark.parametrize("required_count", [1, 2])
@pytest.mark.asyncio
async def test_list_minimization_isolates_accepted_and_rejected_oracle_mutations(
    required_count: int,
) -> None:
    source = "def checkout():\n    return 10\n"
    diff = patch(source, source.replace("10", "20"))
    payload = {
        "patches": [{"diff": diff, "tag": str(index)} for index in range(4)],
        "required": True,
        "noise": {"unused": True},
    }
    original = copy.deepcopy(payload)

    async def oracle(value: dict[str, Any]) -> bool:
        patches = value.get("patches", [])
        accepted = value.get("required") is True and len(patches) >= required_count
        for entry in patches:
            assert entry["diff"] == diff
            entry["diff"] = "invalid Python"
        value.clear()
        return accepted

    result = await DeltaDebugger().minimize_async(payload, oracle, "boundary")

    assert payload == original == result.original_payload
    assert set(result.minimal_payload) == {"required", "patches"}
    retained = result.minimal_payload["patches"]
    assert len(retained) == required_count
    for entry in retained:
        assert entry["diff"] == diff
        assert PatchPolicy().validate(entry["diff"], source).is_valid


@pytest.mark.asyncio
async def test_rejected_initial_oracle_cannot_damage_fallback_source() -> None:
    source = 'def checkout():\n    """Keep indentation.  \n    """\n    return (10,)\n'
    payload = {"source": source, "metadata": {"nested": True}}
    original = copy.deepcopy(payload)

    async def oracle(value: dict[str, Any]) -> bool:
        value["source"] = value["source"].replace("    ", "")
        value["metadata"].clear()
        return False

    result = await DeltaDebugger().minimize_async(payload, oracle, "boundary")

    assert payload == original == result.original_payload == result.minimal_payload


def test_multiple_hunks_preserve_docstrings_call_boundaries_and_line_offsets() -> None:
    source = (
        "def checkout():\n"
        '    """Original documentation."""\n'
        + "".join(f"    value{index} = {index}\n" for index in range(12))
        + "    return dict(\n        total=value11,\n    )\n"
    )
    candidate = source.replace(
        '    """Original documentation."""\n',
        '    """Updated documentation.\n\n        Keep this indentation.  \n    """\n',
    ).replace("        total=value11,\n", "        total=(\n            value11 + 1\n        ),\n")
    diff = patch(source, candidate)
    parsed = parse_unified_diff(diff, source)

    assert len(parsed.hunks) == 2
    assert parsed.patched_source == candidate
    assert PatchPolicy().validate(diff, source).is_valid
    assert (
        parse_unified_diff(recount_unified_diff(diff, source), source).patched_source == candidate
    )
    tree = ast.parse(parsed.patched_source)
    function = tree.body[0]
    assert isinstance(function, ast.FunctionDef)
    assert ast.get_docstring(function, clean=False) == (
        "Updated documentation.\n\n        Keep this indentation.  \n    "
    )
