"""Server-owned scenario definitions; callers cannot select repair paths."""

from pydantic import BaseModel, ConfigDict


class Scenario(BaseModel):
    """A fixed repair target, failure fingerprint, and assertion identifiers."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    id: str
    title: str
    description: str
    target_file: str
    route: str
    error_fingerprint: str
    expected_assertions: list[str]


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
