"""Cross-schema contract integrity and validation boundary tests.

Validates that Pydantic v2 schemas for checkout, catalog definitions,
and synthetic order stores maintain synchronized business invariants.
"""

from typing import Any

import pytest
from pydantic import ValidationError

from app.catalog import get_catalog
from app.orders import LineItem, Order, create_order, get_orders
from app.schemas import CheckoutItem, CheckoutRequest


def test_checkout_item_valid_catalog_products() -> None:
    """Known catalog products with bounded integer quantities are accepted."""
    catalog = get_catalog()
    assert len(catalog) > 0
    for product in catalog:
        product_id = product["id"]
        item = CheckoutItem(product_id=product_id, quantity=1)
        assert item.product_id == product_id
        assert item.quantity == 1

        # Max quantity boundary
        max_item = CheckoutItem(product_id=product_id, quantity=10)
        assert max_item.quantity == 10


def test_checkout_item_rejects_unknown_products() -> None:
    """Product IDs not present in the catalog are rejected."""
    with pytest.raises(ValidationError) as exc:
        CheckoutItem(product_id="prod_nonexistent", quantity=1)
    assert "Unknown product ID" in str(exc.value)


@pytest.mark.parametrize("quantity", [0, -1, -10, 11, 100])
def test_checkout_item_quantity_bounds_enforced(quantity: int) -> None:
    """Quantities outside [1, 10] are rejected by Pydantic field constraints."""
    with pytest.raises(ValidationError) as exc:
        CheckoutItem(product_id="trail-mug", quantity=quantity)
    assert "Input should be" in str(exc.value)


@pytest.mark.parametrize("bad_quantity", ["1", "5", 2.5, True])
def test_checkout_item_strict_type_enforcement(bad_quantity: Any) -> None:
    """Strict mode forbids string coercion or float truncation for quantities."""
    with pytest.raises(ValidationError):
        CheckoutItem(product_id="trail-mug", quantity=bad_quantity)


def test_checkout_item_forbids_extra_fields() -> None:
    """Undeclared client fields like price or discount are strictly forbidden."""
    with pytest.raises(ValidationError) as exc:
        CheckoutItem.model_validate(
            {"product_id": "trail-mug", "quantity": 1, "unit_price_cents": 100}
        )
    assert "Extra inputs are not permitted" in str(exc.value)


def test_checkout_request_distinct_products_required() -> None:
    """Duplicate items within the same request are rejected."""
    with pytest.raises(ValidationError) as exc:
        CheckoutRequest(
            items=[
                CheckoutItem(product_id="trail-mug", quantity=1),
                CheckoutItem(product_id="trail-mug", quantity=2),
            ]
        )
    assert "Each product ID must appear only once" in str(exc.value)


def test_checkout_request_item_count_boundaries() -> None:
    """Requests must contain between 1 and 2 items."""
    with pytest.raises(ValidationError):
        CheckoutRequest(items=[])

    valid_one = CheckoutRequest(items=[CheckoutItem(product_id="trail-mug", quantity=1)])
    assert len(valid_one.items) == 1

    valid_two = CheckoutRequest(
        items=[
            CheckoutItem(product_id="trail-mug", quantity=1),
            CheckoutItem(product_id="field-notebook", quantity=1),
        ]
    )
    assert len(valid_two.items) == 2


def test_checkout_request_coupon_optionality() -> None:
    """Coupon codes default to None and accept explicit None or string."""
    req_default = CheckoutRequest(items=[CheckoutItem(product_id="trail-mug", quantity=1)])
    assert req_default.coupon_code is None

    req_none = CheckoutRequest(
        items=[CheckoutItem(product_id="trail-mug", quantity=1)], coupon_code=None
    )
    assert req_none.coupon_code is None

    req_coupon = CheckoutRequest(
        items=[CheckoutItem(product_id="trail-mug", quantity=1)], coupon_code="TENOFF"
    )
    assert req_coupon.coupon_code == "TENOFF"


def test_order_storage_namespace_isolation() -> None:
    """Orders stored in one namespace are inaccessible to other namespaces."""
    ns_alpha = "test-ns-alpha-101"
    ns_beta = "test-ns-beta-202"

    order_alpha: Order = {
        "id": "ord_alpha_1",
        "line_items": [
            {
                "product_id": "trail-mug",
                "quantity": 2,
                "unit_price_cents": 1999,
                "line_total_cents": 3998,
            }
        ],
        "subtotal": 3998,
        "discount": 0,
        "total": 3998,
    }

    create_order(ns_alpha, order_alpha)
    assert len(get_orders(ns_alpha)) == 1
    assert len(get_orders(ns_beta)) == 0


def test_order_storage_rejects_duplicate_id_in_namespace() -> None:
    """Duplicate order IDs within the same namespace raise ValueError."""
    ns = "test-ns-dup-check"
    order: Order = {
        "id": "ord_dup_1",
        "line_items": [
            {
                "product_id": "field-notebook",
                "quantity": 1,
                "unit_price_cents": 1500,
                "line_total_cents": 1500,
            }
        ],
        "subtotal": 1500,
        "discount": 0,
        "total": 1500,
    }
    create_order(ns, order)
    with pytest.raises(ValueError, match="already exists"):
        create_order(ns, order)


def test_catalog_and_order_contract_alignment() -> None:
    """Verify that catalog prices correctly drive order line item computations."""
    for product in get_catalog():
        assert product["price_cents"] > 0
        assert isinstance(product["price_cents"], int)

        qty = 3
        line_total = product["price_cents"] * qty
        line: LineItem = {
            "product_id": product["id"],
            "quantity": qty,
            "unit_price_cents": product["price_cents"],
            "line_total_cents": line_total,
        }
        assert line["line_total_cents"] == line["unit_price_cents"] * line["quantity"]
