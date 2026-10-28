"""Tests for semantic AST analysis and safety gates."""

from app.ast_analyzer import ASTAnalysisResult, ASTAnalyzer
from app.policy import PatchPolicy

ORIGINAL_SOURCE = """
def checkout(payload: dict) -> dict:
    discounts = {"TENOFF": 10}
    coupon = payload.get("coupon")
    discount = discounts.get(coupon)
    total = 100 - discount
    return {"total": total}
"""

GUARDED_SOURCE = """
def checkout(payload: dict) -> dict:
    discounts = {"TENOFF": 10}
    coupon = payload.get("coupon")
    discount = discounts.get(coupon, 0)
    total = 100 - discount
    return {"total": total}
"""

DANGEROUS_SOURCE = """
def checkout(payload: dict) -> dict:
    import os
    os.system("echo compromised")
    return {"total": 0}
"""

SYNTAX_ERROR_SOURCE = """
def checkout(payload: dict) -> dict:
    this is invalid python syntax %%%
"""


def test_ast_analyzer_detects_dict_get_default_zero() -> None:
    analyzer = ASTAnalyzer(target_function="checkout")
    result = analyzer.analyze(ORIGINAL_SOURCE, GUARDED_SOURCE)

    assert isinstance(result, ASTAnalysisResult)
    assert result.syntax_valid is True
    assert result.ast_safe is True
    assert result.defect_guarded is True
    assert "dict_get_default_zero" in result.guards_detected
    assert "checkout" in result.target_function
    assert result.error_message is None


def test_ast_analyzer_detects_boolean_or_zero() -> None:
    source = """
def checkout(payload: dict) -> dict:
    discounts = {"TENOFF": 10}
    coupon = payload.get("coupon")
    discount = discounts.get(coupon) or 0
    total = 100 - discount
    return {"total": total}
"""
    analyzer = ASTAnalyzer(target_function="checkout")
    result = analyzer.analyze(ORIGINAL_SOURCE, source)

    assert result.syntax_valid is True
    assert result.ast_safe is True
    assert result.defect_guarded is True
    assert "boolean_or_zero_fallback" in result.guards_detected


def test_ast_analyzer_rejects_dangerous_calls() -> None:
    analyzer = ASTAnalyzer(target_function="checkout")
    result = analyzer.analyze(ORIGINAL_SOURCE, DANGEROUS_SOURCE)

    assert result.syntax_valid is True
    assert result.ast_safe is False
    assert result.defect_guarded is False
    assert result.error_message is not None
    assert "Forbidden" in result.error_message


def test_ast_analyzer_handles_syntax_errors() -> None:
    analyzer = ASTAnalyzer(target_function="checkout")
    result = analyzer.analyze(ORIGINAL_SOURCE, SYNTAX_ERROR_SOURCE)

    assert result.syntax_valid is False
    assert result.ast_safe is False
    assert result.defect_guarded is False
    assert "Syntax error" in (result.error_message or "")


def test_policy_validate_with_analysis_integration() -> None:
    from pathlib import Path

    root = Path(__file__).parents[3]
    seed_path = root / "apps/buggyshop-backend/app/routes/checkout.py"
    if not seed_path.is_file():
        return

    source = seed_path.read_text()
    diff = """--- a/apps/buggyshop-backend/app/routes/checkout.py
+++ b/apps/buggyshop-backend/app/routes/checkout.py
@@ -43,2 +43,2 @@
-    discount = cast(int, discounts.get(coupon_code))
+    discount = cast(int, discounts.get(coupon_code, 0))
     total = subtotal - discount
"""
    policy = PatchPolicy()
    validation, analysis = policy.validate_with_analysis(diff, source)

    assert validation.is_valid is True
    assert analysis.syntax_valid is True
    assert analysis.ast_safe is True
    assert analysis.defect_guarded is True
    assert "dict_get_default_zero" in analysis.guards_detected
