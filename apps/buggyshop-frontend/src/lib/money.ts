/**
 * Currency formatting for the UI boundary.
 *
 * BuggyShop keeps every amount in integer USD cents (SpecV1 §2.1). Cents are
 * converted to dollars only here, at the moment they are rendered.
 */

const usdFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** Formats an integer amount of USD cents, e.g. `3998` becomes `$39.98`. */
export function formatUsd(cents: number): string {
  return usdFormatter.format(cents / 100);
}

/**
 * Formats a discount as a deduction. Zero renders as `$0.00` so the summary
 * never shows a misleading negative zero.
 */
export function formatDiscount(cents: number): string {
  return cents > 0 ? `−${formatUsd(cents)}` : formatUsd(0);
}
