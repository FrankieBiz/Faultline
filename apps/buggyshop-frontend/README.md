# BuggyShop frontend

Next.js App Router storefront for the FaultLine scripted checkout repair demo ([SpecV1 §2](../../docs/SpecV1.md)). It stays fixed during v1 repair; only the backend changes.

## Pages

| Route | Purpose |
|---|---|
| `/` | Catalog from `GET /api/products`, with add-to-cart and a header cart badge |
| `/product/[id]` | Product from `GET /api/products/{id}`, quantity selector (1–10), add to cart |
| `/checkout` | Cart lines, shipping details (`name`, `email`, `address`), optional coupon with **Apply**, order summary, **Place order** |

The cart lives in `localStorage`, so every new browser context starts empty. Place order sends exactly one `POST /api/checkout` with `{"items": [...], "coupon_code": ...}`. Shipping details are required in the form but are not sent, because the backend rejects unknown fields. Success replaces the page with an order confirmation built from the server response. Any failure, such as the seeded HTTP 500, keeps the cart and shows a focused `role="alert"` panel headed "Checkout failed".

## Backend contract

The UI follows the settled backend interface in [`apps/buggyshop-backend/README.md`](../buggyshop-backend/README.md). Where that interface differs from the SpecV1 §2.2 examples, the backend wins.

- `GET /api/products` returns a JSON array of `{"id", "name", "price_cents"}`.
- `GET /api/products/{id}` returns one product, or 404.
- `POST /api/checkout` with `{"items": [{"product_id", "quantity"}], "coupon_code": str | null}` returns 201 with `{"id", "line_items", "subtotal", "discount", "total"}`, all amounts in USD cents.
- Published coupons are `TENOFF` (10%) and `FIFTEEN` (15%). Unknown codes are rejected by the backend with 400.

Prices are always taken from the backend. The checkout summary previews published coupon discounts before submission, but the confirmation shows only the server's figures.

## Running

```bash
npm ci
npm run build
BUGGYSHOP_BACKEND_URL=http://127.0.0.1:8000 npm run start  # http://127.0.0.1:3000
```

`src/app/api/[...path]/route.ts` proxies browser `/api/*` requests to the runtime `BUGGYSHOP_BACKEND_URL`. Each candidate storefront can select its own isolated backend without rebuilding. Requests retain the case namespace and server request ID.

`npm run check` runs ESLint, `tsc --noEmit`, and the production build.
