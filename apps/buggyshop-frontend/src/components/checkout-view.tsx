"use client";

import Link from "next/link";
import { useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { fetchCatalog, submitCheckout, type CheckoutResult, type Order, type Product } from "@/lib/api";
import {
  MAX_QUANTITY,
  MIN_QUANTITY,
  clearCart,
  removeFromCart,
  setCartQuantity,
  useCart,
  useHydrated,
  type CartLine,
} from "@/lib/cart";
import { formatDiscount, formatUsd } from "@/lib/money";
import { PUBLISHED_COUPONS, normalizeCoupon, previewOrder, type OrderPreview, type PricedLine } from "@/lib/pricing";
import { useResource, type ResourceState } from "@/lib/use-resource";
import { CheckoutFailure } from "./checkout-failure";
import { Notice } from "./notice";
import { OrderConfirmation, type ShippingDetails } from "./order-confirmation";
import { SummaryRow } from "./summary-row";

const FORM_ID = "checkout-form";

type Failure = Exclude<CheckoutResult, { kind: "placed" }>;

/**
 * Checkout: cart review, shipping details, optional coupon, order summary,
 * and a single "Place order" submission to `POST /api/checkout`.
 *
 * On success the view is replaced by the order confirmation built from the
 * server response. On failure (for example the seeded HTTP 500) the cart is
 * kept and a focused alert explains what happened.
 */
export function CheckoutView() {
  const hydrated = useHydrated();
  const cart = useCart();
  const catalog = useResource("/api/products", fetchCatalog);
  const [placed, setPlaced] = useState<{ order: Order; shipping: ShippingDetails } | null>(null);

  if (placed) {
    const products = catalog.state.status === "ready" ? catalog.state.value : [];
    return <OrderConfirmation order={placed.order} shipping={placed.shipping} catalog={products} />;
  }

  return (
    <div>
      <h1 className="text-5xl leading-[0.95] font-extrabold tracking-tight sm:text-6xl">Checkout</h1>
      {!hydrated ? (
        <p role="status" className="mt-8 text-moss">
          Loading your cart…
        </p>
      ) : cart.lines.length === 0 ? (
        <div className="mt-8 max-w-xl">
          <Notice
            tone="info"
            title="Your cart is empty."
            action={
              <Link href="/" className="btn-primary">
                Browse the catalog
              </Link>
            }
          >
            <p>Add something from the catalog, then come back here to place your order.</p>
          </Notice>
        </div>
      ) : (
        <CheckoutForm
          lines={cart.lines}
          catalog={catalog.state}
          onRetryCatalog={catalog.retry}
          onPlaced={(order, shipping) => {
            clearCart();
            setPlaced({ order, shipping });
          }}
        />
      )}
    </div>
  );
}

interface CheckoutFormProps {
  lines: readonly CartLine[];
  catalog: ResourceState<Product[]>;
  onRetryCatalog: () => void;
  onPlaced: (order: Order, shipping: ShippingDetails) => void;
}

function CheckoutForm({ lines, catalog, onRetryCatalog, onPlaced }: CheckoutFormProps) {
  const couponInputId = useId();
  const couponHintId = useId();
  const [couponText, setCouponText] = useState("");
  const [appliedCoupon, setAppliedCoupon] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  // Guards against a second submission landing before React re-renders the
  // disabled button: the scenario contract allows exactly one checkout request.
  const inFlight = useRef(false);

  const products = catalog.status === "ready" ? catalog.value : [];
  const preview = previewOrder(lines, products, appliedCoupon);
  const canPlaceOrder = catalog.status === "ready" && !preview.hasUnavailableLines && !submitting;

  function applyCoupon() {
    setAppliedCoupon(normalizeCoupon(couponText));
  }

  function removeCoupon() {
    setCouponText("");
    setAppliedCoupon(null);
  }

  function handleCouponKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    // Enter in the coupon field applies the code instead of placing the order.
    if (event.key === "Enter") {
      event.preventDefault();
      applyCoupon();
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (inFlight.current || !canPlaceOrder) return;
    inFlight.current = true;

    const data = new FormData(event.currentTarget);
    const shipping: ShippingDetails = {
      name: String(data.get("name") ?? "").trim(),
      email: String(data.get("email") ?? "").trim(),
      address: String(data.get("address") ?? "").trim(),
    };
    // The coupon field's current text is what gets submitted; the backend
    // trims and upper-cases it. Blank text means "no coupon".
    const couponCode = couponText.trim() ? couponText : null;
    setAppliedCoupon(normalizeCoupon(couponText));
    setFailure(null);
    setSubmitting(true);

    try {
      const result = await submitCheckout({
        items: lines.map((line) => ({ product_id: line.product_id, quantity: line.quantity })),
        coupon_code: couponCode,
      });
      if (result.kind === "placed") {
        onPlaced(result.order, shipping);
      } else {
        setFailure(result);
      }
    } finally {
      inFlight.current = false;
      setSubmitting(false);
    }
  }

  return (
    <div className="mt-10 grid items-start gap-12 lg:grid-cols-[minmax(0,1fr)_23rem]">
      <form id={FORM_ID} onSubmit={handleSubmit} aria-label="Checkout" className="space-y-12">
        {failure ? <CheckoutFailure failure={failure} /> : null}

        <section aria-labelledby="cart-heading">
          <h2 id="cart-heading" className="text-2xl font-extrabold tracking-tight">
            Your cart
          </h2>
          <ul className="mt-4 divide-y divide-stone border-y border-stone">
            {preview.lines.map((line) => (
              <CartRow key={line.kind === "priced" ? line.product.id : line.productId} line={line} />
            ))}
          </ul>
        </section>

        <fieldset className="space-y-5">
          <legend className="text-2xl font-extrabold tracking-tight">Shipping details</legend>
          <Field id="name" label="Name" autoComplete="name" />
          <Field id="email" label="Email" type="email" autoComplete="email" />
          <div>
            <label htmlFor="address" className="block font-bold">
              Address
            </label>
            <textarea
              id="address"
              name="address"
              required
              rows={3}
              autoComplete="street-address"
              className="field-input mt-2 resize-y"
            />
          </div>
        </fieldset>

        <section aria-labelledby="coupon-heading">
          <h2 id="coupon-heading" className="text-2xl font-extrabold tracking-tight">
            Coupon
          </h2>
          <label htmlFor={couponInputId} className="mt-4 block font-bold">
            Coupon code
          </label>
          <div className="mt-2 flex max-w-md gap-3">
            <input
              id={couponInputId}
              name="coupon"
              type="text"
              autoComplete="off"
              spellCheck={false}
              value={couponText}
              aria-describedby={couponHintId}
              onChange={(event) => setCouponText(event.target.value)}
              onKeyDown={handleCouponKeyDown}
              className="field-input uppercase"
            />
            <button type="button" className="btn-secondary shrink-0" onClick={applyCoupon}>
              Apply<span className="sr-only"> coupon</span>
            </button>
          </div>
          <div id={couponHintId} role="status" className="mt-2 min-h-6 text-sm">
            <CouponStatus applied={appliedCoupon} onRemove={removeCoupon} />
          </div>
        </section>
      </form>

      <OrderSummary
        preview={preview}
        appliedCoupon={appliedCoupon}
        catalog={catalog}
        onRetryCatalog={onRetryCatalog}
        submitting={submitting}
        canPlaceOrder={canPlaceOrder}
      />
    </div>
  );
}

interface FieldProps {
  id: "name" | "email";
  label: string;
  type?: "text" | "email";
  autoComplete: string;
}

/** Required single-line shipping field whose `id` and `name` match. */
function Field({ id, label, type = "text", autoComplete }: FieldProps) {
  return (
    <div>
      <label htmlFor={id} className="block font-bold">
        {label}
      </label>
      <input id={id} name={id} type={type} required autoComplete={autoComplete} className="field-input mt-2" />
    </div>
  );
}

function CouponStatus({ applied, onRemove }: { applied: string | null; onRemove: () => void }) {
  if (applied === null) {
    return <p className="text-moss">Optional. Enter a code and choose Apply to preview the discount.</p>;
  }
  const percent = PUBLISHED_COUPONS[applied];
  return (
    <p className="font-semibold">
      {percent !== undefined
        ? `${applied} applied: ${percent}% off your subtotal.`
        : `${applied} isn't a published code. The store checks it when you place the order.`}{" "}
      <button type="button" onClick={onRemove} className="text-link">
        Remove<span className="sr-only"> coupon</span>
      </button>
    </p>
  );
}

const QUANTITY_OPTIONS = Array.from({ length: MAX_QUANTITY - MIN_QUANTITY + 1 }, (_, index) => MIN_QUANTITY + index);

/** One cart line with an accessible quantity selector and remove action. */
function CartRow({ line }: { line: PricedLine }) {
  const selectId = useId();
  const productId = line.kind === "priced" ? line.product.id : line.productId;
  const name = line.kind === "priced" ? line.product.name : "Unavailable item";

  return (
    <li className="grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-3 py-4 sm:grid-cols-[1fr_auto_6rem_auto]">
      <div>
        <p className="text-lg font-bold">{name}</p>
        <p className="text-sm text-moss">
          {line.kind === "priced"
            ? `${formatUsd(line.product.price_cents)} each`
            : `“${line.productId}” is no longer sold. Remove it to continue.`}
        </p>
      </div>
      <div className="flex items-center gap-2">
        <label htmlFor={selectId} className="text-sm font-bold">
          Qty<span className="sr-only"> for {name}</span>
        </label>
        <select
          id={selectId}
          value={line.quantity}
          onChange={(event) => setCartQuantity(productId, Number(event.target.value))}
          className="field-input w-auto py-1.5 pr-8 tabular-nums"
        >
          {QUANTITY_OPTIONS.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
      </div>
      <p className="hidden text-right font-bold tabular-nums sm:block">
        {line.kind === "priced" ? formatUsd(line.lineTotalCents) : "—"}
      </p>
      <button
        type="button"
        onClick={() => removeFromCart(productId)}
        className="text-link justify-self-start text-sm sm:justify-self-end"
      >
        Remove<span className="sr-only"> {name}</span>
      </button>
    </li>
  );
}

interface OrderSummaryProps {
  preview: OrderPreview;
  appliedCoupon: string | null;
  catalog: ResourceState<Product[]>;
  onRetryCatalog: () => void;
  submitting: boolean;
  canPlaceOrder: boolean;
}

/** Notebook-paper totals panel holding the form's "Place order" button. */
function OrderSummary({
  preview,
  appliedCoupon,
  catalog,
  onRetryCatalog,
  submitting,
  canPlaceOrder,
}: OrderSummaryProps) {
  return (
    <aside
      aria-labelledby="summary-heading"
      className="notebook-paper rounded-md border-[1.5px] border-notebook-edge px-6 py-6 lg:sticky lg:top-6"
    >
      <h2 id="summary-heading" className="text-2xl font-extrabold tracking-tight">
        Order summary
      </h2>

      {catalog.status === "loading" ? (
        <p role="status" className="mt-4">
          Loading prices…
        </p>
      ) : catalog.status === "error" ? (
        <div className="mt-4">
          <Notice
            tone="error"
            title="Prices didn't load."
            action={
              <button type="button" className="btn-secondary bg-white" onClick={onRetryCatalog}>
                Try again
              </button>
            }
          >
            <p>{catalog.message}</p>
          </Notice>
        </div>
      ) : (
        <>
          <ul className="mt-4 space-y-1.5 border-b border-spruce/25 pb-4">
            {preview.lines.map((line) =>
              line.kind === "priced" ? (
                <li key={line.product.id} className="flex justify-between gap-4">
                  <span>
                    {line.product.name} <span className="tabular-nums">× {line.quantity}</span>
                  </span>
                  <span className="tabular-nums">{formatUsd(line.lineTotalCents)}</span>
                </li>
              ) : (
                <li key={line.productId} className="font-semibold text-alarm">
                  Unavailable item, remove to continue
                </li>
              ),
            )}
          </ul>
          <dl className="mt-3">
            <SummaryRow label="Subtotal" value={formatUsd(preview.subtotalCents)} />
            <SummaryRow
              label={appliedCoupon ? `Discount (${appliedCoupon})` : "Discount"}
              value={preview.discountCents === null ? "Checked at order" : formatDiscount(preview.discountCents)}
            />
            <SummaryRow
              label={preview.totalCents === null ? "Total before coupon" : "Total"}
              value={formatUsd(preview.totalCents ?? preview.subtotalCents)}
              emphasis
            />
          </dl>
        </>
      )}

      <button type="submit" form={FORM_ID} className="btn-primary mt-6 w-full" disabled={!canPlaceOrder}>
        {submitting ? "Placing order…" : "Place order"}
      </button>
      <p className="mt-3 text-sm">No payment is taken. Prices are in US dollars.</p>
    </aside>
  );
}
