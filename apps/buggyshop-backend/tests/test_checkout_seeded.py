"""Prove the seed fails only the intended optional-coupon checkout family."""

import logging
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.orders import get_orders
from app.routes.checkout import checkout
from app.schemas import CheckoutRequest
from shared.config import REGISTRY

FINGERPRINT = "TypeError: unsupported operand type(s) for -: 'int' and 'NoneType'"
NO_COUPONS: list[dict[str, object]] = [
    {},
    {"coupon_code": None},
    {"coupon_code": ""},
    {"coupon_code": " \t\n "},
]


@pytest.mark.parametrize("coupon", NO_COUPONS, ids=["missing", "null", "empty", "whitespace"])
def test_no_coupon_raises_exact_type_error(coupon: dict[str, object], namespace: str) -> None:
    payload = CheckoutRequest.model_validate(
        {"items": [{"product_id": "trail-mug", "quantity": 2}], **coupon}
    )
    with pytest.raises(TypeError) as error:
        checkout(payload, namespace)
    assert f"TypeError: {error.value}" == FINGERPRINT
    assert get_orders(namespace) == []


@pytest.mark.parametrize("coupon", NO_COUPONS, ids=["missing", "null", "empty", "whitespace"])
def test_no_coupon_http_failure_has_correlated_evidence(
    client: TestClient, namespace: str, coupon: dict[str, object], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="buggyshop.api"):
        response = client.post(
            "/api/checkout",
            json={"items": [{"product_id": "trail-mug", "quantity": 2}], **coupon},
            headers={"Origin": "http://localhost:3000"},
        )
    assert response.status_code == 500
    assert response.json() == {"detail": FINGERPRINT}
    assert "Traceback" not in response.text
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:3000"
    failures = [record for record in caplog.records if record.name == "buggyshop.api"]
    assert len(failures) == 1
    record = failures[0]
    assert record.getMessage() == FINGERPRINT
    assert record.__dict__["case_id"] == namespace
    assert record.__dict__["request_id"] == response.headers["X-Request-Id"]
    assert record.__dict__["route"] == "/api/checkout"
    assert record.exc_info is not None
    assert record.exc_info[0] is TypeError
    assert client.get("/api/orders").json() == {"orders": []}


@pytest.mark.parametrize(
    ("coupon", "quantity", "discount", "total"),
    [
        ("TENOFF", 1, 199, 1800),
        (" tenoff ", 2, 399, 3599),
        ("FIFTEEN", 1, 299, 1700),
        (" fifteen ", 2, 599, 3399),
        ("TENOFF", 10, 1999, 17991),
    ],
)
def test_recognized_coupon_controls(
    client: TestClient, coupon: str, quantity: int, discount: int, total: int
) -> None:
    response = client.post(
        "/api/checkout",
        json={"items": [{"product_id": "trail-mug", "quantity": quantity}], "coupon_code": coupon},
    )
    assert response.status_code == 201
    order = response.json()
    assert str(UUID(order["id"])) == order["id"]
    assert order == {
        "id": order["id"],
        "line_items": [
            {
                "product_id": "trail-mug",
                "quantity": quantity,
                "unit_price_cents": 1999,
                "line_total_cents": 1999 * quantity,
            }
        ],
        "subtotal": 1999 * quantity,
        "discount": discount,
        "total": total,
    }
    assert client.get(f"/api/orders/{order['id']}").json() == order
    assert client.get("/api/orders").json() == {"orders": [order]}


@pytest.mark.parametrize("coupon", ["UNKNOWN", "DEMO10", "  bad  "])
def test_unknown_coupon_is_400_and_creates_no_order(client: TestClient, coupon: str) -> None:
    response = client.post(
        "/api/checkout",
        json={"items": [{"product_id": "trail-mug", "quantity": 1}], "coupon_code": coupon},
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid coupon code"}
    assert client.get("/api/orders").json() == {"orders": []}


def test_registered_fingerprint_matches_observed_exception() -> None:
    assert REGISTRY["scripted_checkout_repair"].error_fingerprint == FINGERPRINT
