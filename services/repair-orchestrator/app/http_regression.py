"""Independent trusted HTTP oracle; never import a candidate Python module."""

from typing import Any
from uuid import UUID, uuid4

import httpx

from shared.contracts.models import AssertionResult


async def regression(client: httpx.AsyncClient) -> list[AssertionResult]:
    """Measure the fixed business cases against an isolated backend over HTTP."""
    assertions: list[AssertionResult] = []

    def record(name: str, passed: bool, expected: str, observed: str) -> None:
        assertions.append(
            AssertionResult(
                id=f"regression.{name}",
                passed=passed,
                expected=expected,
                observed=observed,
                duration_ms=0.0,
            )
        )

    async def success(name: str, items: list[dict[str, Any]], coupon: Any = "__missing__") -> None:
        headers = {"X-Faultline-Case-Id": str(uuid4())}
        payload: dict[str, Any] = {"items": items}
        if coupon != "__missing__":
            payload["coupon_code"] = coupon
        result = await client.post("/api/checkout", json=payload, headers=headers)
        body = result.json()
        prices = {"trail-mug": 1999, "field-notebook": 1500}
        expected_lines = [
            {
                "product_id": item["product_id"],
                "quantity": item["quantity"],
                "unit_price_cents": prices[item["product_id"]],
                "line_total_cents": prices[item["product_id"]] * item["quantity"],
            }
            for item in items
        ]
        subtotal = sum(item["line_total_cents"] for item in expected_lines)
        normalized = coupon.strip().upper() if isinstance(coupon, str) else ""
        discount = (
            subtotal // 10
            if normalized == "TENOFF"
            else (subtotal * 15 // 100 if normalized == "FIFTEEN" else 0)
        )
        expected = {
            "line_items": expected_lines,
            "subtotal": subtotal,
            "discount": discount,
            "total": subtotal - discount,
        }
        identity = body.get("id") if isinstance(body, dict) else None
        valid_identity = False
        try:
            valid_identity = isinstance(identity, str) and str(UUID(identity)) == identity
        except (ValueError, TypeError):
            pass
        valid = (
            result.status_code == 201
            and isinstance(body, dict)
            and set(body) == {"id", *expected}
            and valid_identity
            and all(body.get(key) == value for key, value in expected.items())
            and all(type(body.get(key)) is int for key in ("subtotal", "discount", "total"))
        )
        orders = await client.get("/api/orders", headers=headers)
        valid = valid and orders.status_code == 200 and orders.json() == {"orders": [body]}
        if valid_identity:
            readback = await client.get(f"/api/orders/{identity}", headers=headers)
            valid = valid and readback.status_code == 200 and readback.json() == body
        record(name, valid, str(expected), f"HTTP {result.status_code}: {str(body)[:1024]}")

    one = [{"product_id": "trail-mug", "quantity": 1}]
    await success("missing_coupon", one)
    for name, coupon in (
        ("null_coupon", None),
        ("empty_coupon", ""),
        ("whitespace_coupon", " \t "),
        ("tenoff", "TENOFF"),
        ("fifteen", "FIFTEEN"),
        ("normalized_coupon", " tenoff "),
    ):
        await success(name, one, coupon)
    mixed = one + [{"product_id": "field-notebook", "quantity": 2}]
    await success("mixed_cart", mixed)
    await success("mixed_cart_coupon", mixed, "TENOFF")
    await success("quantity_ten", [{"product_id": "trail-mug", "quantity": 10}])
    invalid: list[tuple[str, dict[str, Any], int]] = [
        ("empty_cart", {"items": []}, 422),
        ("duplicate_product", {"items": one + one}, 422),
        ("unknown_product", {"items": [{"product_id": "unknown", "quantity": 1}]}, 422),
        ("unknown_coupon", {"items": one, "coupon_code": "unknown"}, 400),
        ("invalid_coupon_type", {"items": one, "coupon_code": 5}, 422),
        ("client_price", {"items": [{**one[0], "price": 1}]}, 422),
        ("unknown_fields", {"items": one, "unknown": True}, 422),
        ("quantity_missing", {"items": [{"product_id": "trail-mug"}]}, 422),
    ]
    for name, quantity in (
        ("zero", 0),
        ("eleven", 11),
        ("negative", -1),
        ("fraction", 1.5),
        ("string", "2"),
        ("boolean", True),
        ("null", None),
    ):
        invalid.append((f"quantity_{name}", {"items": [{**one[0], "quantity": quantity}]}, 422))
    for name, payload, status in invalid:
        headers = {"X-Faultline-Case-Id": str(uuid4())}
        response = await client.post("/api/checkout", json=payload, headers=headers)
        orders = await client.get("/api/orders", headers=headers)
        record(
            name,
            response.status_code == status
            and orders.status_code == 200
            and orders.json() == {"orders": []},
            f"HTTP {status} and no order",
            f"HTTP {response.status_code}",
        )
    for name, endpoint in (
        ("unknown_order", "/api/orders/unknown"),
        ("unknown_product_readback", "/api/products/unknown"),
    ):
        result = await client.get(endpoint)
        record(name, result.status_code == 404, "HTTP 404", f"HTTP {result.status_code}")
    return assertions
