"""Strict, non-executing validation of bounded single-file checkout patches.

AST inspection is a policy gate, not a sandbox. Accepted Python must still run
only through the restricted runtime boundary; this module never imports it.
"""

import ast
import hashlib
import re
from dataclasses import dataclass

from shared.contracts.models import PatchValidationResult

TARGET_FILE = "apps/buggyshop-backend/app/routes/checkout.py"
MAX_DIFF_BYTES = 16 * 1024
MAX_SOURCE_BYTES = 32 * 1024
MAX_CHANGED_LINES = 100
_HUNK = re.compile(r"@@ -(\d{1,9})(?:,(\d{1,9}))? \+(\d{1,9})(?:,(\d{1,9}))? @@(?: [^\r\n]*)?\n?\Z")
_INDEX = re.compile(r"index [0-9a-f]{7,64}\.\.[0-9a-f]{7,64}(?: 100644)?\n?\Z")
_IMPORTS = {
    "typing": frozenset({"cast"}),
    "uuid": frozenset({"uuid4"}),
    "fastapi": frozenset({"HTTPException"}),
    "app.catalog": frozenset({"get_product"}),
    "app.orders": frozenset({"LineItem", "Order", "create_order"}),
    "app.schemas": frozenset({"CheckoutRequest"}),
}
_DANGEROUS_NAMES = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
        "open",
        "input",
        "getattr",
        "setattr",
        "delattr",
        "globals",
        "locals",
        "vars",
        "breakpoint",
        "os",
        "subprocess",
        "socket",
        "builtins",
        "importlib",
        "ctypes",
    }
)
_DANGEROUS_ATTRIBUTES = frozenset(
    {
        "system",
        "popen",
        "Popen",
        "spawn",
        "execv",
        "execve",
        "fork",
        "connect",
        "socket",
        "eval",
        "exec",
        "read_text",
        "write_text",
        "read_bytes",
        "write_bytes",
    }
)


class PatchPolicyError(ValueError):
    """An inapplicable, malformed, or forbidden proposed source change."""


