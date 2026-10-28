"""Independent trusted HTTP oracle; never import a candidate Python module."""

from collections.abc import Awaitable
from typing import Any
from uuid import UUID, uuid4

import httpx

from app.runtime import RuntimeUnavailable
from shared.contracts.models import AssertionResult

# A candidate that hangs, crashes, or returns an unbounded or non-JSON body
# fails its business check; it must not be misreported as oracle failure.
CANDIDATE_FAULTS = (httpx.HTTPError, RuntimeUnavailable, TimeoutError)


def _json(response: httpx.Response) -> object:
    """Decode a candidate body, treating malformed JSON as an observed value."""
    try:
        value: object = response.json()
    except ValueError:
        return None
    return value


async def regression(client: httpx.AsyncClient) -> list[AssertionResult]:
    """Measure the fixed business cases against an isolated backend over HTTP."""
    assertions: list[AssertionResult] = []

    async def check(name: str, expected: str, measurement: Awaitable[None]) -> None:
        try:
            await measurement
        except CANDIDATE_FAULTS as exc:
            record(name, False, expected, f"request failed: {type(exc).__name__}")

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
        await check(name, str(expected), created(name, payload, headers, expected))

    async def created(
        name: str, payload: dict[str, Any], headers: dict[str, str], expected: dict[str, Any]
    ) -> None:
        result = await client.post("/api/checkout", json=payload, headers=headers)
        body = _json(result)
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
        valid = valid and orders.status_code == 200 and _json(orders) == {"orders": [body]}
        if valid_identity:
            readback = await client.get(f"/api/orders/{identity}", headers=headers)
            valid = valid and readback.status_code == 200 and _json(readback) == body
        observed = body if body is not None else result.text
        record(name, valid, str(expected), f"HTTP {result.status_code}: {str(observed)[:1024]}")

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

    async def rejected(name: str, payload: dict[str, Any], status: int) -> None:
        headers = {"X-Faultline-Case-Id": str(uuid4())}
        response = await client.post("/api/checkout", json=payload, headers=headers)
        orders = await client.get("/api/orders", headers=headers)
        record(
            name,
            response.status_code == status
            and orders.status_code == 200
            and _json(orders) == {"orders": []},
            f"HTTP {status} and no order",
            f"HTTP {response.status_code}",
        )

    for name, payload, status in invalid:
        await check(name, f"HTTP {status} and no order", rejected(name, payload, status))

    async def missing(name: str, endpoint: str) -> None:
        result = await client.get(endpoint)
        record(name, result.status_code == 404, "HTTP 404", f"HTTP {result.status_code}")

    for name, endpoint in (
        ("unknown_order", "/api/orders/unknown"),
        ("unknown_product_readback", "/api/products/unknown"),
    ):
        await check(name, "HTTP 404", missing(name, endpoint))
    return assertions
