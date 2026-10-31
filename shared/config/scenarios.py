"""Operator-owned scenario metadata and the optional built-in checkout registry.

Project runs build an installation-local registry from validated TOML/ReproSpec
configuration; they never mutate this compatibility registry.
"""

from pydantic import BaseModel, ConfigDict, Field


class Scenario(BaseModel):
    """An admitted repair target, failure fingerprint, and assertion identifiers."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    id: str
    title: str
    description: str
    target_file: str
    route: str
    error_fingerprint: str
    expected_assertions: list[str]
    executor: str = "checkout"
    regression_assertions: list[str] = Field(default_factory=list)


REGISTRY: dict[str, Scenario] = {
    "scripted_checkout_repair": Scenario(
        id="scripted_checkout_repair",
        title="Scripted checkout repair",
        description=(
            "Optional-coupon backend defect causing TypeError during arithmetic "
            "when coupon is omitted or empty"
        ),
        target_file="apps/buggyshop-backend/app/routes/checkout.py",
        route="POST /api/checkout",
        error_fingerprint=("TypeError: unsupported operand type(s) for -: 'int' and 'NoneType'"),
        expected_assertions=[
            "checkout.status_201",
            "checkout.order_id_is_uuid",
            "checkout.line_items_match_cart",
            "checkout.subtotal_matches_catalog",
            "checkout.no_coupon_discount_is_zero",
            "checkout.total_matches_subtotal",
            "checkout.exactly_one_stored_order",
            "checkout.readback_matches_response",
        ],
    ),
}
