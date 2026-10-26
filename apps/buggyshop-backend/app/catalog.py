"""Fixed catalog owned by the backend; monetary amounts are integer cents."""

from typing import TypedDict


class Product(TypedDict):
    """Public catalog product; clients never supply its price at checkout."""

    id: str
    name: str
    price_cents: int


_CATALOG: tuple[Product, ...] = (
    {"id": "trail-mug", "name": "Trail Mug", "price_cents": 1999},
    {"id": "field-notebook", "name": "Field Notebook", "price_cents": 1500},
)


def get_catalog() -> list[Product]:
    """Return catalog copies so callers cannot mutate trusted prices."""
    return [product.copy() for product in _CATALOG]


def get_product(product_id: str) -> Product | None:
    """Return an independent product record, or None for an unknown ID."""
    return next((product.copy() for product in _CATALOG if product["id"] == product_id), None)
