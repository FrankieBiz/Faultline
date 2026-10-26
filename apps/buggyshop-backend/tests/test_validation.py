"""Invalid requests must fail before arithmetic and never create orders."""

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize("quantity", [0, 11, -1, 1.5, 2.0, "2", True, False, None])
def test_quantity_is_a_strict_bounded_integer(client: TestClient, quantity: object) -> None:
    response = client.post(
        "/api/checkout",
        json={
            "items": [{"product_id": "trail-mug", "quantity": quantity}],
            "coupon_code": "TENOFF",
        },
    )
    assert response.status_code == 422
    assert client.get("/api/orders").json() == {"orders": []}


@pytest.mark.parametrize(
    "items",
    [
        [],
        None,
        "trail-mug",
        [{"product_id": "trail-mug"}],
        [{"product_id": "unknown", "quantity": 1}],
        [{"quantity": 1}],
        [{"product_id": 1, "quantity": 1}],
        [{"product_id": "trail-mug", "quantity": 1}] * 2,
        [{"product_id": "trail-mug", "quantity": 1}] * 3,
        [{"product_id": "trail-mug", "quantity": 1, "price_cents": 1}],
        [{"product_id": "trail-mug", "quantity": 1, "unexpected": "field"}],
    ],
)
def test_invalid_cart_is_422(client: TestClient, items: object) -> None:
    response = client.post("/api/checkout", json={"items": items, "coupon_code": "TENOFF"})
    assert response.status_code == 422
    assert client.get("/api/orders").json() == {"orders": []}


@pytest.mark.parametrize("coupon", [True, 10, 1.5, [], {}])
def test_coupon_type_is_strict(client: TestClient, coupon: object) -> None:
    response = client.post(
        "/api/checkout",
        json={"items": [{"product_id": "trail-mug", "quantity": 1}], "coupon_code": coupon},
    )
    assert response.status_code == 422
    assert client.get("/api/orders").json() == {"orders": []}


@pytest.mark.parametrize("body", [{}, {"coupon_code": "TENOFF"}, [], None])
def test_missing_cart_or_invalid_body_is_422(client: TestClient, body: object) -> None:
    response = client.post("/api/checkout", json=body)
    assert response.status_code == 422
    assert client.get("/api/orders").json() == {"orders": []}


@pytest.mark.parametrize("field", ["price", "subtotal", "discount", "total", "namespace"])
def test_unknown_checkout_fields_are_rejected(client: TestClient, field: str) -> None:
    response = client.post(
        "/api/checkout",
        json={
            "items": [{"product_id": "trail-mug", "quantity": 1}],
            "coupon_code": "TENOFF",
            field: 1,
        },
    )
    assert response.status_code == 422
    assert client.get("/api/orders").json() == {"orders": []}


def test_invalid_checkout_does_not_remove_an_existing_order(client: TestClient) -> None:
    created = client.post(
        "/api/checkout",
        json={"items": [{"product_id": "trail-mug", "quantity": 1}], "coupon_code": "TENOFF"},
    )
    assert created.status_code == 201
    assert client.post("/api/checkout", json={"items": []}).status_code == 422
    assert client.get("/api/orders").json() == {"orders": [created.json()]}
