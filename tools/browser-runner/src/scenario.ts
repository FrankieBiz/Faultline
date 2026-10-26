/**
 * Trusted scenario entry and fixture expectations for the scripted checkout
 * repair (SpecV1 §4 and §11, with the settled backend interface from
 * `apps/buggyshop-backend/README.md`).
 *
 * Every expected value here is authored from the business contract, never
 * imported from BuggyShop's pricing code, so a candidate patch cannot change
 * what the oracle considers correct.
 */

/** Registry identity, matching `shared/config/scenarios.py`. */
export const SCENARIO_ID = "scripted_checkout_repair";

/** Catalog entry as fixed by the business contract (prices in USD cents). */
export interface FixtureProduct {
  id: string;
  name: string;
  price_cents: number;
}

/** Fixture catalog. */
export const FIXTURE_CATALOG: Readonly<Record<string, FixtureProduct>> = {
  "trail-mug": { id: "trail-mug", name: "Trail Mug", price_cents: 1999 },
  "field-notebook": { id: "field-notebook", name: "Field Notebook", price_cents: 1500 },
};

/** Primary input from the scenario registry: two mugs. */
export const PRIMARY_PRODUCT_ID = "trail-mug";
export const PRIMARY_QUANTITY = 2;

/** Recognized coupons and their percent off; discounts round down to whole cents. */
export const RECOGNIZED_COUPONS: Readonly<Record<string, number>> = {
  TENOFF: 10,
  FIFTEEN: 15,
};

/** Status the backend returns for an unknown nonempty coupon. */
export const UNKNOWN_COUPON_STATUS = 400;

/** Synthetic shipping details typed into the checkout form. */
export const SHIPPING_DETAILS = {
  name: "Avery Trailhead",
  email: "avery@example.com",
  address: "14 Ridgeline Road\nBoulder, CO 80302",
} as const;

/** Expected priced line of the created order. */
export interface ExpectedLine {
  product_id: string;
  quantity: number;
  unit_price_cents: number;
  line_total_cents: number;
}

/** What the oracle requires for a given coupon input. */
export type CheckoutExpectation =
  | {
      kind: "order";
      /** Coupon meaning after the contract's normalization; `null` means none. */
      normalized_coupon: string | null;
      status: 201;
      line_items: ExpectedLine[];
      subtotal: number;
      discount: number;
      total: number;
    }
  | {
      kind: "rejected";
      normalized_coupon: string;
      status: typeof UNKNOWN_COUPON_STATUS;
    };

/**
 * Normalizes a coupon as the contract specifies: missing, empty, or
 * whitespace-only means no coupon; otherwise trim and upper-case.
 */
export function normalizeCoupon(raw: string | null | undefined): string | null {
  if (raw === null || raw === undefined) return null;
  const trimmed = raw.trim();
  return trimmed ? trimmed.toUpperCase() : null;
}

/**
 * Computes the independently derived expectation for the primary flow (two
 * Trail Mugs) with an optional coupon. Unknown coupons must be rejected and
 * create no order.
 */
export function expectCheckout(coupon: string | null | undefined): CheckoutExpectation {
  const normalized = normalizeCoupon(coupon);
  const percent = normalized === null ? 0 : RECOGNIZED_COUPONS[normalized];
  if (normalized !== null && percent === undefined) {
    return { kind: "rejected", normalized_coupon: normalized, status: UNKNOWN_COUPON_STATUS };
  }
  const product = FIXTURE_CATALOG[PRIMARY_PRODUCT_ID];
  if (!product) throw new Error(`Fixture catalog is missing ${PRIMARY_PRODUCT_ID}.`);
  const lineTotal = product.price_cents * PRIMARY_QUANTITY;
  const subtotal = lineTotal;
  const discount = Math.floor((subtotal * (percent ?? 0)) / 100);
  return {
    kind: "order",
    normalized_coupon: normalized,
    status: 201,
    line_items: [
      {
        product_id: product.id,
        quantity: PRIMARY_QUANTITY,
        unit_price_cents: product.price_cents,
        line_total_cents: lineTotal,
      },
    ],
    subtotal,
    discount,
    total: subtotal - discount,
  };
}
