"""Semantic AST analysis and safety gate compiler for repair patches.

Inspects Python AST structures to verify syntax, security boundaries,
and semantic defect guarding before containerized execution.
"""

from __future__ import annotations

import ast

from shared.contracts.models import ContractModel

_DANGEROUS_CALLS = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
        "open",
        "input",
        "system",
        "popen",
        "spawn",
        "fork",
    }
)


class ASTAnalysisResult(ContractModel):
    """Structured inspection result of candidate source AST."""

    syntax_valid: bool
    ast_safe: bool
    defect_guarded: bool
    target_function: str
    affected_symbols: list[str]
    guards_detected: list[str]
    complexity_delta: int
    error_message: str | None = None


class ASTAnalyzer:
    """Static AST inspector evaluating semantic soundness and safety of patches."""

    def __init__(self, target_function: str = "checkout") -> None:
        self.target_function = target_function

    def analyze(self, original_source: str, patched_source: str) -> ASTAnalysisResult:
        """Analyze patched Python source against the original baseline."""
        try:
            patched_tree = ast.parse(patched_source)
        except (SyntaxError, ValueError, RecursionError) as exc:
            return ASTAnalysisResult(
                syntax_valid=False,
                ast_safe=False,
                defect_guarded=False,
                target_function=self.target_function,
                affected_symbols=[],
                guards_detected=[],
                complexity_delta=0,
                error_message=f"Syntax error: {exc}",
            )

        try:
            original_tree = ast.parse(original_source)
            orig_complexity = self._count_nodes(original_tree)
        except Exception:
            orig_complexity = 0

        patched_complexity = self._count_nodes(patched_tree)
        complexity_delta = patched_complexity - orig_complexity

        # 1. Check safety: disallow dangerous calls and attributes
        safe, safety_err = self._check_safety(patched_tree)
        if not safe:
            return ASTAnalysisResult(
                syntax_valid=True,
                ast_safe=False,
                defect_guarded=False,
                target_function=self.target_function,
                affected_symbols=[],
                guards_detected=[],
                complexity_delta=complexity_delta,
                error_message=safety_err,
            )

        # 2. Extract affected symbols in target function
        symbols, guards = self._inspect_target_function(patched_tree)
        defect_guarded = len(guards) > 0

        return ASTAnalysisResult(
            syntax_valid=True,
            ast_safe=True,
            defect_guarded=defect_guarded,
            target_function=self.target_function,
            affected_symbols=sorted(symbols),
            guards_detected=guards,
            complexity_delta=complexity_delta,
            error_message=None,
        )

    def _check_safety(self, tree: ast.AST) -> tuple[bool, str | None]:
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in _DANGEROUS_CALLS:
                return False, f"Forbidden dangerous call: {node.id}"
            if isinstance(node, ast.Attribute) and node.attr in _DANGEROUS_CALLS:
                return False, f"Forbidden dangerous attribute: {node.attr}"
        return True, None

    def _inspect_target_function(self, tree: ast.AST) -> tuple[set[str], list[str]]:
        symbols: set[str] = set()
        guards: list[str] = []

        target_def: ast.FunctionDef | None = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == self.target_function:
                target_def = node
                break

        if target_def is None:
            return symbols, guards

        for node in ast.walk(target_def):
            if isinstance(node, ast.Name):
                symbols.add(node.id)

            # Detect NoneType guards on discount or subtraction
            # Case A: discount = ... or 0
            if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
                for val in node.values:
                    if isinstance(val, ast.Constant) and val.value == 0:
                        guards.append("boolean_or_zero_fallback")

            # Case B: if discount is None / if not discount
            if isinstance(node, ast.If):
                test_str = ast.unparse(node.test)
                if "discount" in test_str and ("None" in test_str or "not" in test_str):
                    guards.append("conditional_discount_none_check")

            # Case C: discounts.get(coupon_code, 0)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "get" and len(node.args) >= 2:
                    arg1 = node.args[1]
                    if isinstance(arg1, ast.Constant) and arg1.value == 0:
                        guards.append("dict_get_default_zero")

            # Case D: ternary: 0 if discount is None else discount
            if isinstance(node, ast.IfExp):
                test_str = ast.unparse(node.test)
                if "discount" in test_str or "None" in test_str:
                    guards.append("ternary_discount_guard")

            # Case E: default dictionary: discounts: dict[str, int] = ...
            if isinstance(node, ast.Dict):
                # Check if "" or None is mapped to 0
                for k, v in zip(node.keys, node.values, strict=False):
                    if k is not None and isinstance(k, ast.Constant) and k.value in {"", None}:
                        if isinstance(v, ast.Constant) and v.value == 0:
                            guards.append("discount_map_empty_key_zero")

        return symbols, guards

    @staticmethod
    def _count_nodes(tree: ast.AST) -> int:
        return sum(1 for _ in ast.walk(tree))