@dataclass(frozen=True)
class DiffHunk:
    """One fully parsed hunk with exact old and new line coordinates."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: tuple[str, ...]


@dataclass(frozen=True)
class ParsedPatch:
    """Parsed file identity, hunks, and the exact resulting source bytes."""

    target_file: str
    hunks: tuple[DiffHunk, ...]
    patched_source: str


def _utf8_size(value: str) -> int:
    try:
        return len(value.encode("utf-8"))
    except UnicodeError as exc:
        raise PatchPolicyError("Patch and source must be valid UTF-8") from exc


def parse_unified_diff(diff: str, source: str) -> ParsedPatch:
    """Parse and apply exact hunks in memory, rejecting fuzzy or multiple files."""
    if not diff or _utf8_size(diff) > MAX_DIFF_BYTES:
        raise PatchPolicyError("Diff is empty or exceeds 16 KiB")
    if not diff.endswith("\n"):
        diff = diff + "\n"
    if _utf8_size(source) > MAX_SOURCE_BYTES:
        raise PatchPolicyError("Source exceeds 32 KiB")
    if "\x00" in diff or "\r" in diff or "\x00" in source:
        raise PatchPolicyError("NUL bytes and noncanonical diff line endings are forbidden")
    raw_lines = diff.splitlines(keepends=True)
    lines: list[str] = []
    for line in raw_lines:
        if line.rstrip("\n") == "\\ No newline at end of file":
            if not lines or lines[-1][:1] not in {" ", "+", "-"} or not lines[-1].endswith("\n"):
                raise PatchPolicyError("Misplaced end-of-file marker")
            if lines[-1].startswith(("---", "+++")):
                raise PatchPolicyError("Misplaced end-of-file marker")
            lines[-1] = lines[-1][:-1]
        else:
            lines.append(line)
    cursor = 0
    if lines and lines[0].startswith("diff "):
        if lines[0].rstrip("\n") != f"diff --git a/{TARGET_FILE} b/{TARGET_FILE}":
            raise PatchPolicyError("Only the exact allowlisted file may be modified")
        cursor += 1
        if cursor < len(lines) and lines[cursor].startswith("index "):
            if not _INDEX.fullmatch(lines[cursor]):
                raise PatchPolicyError("Invalid index metadata or file mode")
            cursor += 1
    if lines[cursor : cursor + 2] != [f"--- a/{TARGET_FILE}\n", f"+++ b/{TARGET_FILE}\n"]:
        raise PatchPolicyError("Require one existing allowlisted file with canonical paths")
    cursor += 2
    hunks: list[DiffHunk] = []
    changed_lines = 0
    while cursor < len(lines):
        match = _HUNK.fullmatch(lines[cursor])
        if match is None:
            raise PatchPolicyError("Malformed hunk, extra file section, or forbidden metadata")
        old_start, old_count, new_start, new_count = (
            int(match[1]),
            int(match[2] or 1),
            int(match[3]),
            int(match[4] or 1),
        )
        cursor += 1
        content: list[str] = []
        old_seen = new_seen = 0
        while cursor < len(lines) and not lines[cursor].startswith("@@"):
            line = lines[cursor]
            if line[:1] not in {" ", "+", "-"}:
                raise PatchPolicyError("Non-unified hunk content or multiple files")
            old_seen += line[0] in {" ", "-"}
            new_seen += line[0] in {" ", "+"}
            changed_lines += line[0] in {"-", "+"}
            if old_seen > old_count or new_seen > new_count:
                raise PatchPolicyError("Hunk exceeds declared line counts")
            content.append(line)
            cursor += 1
        if (old_seen, new_seen) != (old_count, new_count):
            raise PatchPolicyError("Hunk line counts do not match its header")
        hunks.append(DiffHunk(old_start, old_count, new_start, new_count, tuple(content)))
    if not hunks or not 1 <= changed_lines <= MAX_CHANGED_LINES:
        raise PatchPolicyError("Require between 1 and 100 changed lines")
    original = source.splitlines(keepends=True)
    output: list[str] = []
    position = 0
    for hunk in hunks:
        start = hunk.old_start - 1 if hunk.old_count else hunk.old_start
        if start < position or start > len(original):
            raise PatchPolicyError("Hunks overlap or reference lines outside the source")
        if hunk.old_count and hunk.old_start == 0:
            raise PatchPolicyError("Invalid old hunk coordinate")
        output.extend(original[position:start])
        position = start
        new_start = hunk.new_start - 1 if hunk.new_count else hunk.new_start
        if new_start != len(output):
            raise PatchPolicyError("New hunk coordinates are inconsistent")
        for line in hunk.lines:
            if line[0] in {" ", "-"}:
                if position >= len(original) or original[position] != line[1:]:
                    raise PatchPolicyError("Patch does not match the exact seeded source")
                position += 1
            if line[0] in {" ", "+"}:
                output.append(line[1:])
    output.extend(original[position:])
    candidate = "".join(output)
    if candidate == source or _utf8_size(candidate) > MAX_SOURCE_BYTES:
        raise PatchPolicyError("Patch is a no-op or candidate exceeds 32 KiB")
    return ParsedPatch(TARGET_FILE, tuple(hunks), candidate)


_LOOSE_HUNK = re.compile(r"@@ -(\d{1,9})(?:,\d{1,9})? \+\d{1,9}(?:,\d{1,9})? @@( [^\r\n]*)?\n?\Z")


def recount_unified_diff(diff: str, source: str) -> str:
    """Recompute derivable hunk metadata, like ``git apply --recount``.

    Line counts follow from each hunk body, and a start line follows from the
    single exact occurrence of the hunk's old side in ``source`` when the
    declared start does not match. Content lines are never edited or fuzzily
    matched; blank lines inside a hunk regain their context prefix. The input
    is returned unchanged whenever this is ambiguous, so the strict parser
    still decides every proposal.
    """
    lines = diff.splitlines(keepends=True)
    first = next((index for index, line in enumerate(lines) if line.startswith("@@")), None)
    if first is None:
        return diff
    original = source.splitlines(keepends=True)
    output = lines[:first]
    hunks: list[tuple[int, str, list[str]]] = []
    cursor = first
    while cursor < len(lines):
        match = _LOOSE_HUNK.fullmatch(lines[cursor])
        if match is None:
            return diff
        cursor += 1
        body: list[str] = []
        while cursor < len(lines) and not lines[cursor].startswith("@@"):
            body.append(lines[cursor])
            cursor += 1
        while body and body[-1] == "\n":
            body.pop()
        body = [" \n" if line == "\n" else line for line in body]
        if not body or any(line[:1] not in {" ", "-", "+", "\\"} for line in body):
            return diff
        hunks.append((int(match[1]), match[2] or "", body))
    position = delta = 0
    for declared, section, body in hunks:
        old = [line[1:] for line in body if line[:1] in {" ", "-"}]
        new_count = sum(1 for line in body if line[:1] in {" ", "+"})
        if not old or any(line.startswith("\\") for line in body):
            return diff
        start = declared - 1
        if original[start : start + len(old)] != old:
            found = [
                index
                for index in range(len(original) - len(old) + 1)
                if original[index : index + len(old)] == old
            ]
            if len(found) != 1:
                return diff
            start = found[0]
        if start < position:
            return diff
        output.append(f"@@ -{start + 1},{len(old)} +{start + 1 + delta},{new_count} @@{section}\n")
        output.extend(body)
        position = start + len(old)
        delta += new_count - len(old)
    return "".join(output)


_CATCH_ALL = frozenset({"Exception", "BaseException"})


def _catches_everything(handler_type: ast.expr | None) -> bool:
    """A bare ``except`` or one naming Exception/BaseException suppresses any failure."""
    if handler_type is None:
        return True
    candidates = handler_type.elts if isinstance(handler_type, ast.Tuple) else [handler_type]
    return any(isinstance(item, ast.Name) and item.id in _CATCH_ALL for item in candidates)


def validate_ast(source: str) -> tuple[bool, bool, str | None]:
    """Parse without executing and reject forbidden capabilities and aliases."""
    try:
        tree = ast.parse(source, filename=TARGET_FILE)
    except (SyntaxError, ValueError, RecursionError):
        return False, False, "Candidate contains invalid Python syntax"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            # Modules expose transitive capabilities, such as typing.sys.modules.
            return True, False, "Module imports are forbidden; import an approved symbol"
        elif isinstance(node, ast.ImportFrom):
            if node.level or node.module not in _IMPORTS:
                return True, False, "Import outside the trusted application dependencies"
            if any(alias.name not in _IMPORTS[node.module] for alias in node.names):
                return True, False, "Import outside the approved application symbols"
        elif isinstance(node, ast.Name):
            if node.id in _DANGEROUS_NAMES or node.id.startswith("__"):
                return True, False, "Forbidden dynamic execution or operating-system capability"
        elif isinstance(node, ast.Attribute):
            if node.attr in _DANGEROUS_ATTRIBUTES or node.attr.startswith("__"):
                return True, False, "Forbidden dynamic or operating-system attribute"
        elif isinstance(node, ast.ExceptHandler) and _catches_everything(node.type):
            return True, False, "Catch-all exception handlers are forbidden; handle the failure"
        elif isinstance(node, ast.MatchClass):
            if any(
                name.startswith("__") or name in _DANGEROUS_ATTRIBUTES for name in node.kwd_attrs
            ):
                return True, False, "Forbidden private attributes in class patterns"
    return True, True, None


class PatchPolicy:
    """Enforce the fixed file, byte, applicability, syntax, and AST gates."""

    def validate(
        self,
        diff: str,
        source: str,
        *,
        base_sha256: str | None = None,
    ) -> PatchValidationResult:
        """Return a canonical gate result without mutating any source file."""
        try:
            if (
                base_sha256 is not None
                and hashlib.sha256(source.encode()).hexdigest() != base_sha256
            ):
                raise PatchPolicyError("Proposal base hash is stale")
            candidate = parse_unified_diff(diff, source).patched_source
            syntax_valid, ast_safe, error = validate_ast(candidate)
            return PatchValidationResult(
                is_valid=syntax_valid and ast_safe,
                target_file=TARGET_FILE,
                syntax_valid=syntax_valid,
                ast_safe=ast_safe,
                error_message=error,
            )
        except (PatchPolicyError, RecursionError) as exc:
            return PatchValidationResult(
                is_valid=False,
                target_file=TARGET_FILE,
                syntax_valid=False,
                ast_safe=False,
                error_message=str(exc),
            )


def validate_patch(
    diff: str,
    source: str,
    *,
    base_sha256: str | None = None,
) -> PatchValidationResult:
    """Convenience entry point for callers using the stateless policy engine."""
    return PatchPolicy().validate(diff, source, base_sha256=base_sha256)
