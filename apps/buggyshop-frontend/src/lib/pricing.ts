/**
 * Pre-submission order preview.
 *
 * The backend is the only authority on order totals; the confirmation view
 * always renders the server's numbers. This module only previews what the
 * shopper should expect before pressing "Place order", using catalog prices
 * fetched from the backend and the published promotions.
 */

import type { Product } from "./api";
import type { CartLine } from "./cart";

/** Promotions BuggyShop advertises, as percent off; discounts round down to the cent. */
export const PUBLISHED_COUPONS: Readonly<Record<string, number>> = {
  TENOFF: 10,
  FIFTEEN: 15,
};

/** A cart line joined with its catalog entry, or flagged when it has none. */
export type PricedLine =
  | { kind: "priced"; product: Product; quantity: number; lineTotalCents: number }
  | { kind: "unavailable"; productId: string; quantity: number };

/** Preview totals shown in the checkout summary. */
export interface OrderPreview {
  lines: PricedLine[];
  subtotalCents: number;
  /** `null` when a coupon is entered that the storefront cannot price. */
  discountCents: number | null;
  totalCents: number | null;
  hasUnavailableLines: boolean;
}

/** Normalizes a coupon the way the backend does: trimmed and upper-cased. */
export function normalizeCoupon(raw: string): string | null {
  const trimmed = raw.trim();
  return trimmed ? trimmed.toUpperCase() : null;
}

/** Prices the cart against the catalog and previews the discount. */
export function previewOrder(
  lines: readonly CartLine[],
  catalog: readonly Product[],
  appliedCoupon: string | null,
): OrderPreview {
  const byId = new Map(catalog.map((product) => [product.id, product]));
  const priced: PricedLine[] = lines.map((line) => {
    const product = byId.get(line.product_id);
    return product
      ? { kind: "priced", product, quantity: line.quantity, lineTotalCents: product.price_cents * line.quantity }
      : { kind: "unavailable", productId: line.product_id, quantity: line.quantity };
  });
  const subtotalCents = priced.reduce((sum, line) => sum + (line.kind === "priced" ? line.lineTotalCents : 0), 0);

  let discountCents: number | null = 0;
  if (appliedCoupon !== null) {
    const percent = PUBLISHED_COUPONS[appliedCoupon];
    discountCents = percent === undefined ? null : Math.floor((subtotalCents * percent) / 100);
  }

  return {
    lines: priced,
    subtotalCents,
    discountCents,
    totalCents: discountCents === null ? null : subtotalCents - discountCents,
    hasUnavailableLines: priced.some((line) => line.kind === "unavailable"),
  };
}
