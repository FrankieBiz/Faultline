"""FastAPI entry point; run from the service directory with app.main:app."""

import logging
from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.catalog import Product, get_catalog, get_product
from app.orders import Order, get_orders
from app.routes import checkout as checkout_route
from app.schemas import CheckoutRequest

logger = logging.getLogger("buggyshop.api")

app = FastAPI(title="BuggyShop API", version="0.1.0", debug=False)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        "http://127.0.0.1:4000",
        "http://localhost:4000",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Faultline-Case-Id"],
    expose_headers=["X-Request-Id"],
)


def case_namespace(
    case_id: Annotated[str, Header(alias="X-Faultline-Case-Id")] = "demo",
) -> str:
    """Select a trusted runner's opaque case key, defaulting to manual demo."""
    return case_id


CaseNamespace = Annotated[str, Depends(case_namespace)]


@app.middleware("http")
async def correlate_request(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Attach a server-generated request ID to responses and failure logs."""
    request.state.request_id = str(uuid4())
    response = await call_next(request)
    response.headers["X-Request-Id"] = request.state.request_id
    return response


@app.exception_handler(TypeError)
async def report_type_error(request: Request, exc: TypeError) -> JSONResponse:
    """Expose the fixture's exception fingerprint without a public traceback.

    Preserve the full exception in backend logs for correlated failure evidence.
    An HTTP 500 remains a failure and never creates a synthetic confirmation.
    """
    fingerprint = f"{type(exc).__name__}: {exc}"
    logger.error(
        "%s",
        fingerprint,
        exc_info=(type(exc), exc, exc.__traceback__),
        extra={
            "case_id": request.headers.get("X-Faultline-Case-Id", "demo"),
            "request_id": request.state.request_id,
            "route": request.url.path,
            "exception_type": type(exc).__name__,
        },
    )
    return JSONResponse(status_code=500, content={"detail": fingerprint})


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Return the exact backend readiness identity."""
    return {"status": "ok", "app": "buggyshop-api"}


@app.get("/api/products")
def list_products() -> list[Product]:
    """List the fixed catalog in stable display order."""
    return get_catalog()


@app.get("/api/products/{product_id}")
def read_product(product_id: str) -> Product:
    """Read one product or return 404 for an unknown catalog ID."""
    product = get_product(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@app.post("/api/checkout", status_code=201)
def create_checkout(payload: CheckoutRequest, namespace: CaseNamespace) -> Order:
    """Delegate checkout pricing to the registered repairable route."""
    return checkout_route.checkout(payload, namespace)


@app.get("/api/orders")
def list_orders(namespace: CaseNamespace) -> dict[str, list[Order]]:
    """List orders only within the caller's current case namespace."""
    return {"orders": get_orders(namespace)}


@app.get("/api/orders/{order_id}")
def read_order(order_id: str, namespace: CaseNamespace) -> Order:
    """Read an order in this namespace without leaking another case's orders."""
    order = next((order for order in get_orders(namespace) if order["id"] == order_id), None)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order
