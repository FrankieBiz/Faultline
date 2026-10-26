"""Storage isolation, defensive copies, and namespace-aware HTTP readback."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.orders import Order, create_order, get_orders


def order_record(order_id: str) -> Order:
    """Create an independent synthetic order for storage-only tests."""
    return {
        "id": order_id,
        "line_items": [
            {
                "product_id": "trail-mug",
                "quantity": 1,
                "unit_price_cents": 1999,
                "line_total_cents": 1999,
            }
        ],
        "subtotal": 1999,
        "discount": 199,
        "total": 1800,
    }


def test_store_isolates_namespaces(namespace: str) -> None:
    first = create_order(namespace, order_record("same-id"))
    second = create_order(namespace + "-other", order_record("same-id"))
    assert get_orders(namespace) == [first]
    assert get_orders(namespace + "-other") == [second]
    assert get_orders(namespace + "-missing") == []


def test_storage_owns_deep_copies(namespace: str) -> None:
    original = order_record("immutable-copy")
    returned = create_order(namespace, original)
    original["line_items"][0]["quantity"] = 10
    returned["line_items"].clear()
    fetched = get_orders(namespace)
    fetched[0]["line_items"][0]["unit_price_cents"] = 0
    fetched.clear()
    assert get_orders(namespace) == [order_record("immutable-copy")]


def test_duplicate_order_id_is_rejected_atomically(namespace: str) -> None:
    create_order(namespace, order_record("existing"))
    with pytest.raises(ValueError, match="already exists"):
        create_order(namespace, order_record("existing"))
    assert get_orders(namespace) == [order_record("existing")]


def test_concurrent_creates_are_not_lost(namespace: str) -> None:
    def insert(index: int) -> Order:
        return create_order(namespace, order_record(str(index)))

    with ThreadPoolExecutor(max_workers=8) as executor:
        created = list(executor.map(insert, range(32)))
    assert {order["id"] for order in get_orders(namespace)} == {order["id"] for order in created}
    assert len(get_orders(namespace)) == 32


def test_http_namespace_isolation(client: TestClient, namespace: str) -> None:
    response = client.post(
        "/api/checkout",
        json={"items": [{"product_id": "trail-mug", "quantity": 1}], "coupon_code": "TENOFF"},
    )
    assert response.status_code == 201
    order = response.json()
    other = {"X-Faultline-Case-Id": namespace + "-other"}
    assert client.get("/api/orders", headers=other).json() == {"orders": []}
    assert client.get(f"/api/orders/{order['id']}", headers=other).status_code == 404
    assert client.get("/api/orders").json() == {"orders": [order]}
    assert client.get(f"/api/orders/{order['id']}").json() == order
    assert client.get(f"/api/orders/{uuid4()}").status_code == 404


def test_missing_namespace_header_defaults_to_demo(client: TestClient) -> None:
    del client.headers["X-Faultline-Case-Id"]
    before = get_orders("demo")
    response = client.post(
        "/api/checkout",
        json={"items": [{"product_id": "field-notebook", "quantity": 1}], "coupon_code": "TENOFF"},
    )
    assert response.status_code == 201
    assert get_orders("demo") == [*before, response.json()]
    assert client.get(f"/api/orders/{response.json()['id']}").json() == response.json()


def test_namespace_is_an_opaque_key(namespace: str) -> None:
    key = "../../" + namespace
    expected = create_order(key, order_record("path-looking-key"))
    assert get_orders(key) == [expected]
    assert get_orders(namespace) == []
