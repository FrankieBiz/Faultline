"""Business cases for the trusted healthy snapshot, through the real API."""

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    "coupon", [{}, {"coupon_code": None}, {"coupon_code": ""}, {"coupon_code": " \t "}]
)
def test_optional_coupon_family_is_healthy(
    healthy_client: TestClient, coupon: dict[str, object]
) -> None:
    response = healthy_client.post(
        "/api/checkout", json={"items": [{"product_id": "trail-mug", "quantity": 1}], **coupon}
    )
    assert response.status_code == 201
    order = response.json()
    assert (order["subtotal"], order["discount"], order["total"]) == (1999, 0, 1999)
    assert healthy_client.get(f"/api/orders/{order['id']}").json() == order
    assert healthy_client.get("/api/orders").json() == {"orders": [order]}


@pytest.mark.parametrize(
    ("coupon", "discount", "total"),
    [(None, 0, 4999), ("TENOFF", 499, 4500), ("FIFTEEN", 749, 4250)],
)
def test_mixed_cart_pricing(
    healthy_client: TestClient, coupon: str | None, discount: int, total: int
) -> None:
    response = healthy_client.post(
        "/api/checkout",
        json={
            "items": [
                {"product_id": "trail-mug", "quantity": 1},
                {"product_id": "field-notebook", "quantity": 2},
            ],
            "coupon_code": coupon,
        },
    )
    assert response.status_code == 201
    order = response.json()
    assert order["line_items"] == [
        {
            "product_id": "trail-mug",
            "quantity": 1,
            "unit_price_cents": 1999,
            "line_total_cents": 1999,
        },
        {
            "product_id": "field-notebook",
            "quantity": 2,
            "unit_price_cents": 1500,
            "line_total_cents": 3000,
        },
    ]
    assert (order["subtotal"], order["discount"], order["total"]) == (4999, discount, total)


def test_maximum_quantities_without_coupon(healthy_client: TestClient) -> None:
    response = healthy_client.post(
        "/api/checkout",
        json={
            "items": [
                {"product_id": "trail-mug", "quantity": 10},
                {"product_id": "field-notebook", "quantity": 10},
            ]
        },
    )
    assert response.status_code == 201
    order = response.json()
    assert (order["subtotal"], order["discount"], order["total"]) == (34990, 0, 34990)


@pytest.mark.parametrize(
    ("coupon", "discount", "total"),
    [("TENOFF", 199, 1800), (" tenoff ", 199, 1800), ("FIFTEEN", 299, 1700)],
)
def test_healthy_coupon_controls(
    healthy_client: TestClient, coupon: str, discount: int, total: int
) -> None:
    response = healthy_client.post(
        "/api/checkout",
        json={"items": [{"product_id": "trail-mug", "quantity": 1}], "coupon_code": coupon},
    )
    assert response.status_code == 201
    order = response.json()
    assert (order["subtotal"], order["discount"], order["total"]) == (1999, discount, total)
