"""Fresh case namespaces and an independently loaded healthy source fixture."""

import importlib.util
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.orders import Order
from app.routes import checkout as checkout_route
from app.schemas import CheckoutRequest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CheckoutHandler = Callable[[CheckoutRequest, str], Order]


@pytest.fixture
def namespace() -> str:
    """Give every test a new opaque storage namespace without reset endpoints."""
    return f"test-{uuid4()}"


@pytest.fixture
def client(namespace: str) -> Iterator[TestClient]:
    """Run the committed seeded application with isolated orders."""
    with TestClient(app, headers={"X-Faultline-Case-Id": namespace}) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def healthy_checkout() -> CheckoutHandler:
    """Import healthy reference bytes without changing the live route file."""
    path = REPOSITORY_ROOT / "fixtures/seeds/checkout_healthy.py"
    spec = importlib.util.spec_from_file_location("fixture_healthy_checkout", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load the trusted healthy checkout snapshot")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast(CheckoutHandler, module.checkout)


@pytest.fixture
def healthy_client(
    monkeypatch: pytest.MonkeyPatch, healthy_checkout: CheckoutHandler, client: TestClient
) -> TestClient:
    """Exercise healthy pricing through the same validation and HTTP routes."""
    monkeypatch.setattr(checkout_route, "checkout", healthy_checkout)
    return client
