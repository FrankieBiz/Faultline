"""Catalog controls must pass even when checkout carries the seeded defect."""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.catalog import Product, get_catalog, get_product

EXPECTED_PRODUCTS: list[Product] = [
    {"id": "trail-mug", "name": "Trail Mug", "price_cents": 1999},
    {"id": "field-notebook", "name": "Field Notebook", "price_cents": 1500},
]


def test_health_identity(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "app": "buggyshop-api"}
    assert str(UUID(response.headers["X-Request-Id"])) == response.headers["X-Request-Id"]


def test_fixed_catalog(client: TestClient) -> None:
    assert get_catalog() == EXPECTED_PRODUCTS
    response = client.get("/api/products")
    assert response.status_code == 200
    assert response.json() == EXPECTED_PRODUCTS


@pytest.mark.parametrize("product", EXPECTED_PRODUCTS)
def test_product_readback(client: TestClient, product: Product) -> None:
    assert get_product(product["id"]) == product
    response = client.get(f"/api/products/{product['id']}")
    assert response.status_code == 200
    assert response.json() == product


def test_unknown_product_is_404(client: TestClient) -> None:
    assert get_product("unknown") is None
    assert client.get("/api/products/unknown").status_code == 404


def test_catalog_cannot_be_changed_through_returned_objects() -> None:
    catalog = get_catalog()
    catalog[0]["price_cents"] = 1
    catalog.clear()
    product = get_product("trail-mug")
    assert product is not None
    product["name"] = "Changed"
    assert get_catalog() == EXPECTED_PRODUCTS


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:4000",
        "http://127.0.0.1:4000",
    ],
)
def test_frontend_cors_preflight(client: TestClient, origin: str) -> None:
    response = client.options(
        "/api/checkout",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-faultline-case-id",
        },
    )
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == origin


def test_unregistered_origin_is_not_allowed(client: TestClient) -> None:
    response = client.get("/api/products", headers={"Origin": "https://outside.example"})
    assert "Access-Control-Allow-Origin" not in response.headers
