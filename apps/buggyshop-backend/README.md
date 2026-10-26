# BuggyShop backend fixture

From this directory, install the locked Python 3.13 environment and start one
backend process:

```bash
uv sync --python 3.13 --locked
uv run --python 3.13 --locked uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Run `uv run --python 3.13 --locked pytest` here, or `make check` at the repository
root for tests, formatting, lint, strict typing, provenance, and package builds.

The committed route intentionally fails checkout for missing, null, empty, and
whitespace-only coupons. It returns HTTP 500 with the TypeError fingerprint and
records the traceback in backend logs. `TENOFF` and `FIFTEEN` work, normalized
with trim/uppercase, and unknown nonempty coupons return HTTP 400. Discounts
truncate fractional cents. These coupon names, statuses, scenario ID, and order
summary fields follow the backend task's explicit requirements, superseding the
corresponding examples in SpecV1. No real payments or persistent orders exist.

Products use `id`, `name`, and `price_cents`. Checkout accepts `items` containing
`product_id` and strict integer `quantity` (1–10), plus optional `coupon_code`.
Unknown fields, duplicate products, invalid quantities, and unknown products
return 422. A successful response contains `id`, `line_items`, `subtotal`,
`discount`, and `total`; all amounts are USD cents. Read orders through
`GET /api/orders` or `GET /api/orders/{order_id}` using the same
`X-Faultline-Case-Id` header. An absent header selects `demo`.

The trusted healthy/seeded snapshots and SHA-256 manifest live in `fixtures/`.
Tests load the healthy snapshot independently; the live checkout file stays
seeded throughout verification. `python -m fixtures.provenance` checks exact
bytes and, when pinned, the source Git revision. These reference files must not
be included in candidate runtime exports or repair prompts.
