"""Create synthetic orders from catalog prices and normalized coupon codes."""

from typing import cast
from uuid import uuid4

from fastapi import HTTPException

from app.catalog import get_product
from app.orders import LineItem, Order, create_order
from app.schemas import CheckoutRequest


def checkout(payload: CheckoutRequest, namespace: str = "demo") -> Order:
    """Validate coupon eligibility, price the cart, and persist a new order.

    Percentage discounts are truncated to whole cents using integer arithmetic.
    Input validation precedes pricing and storage, so rejected carts create no
    synthetic orders.
    """
    line_items: list[LineItem] = []
    for item in payload.items:
        product = get_product(item.product_id)
        if product is None:
            raise HTTPException(status_code=422, detail="Unknown product ID")
        line_items.append(
            {
                "product_id": product["id"],
                "quantity": item.quantity,
                "unit_price_cents": product["price_cents"],
                "line_total_cents": product["price_cents"] * item.quantity,
            }
        )

    subtotal = sum(item["line_total_cents"] for item in line_items)
    coupon_code = (payload.coupon_code or "").strip().upper()
    discounts: dict[str, int | None] = {
        "TENOFF": line_items[0]["line_total_cents"] // 10,
        "FIFTEEN": line_items[0]["line_total_cents"] * 15 // 100,
    }
    if coupon_code and coupon_code not in discounts:
        raise HTTPException(status_code=400, detail="Invalid coupon code")

    discount = cast(int, discounts.get(coupon_code, 0))
    total = subtotal - discount
    order: Order = {
        "id": str(uuid4()),
        "line_items": line_items,
        "subtotal": subtotal,
        "discount": discount,
        "total": total,
    }
    return create_order(namespace, order)
