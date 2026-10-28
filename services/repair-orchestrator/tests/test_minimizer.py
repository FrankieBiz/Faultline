"""Tests for the delta-debugging (ddmin) incident minimization engine."""

from typing import Any

import pytest

from app.minimizer import DeltaDebugger, MinimalIncidentPayload


@pytest.mark.asyncio
async def test_minimizer_reduces_noisy_payload_to_single_key() -> None:
    # Failure occurs ONLY if 'coupon_code' is None
    async def oracle(payload: dict[str, Any]) -> bool:
        return "coupon_code" in payload and payload["coupon_code"] is None

    noisy_payload = {
        "items": [{"product_id": "trail-mug", "quantity": 2}],
        "coupon_code": None,
        "analytics_session": "sess-xyz-987",
        "user_agent": "Mozilla/5.0",
        "utm_source": "google_ads",
        "referrer": "https://example.com",
    }

    debugger = DeltaDebugger(max_iterations=30)
    result = await debugger.minimize_async(noisy_payload, oracle, "TypeError: unsupported operand")

    assert isinstance(result, MinimalIncidentPayload)
    assert result.minimal_payload == {"coupon_code": None}
    assert set(result.removed_keys) == {
        "items",
        "analytics_session",
        "user_agent",
        "utm_source",
        "referrer",
    }
    assert result.reduction_ratio > 0.5
    assert result.iterations > 0
    assert result.preserved_error_fingerprint == "TypeError: unsupported operand"


@pytest.mark.asyncio
async def test_minimizer_reduces_list_items() -> None:
    # Failure occurs ONLY if product 'trail-mug' is in items and 'coupon_code' is explicitly None
    async def oracle(payload: dict[str, Any]) -> bool:
        items = payload.get("items", [])
        has_mug = any(item.get("product_id") == "trail-mug" for item in items)
        return has_mug and "coupon_code" in payload and payload["coupon_code"] is None

    payload = {
        "items": [
            {"product_id": "field-notebook", "quantity": 1},
            {"product_id": "trail-mug", "quantity": 2},
            {"product_id": "water-bottle", "quantity": 1},
        ],
        "coupon_code": None,
        "client_metadata": {"ip": "127.0.0.1"},
    }

    debugger = DeltaDebugger()
    result = await debugger.minimize_async(payload, oracle, "TypeError")

    assert result.minimal_payload["coupon_code"] is None
    assert result.minimal_payload["items"] == [{"product_id": "trail-mug", "quantity": 2}]
    assert "client_metadata" not in result.minimal_payload


@pytest.mark.asyncio
async def test_minimizer_returns_original_if_oracle_fails_initially() -> None:
    async def oracle(payload: dict[str, Any]) -> bool:
        return False

    payload = {"items": [], "coupon_code": "TENOFF"}
    debugger = DeltaDebugger()
    result = await debugger.minimize_async(payload, oracle, "error")

    assert result.minimal_payload == payload
    assert result.removed_keys == []
    assert result.reduction_ratio == 0.0


@pytest.mark.asyncio
async def test_minimizer_handles_already_minimal_payload() -> None:
    async def oracle(payload: dict[str, Any]) -> bool:
        return True

    payload = {"coupon_code": None}
    debugger = DeltaDebugger()
    result = await debugger.minimize_async(payload, oracle, "error")

    assert result.minimal_payload == payload
    assert result.removed_keys == []
    assert result.reduction_ratio == 0.0


def test_minimizer_sync_wrapper() -> None:
    def sync_oracle(payload: dict[str, Any]) -> bool:
        return "bug" in payload

    payload = {"bug": True, "noise1": 1, "noise2": 2}
    debugger = DeltaDebugger()
    result = debugger.minimize_sync(payload, sync_oracle, "test_fp")

    assert result.minimal_payload == {"bug": True}
    assert "noise1" in result.removed_keys
    assert "noise2" in result.removed_keys
