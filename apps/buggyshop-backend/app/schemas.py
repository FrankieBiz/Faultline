"""Trusted checkout validation outside the repairable pricing route."""

from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.catalog import get_product


class CheckoutItem(BaseModel):
    """One known product with a strict bounded integer quantity."""

    model_config = ConfigDict(extra="forbid", strict=True)

    product_id: str
    quantity: Annotated[int, Field(ge=1, le=10)]

    @model_validator(mode="after")
    def require_known_product(self) -> Self:
        """Reject product IDs that cannot be priced from the fixed catalog."""
        if get_product(self.product_id) is None:
            raise ValueError("Unknown product ID")
        return self


class CheckoutRequest(BaseModel):
    """Checkout inputs; prices and other undeclared fields are forbidden."""

    model_config = ConfigDict(extra="forbid", strict=True)

    items: Annotated[list[CheckoutItem], Field(min_length=1, max_length=2)]
    coupon_code: str | None = None

    @model_validator(mode="after")
    def require_distinct_products(self) -> Self:
        """Prevent duplicate entries from bypassing the per-product limit."""
        product_ids = [item.product_id for item in self.items]
        if len(set(product_ids)) != len(product_ids):
            raise ValueError("Each product ID must appear only once")
        return self
