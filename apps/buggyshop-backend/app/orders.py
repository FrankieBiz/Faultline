"""Thread-safe, process-local synthetic order storage with case isolation."""

from copy import deepcopy
from threading import Lock
from typing import TypedDict


class LineItem(TypedDict):
    """A purchased quantity with catalog-derived unit and extended prices."""

    product_id: str
    quantity: int
    unit_price_cents: int
    line_total_cents: int


class Order(TypedDict):
    """Checkout response and stored order; all amounts are USD cents."""

    id: str
    line_items: list[LineItem]
    subtotal: int
    discount: int
    total: int


_orders: dict[str, list[Order]] = {}
_lock = Lock()


def create_order(namespace: str, order_dict: Order) -> Order:
    """Store and return independent copies of an order in one case namespace.

    Duplicate IDs within the namespace are rejected without changing the store.
    Namespace strings are opaque in-memory keys and are never used as paths.
    """
    with _lock:
        existing = _orders.setdefault(namespace, [])
        if any(order["id"] == order_dict["id"] for order in existing):
            raise ValueError("Order ID already exists in this namespace")
        existing.append(deepcopy(order_dict))
        return deepcopy(order_dict)


def get_orders(namespace: str) -> list[Order]:
    """Read independent order snapshots without creating an empty namespace."""
    with _lock:
        return deepcopy(_orders.get(namespace, []))
