"""Trusted subprocess API oracle used only by the simulated lifecycle tests.

This is test-host execution, never a production runtime fallback. Expectations
are authored independently of candidate pricing code and use a fresh API process.
"""

import json
import sys
from typing import Any
from uuid import UUID, uuid4


def main() -> None:
    """Exercise the actual exported FastAPI fixture and return measured assertions."""
    sys.path.insert(0, sys.argv[1])
    from fastapi.testclient import TestClient

    from app.main import app

    assertions: dict[str, bool] = {}
    client = TestClient(app, raise_server_exceptions=False)
    items = [{"product_id": "trail-mug", "quantity": 2}]
    case = str(uuid4())
    headers = {"X-Faultline-Case-Id": case}
    response = client.post("/api/checkout", json={"items": items}, headers=headers)
    order = response.json()
    is_uuid = False
    try:
        UUID(order.get("id", ""))
        is_uuid = True
    except ValueError:
        pass
    assertions.update(
        {
            "checkout.status_201": response.status_code == 201,
            "checkout.order_id_is_uuid": is_uuid,
            "checkout.line_items_match_cart": order.get("line_items")
            == [
                {
                    "product_id": "trail-mug",
                    "quantity": 2,
                    "unit_price_cents": 1999,
                    "line_total_cents": 3998,
                }
            ],
            "checkout.subtotal_matches_catalog": order.get("subtotal") == 3998,
            "checkout.no_coupon_discount_is_zero": order.get("discount") == 0,
            "checkout.total_matches_subtotal": order.get("total") == 3998,
            "checkout.exactly_one_stored_order": client.get("/api/orders", headers=headers).json()
            == {"orders": [order]},
            "checkout.readback_matches_response": client.get(
                f"/api/orders/{order.get('id', '')}",
                headers=headers,
            ).json()
            == order,
        }
    )
    if sys.argv[2] == "baseline":
        print(json.dumps(assertions))
        return

    def success(name: str, payload: dict[str, Any], subtotal: int, discount: int) -> None:
        case_headers = {"X-Faultline-Case-Id": str(uuid4())}
        result = client.post("/api/checkout", json=payload, headers=case_headers)
        body = result.json()
        assertions[f"regression.{name}"] = (
            result.status_code == 201
            and (body.get("subtotal"), body.get("discount"), body.get("total"))
            == (subtotal, discount, subtotal - discount)
            and client.get(f"/api/orders/{body.get('id', '')}", headers=case_headers).json() == body
            and client.get("/api/orders", headers=case_headers).json() == {"orders": [body]}
        )

    one = [{"product_id": "trail-mug", "quantity": 1}]
    success("missing_coupon", {"items": one}, 1999, 0)
    for name, coupon in [
        ("null_coupon", None),
        ("empty_coupon", ""),
        ("whitespace_coupon", " \t "),
        ("tenoff", "TENOFF"),
        ("fifteen", "FIFTEEN"),
        ("normalized_coupon", " tenoff "),
    ]:
        discount = (
            299 if name == "fifteen" else 199 if name in {"tenoff", "normalized_coupon"} else 0
        )
        success(name, {"items": one, "coupon_code": coupon}, 1999, discount)
    mixed = one + [{"product_id": "field-notebook", "quantity": 2}]
    success("mixed_cart", {"items": mixed}, 4999, 0)
    success("mixed_cart_coupon", {"items": mixed, "coupon_code": "TENOFF"}, 4999, 499)
    success("quantity_ten", {"items": [{"product_id": "trail-mug", "quantity": 10}]}, 19990, 0)
    invalid: list[tuple[str, dict[str, Any], int]] = [
        ("empty_cart", {"items": []}, 422),
        ("duplicate_product", {"items": one + one}, 422),
        ("unknown_product", {"items": [{"product_id": "unknown", "quantity": 1}]}, 422),
        ("unknown_coupon", {"items": one, "coupon_code": "unknown"}, 400),
        ("invalid_coupon_type", {"items": one, "coupon_code": 5}, 422),
        ("client_price", {"items": [{**one[0], "price": 1}]}, 422),
        ("unknown_fields", {"items": one, "unknown": True}, 422),
    ]
    for name, quantity in [
        ("zero", 0),
        ("eleven", 11),
        ("negative", -1),
        ("fraction", 1.5),
        ("string", "2"),
        ("boolean", True),
        ("null", None),
    ]:
        invalid.append((f"quantity_{name}", {"items": [{**one[0], "quantity": quantity}]}, 422))
    invalid.append(("quantity_missing", {"items": [{"product_id": "trail-mug"}]}, 422))
    for name, payload, status in invalid:
        case_headers = {"X-Faultline-Case-Id": str(uuid4())}
        result = client.post("/api/checkout", json=payload, headers=case_headers)
        assertions[f"regression.{name}"] = result.status_code == status and client.get(
            "/api/orders", headers=case_headers
        ).json() == {"orders": []}
    assertions["regression.unknown_order"] = client.get("/api/orders/unknown").status_code == 404
    assertions["regression.unknown_product_readback"] = (
        client.get(
            "/api/products/unknown",
        ).status_code
        == 404
    )
    success("confirmation", {"items": items}, 3998, 0)
    assertions["confirmation.checkout"] = assertions.pop("regression.confirmation")
    print(json.dumps(assertions))


if __name__ == "__main__":
    main()
